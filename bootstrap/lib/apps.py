"""Application guidance and checks derived from repository manifests."""
import base64
import json
from .common import ROOT, Failure, confirm, hidden, say, yaml_module

REPO = 'https://github.com/rammad/homelab-platform.git'

def names():
    return sorted([p.name for p in (ROOT / 'cluster/apps').iterdir() if p.is_dir()] + ['database-backups'])

def source(name):
    if name == 'database-backups':
        return ROOT / 'cluster/infrastructure/backups'
    if name not in names():
        raise Failure('Unknown app. Choose: ' + ', '.join(names()))
    return ROOT / 'cluster/apps' / name

def documents(name):
    """Read checked-in inputs for offline guide only; check/register use rendering."""
    yaml = yaml_module()
    folder = source(name)
    k = folder / 'kustomization.yaml'
    paths = [folder / x for x in yaml.safe_load(k.read_text()).get('resources', [])] if k.exists() else sorted(folder.glob('*.yaml'))
    return [o for p in paths if p.is_file() for o in yaml.safe_load_all(p.read_text()) if isinstance(o, dict)]

def application(name):
    folder = source(name)
    yaml = yaml_module()
    matches = []
    for p in list((ROOT / 'bootstrap').glob('*application*.yaml')) + list((ROOT / 'argocd/edge-applications').glob('*.yaml')):
        for o in yaml.safe_load_all(p.read_text()):
            if isinstance(o, dict) and o.get('kind') == 'Application' and o.get('spec', {}).get('source', {}).get('path') == str(folder.relative_to(ROOT)):
                matches.append(o)
    if len(matches) > 1:
        raise Failure('Multiple Application definitions reference this path; reconcile ownership first.')
    if matches:
        return matches[0], True
    ns = {o['metadata'].get('namespace') for o in documents(name) if o.get('kind') == 'Deployment'} - {None}
    if len(ns) != 1:
        raise Failure('Cannot infer a single destination namespace; add an Application definition to the repo.')
    return {'apiVersion': 'argoproj.io/v1alpha1', 'kind': 'Application',
            'metadata': {'name': name, 'namespace': 'argocd'},
            'spec': {'project': 'default', 'source': {'repoURL': REPO, 'targetRevision': 'master', 'path': str(folder.relative_to(ROOT))},
                     'destination': {'server': 'https://kubernetes.default.svc', 'namespace': next(iter(ns))},
                     'syncPolicy': {'syncOptions': ['CreateNamespace=true', 'FailOnSharedResource=true']}}}, False

def guide(name):
    app, recorded = application(name)
    spec = app['spec']
    say(f'Argo → New App: {app["metadata"]["name"]}')
    for key, value in spec['source'].items():
        print(f'  {key}: {value}')
    print('  destination:', spec['destination'])
    print('  sync policy:', json.dumps(spec.get('syncPolicy', {})))
    if not recorded:
        say('No checked-in Application definition: these are suggested MANUAL-sync settings; registration will require adding a definition first.', 'WARN')
    if name == 'database-backups':
        print('  Setup: app storage database-backups → app secrets database-backups → app stage database-backups.')
        print('  Stage creates missing resources with ALL schedules suspended; it refuses existing CronJobs or Argo ownership.')
        print('  Run each backup manually, then review enabled schedules and sync the canonical registration.')
        print('  Discord uses backup-discord/webhook-url. Use existing database credentials, not new passwords.')
        print('  Full setup, activation and raw diagnostics: cluster/infrastructure/backups/README.md')
        return
    print('  1. Configure repository access in Argo if private (never paste tokens into Git).')
    print('  2. Prepare NAS exports/state, run app storage for missing PV/PVCs, configure Secrets, then app check.')
    print('  3. Create using the settings above, or use app register after checks pass.')
    print('  4. Review rendered resources in Argo before Sync. Registration may auto-sync if enabled above.')
    print('  5. Run app verify, then test the actual UI/workflow.')
    print('  Recovery prerequisites: docs/operations/application-state-recovery.md')
    if name == 'nextcloud':
        say('Existing-installation workflow only: restore config.php, zzz-k3s.config.php, version.php, PostgreSQL 13 data and user files/.ncdata. Fresh Nextcloud initialization is not implemented.', 'WARN')
    if name in ('emby', 'tdarr'):
        say('Verify GPU host, render-device permissions and media/cache paths. Do not restart active streams/jobs.', 'WARN')
    if name == 'qbittorrent':
        say('Restore private VPN configuration and BT_backup; preserve tracker-approved image and paths. Verify VPN behavior and seeding before accepting recovery.', 'WARN')

def render(name, kube):
    yaml = yaml_module()
    folder = source(name)
    if (folder / 'kustomization.yaml').exists():
        return [o for o in yaml.safe_load_all(kube.call('kustomize', str(folder))) if o]
    return documents(name)

