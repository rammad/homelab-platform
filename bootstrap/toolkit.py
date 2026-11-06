#!/usr/bin/env python3
"""Run bootstrap.sh --help for individually callable workflows."""
import argparse
import sys
from lib import apps, argo, host
from lib.common import Failure, Kube, say

def parser():
    p = argparse.ArgumentParser(description='Homelab setup toolkit. No arguments opens the guided menu; checks never mutate the cluster.')
    p.add_argument('--kubectl', help='Command prefix, e.g. "sudo k3s kubectl" (no shell evaluation)')
    p.add_argument('--context', help='Explicit kubeconfig context')
    p.add_argument('--dry-run', action='store_true', help='Preview mutations; read-only checks still run. Place before subcommand.')
    commands = p.add_subparsers(dest='command')
    h = commands.add_parser('host', help='Local machine checks/preparation')
    hs = h.add_subparsers(dest='action', required=True)
    hs.add_parser('check')
    packages = hs.add_parser('packages'); packages.add_argument('--ssh', action='store_true', help='Include openssh-server')
    for role in ('control-plane', 'worker'):
        i = hs.add_parser(role); i.add_argument('--node-name', required=True)
        i.add_argument('--server', required=role=='worker')
    f = hs.add_parser('features'); f.add_argument('--with-qbittorrent', action='store_true')
    a = commands.add_parser('argo'); a.add_argument('action', choices=['check', 'install', 'access'])
    ap = commands.add_parser('app'); aps = ap.add_subparsers(dest='action', required=True)
    aps.add_parser('list')
    for action in ('guide', 'check', 'storage', 'secrets', 'register', 'verify', 'stage'):
        child = aps.add_parser(action); child.add_argument('name')
        if action == 'check': child.add_argument('--inside', action='store_true', help='Read-only Nextcloud checks inside running container')
        if action == 'secrets': child.add_argument('--replace', action='store_true', help='Explicitly rotate existing required keys; no automatic rollout')
    return p

def dispatch(args):
    if args.command == 'host':
        if args.action == 'check': return host.check()
        if args.action == 'packages': return host.packages(args.ssh, args.dry_run)
        if args.action == 'features': return host.features(args.with_qbittorrent, args.dry_run)
        return host.fresh_install(args.action, args.node_name, args.server, args.dry_run)
    if args.command == 'argo' and args.action == 'access': return argo.access()
    if args.command == 'app':
        if args.action == 'list':
            for name in apps.names(): print(name)
            return
        if args.action == 'guide': return apps.guide(args.name)
    kube = Kube(args.kubectl, args.context)
    if args.command == 'argo':
        return argo.check(kube) if args.action == 'check' else argo.install(kube, args.dry_run)
    if args.action == 'check':
        if not apps.check(args.name, kube, args.inside): raise Failure('App checks found prerequisites needing attention.')
    elif args.action == 'storage': apps.prepare_storage(args.name, kube, args.dry_run)
    elif args.action == 'secrets': apps.configure_secrets(args.name, kube, args.replace, args.dry_run)
    elif args.action == 'register': apps.register(args.name, kube, args.dry_run)
    elif args.action == 'stage': apps.stage(args.name, kube, args.dry_run)
    elif args.action == 'verify': apps.verify(args.name, kube)

def menu(base, p):
    print('\nHomelab setup toolkit — read-only checks are the starting point\n')
    host.check()
    while True:
        print('\n1. Check this host\n2. Install host prerequisites\n3. Set up a NEW control plane\n4. Join a NEW worker\n5. Configure node sysctls\n6. Check Argo\n7. Install NEW Argo\n8. Application walkthrough\n0. Exit')
        choice = input('Choose [0]: ').strip() or '0'
        if choice == '0': return
        options = {'1':['host','check'], '2':['host','packages'], '3':['host','control-plane'],
                   '4':['host','worker'], '5':['host','features'], '6':['argo','check'], '7':['argo','install']}
        if choice == '8':
            print('Apps: ' + ', '.join(apps.names()))
            name = input('App name: ').strip()
            print('Actions: guide (offline), check (cluster), storage, secrets, register, verify, stage')
            action = input('Action [guide]: ').strip() or 'guide'
            if action not in ('guide','check','storage','secrets','register','verify','stage'):
                say('Unknown action.', 'WARN'); continue
            command = ['app', action, name]
        elif choice in options:
            command = options[choice][:]
            if choice in ('3','4'): command += ['--node-name', input('Unique node name: ').strip()]
            if choice == '4': command += ['--server', input('Control-plane URL (https://host:6443): ').strip()]
            if choice == '2' and input('Include SSH server installation? [y/N] ').lower() == 'y': command += ['--ssh']
            if choice == '5' and input('Include qBittorrent VPN sysctls? [y/N] ').lower() == 'y': command += ['--with-qbittorrent']
        else:
            say('Unknown menu selection.', 'WARN'); continue
        args = p.parse_args(base + command)
        try: dispatch(args)
        except Failure as e: say(str(e), 'ERROR')

def main():
    p = parser(); args = p.parse_args()
    try:
        if args.command: dispatch(args)
        elif sys.stdin.isatty(): menu(sys.argv[1:], p)
        else: p.print_help()
    except Failure as e:
        say(str(e), 'ERROR'); return 1
    except EOFError:
        say("Input closed; exiting without continuing the workflow.", "WARN"); return 1
    except KeyboardInterrupt:
        say('Interrupted. No automatic rollback attempted; check the last reported step.', 'WARN'); return 130
    return 0

if __name__ == '__main__':
    sys.exit(main())
