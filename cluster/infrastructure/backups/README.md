# Backups and Discord notifications

Scheduled Kubernetes Jobs export application and cluster state to another NAS
pool. A separate monitor reports failed or overdue backups to Discord. 

As of **2026-11-05**, operator logs confirm successful manual backups for all
four public targets, and the operator reports their schedules enabled. Discord received
the monitor's connection message and its Job completed. The first overnight
scheduled runs, live failure/recovery notification exercise and isolated restore
drills remain unverified. Restore drills were deliberately deferred.

## Coverage and schedules

All schedules use `America/Los_Angeles`. Workloads remain online during export.

| CronJob | Time | Captured state |
|---|---|---|
| `immich-backup` | 01:00 | PostgreSQL database |
| `tracearr-backup` | 01:20 | PostgreSQL/TimescaleDB database |
| `nextcloud-backup` | 01:40 | PostgreSQL database |
| `k3s-backup` | 02:30 | SQLite control-plane state, server token and selected configuration |
| `backup-monitor` | Every 5 minutes | Job/schedule checks and Discord state-change notifications |

Archives live on `storage-pool/cluster-backups`, separate from the application SSD
pool but on the **same NAS**. Each exporter keeps the new successful backup plus
13 prior completed copies. Manual runs count toward these 14 runs; this is not
necessarily 14 days. Retention runs after successful archive checks and ignores
partial, unrecognized and symlink entries. Snapshots can retain deleted blocks.

Nightly database backups target roughly 24 hours of data loss, extended by failed
runs. Archive validation is not a restore test. These are unencrypted, sensitive
archives; k3s state includes Kubernetes Secrets and administrator credentials.
Never commit archives, kubeconfigs, database credentials or webhook URLs.

## 1. Prepare the NAS

Create `storage-pool/cluster-backups` with compression enabled, dedup off, sync
Standard, atime off and no SMB share. Use a non-login backup account with UID
3900 and primary GID 3001, directory mode 0700. These IDs match the manifests;
if occupied on a new system, select unused IDs and change the manifests together.
Do not recursively change permissions on the parent pool.

Export `/mnt/storage-pool/cluster-backups` read/write through NFS to the master
`192.0.2.10`, with Maproot/Mapall unset. AUTH_SYS trusts client numeric IDs;
this is not strong authentication against root on an authorized host.

Set a capacity budget using a dataset **quota** if snapshots must count toward
it. The observed initial limit was a 100 GiB **refquota**, which excludes snapshot
usage; a total quota was not confirmed. The PVC's 100Gi does not enforce either.

Initialize the marker once, after setting ownership:

```bash
sudo sh -eu -c '
  p=/mnt/storage-pool/cluster-backups
  test "$(stat -c %u:%g "$p")" = 3900:3001
  test ! -e "$p/.backup-target"
  umask 077
  printf "%s\n" homelab-cluster-backups-v1 > "$p/.backup-target"
  chown 3900:3001 "$p/.backup-target"
'
```

Before running jobs, test marker read and file create/write/rename/delete over
NFS as **3900:3001** from the master. A Bound PVC alone does not prove access.
The current installation passed this check on 2026-11-05.

## 2. Bootstrap a new installation

Run from the repository root on a host with Python/PyYAML and cluster access.
Review the NAS paths, host selector and pinned images first. The setup toolkit
uses existing manifests; it does not duplicate workload YAML or configure TrueNAS.

```bash
bash bootstrap/bootstrap.sh app guide database-backups
bash bootstrap/bootstrap.sh --kubectl 'sudo k3s kubectl' app storage database-backups
bash bootstrap/bootstrap.sh --kubectl 'sudo k3s kubectl' app secrets database-backups
bash bootstrap/bootstrap.sh --kubectl 'sudo k3s kubectl' app stage database-backups
```

`storage` creates missing namespace/PV/PVC objects. `secrets` prompts twice with
hidden input, preserves existing keys and verifies writes without displaying
values. It configures:

| Secret (namespace `backups`) | Required keys / source |
|---|---|
| `immich-backup-db` | `PGUSER`, `PGPASSWORD`, `PGDATABASE`: existing Immich database credentials |
| `tracearr-backup-db` | Same keys: existing Tracearr database credentials |
| `nextcloud-backup-db` | Same keys: private Nextcloud config.php `dbuser`, `dbpassword`, `dbname` |
| `backup-discord` | `webhook-url`: a Discord channel webhook created under Server Settings → Integrations → Webhooks |