def secret_refs(objects):
    refs = {}
    def walk(value, ns):
        if isinstance(value, list):
            for item in value: walk(item, ns)
        elif isinstance(value, dict):
            ref = value.get('secretKeyRef')
            if ref and not ref.get('optional'):
                refs.setdefault((ns, ref['name']), set()).add(ref['key'])
            if 'secretRef' in value or 'secret' in value and 'secretName' in value.get('secret', {}):
                # Whole-secret mounts/envFrom require explicit configuration rather than invented keys.
                ref = value.get('secretRef', value.get('secret', {}))
                if not ref.get('optional'):
                    refs.setdefault((ns, ref.get('name', ref.get('secretName'))), set()).update(
                        item['key'] for item in ref.get('items', []))
            for child in value.values(): walk(child, ns)
    for obj in objects:
        walk(obj.get('spec', {}), obj.get('metadata', {}).get('namespace', 'default'))
    return refs

def check(name, kube, inside=False):
    kube.identity()
    app, _ = application(name)
    namespace = app['spec']['destination']['namespace']
    objects = render(name, kube)
    problems = []
    if not kube.get('namespace', namespace): problems.append(f'Namespace missing: {namespace}')
    for (ns, secret), keys in sorted(secret_refs(objects).items()):
        obj = kube.get('secret', secret, ns, sensitive=True)
        missing = keys - {k for k, v in (obj or {}).get('data', {}).items() if v}
        if obj is None or missing:
            problems.append(f'Secret {ns}/{secret}: missing object or keys {", ".join(sorted(missing))}')
        else: say(f'Secret {ns}/{secret}: required keys present (values hidden)', 'OK')
    claims = set()
    def find_claims(value, ns):
        if isinstance(value, list):
            for child in value: find_claims(child, ns)
        elif isinstance(value, dict):
            ref = value.get('persistentVolumeClaim')
            if ref and ref.get('claimName'): claims.add((ns, ref['claimName']))
            for child in value.values(): find_claims(child, ns)
    for obj in objects:
        find_claims(obj.get('spec', {}), obj.get('metadata', {}).get('namespace', namespace))
    for obj in objects:
        kind, meta = obj.get('kind'), obj.get('metadata', {})
        ns = meta.get('namespace', namespace)
        if kind == 'PersistentVolume':
            nfs = obj['spec'].get('nfs')
            if nfs: say(f'Declared NFS: {nfs["server"]}:{nfs["path"]}; server-side existence/ACLs require verification', 'WARN')
        if kind == 'PersistentVolumeClaim':
            claims.add((ns, meta['name']))
    for ns, claim in sorted(claims):
        live = kube.get('pvc', claim, ns)
        if not live or live.get('status', {}).get('phase') != 'Bound':
            problems.append(f'PVC {ns}/{claim} not Bound; prepare its owning app storage first')
        else: say(f'PVC {ns}/{claim}: Bound', 'OK')
    existing = kube.get('applications.argoproj.io', app['metadata']['name'], 'argocd')
    if existing:
        desired = app['spec']
        live = existing['spec']
        for field in ('source', 'destination'):
            if live.get(field) != desired.get(field): problems.append(f'Argo {field} differs from repo; inspect, do not overwrite blindly')
        say('Argo Application exists; status: ' + json.dumps(existing.get('status', {}).get('sync', {})))
    else: say('Argo Application is not registered.', 'WARN')
    if inside:
        if name != 'nextcloud':
            raise Failure('--inside is currently implemented only for Nextcloud; other app checks do not inspect private files.')
        kube.call('-n', namespace, 'exec', 'deployment/nextcloud', '-c', 'nextcloud', '--',
                  'su', '-s', '/bin/sh', 'www-data', '-c',
                  'test -s /var/www/html/config/config.php && test -s /var/www/html/config/zzz-k3s.config.php && test -r /var/www/html/data/.ncdata && test -w /var/www/html/data')
        say('Nextcloud required config/marker and data access verified as www-data; file contents not printed.', 'OK')
    else:
        say('File contents, NFS access as app UID, and end-to-end behavior are not proven by Kubernetes object checks.', 'WARN')
    for problem in problems: say(problem, 'WARN')
    return not problems

