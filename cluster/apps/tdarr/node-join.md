# Joining the GPU worker node to the cluster

**Status: done and verified.** The GPU worker node is joined, labeled, tainted,
and running the Tdarr Node deployment against the TrueNAS Tdarr Server in
**mapped** mode — both the media library and the transcode cache
NFS-mounted at the same paths the server sees. Confirmed stable over a
15+ minute soak with both transcode nodes (previous GPU + GPU worker) running
concurrently, no errors — pipeline is now knocking out roughly a full
episode per minute, so the media library backlog is in good shape to
clear. Transcodes land around 1500 fps vs. ~400 fps on the previous GPU alone.
This doc is kept as the record of two wrong turns before landing here
(mapped-without-cache-mount, then unmapped) — both worth understanding
before touching this again.

One-time, imperative steps — not GitOps-managed, since this is cluster
membership, not application state.

## 1. Confirm GPU is usable on the host first

Before touching K3s, verify the Arc GPU worker actually hardware-transcodes on the
bare host:

```
vainfo
intel_gpu_top
```

If these don't show the card, fix the kernel/i915/media-driver stack before
going further — K3s won't fix a GPU that doesn't work outside a container.
Arc (Alchemist) needs a recent kernel (6.2+, ideally newer) and current
`intel-media-driver`.

## 2. Join as a K3s agent

On the K3s server (currently the TrueNAS-hosted VM, 192.0.2.10), grab
the join token:

```
sudo cat /var/lib/rancher/k3s/server/node-token
```

On the GPU worker node:

```
curl -sfL https://get.k3s.io | K3S_URL=https://192.0.2.10:6443 \
  K3S_TOKEN=<token from above> sh -
```

## 3. Label the node

From any machine with kubectl access:

```
kubectl label node <gpu-worker-hostname> hardware/gpu=intel
```

`node.yaml`'s `nodeSelector` targets this label — but a label alone only
*permits* scheduling here, it doesn't *exclude* everything else. Do step 4
below or general workloads (tracearr, immich, etc.) will happily land on
this node any time the master is busy/rebooting/unavailable — which is
exactly what happened the first time around: master went down for a
rename, the scheduler had nowhere else to put things, and dumped tracearr
onto gpu-worker, which choked.

## 4. Taint the node so it's dedicated to transcode only

```
kubectl taint nodes <gpu-worker-hostname> dedicated=transcode:NoSchedule
```

`node.yaml` carries a matching `tolerations` entry, so the tdarr pod is the
only thing that can still land here. Everything else in the cluster is
repelled unless it's given the same toleration on purpose.

If you already have stray pods sitting on gpu-worker from before the taint
existed (check with
`kubectl get pods -A -o wide --field-selector spec.nodeName=<gpu-worker-hostname>`),
the taint won't evict them retroactively — `NoSchedule` only blocks new
placements. Delete the stray pods once the master is healthy again and
their controllers (Deployments) will recreate them; with the taint in place
they'll land back on the master instead.

## 5. Render group / permissions

`/dev/dri` on the host needs to be readable by whatever the container runs
as. `node.yaml` currently uses `privileged: true` to sidestep this — fine
for a single trusted homelab node, but if that starts to bother you, drop
the privileged flag and instead add the container user to the host's
`render` group GID via `securityContext.supplementalGroups`.

## 6. Node mode: mapped vs. unmapped (read this before changing anything)

Tdarr nodes run in one of two modes, and picking the wrong one — or
implementing the right one incompletely — is a subtle failure that looks
fine for a while, then quietly breaks:

- **Mapped:** server and node are assumed to share an identical
  filesystem, for BOTH the library and the transcode cache. The server
  does the final file move itself, directly, trusting that any path the
  node can see, it can see too.
- **Unmapped:** the node is treated as a separate machine with its own
  storage. It downloads the source from the server over Tdarr's HTTP API,
  transcodes to a local cache path, then uploads the result back over
  HTTP. No shared filesystem assumption anywhere — **but free-tier
  unmapped nodes cap video files at 10MB**. Tdarr Pro removes that cap;
  without it, unmapped mode is unusable for real media.