Do not guess defaults or change database passwords to configure a backup.
Credential updates use `app secrets database-backups --replace`; this deliberately
prompts for all required keys, so have each available. New Jobs read updated
Secrets; existing Jobs are not restarted. Credentials may currently be broader
than a dedicated dump role; least-privilege roles need separate validation.

`stage` creates first-install resources with **all CronJobs suspended**, even
though the canonical manifests are enabled. It refuses existing CronJobs or an
Argo registration for this path. It never overwrites alert state or existing
scripts/RBAC. A partially failed stage requires inspection using raw kubectl;
there is no automatic rollback or destructive retry. It requires Argo CRDs.
**Do not run stage against the already installed system.**

## 3. Validate manually, then activate

Run one backup at a time, replacing `immich` below with `tracearr`, `nextcloud`,
then `k3s`. Use a new Job name on every attempt:

```bash
job="immich-backup-manual-$(date +%s)"
sudo k3s kubectl -n backups create job --from=cronjob/immich-backup "$job"
sudo k3s kubectl -n backups logs -f "job/$job" --pod-running-timeout=180s
sudo k3s kubectl -n backups wait --for=condition=complete "job/$job" --timeout=1900s
```

A suspended CronJob permits manual Jobs. Confirm completion and the archive's
checks; do not infer success from an empty log stream. Never run concurrent manual
backups for one app. Exporters use per-app locks; timeout/node failure may leave
`.lock` or `.partial.*`. Confirm no exporter is running before removing leftovers.

After all manual runs succeed, choose **one deployment owner**:

- **Argo:** publish reviewed changes yourself, then run `app register database-backups`.
  The canonical registration is `bootstrap/database-backups-application.yaml`,
  name `database-backups`, path `cluster/infrastructure/backups`, destination
  namespace `backups`. It uses manual sync and is not included in the parent app.
  Review the rendered diff and Sync to enable schedules.
- **Direct kubectl (current operator workflow):** apply the reviewed directory:

```bash
sudo k3s kubectl apply --dry-run=server -k cluster/infrastructure/backups &&
sudo k3s kubectl apply -k cluster/infrastructure/backups
sudo k3s kubectl -n backups get cronjobs
```

All six CronJobs should show `SUSPEND=False`. Apply scripts and CronJobs together.
Activation can catch up a missed backup within its 600-second starting deadline.
The exporter deadline is 30 minutes, with no automatic retries; Forbid prevents
same-CronJob scheduled overlap, not manual overlap or overlap between apps.

Wait up to five minutes for the first Discord connection message and a Complete
monitor Job. On a fresh staged install, do this after activation to avoid alerts
about deliberately suspended schedules. An already initialized monitor stays
quiet when healthy; reapplying configuration does not reset its state.

## Raw operational checks

Routine troubleshooting belongs here, not in a growing bootstrap command suite.

```bash
sudo k3s kubectl -n backups get cronjobs
sudo k3s kubectl -n backups get jobs --sort-by=.metadata.creationTimestamp
sudo k3s kubectl -n backups get pods
# Substitute the actual failing Job/pod name:
sudo k3s kubectl -n backups logs job/JOB_NAME --all-containers=true --tail=100
sudo k3s kubectl -n backups describe pod POD_NAME
```

Old failed attempts may remain after a successful retry. Inspect the newest
relevant result and its timestamp. Database dump errors are deliberately generic
to avoid exposing credentials; check database logs privately for authentication
or connectivity errors. Never paste Secret values into diagnostic output.

The Discord monitor alerts on a new failure, a missing/suspended schedule, or
26 hours without success, and sends recovery transitions. Manual exporter Jobs
count; diagnostic Jobs do not. A new monitor with no success history grants a
26-hour initial grace period. Persisted times in `backup-alert-state` survive Job
history pruning. Unchanged alerts are not repeated every five minutes.

The monitor has no NFS mount. Its ServiceAccount can list Jobs/CronJobs only in
`backups`, and get/update only its state ConfigMap. It cannot read Secrets through
the API or change workloads; the webhook is a mounted Secret. Discord delivery
uses confirmation, disabled mentions and no redirects. State saves after delivery;
failed delivery/state writes retry and can produce duplicates.