def configure_secrets(name, kube, replace=False, dry_run=False):
    kube.identity()
    refs = secret_refs(render(name, kube))
    if not refs:
        say('No required secretKeyRef inputs found. Private app configs and hardcoded legacy credentials need separate review.')
        return
    for (ns, secret), keys in sorted(refs.items()):
        if not keys: raise Failure(f'{ns}/{secret} has no declared individual keys; configure it using its documented schema.')
        if not kube.get('namespace', ns): raise Failure(f'Create namespace {ns} explicitly first; no implicit namespace changes.')
        existing = kube.get('secret', secret, ns, sensitive=True)
        meta = (existing or {}).get('metadata', {})
        if meta.get('ownerReferences') or meta.get('annotations', {}).get('argocd.argoproj.io/tracking-id') or meta.get('labels', {}).get('app.kubernetes.io/instance'):
            raise Failure(f'{ns}/{secret} appears controller-managed; update its source instead.')
        if existing and existing.get('type', 'Opaque') != 'Opaque': raise Failure('Refusing to alter a non-Opaque Secret.')
        if existing and existing.get('immutable'): raise Failure('Secret is immutable; no replacement attempted.')
        present = {k for k, v in (existing or {}).get('data', {}).items() if v}
        selected = keys if replace else keys - present
        if not selected:
            say(f'{ns}/{secret}: keys exist; unchanged. Use --replace only for deliberate rotation.', 'OK')
            continue
        if not confirm(f'{"Update" if existing else "Create"} {ns}/{secret}, keys: {", ".join(sorted(selected))}. Values stay hidden. Running containers will NOT restart.', dry_run):
            continue
        values = {}
        for key in sorted(selected):
            value = hidden(f'{key}: ')
            if value != hidden(f'Confirm {key}: '): raise Failure('Values did not match; Secret not written.')
            values[key] = base64.b64encode(value.encode()).decode()
        if existing:
            merged = dict(existing.get('data', {})); merged.update(values)
            payload = [{'op': 'test', 'path': '/metadata/resourceVersion', 'value': meta['resourceVersion']},
                       {'op': 'add', 'path': '/data', 'value': merged}]
            kube.call('-n', ns, 'patch', 'secret', secret, '--type=json', '--patch-file=/dev/stdin', data=json.dumps(payload), sensitive=True)
        else:
            payload = {'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': secret, 'namespace': ns}, 'type': 'Opaque', 'data': values}
            kube.call('create', '-f', '-', data=json.dumps(payload), sensitive=True)
        observed = kube.get('secret', secret, ns, sensitive=True)
        if not observed or any(observed.get('data', {}).get(k) != v for k, v in values.items()):
            raise Failure('Secret readback did not match; investigate without printing values.')
        say(f'{ns}/{secret}: update verified. Coordinate dependent services before any rollout; environment values do not refresh automatically.', 'OK')

def prepare_storage(name, kube, dry_run=False):
    kube.identity()
    app, _ = application(name)
    ns = app['spec']['destination']['namespace']
    objects = render(name, kube)
    pending = []
    if not kube.get('namespace', ns):
        pending.append({'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': ns}})
    for obj in objects:
        if obj.get('kind') not in ('PersistentVolume', 'PersistentVolumeClaim'):
            continue
        kind, meta = obj['kind'], obj['metadata']
        namespace = meta.get('namespace', ns) if kind == 'PersistentVolumeClaim' else None
        live = kube.get(kind, meta['name'], namespace)
        if live:
            # Protect accidental reuse of an existing volume pointing somewhere else.
            fields = ('nfs', 'storageClassName', 'accessModes', 'volumeMode') if kind == 'PersistentVolume' else ('volumeName', 'storageClassName', 'accessModes')
            for field in fields:
                if field in obj['spec'] and live['spec'].get(field) != obj['spec'][field]:
                    raise Failure(f'Existing {kind}/{meta["name"]} differs in {field}; no changes made.')
            owner = live.get('metadata', {}).get('annotations', {}).get('argocd.argoproj.io/tracking-id', '')
            if owner and not owner.startswith(app['metadata']['name'] + ':'):
                raise Failure('Storage belongs to another Argo app: ' + owner.split(':')[0])
            say(f'{kind}/{meta["name"]} exists; left unchanged.', 'OK')
        else:
            pending.append(obj)
    if not pending:
        say('Storage objects already exist. Run app check for binding status.', 'OK'); return
    for obj in pending:
        say(f'Create {obj["kind"]}/{obj["metadata"]["name"]}')
        nfs = obj.get('spec', {}).get('nfs')
        if nfs: print('  Existing NAS export required:', nfs['server'] + ':' + nfs['path'])
    if not confirm('Create only missing namespace/PV/PVC objects. This does not create NAS directories, initialize app data or start workloads. Verify exports and backups first.', dry_run): return
    for obj in pending:
        kube.call('create', '-f', '-', data=json.dumps(obj))
        namespace = obj['metadata'].get('namespace', ns) if obj['kind'] == 'PersistentVolumeClaim' else None
        if not kube.get(obj['kind'], obj['metadata']['name'], namespace):
            raise Failure('Created resource could not be read back.')
    say('Storage objects created. Run app check; Bound does not prove filesystem access.', 'OK')


