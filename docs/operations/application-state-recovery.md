# Application state and recovery prerequisites

Reviewed against repository manifests and migration evidence on 2026-11-05.
This documents the existing installations' dependencies; it is not a tested
one-command rebuild or a replacement for application-specific restore procedures.

## Common requirements

Keep app-consistent backups off the compute node. NAS persistence, a replicated
image archive and a Git checkout protect different things. Restoring a Deployment
does not recreate its private configuration or database. Do not start an old and
new application instance against the same writable database. Stop writers before
physical database copies; preserve numeric ownership and hidden files, compare
content, and retain an untouched backup. A copy of a running database directory
is not automatically a consistent backup.

Check NFS exports from the actual node and with the pod's UID/GID. Preserve
container paths, not only host paths. Check read/write and disposable
create/rename/delete operations in the exact app/download/library directories;
do not recursively relax ACLs on the whole pool. Use database integrity checks
on a suitable stopped copy, not casually against live data. These checks do not
prove NFS locking or failure durability.

## Nextcloud existing-installation recovery

The manifests require an existing Nextcloud 31.0.9 installation and PostgreSQL
13 data. Restore compatible versions before considering an upgrade. The app
mounts /mnt/application-pool/k3s-app-data/nextcloud/html at /var/www/html, postgres state
from the sibling postgres directory, and the separate files export
/mnt/storage-pool/nextcloud-data/user-data at /var/www/html/data. Check the current
storage manifests before restoring. Web files use UID 33; PostgreSQL uses UID 999.

Preserve the private config.php (including instance identity, salts, secrets and
database credentials), installation/custom-app files, database and user files as
a consistent set. Physical PostgreSQL copies require clean shutdown, compatible
major version and any referenced tablespaces; do not blindly copy live data or
omit symlink targets. A logical database restore is a separate procedure.

The init container explicitly requires config/zzz-k3s.config.php. The retired
migration script created this override; retain it in the private app backup:

```php
<?php
$CONFIG = [
    'dbhost' => 'nextcloud-db',
    'redis' => ['host' => 'nextcloud-cache', 'port' => 6379,
                'password' => getenv('REDIS_HOST_PASSWORD')],
    'overwriteprotocol' => 'https',
    'overwrite.cli.url' => 'https://nextcloud.example.com',
];
```

The original script set this file to owner 33:33 and mode 640. The data root
must contain the existing .ncdata marker and be writable by UID 33. Restore
Secret data/nextcloud-cache-auth with key password; both app and cache must use
the same value. Verify occ status, web login, existing files and a new sync/upload.
Never publish private config.php or database dumps in Git.

## Download-client integration and Secrets

| Namespace | Secret | Required keys |
|---|---|---|
| media | unpackerr-credentials | UN_SONARR_0_API_KEY, UN_RADARR_0_API_KEY |
| media | nzbget-credentials | NZBGET_USER, NZBGET_PASS |

For an absent Secret, populate a mode-600 local env file containing KEY=value
lines and use `kubectl -n media create secret generic NAME --from-env-file=FILE`.
Use actual existing credentials, keep the file outside Git and remove the
plaintext temporary file after secure storage is confirmed. Do not print Secret
YAML into logs or commit it. For an existing Secret, use the established secret
management/update process rather than deleting it during running workloads;
containers using environment variables need a rollout to consume updates.

In-cluster endpoints are prowlarr.media.svc.cluster.local:9696,
sonarr.media.svc.cluster.local:8989, radarr.media.svc.cluster.local:7878,
nzbget.media.svc.cluster.local:6789 and qbittorrent.media.svc.cluster.local:8080.
External clients use trusted-LAN addresses/NodePorts from the Service manifests;
NAS-native apps cannot normally resolve Kubernetes Service DNS.

Preserve existing categories, API keys, queue/history and /media-data mappings.
Recorded categories were Sonarr tv-sonarr / Series and Radarr radarr / Movies
for qBittorrent / NZBGet respectively. Confirm saved settings in the app before
changing them. An old Sonarr SABnzbd entry was observed during migration; its
purpose/enabled state was not verified. Avoid deleting jobs to clear warnings.
Test a deliberately chosen download through import, including archive extraction
when applicable. Hardlinks require a compatible shared backing filesystem;
a common mount path alone does not prove they are working.

## Emby, Tdarr and qBittorrent

Emby configuration lives under /mnt/application-pool/k3s-app-data/emby and includes
users/watch history/library state. Verify B580 device access and current node
GPU group IDs rather than assuming another host has the same IDs. Check direct
play and forced hardware transcode, then public playback and saved Emby URLs
in Seerr/Tracearr. Review the transcode temporary path separately from media.

Tdarr state includes config, server and logs under its dedicated app directory.
Server and worker must agree on library/cache paths; a successful encode without
copy-back is not a successful job. Verify a full job before marking recovery done.

qBittorrent state includes configuration, private wireguard/wg0.conf and
BT_backup torrent/fast-resume files. Preserve existing file paths, identity,
tracker-approved version and VPN behavior. Never run both restored and original
clients concurrently. Verify job counts, tracker status and VPN failure behavior
separately. Keep the pinned image backup off-node and outside Git. The recorded
Skopeo directory backup must be extracted and read with Skopeo's dir transport;
it is not directly an OCI archive for ctr import. A restore test is still pending.

## GitOps and rollback

Scale through Git when Argo reconciliation controls replicas. Before rollback,
stop the replacement, reconcile post-cutover changes, then restore compatible
application/data versions and dependent endpoints. Old NAS config copies are
stale after new writes. Do not assume changing an image tag reverses database
migrations. Current app owners manage their ingress/TLS alongside workloads;
shared Traefik configuration and redirects remain under infrastructure.

## Immich and Tracearr credentials

Both apps now require manually provisioned credential Secrets before syncing.
See the [credential and publication checklist](publication.md) for exact keys,
existing-data considerations and coordinated rotation. PostgreSQL initialization
environment variables do not rotate passwords in an existing database.