We tried unmapped first, since the GPU worker is genuinely a separate machine —
architecturally cleaner, no NFS/ACL story at all. Hit the 10MB wall
immediately on the first real file (346MB), and without a Pro license,
that's a hard stop. Landed on **mapped**, which is free, and which we'd
already mostly solved from the first pass — the remaining gap wasn't the
concept, it was that only the *library* path had been NFS-mounted, not
the *cache* path too.

`node.yaml` now mounts both, matching the TrueNAS Tdarr Server's own
storage config exactly:

| | Server's internal path | TrueNAS host path (NFS export) |
|---|---|---|
| Library | `/media-data` | `/mnt/storage-pool/media-data` |
| Cache | `/temp` | `/mnt/application-pool/configs/tdarr/temp` |

Both confirmed against the server app's own Storage config in the TrueNAS
UI — don't guess these, check Edit → Storage on the app itself, since
Tdarr matches jobs between server and node by exact path string.

`nodeType` is a real Tdarr config variable — it defaults to `mapped`, but
`node.yaml` sets it explicitly anyway after getting bitten once by an
unset value silently doing the wrong thing during the unmapped attempt.

### The two wrong turns (both worth understanding before touching this again)

**First attempt — mapped, library only.** NFS-mounted the library at
`/media-data`, matching the server. This looked like it worked —
transcodes completed, fps was great — but every completed job then failed
silently at the copy-back step. The *cache* path also needs to match
under mapped mode, and the node's cache was local to the ephemeral pod
filesystem. The server tried to move the finished file from a `/temp/...`
path that only existed inside the K3s pod, got `ENOENT`, and marked the
job failed. This is what caused "queue fills with failed copy jobs after
about an hour" — jobs don't fail until they finish transcoding, so it
only shows up once a batch of jobs completes.

Getting the library half of mapped mode working at all required, on the
TrueNAS side (still true, still required):

1. NFS share → Maproot User/Group = `root` (disables root squash).
2. Dataset → Edit Permissions → an `everyone@` ACE (Modify), applied
   recursively — `media-data` is also SMB-shared and written to by 8+
   different apps (sonarr, nzbget, unpackerr, etc.), so it uses NFSv4
   ACLs, and individual files are owned by whatever UID the app that
   wrote them used. No single `owner@`/`group@`/named-user ACE reliably
   covered files written by apps other than Tdarr.

The cache dataset (`application-pool/configs/tdarr/temp`) isn't SMB-shared and is
written only by Tdarr, so it likely only needs the Maproot fix — verify
this once its NFS share exists rather than assuming.

**Second attempt — unmapped.** Switched to avoid the NFS/ACL complexity
entirely: local `hostPath` cache on the GPU worker's own disk, HTTP transfer to
the server. Architecturally the "correct" choice for a separate machine,
but free-tier unmapped nodes cap video files at 10MB — discovered this
the moment a 346MB episode failed with a Tdarr Pro upsell message. Reverted.

### NFS share for the cache path (done)

The library path had its own NFS share already; the cache path
(`/mnt/application-pool/configs/tdarr/temp`) needed a new one — created via
Sharing → NFS → Add, Maproot User/Group = `root`. Confirmed working
without needing the broader `everyone@` ACE the library required — this
dataset isn't SMB-shared and is written only by Tdarr, so Maproot alone
was sufficient.

## 7. Confirm the node connects

Check the Tdarr Server UI (on TrueNAS) — the new node should show up under
Nodes once the pod is running and can reach `serverIP:serverPort`. If it
doesn't show up, it's almost always one of: firewall between the two
subnets, wrong `serverIP`, or the pod not actually having the token to
reach out (check `kubectl logs`).

## Note on scope

This intentionally only puts the Tdarr *node* in K3s. The Tdarr *server*
stays exactly where it is on TrueNAS — no reason to move it, and per the
current plan the rest of the media stack isn't migrating into K3s until
after the move. See ADR-005 in the root README.

## Planned storage and worker expansion

Move the shared transcode workspace out of the legacy configs directory and add
GPU worker capacity. Preserve matching cache and library paths across server and
workers, then verify processing and copy-back before retiring the old location.
The new worker is also intended to support flexible Emby placement; resource
allocation and processing schedules must account for simultaneous streaming.
Current manifests retain the existing storage paths and worker placement.