def register(name, kube, dry_run=False):
    app, recorded = application(name)
    guide(name)
    if not recorded: raise Failure('Add/review a canonical Application YAML in bootstrap first; no ad hoc ownership definitions created.')
    kube.identity()
    if kube.get('applications.argoproj.io', app['metadata']['name'], 'argocd'):
        say('Already registered. Run app check; this command never overwrites an existing Application.', 'WARN')
        return
    if not check(name, kube): raise Failure('Prerequisite checks failed. Resolve storage/Secrets before registration.')
    # Refuse differently named owners of the same repository path.
    all_apps = json.loads(kube.call('-n', 'argocd', 'get', 'applications.argoproj.io', '-o', 'json'))
    for existing in all_apps.get('items', []):
        sources = [existing['spec'].get('source', {})] + existing['spec'].get('sources', [])
        if any(s.get('repoURL') == app['spec']['source']['repoURL'] and s.get('path') == app['spec']['source']['path'] for s in sources):
            raise Failure('Another Application already manages this source path: ' + existing['metadata']['name'])
    if not confirm('Register the displayed Application. Its configured automatic sync may immediately start workloads. Confirm Git has your reviewed manifests.', dry_run): return
    kube.call('create', '-f', '-', data=json.dumps(app))
    live = kube.get('applications.argoproj.io', app['metadata']['name'], 'argocd')
    if not live or live['spec']['source'] != app['spec']['source']: raise Failure('Application registration readback mismatch.')
    say('Application registered. Review Argo diff, sync if manual, then run app verify.', 'OK')

def verify(name, kube):
    kube.identity()
    for obj in render(name, kube):
        if obj.get('kind') in ('Deployment', 'StatefulSet', 'DaemonSet'):
            ns = obj['metadata'].get('namespace', 'default')
            print(kube.call('-n', ns, 'rollout', 'status', obj['kind'].lower() + '/' + obj['metadata']['name'], '--timeout=180s', timeout=195), end='')
    app, _ = application(name)
    live = kube.get('applications.argoproj.io', app['metadata']['name'], 'argocd')
    status = (live or {}).get('status', {})
    say(f'Argo: {status.get("sync", {}).get("status", "Unknown")} / {status.get("health", {}).get("status", "Unknown")}')
    if status.get('sync', {}).get('status') != 'Synced' or status.get('health', {}).get('status') != 'Healthy':
        raise Failure('Argo is not yet Synced/Healthy; inspect its diff/events.')
    if name == 'database-backups':
        say('Argo checks passed; verify completed backup Jobs, Discord delivery and isolated restores using the runbook.', 'OK')
    else:
        say('Kubernetes rollout and Argo checks passed. Still test login, existing data and one real app workflow.', 'OK')


def stage(name, kube, dry_run=False):
    """Initial backup setup only; never suspend or overwrite an installed schedule."""
    if name != 'database-backups':
        raise Failure('Staging is supported only for database-backups.')
    kube.identity()
    objects = render(name, kube)
    owners = json.loads(kube.call('-n', 'argocd', 'get', 'applications.argoproj.io', '-o', 'json'))
    for owner in owners.get('items', []):
        sources = [owner['spec'].get('source', {})] + owner['spec'].get('sources', [])
        if any(s.get('path') == 'cluster/infrastructure/backups' for s in sources):
            raise Failure('Backups already registered in Argo; use its reviewed sync workflow.')
    for obj in objects:
        if obj['kind'] == 'CronJob':
            if kube.get('cronjob', obj['metadata']['name'], 'backups'):
                raise Failure('Backup schedules already exist; staging is for first installation only.')
            obj['spec']['suspend'] = True
    pending = []
    for obj in objects:
        meta = obj['metadata']
        ns = meta.get('namespace')
        if kube.get(obj['kind'], meta['name'], ns):
            # Namespace/storage are prepared separately. Never overwrite existing state/RBAC/scripts.
            if obj['kind'] not in ('Namespace', 'PersistentVolume', 'PersistentVolumeClaim'):
                raise Failure('Existing backup resource found; inspect partial installation before continuing.')
        else:
            pending.append(obj)
    if not check(name, kube):
        raise Failure('Prepare storage and Secrets before staging.')
    if not confirm('Create backup resources with all CronJobs suspended. No backup or Discord message runs yet.', dry_run):
        return
    for obj in pending:
        kube.call('create', '-f', '-', data=json.dumps(obj))
        live = kube.get(obj['kind'], obj['metadata']['name'], obj['metadata'].get('namespace'))
        if not live or (obj['kind'] == 'CronJob' and live.get('spec', {}).get('suspend') is not True):
            raise Failure('Staging readback mismatch; inspect partial installation.')
    say('Staged suspended schedules. Follow the backup runbook for manual runs and activation.', 'OK')
