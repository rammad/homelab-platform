"""Terminal UI and explicit command execution. Never use shell=True."""
import getpass
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]

class Failure(Exception):
    pass

def say(message, state='INFO'):
    colors = {'OK': '32', 'WARN': '33', 'ERROR': '31', 'INFO': '36'}
    label = f'[{state}]'
    if sys.stdout.isatty() and not os.environ.get('NO_COLOR'):
        label = f'\033[{colors.get(state, "36")}m{label}\033[0m'
    print(f'{label} {message}', flush=True)

def confirm(description, dry_run=False):
    say(description)
    if dry_run:
        say('Dry run: no changes made.', 'WARN')
        return False
    if not sys.stdin.isatty():
        raise Failure('A terminal is required for changes; use --dry-run to preview.')
    return input('Proceed? [y/N] ').strip().lower() == 'y'

def hidden(prompt):
    if not sys.stdin.isatty():
        raise Failure('Secret input requires a terminal.')
    value = getpass.getpass(prompt)
    if not value or '\n' in value or '\r' in value:
        raise Failure('Value must be nonempty and single-line.')
    return value

def run(command, data=None, sensitive=False, timeout=120, env=None):
    try:
        result = subprocess.run(command, input=data, capture_output=True,
                                text=True, timeout=timeout, env=env)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Failure(f'Command could not complete: {command[0]} ({type(error).__name__})') from None
    if result.returncode:
        # API validation errors can echo Secret payloads. Never display them.
        detail = 'Sensitive operation failed; inspect namespace, permissions and resource ownership.' if sensitive else result.stderr.strip()
        raise Failure(f'{command[0]} exited {result.returncode}: {detail}')
    return result.stdout

class Kube:
    def __init__(self, executable=None, context=None):
        if executable:
            self.command = shlex.split(executable)
        elif shutil.which('kubectl'):
            self.command = ['kubectl']
        elif shutil.which('k3s'):
            self.command = ['k3s', 'kubectl']
        else:
            raise Failure('kubectl is missing. On a node use --kubectl "sudo k3s kubectl"; workstation commands need kubectl and a kubeconfig.')
        if not self.command:
            raise Failure('Empty kubectl command.')
        if context:
            self.command += ['--context', context]

    def call(self, *args, data=None, sensitive=False, timeout=120):
        return run(self.command + list(args), data=data, sensitive=sensitive, timeout=timeout)

    def get(self, kind, name, namespace=None, sensitive=False):
        args = ['-n', namespace] if namespace else []
        output = self.call(*args, 'get', kind, name, '--ignore-not-found', '-o', 'json', sensitive=sensitive)
        return json.loads(output) if output.strip() else None

    def identity(self):
        # Avoid --raw: never display kubeconfig credentials.
        obj = json.loads(self.call('config', 'view', '--minify', '-o', 'json'))
        context = obj.get('current-context', '(unnamed)')
        server = obj.get('clusters', [{}])[0].get('cluster', {}).get('server', '(unknown)')
        say(f'Target context: {context}; API: {server}', 'WARN')
        return context, server

def yaml_module():
    try:
        import yaml
    except ImportError:
        raise Failure('PyYAML is required for app commands. Debian: install python3-yaml; Arch/Omarchy: python-yaml. No automatic package changes.') from None
    return yaml

def versions():
    return json.loads((ROOT / 'bootstrap/versions.json').read_text())
