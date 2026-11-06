# Arr stack

Prowlarr, Sonarr, Radarr and Unpackerr run in `media`. Each has one replica and
Recreate deployment strategy. Application config remains on TrueNAS under
`/mnt/application-pool/k3s-app-data/<app>`, using UID/GID 568. Sonarr, Radarr and
Unpackerr share `/media-data`; Prowlarr does not need a media mount.

## Access and integrations

| App | LAN port | Internal URL |
|---|---|---|
| Prowlarr | 30969 | http://prowlarr.media.svc.cluster.local:9696 |
| Sonarr | 30989 | http://sonarr.media.svc.cluster.local:8989 |
| Radarr | 30787 | http://radarr.media.svc.cluster.local:7878 |

Use `http://192.0.2.10:PORT` on the trusted LAN. No public ingress is
configured. NodePorts can listen on other node interfaces; firewall policy
must enforce the intended access boundary.

Prowlarr's app connections and Seerr's servers should reference the internal
Services above. Unpackerr's URLs are declared in `unpackerr.yaml`; its API keys
come from `media/unpackerr-credentials`. Other private API keys and downloader
settings reside in the application configs, not this README.

qBittorrent and NZBGet have separate app directories and Argo registrations.
Their former NAS endpoints are obsolete. Preserve downloader categories and
paths when changing connections: Sonarr uses `tv-sonarr` / `Series`, Radarr uses
`radarr` / `Movies`. Inspect the live app settings before editing them.

## Storage and operation

NFS-backed SQLite configuration is an accepted portability trade-off. Keep one
writer; never start an old NAS copy against the active configuration. Retain
volumes and consistent backups before changes. A complete media-export mount
preserves paths and permits hardlinks only where source and destination share
the same backing filesystem; separate datasets prevent hardlinks.

`bootstrap/arr-stack-application.yaml` registers this directory. Its checked-in
policy is manual; inspect live Argo policy before assuming a scale edit will
persist. Scaling through Git is required when reconciliation would undo a live edit.

```bash
sudo k3s kubectl -n media get pods
sudo k3s kubectl -n media logs deployment/unpackerr --tail=100 -f
sudo k3s kubectl -n media logs deployment/sonarr --tail=100
```

Listener readiness does not prove imports work. Check the queue reason, actual
extracted files, mounted paths and permissions when an import stalls. Unpackerr
reporting “awaiting import” alone is not proof that usable video was extracted.
Do not delete seeding jobs to clear import warnings.

## Verification and recovery

Operator reports on 2026-11-04 confirmed a Seerr request passed through indexers
and downloaders into the library, and a separate NZBGet movie import succeeded.
Earlier copy checks covered SQLite integrity and selected library permissions;
these do not establish durability through every NAS/network failure.

See the [migration case study](../../../docs/case-studies/truenas-to-k3s.md) and
[state recovery prerequisites](../../../docs/operations/application-state-recovery.md).
An old stopped NAS database is a historical snapshot, not a current rollback copy.
