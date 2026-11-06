# Moving a household application stack from TrueNAS to k3s

Recorded 2026-11-05 from operator reports, supplied logs/screenshots and the
repository's migration notes. This is a retrospective, not a deployment script.
The owner is undertaking a personal file-by-file review before publication;
AI assistance and operator verification should not be confused with independent
review or automated end-to-end testing.

## Objective and constraints

Move application execution into a GitOps-managed k3s cluster while keeping
application state and media on TrueNAS. Preserve existing libraries, accounts,
queues and torrent seeding state. Keep public streaming available during
preparation, and schedule disruptive cutovers around active streams.

The control plane moved from a TrueNAS VM to a physical control-plane node while
retaining its node identity and LAN address. A separate GPU worker node serves
GPU workloads. Shared NAS storage made replacing compute simpler, but retained
a shared failure dependency. This is not a highly available cluster.

## Separate compute movement from data movement

For the control-plane move, the operator staged the matching k3s binary, node
configuration, identity and container images before stopping the old server.
The final stopped-server archive included the SQLite datastore and server token.
The old VM was kept off while the replacement took over its address. Existing
NAS-backed applications reopened their existing data; application backup restores
were not what made their data reappear.

Host DNS failed after the address change because DHCP tooling rewrote resolv.conf
without nameservers. Restoring DNS and its persistent configuration recovered
registry pulls. A subsequent reboot and public cellular playback were verified.
Image preloading reduced download work but did not eliminate DNS dependencies:
containers using Always pull policy still needed registry access.

## Migrate applications in manageable groups

Cloudflare DDNS, OpenSpeedTest and Seerr established the workflow first. Seerr
used a copied Jellyseerr configuration and a LAN test before the public route
changed. Prowlarr, Sonarr and Radarr moved together, preserving media paths and
existing downloader categories while downloaders initially remained on TrueNAS.
The operator subsequently migrated Unpackerr, NZBGet, Nextcloud, Tdarr, Emby and
qBittorrent with separate verification steps.

The app-copy scripts required stopped sources and fresh destinations, preserved
ownership, copied into staging directories, compared file content and published
the destination only after verification. Trailing slashes and hidden files
mattered: an earlier Nextcloud copy produced an unwanted nested user-data folder.
The .ncdata marker and permissions had to match the directory mounted by the app.

Database/configuration ownership was application-specific: arr apps used UID/GID
568, Nextcloud's web process used 33 and PostgreSQL used 999. An NFS mount test
as root alone did not prove the application could read or write its data.
SQLite quick checks and disposable file operations helped validate copies and
permissions; they did not certify NFS locking or crash durability. The operator
accepted NFS-backed app state for portability, with those trade-offs explicit.

Nextcloud needed both its existing installation and its PostgreSQL data, not
just the uploaded files. The stopped PostgreSQL 13 copy was checked for clean
shutdown and matching major version. A private configuration override redirected
its database/cache connections to Kubernetes Services. These requirements remain
in the [state recovery guide](../operations/application-state-recovery.md).

## Preserve application behavior

qBittorrent stayed on its tracker-approved 5.1.0 image digest. The source had
75 torrent files and 75 fast-resume files; preserving those and the original
paths was essential to adopting existing jobs. The deployment retained VPN
configuration. A registry NotFound during migration was not later reproducible:
the exact digest became accessible, and a Skopeo directory-format image backup
was downloaded and copied off-node. An image archive is not a backup of torrent
state or VPN credentials. Full image restore and VPN failure testing remain
separate from the successful archive download.

Emby was staged without starting it while streams were active, then copied
with the source stopped. Public domain playback was confirmed. A supplied
FFmpeg log showed hevc_qsv decode/encode and vpp_qsv processing through the GPU;
this establishes hardware acceleration for that test, not every codec/client.
Tdarr's server UI and GPU worker connection were confirmed after migration; a complete
post-migration transcode and copy-back still needs explicit verification.

## Transfer GitOps ownership without deleting live routes

Legacy edge Applications originally managed routes to external NAS services.
After migration, workload apps adopted their own Ingress, Certificate and TLS
resources. Seerr's ingress moved into tools and reached its Service directly,
replacing a cross-namespace NodePort proxy. Shared Traefik configuration, issuers
and HTTP redirects remained infrastructure resources.

Argo's FailOnSharedResource check exposed an inventory mistake: the live legacy
speed-test app was named open-speedtest, while earlier repository definitions
used edge-speedtest. The new openspeedtest app could not adopt the shared objects
until the extra old owner was removed without cascading deletion and its tracking
metadata was released. Public access continued while the resources were orphaned.
The parent was resumed at the new commit, new owners were verified, and obsolete
proxies were then removed. The operator reported all public routes working after
final cleanup. Both old names are recorded here so the lesson survives removal
of the one-time handoff script.

## Evidence and remaining limits

- Operator-confirmed: control-plane reboot, Emby cellular/domain playback,
  Immich upload, Nextcloud web/Nautilus/test-file sync, Seerr request through
  indexers/downloaders into the library, and Radarr import from NZBGet.
- Supplied log evidence: Emby hardware-accelerated transcode for one test.
- Operator-confirmed: edge consolidation/public-route checks on 2026-11-05.
- Not established by these checks: HA/failover, hardlink behavior, complete
  backup restoration, all torrent tracker/kill-switch scenarios, or a completed
  post-migration Tdarr job. Do not present these as verified portfolio results.

## What remains in the repository

Current manifests, bootstrap/prerequisite tooling, reusable backup capabilities
and operational documentation remain. Completed cold-copy scripts, one-off arr
preflight Job and edge handoff tooling were removed from the working tree.
Git history preserves their implementation. Historical proxy experiments remain
in the [earlier rollout record](../traefik-edge-rollout.md) and incident notes;
those are evidence, not instructions for the current architecture.
