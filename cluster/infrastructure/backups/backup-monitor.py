"""Poll backup Jobs; send transition-only Discord alerts. Never log credentials."""
import datetime as dt
import json
import ssl
import sys
from pathlib import Path
from urllib import request, parse

APPS = ('immich', 'tracearr', 'nextcloud', 'k3s')
BASE = 'https://kubernetes.default.svc'
API = '/apis/batch/v1/namespaces/backups/'
STATE = '/api/v1/namespaces/backups/configmaps/backup-alert-state'
SA = Path('/var/run/secrets/kubernetes.io/serviceaccount')


def timestamp(value):
    return dt.datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp() if value else 0


def evaluate(app, cron, jobs, previous, now):
    first = previous.get('first_seen', now)
    success = previous.get('last_success', 0)
    failures = [tuple(previous.get("last_failure", (0, "", "")))]
    if cron:
        success = max(success, timestamp(cron.get('status', {}).get('lastSuccessfulTime')))
    for job in jobs:
        containers = job.get('spec', {}).get('template', {}).get('spec', {}).get('containers', [])
        matching = False
        for c in containers:
            command = c.get('command', [])
            env = {e['name']: e.get('value') for e in c.get('env', [])}
            matching |= ('/scripts/backup-postgres.sh' in command and env.get('APP') == app)
            matching |= (app == 'k3s' and f'/scripts/backup-{app}.py' in command)
        if not matching:
            continue  # Exclude diagnostic and monitor Jobs.
        for condition in job.get('status', {}).get('conditions', []):
            if condition.get('status') != 'True':
                continue
            when = timestamp(condition.get('lastTransitionTime') or job['metadata']['creationTimestamp'])
            if condition['type'] == 'Complete':
                success = max(success, timestamp(job.get('status', {}).get('completionTime')) or when)
            elif condition['type'] == 'Failed':
                failures.append((when, job['metadata']['name'], job['metadata']['uid']))
    failure = max(failures, default=(0, '', ''))
    if not cron:
        key, detail = 'missing', 'Backup CronJob is missing.'
    elif cron.get('spec', {}).get('suspend', False):
        key, detail = 'suspended', 'Backup schedule is suspended.'
    elif failure[0] > success:
        key, detail = 'failed:' + failure[2], 'Backup Job failed: ' + failure[1]
    elif now - (success or first) > 26 * 3600:
        key, detail = 'stale', 'No successful backup within 26 hours.'
    else:
        key, detail = 'healthy', 'Backup monitoring is healthy.'
    return {'first_seen': first, 'last_success': success, 'last_failure': failure, 'key': key}, detail


def api(path, body=None):
    token = (SA / 'token').read_text().strip()
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    req = request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                          headers=headers, method='PUT' if body is not None else 'GET')
    with request.urlopen(req, context=ssl.create_default_context(cafile=str(SA / 'ca.crt')), timeout=20) as response:
        return json.load(response)


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def discord(message):
    url = Path('/discord/webhook-url').read_text().strip()
    parsed = parse.urlsplit(url)
    if parsed.scheme != 'https' or parsed.netloc != 'discord.com' or not parsed.path.startswith('/api/webhooks/'):
        raise ValueError('Invalid webhook endpoint')
    url = parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, 'wait=true', ''))
    payload = {'content': message[:1900], 'allowed_mentions': {'parse': []}}
    req = request.Request(url, data=json.dumps(payload).encode(),
                          headers={'Content-Type': 'application/json', 'User-Agent': 'HomelabBackupMonitor/1.0'})
    with request.build_opener(NoRedirect).open(req, timeout=20) as response:
        if response.status != 200:
            raise RuntimeError('Discord did not confirm delivery')
        response.read()


def main():
    now = dt.datetime.now(dt.timezone.utc).timestamp()
    state_obj = api(STATE)
    state = json.loads(state_obj.get('data', {}).get('state.json', '{}'))
    crons = {c['metadata']['name']: c for c in api(API + 'cronjobs')['items']}
    jobs = api(API + 'jobs')['items']
    if not state.get('initialized'):
        discord('Homelab backup monitoring connected. Checking Immich, Tracearr, Nextcloud and k3s every 5 minutes. Restore testing remains pending.')
        state['initialized'] = True
    for app in APPS:
        previous = state.get(app, {})
        current, detail = evaluate(app, crons.get(app + '-backup'), jobs, previous, now)
        if current['key'] != previous.get('key', 'healthy'):
            if current['key'] == 'healthy':
                discord(f'RECOVERED — {app}: backup alert cleared; schedule enabled and a recent successful Job exists.' if current['last_success'] else f'RECOVERED — {app}: schedule restored; still awaiting the first successful backup.')
            else:
                discord(f'BACKUP ALERT — {app}: {detail} Inspect Jobs in namespace backups.')
        state[app] = current
    state_obj.setdefault('data', {})['state.json'] = json.dumps(state)
    api(STATE, state_obj)  # resourceVersion protects against overlapping manual runs.
    print('Backup monitor check complete; delivery state saved.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # urllib exceptions can contain the webhook URL; never print their text.
        print('Backup monitor failed (' + type(exc).__name__ + '); inspect API access, Secret and Discord connectivity.', file=sys.stderr)
        sys.exit(1)
