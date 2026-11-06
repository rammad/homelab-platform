# TiasTube

Single-replica finance/usage tracker in `tools`. SQLite is embedded in the app
process, not a separate service/pod. Source code is mounted from hash-versioned
Kustomize ConfigMaps into an immutable standard Python image; no external package
install or image-build service is needed. ConfigMap hash changes roll the pod.

- LAN URL: http://192.0.2.10:30865 (NodePort; no public Ingress).
- NAS: `192.0.2.30:/mnt/application-pool/k3s-app-data/tiastube`.
- Persistent database: `/data/tracearr.sqlite3`.
- Private configuration/backups: `/data/private/tracearr/`.
- Argo registration: `bootstrap/tiastube-application.yaml`.
- App resources: this Kustomize directory. Argo tracks `master`; registration and sync are manual.

## Initial import on a new installation

The existing installation is operational (operator browser/sync check, 2026-11-05).
Do not rerun this import to maintain the running instance.

Create a consistent migration archive on the current app host using
`source/export_migration.py`. It contains the current database and private
Tracearr configuration, so keep it mode 0600, transfer privately, and never
commit/upload it to GitHub. The repository contains source and fixtures only.

On the k3s master, with a fresh checkout containing this commit:

```sh
sudo bash cluster/apps/tiastube/bootstrap.sh /path/to/tiastube-migration.tar
```

The bootstrap checks the NodePort, mounts the existing parent NFS export in a
short-lived pod, creates only the new `tiastube` directory, imports and checks
the database, validates manifests with the API server, and stops. Register the Argo
Application using `bootstrap/tiastube-application.yaml`, then sync it manually. It refuses to overwrite an existing app or data directory. The pod
is removed on exit. An interrupted rollout may leave imported NAS data; inspect
that directory and register the Application directly rather than deleting data
to make the initial-import script run again.

If starting empty deliberately, create the dedicated NAS directory and apply
the Argo registration; production mode creates schema but no demo users or costs.
Configure Tracearr through Data & backups. Do not use this empty-start path when
migrating existing records.

After a verified rollout, stop writes to the old local app. Use the production
instance as the source of truth; its SQLite file is independent of the old copy.

## Storage and updates

`Recreate` and one replica prevent overlapping pods during normal rollouts. A
process lock rejects a second process using the same data path. Keep this
configuration; never scale out, force-delete a partitioned pod, or mount the
live database in another app. SQLite uses rollback journaling (`DELETE`) and
`FULL` synchronous writes; WAL is deliberately disabled on NFS.

