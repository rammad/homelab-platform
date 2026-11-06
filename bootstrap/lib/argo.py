"""Pinned Argo installation; no upgrades, auto registration or exposure changes."""
import json
import re
from .common import Failure, confirm, say, versions

def install(kube, dry_run=False):
    kube.identity()
    if kube.get('deployment', 'argocd-server', 'argocd'):
        raise Failure('Argo already exists; refusing to reinstall/upgrade it. Use argo check.')
    if kube.get('namespace', 'argocd'):
        raise Failure('argocd namespace already exists; inspect partial/existing installation before proceeding.')
    if kube.get('customresourcedefinition', 'applications.argoproj.io'):
        raise Failure('Argo CRDs already exist; inspect another/partial installation before proceeding.')
    version = versions()['argocd']
    if not re.fullmatch(r'v\d+\.\d+\.\d+', version): raise Failure('Invalid Argo version pin.')
    if not confirm(f'Install Argo CD {version} into the displayed cluster. Creates namespace, CRDs and cluster-wide RBAC. No apps or public/NodePort access will be created.', dry_run): return
    kube.call('create', 'namespace', 'argocd')
    kube.call('-n', 'argocd', 'apply', '--server-side', '-f', f'https://raw.githubusercontent.com/argoproj/argo-cd/{version}/manifests/install.yaml', timeout=300)
    print(kube.call('-n', 'argocd', 'rollout', 'status', 'deployment/argocd-server', '--timeout=300s', timeout=315), end='')
    say('Argo server rollout ready. Run argo check. Access via localhost tunnel; no ingress or insecure-server setting was enabled.', 'OK')
    access()

def access():
    print('On a workstation with cluster access:')
    print('  kubectl -n argocd port-forward service/argocd-server 8080:443')
    print('  Open https://localhost:8080 (initial installation uses a self-signed certificate).')
    print('  Retrieve the initial password privately with the Argo CLI or initial-admin Secret; never paste it into shared logs.')
    print('  Configure repository credentials in Argo before registering private-repo apps.')

def check(kube):
    kube.identity()
    obj = kube.get('deployment', 'argocd-server', 'argocd')
    if not obj: raise Failure('Argo server Deployment is missing.')
    print(kube.call('-n', 'argocd', 'get', 'pods', '-o', 'wide'), end='')
    say('Argo server ready replicas: ' + str(obj.get('status', {}).get('readyReplicas', 0)))
    print(kube.call('-n', 'argocd', 'get', 'applications.argoproj.io'), end='')
    say('This status check does not change your existing access or sync settings.')
