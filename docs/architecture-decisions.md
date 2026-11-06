# Architecture decisions

Preserved from the earlier README on 2026-11-05. These records explain the
original choices, not current runtime state. See the [current overview](../README.md).
Terraform remains an option, not a committed implementation step. ADR-005 is
superseded by the completed control-plane and application migration; its
performance and permission observations are historical, not deployment guidance.

## Decision Log

Architecture Decision Records (ADRs) for significant choices made during the build. Format: context → decision → rationale → trade-offs.

---

### ADR-001 — Static NFS Provisioning over Dynamic StorageClass

**Date:** Project inception  
**Status:** Active

**Context:** K3s ships with a local-path provisioner, but workloads need storage backed by TrueNAS over NFS for durability and centralized management. Options were: (a) static PV/PVC, (b) NFS subdir external provisioner (dynamic), (c) Longhorn.

**Decision:** Static provisioning via manually defined PV objects.

**Rationale:**
- Forces deep understanding of the PV/PVC binding lifecycle — critical foundational knowledge.
- No additional components to operate or debug during the learning phase.
- Full control and visibility over exactly what NFS paths are mounted where.

**Trade-offs:**
- More YAML per app (one PV + one PVC minimum, per volume).
- No automatic reclaim or provisioning on new app deploys.
- Accepted: this pain is the point. Terraform will abstract this later.

---

### ADR-002 — Namespace Organization by Operational Coupling

**Date:** Project inception  
**Status:** Active

**Context:** Kubernetes namespaces can be organized by team, environment, or function. In a single-owner homelab, the deciding factor is operational coupling — specifically, which apps share storage access and need to co-exist for the platform to function.

**Decision:** Four namespaces: `media`, `data`, `tools`, `default` (transitional).

**Rationale:**
- Apps in `media` all interact with the shared media library volume — grouping them simplifies RBAC and PVC referencing patterns.
- `data` isolates personal data stores (Immich, Nextcloud) from the automation/media pipeline.
- `tools` houses apps that *talk to* the media stack (Jellyseerr, Tracearr) but don't share its storage.

**Trade-offs:**
- Some cross-namespace service communication required (e.g., Jellyseerr → Sonarr/Radarr). Resolved via FQDN service DNS (`service.namespace.svc.cluster.local`).

---

### ADR-003 — ReadWriteMany on Shared Media Volumes

**Date:** Media stack architecture phase  
**Status:** Active

**Context:** NFS natively supports concurrent mounts. The media library PV could be provisioned as `ReadWriteOnce` (sufficient for a single-node cluster) or `ReadWriteMany`.

**Decision:** `ReadWriteMany` on all shared media volumes.

**Rationale:**
- Single-node clusters won't exercise RWX, but the access mode is declared at PV creation and cannot be changed without reprovisioning.
- Future multi-node expansion requires RWX for pods scheduled to different nodes to mount the same volume concurrently.
- Zero cost to do this right now.

**Trade-offs:**
- None meaningful at this scale. RWX is supported by NFS.

---

### ADR-004 — Defer Terraform Until Manual Provisioning Pain is Felt

**Date:** Project inception  
**Status:** Active

**Context:** Terraform (with the Kubernetes provider) can automate PV/PVC/namespace/configmap creation. Adopting it early would reduce repetitive YAML work.

**Decision:** No Terraform until the media stack is fully provisioned manually.

**Rationale:**
- Manual provisioning builds muscle memory and genuine understanding of the Kubernetes object model.
- Automating something you don't fully understand produces fragile automation.
- The "pain" of manual provisioning is the feedback signal that drives meaningful Terraform abstractions — rather than abstracting prematurely.

**Trade-offs:**
- More repetitive YAML work in the short term.
- Accepted as intentional.

---

### ADR-005 — Tdarr Node in K3s, Server Stays on TrueNAS

**2026-11-04 update:** The server has since moved to k3s. The decision below describes the original worker deployment.

**Date:** 2026-08-06
**Status:** Implemented

**Context:** Full migration of the media stack into K3s is on hold until
after the next move/resettle. Meanwhile, a second physical node (Intel B580,
for hardware transcode) is available now and idle otherwise.

**Decision:** Join the B580 box to the K3s cluster as a second node, but
only run the Tdarr *Node* workload on it (`cluster/apps/tdarr/`), pinned via
`nodeSelector`. The Tdarr *Server* remains a native TrueNAS app, outside K3s.

**Rationale:**
- Tdarr's server/node split makes this cheap: the node just needs network
  reachability to the server, not shared cluster membership for both
  halves.
- Gets GPU transcode capacity in use now without pulling forward the rest
  of the media stack migration.
- Exercises multi-node scheduling (`nodeSelector`, node labels) ahead of
  the eventual baremetal expansion, on a low-stakes single workload.

**Trade-offs:**
- Cluster is now mixed: one node running general workloads (currently
  none from the media stack), one dedicated to GPU transcode. Slightly odd
  shape for a "single-node, expansion planned" cluster, but temporary.
- Mapped mode (see Outcome) means the node depends on two NFS mounts
  staying byte-for-byte in sync with the TrueNAS Tdarr Server's own
  storage config. Any future change to the server's library/cache paths
  has to be mirrored here by hand — no shared source of truth between a
  TrueNAS-native app and a K3s pod.

**Outcome:** Working and verified — it took three attempts. B580 node joined,
labeled (`hardware/gpu: intel-b580`), and tainted
(`dedicated=transcode:NoSchedule`) so it's exclusively used by the Tdarr
node pod — this also fixed an early incident where a master reboot caused
general workloads to schedule onto the untainted GPU node and choke.
Transcoding at ~1500 fps vs. ~400 fps on the previous A310.

Landed on Tdarr's **mapped** mode: both the media library and the
transcode cache NFS-mounted at the exact paths the TrueNAS Tdarr Server
itself uses (`/media-data` and `/temp` respectively). Two wrong turns
first:

1. *Mapped, library-only* — NFS-mounted just the library, matching the
   server. Looked like it worked (transcodes completed at full speed),
   but every job then failed silently at the server's copy-back step,
   because mapped mode needs a shared *cache* path too, and the node's
   cache was local to the ephemeral pod filesystem (`ENOENT` on a path
   only the pod could see). Queue would fill with failed jobs about an
   hour in — jobs don't fail until they finish transcoding, so the
   failure mode only shows up once a batch completes. Getting even the
   library half working required `runAsUser: 0` in the pod, `Maproot
   User/Group = root` on the NFS share, and a recursive `everyone@` ACE
   on the dataset (it's SMB-shared and written to by 8+ different apps
   with inconsistent file ownership, so no narrower ACE reliably covered
   it).
2. *Unmapped* — switched to avoid the NFS/ACL complexity entirely: local
   `hostPath` cache on the B580's own disk, file transfer over Tdarr's
   HTTP API. Architecturally the "correct" fit for a genuinely separate
   machine — but free-tier unmapped nodes cap video files at 10MB, a hard
   stop for real media without a paid Tdarr Pro license. Reverted.

Mapped, both paths mounted, is where it landed — and where it's staying.
Soak-tested for 15+ minutes with both transcode nodes (the original A310
and the new B580) running concurrently against the same queue: no errors,
throughput around one full episode transcoded per minute. Backlog
clearing is now realistic on a timescale that matters. Full narrative,
including both wrong turns, in `cluster/apps/tdarr/node-join.md`.

---