NFS locking/fsync semantics are a residual reliability dependency, even with
one writer. See [SQLite over a network](https://www.sqlite.org/useovernet.html)
and [WAL restrictions](https://www.sqlite.org/wal.html). Successful mount/restore
tests cannot establish safety under all NAS/network failures. If that risk is
unacceptable, use local/block storage for the live SQLite file with NAS backups,
or migrate to a database server. Do not silently enable WAL on this share.

PV reclaim policy is Retain. The static capacity is a binding declaration, not
an NFS dataset quota. Credentials and daily backups persist in the app directory.
Thirty daily copies are retained; manual/import/recovery copies need manual
housekeeping. Copies on the same pool do not protect against loss of that pool;
download or replicate backups separately. Backup/restore controls check integrity
and preserve a safety copy before restoring. Restore is blocked during sync.

No public DNS, public ingress, authentication, or WAN forwarding is configured.
Access is intended for the trusted LAN; do not forward port 30865 from WAN.
If the LAN address/port changes, update both allowed hosts and origins in the
Deployment and the Service together.

## Validate and operate

```sh
python3 -m unittest discover -s cluster/apps/tiastube/source -v
kubectl kustomize cluster/apps/tiastube >/tmp/tiastube-rendered.yaml
kubectl apply --dry-run=server -k cluster/apps/tiastube
kubectl -n argocd get application tiastube
kubectl -n tools rollout status deployment/tiastube
kubectl -n tools logs deployment/tiastube --tail=100
```

Health probes check HTTP responsiveness. The Data & backups page separately
reports Tracearr sync health, last success, and backup errors. Sync runs hourly
with a 45-day overlap and weekly full reconciliation; it never auto-approves
usage. Network/API failures preserve the last successful import. Approved-month
usage changes are flagged for manual review without rewriting charges.

To roll back code, revert the relevant source/manifests in Git; sync Argo manually to recreate
the app using the previous code with the retained data. Do not roll back to an
incompatible schema without a matching backup. For data recovery, use the app's
backup upload/restore UI and inspect its before-restore safety copy.

## Pre-deployment validation (2026-10-29)

24 tests passed on the host and inside the pinned Python image. A disposable
production container passed health, empty-start (no fictional records), and
automatic-backup checks. Kustomize rendering and generated ConfigMap references
were checked. At that pre-deployment checkpoint, live admission, NFS behavior and rollout
were still unverified. Subsequent operator reports confirmed the app running;
see the dated startup incident and ConfigMap cleanup below.

## Kubernetes service environment collision (2026-10-29)

The first live startup failed because Kubernetes generated `TIASTUBE_PORT`
with a `tcp://...` value for the `tiastube` Service. The app previously tried
to parse that value as an integer. It now reads `TIASTUBE_HTTP_PORT`, explicitly
set to `8765` in the Deployment, and service-link environment injection is
disabled with `enableServiceLinks: false`. Regression tests include the actual
service-URL format. This describes the historical startup fix now present in the Deployment;
no storage changes or data reset are needed.

## Tracearr pagination recovery

When IDs overlap, the scan re-reads the affected page neighbourhood using
shifted boundaries to recover missing IDs. The scan retries up to three times
if unique IDs still fall short, totals change, or pagination ends early. Every attempt starts at page one and discards
all partial records from the failed attempt. Page sizes 100, 99, and 97 move
boundaries around equal playback timestamps in the upstream offset sort.
Only a scan containing the advertised number of unique IDs is imported;
persistent inconsistencies still fail without modifying usage or its success
watermark. Malformed records fail directly with resource/page details. This
mitigates offset instability; it does not create an upstream snapshot guarantee.

## Ledger review

The ledger defaults to actual money (contributions, purchases, refunds and
subscriptions), excluding usage deductions and hypothetical streaming costs.
Filter by person, charged group, entry type, inclusive date range or text; sort
by date, amount, description or person. Person filters use contribution
attribution; use the group filter to inspect pooled/shared-device charges.
Filters combine, stay selected while navigating or editing in the current page
session, and do not change records or charts. Reset restores the actual-money
view with newest entries first.

## User breakdowns

Click a person in the dashboard's balances list to open their full user
page: personal transactions, current physical-device/client mappings, pooled
group balance, and monthly viewing hours/device counts. A user selector includes
people with no contributions. Personal and group ledger shortcuts retain the
distinction between donor attribution and shared-device charges.

Viewing statistics use sessions longer than 10 minutes, independently of approved
billing thresholds or waived months. Physical devices are deduplicated per person
and month using current mappings; unmapped qualifying clients are counted
separately. Averages include zero-activity months from first imported activity
through the last completed month; the partial current month appears on charts
but does not affect averages. These are viewing statistics, not frozen billing
snapshots. No schema migration is needed.

The dashboard keeps one balances list with individual profile links (including
each member of pooled groups). Usage review and spending categories stack in
the right column, collapsing beneath balances on narrow screens.

## Generated ConfigMap cleanup — 2026-11-05

The operator removed obsolete generated ConfigMaps and three zero-replica
ReplicaSets after comparing references against the running pod. The current
revision and persistent storage were retained. The operator then confirmed Argo
reported Synced and the browser UI worked. This removed old Kubernetes rollout
history; recreate older code through a Git revert and sync if needed.
For future cleanup, inspect live pod, Deployment and retained ReplicaSet
references before pruning generated ConfigMaps. Do not disable Kustomize hashes
just to suppress obsolete-resource drift.
