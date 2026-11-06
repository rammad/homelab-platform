# Deployment flow and evidence

Reviewed 2026-11-05 against repository files and operator migration reports;
no new live cluster inspection performed.

## What this repository implements

Application workloads, Services, public routes, namespaces and static NFS
PV/PVCs are defined under `cluster/`. The [main inventory](../README.md#applications)
lists the migrated apps. Emby and the Tdarr worker target the B580 node; the Tdarr
server also runs in k3s. Node configuration, NAS exports and private application
state are not completely represented by these manifests.

The guided toolkit lives at `bootstrap/bootstrap.sh`; see the
[toolkit guide](../bootstrap/README.md). Checks are read-only, installation is
explicit, and existing nodes are not reinstalled. Individual app preparation,
Secrets and registration use current repository manifests. Application definitions
exist under `bootstrap/` and `argocd/edge-applications/`; their exact sync policies
must be reviewed rather than assumed uniform. Workload images come from upstream
registries, not a custom build pipeline.

## Example: changing the Tdarr worker image

1. Review both server and worker image versions in this app directory; keep them compatible.
2. Edit the image reference in `cluster/apps/tdarr/node.yaml` and review the diff.
3. An authorized push updates the tracked Git revision.
4. Argo CD compares the configured Git path with cluster resources and applies
   the desired manifests when its sync policy permits.
5. A changed Deployment pod template causes Kubernetes to roll out replacement
   pods. The node's kubelet/container runtime obtains the referenced image
   according to image pull policy, then starts the container and mounts volumes.
6. Verify rollout, worker registration, and completion/copy-back of a test job.

Argo CD does not build or itself pull the container image. A new upstream image
under an unchanged tag does not by itself change the Git manifest or trigger
an Argo CD rollout. Automated image updates require a separate mechanism.
Several images are digest-pinned; others use version tags. A version tag alone
is not immutable. Review the actual app manifest rather than assuming one policy.

## Three different recovery mechanisms

- Kubernetes controllers replace missing managed pods; kubelet handles
  container restarts and image-pull retries.
- Argo CD can correct resource drift when configured for self-heal; this is
  separate from Kubernetes restarting a workload.
- Application readiness/liveness/startup probes evaluate running containers.
  They cannot repair a pre-start image download failure or restore lost data.

## Evidence to capture next (not yet collected)

Record Git revision, image digest, Argo Application sync policy/status,
rollout status, relevant pod events, and one application-level verification.
For recovery testing, agree a disruption window and verify storage/backups
before deliberately interrupting a stateful service. Record actual results,
including failures, rather than assuming a recreated pod proves recovery.

References: [Argo CD auto-sync](https://argo-cd.readthedocs.io/en/stable/user-guide/auto_sync/),
[Kubernetes images](https://kubernetes.io/docs/concepts/containers/images/),
[Kubernetes probes](https://kubernetes.io/docs/concepts/workloads/pods/probes/).
