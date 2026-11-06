"""Local host inspection and fresh-node provisioning, never an upgrade tool."""
import json
import os
from pathlib import Path
import re
import shutil
import socket
import tempfile
from urllib.parse import urlparse
from .common import ROOT, Failure, confirm, hidden, run, say, versions

def os_info():
    result = {}
    p = Path('/etc/os-release')
    if p.exists():
        for line in p.read_text().splitlines():
            if '=' in line:
                key, value = line.split('=', 1); result[key] = value.strip('"')
    return result

def installed():
    markers = ['/etc/rancher/k3s/config.yaml', '/var/lib/rancher/k3s/server',
               '/var/lib/rancher/k3s/agent', '/etc/systemd/system/k3s.service',
               '/etc/systemd/system/k3s-agent.service']
    try:
        return bool(shutil.which('k3s') or any(Path(p).exists() for p in markers))
    except PermissionError:
        return True  # Unreadable cluster state is not a fresh node.

def check():
    say(f'Local host: {socket.gethostname()} — {os_info().get("PRETTY_NAME", "unknown OS")}')
    say('Existing k3s installation/state detected; fresh-install commands will refuse.' if installed() else 'No obvious k3s installation detected.', 'WARN' if installed() else 'INFO')
    for program in ('ssh', 'sshd', 'curl', 'mount.nfs', 'rsync', 'kubectl', 'k3s'):
        found = shutil.which(program)
        if not found:
            found = next((str(p) for p in [Path('/usr/sbin')/program, Path('/sbin')/program] if p.exists()), None)
        say(f'{program}: {found or "not found"}', 'OK' if found else 'WARN')
    swaps = Path('/proc/swaps')
    if swaps.exists(): say('Active swap: ' + ('YES' if len(swaps.read_text().splitlines()) > 1 else 'none'))
    dri = Path('/dev/dri')
    if dri.exists():
        for p in sorted(dri.glob('*')):
            if p.is_char_device():
                st = p.stat(); say(f'GPU {p}: uid={st.st_uid} gid={st.st_gid} mode={oct(st.st_mode & 0o777)}')
    else: say('No /dev/dri devices found; GPU driver installation is not automated.', 'WARN')
    say('Read-only check complete. No packages, network settings, swap or services changed.', 'OK')

def require_debian_root():
    if os.geteuid() != 0: raise Failure('This host mutation requires root. Rerun only this command with sudo.')
    if os_info().get('ID') != 'debian': raise Failure('Host package/install operations support Debian only. Workstation read-only commands support other Linux distributions.')
    if not Path('/run/systemd/system').exists(): raise Failure('A running systemd host is required.')

def packages(ssh=False, dry_run=False):
    require_debian_root()
    wanted = ['curl', 'ca-certificates', 'nfs-common', 'rsync', 'python3-yaml']
    if ssh: wanted.append('openssh-server')
    missing = []
    for package in wanted:
        try:
            state = run(['dpkg-query', '-W', '-f=${Status}', package])
            if state.strip() != 'install ok installed': missing.append(package)
        except Failure: missing.append(package)
    if not missing:
        say('Requested packages are installed; no changes.', 'OK'); return
    if confirm('Install Debian packages: ' + ', '.join(missing) + '. Package hooks may start services, including SSH if selected.', dry_run):
        print(run(['apt-get', 'update'], timeout=600))
        print(run(['apt-get', 'install', '-y', *missing], timeout=900))
        for package in missing:
            if run(['dpkg-query', '-W', '-f=${Status}', package]).strip() != 'install ok installed':
                raise Failure('Package did not verify: ' + package)
        say('Packages verified. Existing service configuration was not edited by this toolkit.', 'OK')

def fresh_install(role, name, server=None, dry_run=False):
    require_debian_root()
    if installed(): raise Failure('Existing k3s binary/config/state detected. Refusing reinstall or downgrade; use host check and a separate upgrade/recovery procedure.')
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]{0,61}[a-z0-9])?', name): raise Failure('Use a valid lowercase node hostname.')
    if Path('/proc/swaps').exists() and len(Path('/proc/swaps').read_text().splitlines()) > 1:
        raise Failure('Swap is active. Review /etc/fstab and disable it persistently before installation; toolkit does not edit boot/storage configuration.')
    for command in ('curl', 'mount.nfs'):
        if not shutil.which(command): raise Failure('Missing prerequisite: ' + command + '. Run host packages first.')
    config = {'node-name': name}
    if role == 'worker':
        parsed = urlparse(server or '')
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment:
            raise Failure('Worker requires --server https://CONTROL_PLANE:6443 without credentials or extra path.')
        config['server'] = server
        config['token-file'] = '/etc/rancher/k3s/join-token'
    elif server:
        raise Failure('A new standalone control plane does not accept --server. HA joins/recovery are not implemented.')
    version = versions()['k3s']
    if not re.fullmatch(r'v\d+\.\d+\.\d+\+k3s\d+', version): raise Failure('Invalid pinned k3s version.')
    say('Before joining: confirm unique node name/IP and that the pinned agent version matches your server plan. This command does not change LAN addresses or router settings.', 'WARN')
    if not confirm(f'Install and START k3s {version} as {role} on LOCAL host {socket.gethostname()}, node name {name}. Server: {server or "new standalone cluster"}.', dry_run): return
    token = hidden('Cluster join token (hidden): ') if role == 'worker' else None
    directory = Path('/etc/rancher/k3s'); directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if token:
        with os.fdopen(os.open(directory/'join-token', os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600), 'w') as f: f.write(token+'\n')
    with os.fdopen(os.open(directory/'config.yaml', os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600), 'w') as f:
        json.dump(config, f, indent=2); f.write('\n')
    # Do not inherit accidental installer overrides or a token from the caller environment.
    env = {k:v for k,v in os.environ.items() if not k.startswith(('K3S_', 'INSTALL_K3S_'))}
    env['INSTALL_K3S_VERSION'] = version
    with tempfile.TemporaryDirectory(prefix='homelab-k3s-') as tmp:
        installer = str(Path(tmp)/'install.sh')
        run(['curl', '-fLsS', '--proto', '=https', '--tlsv1.2', 'https://get.k3s.io', '-o', installer])
        print(run(['sh', installer, 'server' if role == 'control-plane' else 'agent'], env=env, timeout=900, sensitive=True))
    service = 'k3s' if role == 'control-plane' else 'k3s-agent'
    if run(['systemctl', 'is-active', service]).strip() != 'active': raise Failure('Installed service is not active.')
    if role == 'control-plane':
        print(run(['k3s', 'kubectl', 'wait', '--for=condition=Ready', 'node/'+name, '--timeout=180s'], timeout=195))
    else:
        say(f'Agent service active. On the control plane verify: kubectl wait --for=condition=Ready node/{name} --timeout=180s', 'WARN')
    say('Installation finished. Root kubeconfig remains private; no kubeconfig was copied or chmodded for other users.', 'OK')

def features(qbit=False, dry_run=False):
    require_debian_root()
    if not confirm('Configure BBR module persistence and kubelet sysctl allowances' + (' including qBittorrent VPN sysctls' if qbit else '') + '. No service restart will be performed.', dry_run): return
    command = ['bash', str(ROOT/'bootstrap/configure-traefik-bbr.sh')]
    if qbit: command.append('--with-qbittorrent')
    print(run(command))
    say('If k3s is already running, schedule its restart separately. Do not restart during active streams.', 'WARN')