**Coverage limit:** this is backup monitoring, not general Kubernetes/TrueNAS/Emby
alerting. It observes Job results, not later archive deletion/corruption. A broken
monitor, cluster/API outage or Discord outage may prevent alerts. An independent
heartbeat remains pending. No live failure/recovery notification drill is claimed.

## Export details and recovery limits

PostgreSQL exports include a custom-format dump, table-of-contents validation,
checksums, timestamps and server/client/extension versions. Restore Tracearr with
its compatible TimescaleDB version/procedure and Immich with compatible extensions.
Roles/global grants and general app configs are not captured by these SQL dumps.
Nextcloud stays online: its dump is not coordinated with user-file/config changes,
so it is not a complete point-in-time recovery set.

k3s runs only on the master. It uses SQLite's online backup API for `db/state.db`,
checks integrity and the kine table, and includes the server token, server
certificates/manifests, `/etc/rancher`, k3s systemd unit/env/drop-ins and kubelet
configuration. Live WAL/SHM are excluded. Token rotation during export fails the
job; avoid concurrent token/certificate/config changes because those files are
not captured atomically with the database. It reads the source with restricted root capabilities, then drops to the backup
UID/GID before writing the destination. It never stops k3s.

This exporter requires the default SQLite datastore and refuses etcd. Symlinks
are preserved, not dereferenced; the actual server token is explicitly copied.
External link targets, optional `/etc/default/k3s` or `/etc/sysconfig/k3s`, local
PV contents, container images and the complete OS/network configuration are not
included. Record `sudo k3s --version` after upgrades; the last operator-verified
control-plane version was `v1.35.5+k3s1`.

For a k3s restore drill, use an isolated stopped target with a compatible version,
inspect the archive in staging, restore datastore/token and applicable config,
and remove any stale WAL/SHM from a different database. Preserve modes/owners and
handle networking/storage separately. Never boot a duplicate production IP/node
identity, or unpack blindly over a running cluster.

## TrueNAS snapshot layer

Operator screenshots confirmed these tasks enabled on 2026-11-05; their first
scheduled executions remain to be checked in TrueNAS Data Protection.

| Dataset | Schedule / retention |
|---|---|
| `storage-pool/media-data` | Daily midnight / 2 days |
| `storage-pool/nextcloud-data` | Hourly / 1 day; daily midnight / 2 weeks |
| `application-pool/k3s-app-data` | Hourly / 1 day; daily midnight / 2 weeks; recursive |
| `application-pool/configs/immich/storage` | Hourly / 1 day; daily midnight / 2 weeks; recursive |
| `storage-pool/cluster-backups` | Daily 03:00 / 2 weeks |

Use distinct `hourly-%Y-%m-%d_%H-%M` and `daily-%Y-%m-%d_%H-%M` names and confirm
NAS timezone. Include child datasets recursively where needed. Local snapshots
preserve changed/deleted blocks, not a full duplicate each time, but Tdarr rewrites
and download churn can consume substantial space. Check growth after 48 hours and
a full retention cycle. They do not protect against pool loss or prove database
consistency. NAS snapshots/exports are administered in TrueNAS, outside bootstrap.

## Remaining recovery work

- Verify first overnight schedules, snapshots and storage growth.
- Restore all four public targets into isolated environments; record results and time.
- Exercise Discord failure/recovery and add an independent outage heartbeat.
- Add coordinated Nextcloud files/config/database recovery points.
- Protect remaining app configs and irreplaceable assets with independent copies.
- Arrange encrypted off-machine backups; review total quota including snapshots.

## Local validation

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s bootstrap/tests -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s cluster/infrastructure/backups/tests -v
bash -n cluster/infrastructure/backups/backup-postgres.sh cluster/infrastructure/backups/retain-backups.sh
```

These tests cover local fixtures/mocks; they are not live disaster-recovery tests.

References: [k3s recovery](https://docs.k3s.io/datastore/backup-restore),
[SQLite online backup](https://sqlite.org/backup.html),
[PostgreSQL dumps](https://www.postgresql.org/docs/current/app-pgdump.html),
[Nextcloud backup](https://docs.nextcloud.com/server/stable/admin_manual/maintenance/backup.html).
