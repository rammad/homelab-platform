# Seerr

Request management in `tools`, migrated from Jellyseerr. Configuration and its
SQLite database live at `/mnt/application-pool/k3s-app-data/seerr` on TrueNAS. The app
runs as UID/GID 1000, with one replica and Recreate strategy. No media mount is
needed. The current image version is declared in `deployment.yaml`.

## Access and ownership

- Public: https://request.example.com
- Trusted LAN: http://192.0.2.10:30555
- Internal Service: `seerr:5055` in `tools`
- Registration: `bootstrap/seerr-application.yaml`

The Seerr Application owns its workload, storage, Service, certificate and
ingress. `edge.yaml` routes directly to the Service; the old external-backend
proxy is retired. The checked-in registration uses manual sync; live policy
must be inspected before operational changes. Scaling Seerr to zero stops both
LAN and public access.

## Checks and changes

The deployment's init check verifies config access as the application user.
`preflight.yaml` is a separate, opt-in check excluded from Kustomization; it
performs temporary file writes. Run it only with Seerr stopped, and remove an
old completed `seerr-nfs-check` Job before explicitly rerunning it. It is not a
SQLite locking or NFS durability certification.

```bash
sudo k3s kubectl -n tools rollout status deployment/seerr
sudo k3s kubectl -n tools logs deployment/seerr --tail=100
```

Check login and Sonarr/Radarr connectivity after changes. A real request can
trigger downloads and notifications; use a deliberately selected test request.
API keys and private integration settings stay in the config, not Git.

## Data and verification

The copied Jellyseerr database was upgraded during Seerr startup. Do not copy
the old database over the running installation or open the upgraded database
with an older Jellyseerr image. Take consistent backups and retain a compatible
image for restoration. Single-writer operation reduces overlap but does not
provide fencing or guarantee SQLite safety on NFS.

The operator confirmed request-to-library delivery on 2026-11-04 and public
routing after ownership consolidation on 2026-11-05. These are functional tests,
not proof of every notification, user setting or failure-recovery path.

See [state recovery](../../../docs/operations/application-state-recovery.md),
[the migration case study](../../../docs/case-studies/truenas-to-k3s.md), and the
[upstream migration guide](https://docs.seerr.dev/migration-guide/).
