#!/usr/bin/env bash
# Node prerequisite only. Does not change host TCP defaults or restart K3s.
# Run as root on the node hosting Traefik; requires python3-yaml and K3s >=1.32.
set -euo pipefail
if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo bash $0" >&2
  exit 1
fi
case "${1:-}" in
  ""|--with-qbittorrent) ;;
  *) echo "Usage: $0 [--with-qbittorrent]" >&2; exit 2 ;;
esac
python3 -c 'import yaml'
/sbin/modprobe tcp_bbr
if ! /sbin/sysctl -n net.ipv4.tcp_available_congestion_control | grep -qw bbr; then
  echo "BBR is not available in this kernel" >&2
  exit 1
fi
install -d /etc/modules-load.d
printf 'tcp_bbr\n' > /etc/modules-load.d/traefik-bbr.conf
python3 - "${1:-}" <<'PYTHON'
from pathlib import Path
import json
import sys
import yaml

folder = Path('/var/lib/rancher/k3s/agent/etc/kubelet.conf.d')
folder.mkdir(parents=True, exist_ok=True)
target = folder / '90-homelab-traefik-bbr.conf'
allowed = []
# Kubelet replaces lists across drop-ins. Preserve all existing allowances.
for path in sorted(folder.glob('*.conf')):
    config = yaml.safe_load(path.read_text()) or {}
    for name in config.get('allowedUnsafeSysctls', []):
        if name not in allowed:
            allowed.append(name)
    if path.name > target.name and 'allowedUnsafeSysctls' in config:
        raise SystemExit(f'{path} overrides this drop-in; reconcile it before continuing')
required = ['net.ipv4.tcp_congestion_control']
if sys.argv[1] == '--with-qbittorrent':
    required.extend(['net.ipv4.conf.all.src_valid_mark', 'net.ipv6.conf.all.disable_ipv6'])
for name in required:
    if name not in allowed:
        allowed.append(name)
config = {
    'apiVersion': 'kubelet.config.k8s.io/v1beta1',
    'kind': 'KubeletConfiguration',
    'allowedUnsafeSysctls': allowed,
}
content = json.dumps(config, indent=2) + '\n'
if not target.exists() or target.read_text() != content:
    if target.exists():
        target.with_suffix('.conf.bak').write_text(target.read_text())
    temporary = target.with_suffix('.tmp')
    temporary.write_text(content)
    temporary.replace(target)
print(f'Configured {target}')
PYTHON
echo "BBR prerequisite ready; host TCP default remains unchanged."
echo "Existing K3s: restart k3s in a maintenance window BEFORE deploying the Traefik change."
