# Tdarr worker failed to pull its image after node startup

Date: 2026-10-19. Source: operator account, recorded the same day.
Status: service recovered according to operator; original DNS cause unresolved.
No original event output, timestamps, or image digest was retained here.

## Impact and detection

After powering on the secondary Kubernetes node, the expected additional
Tdarr worker did not appear in the Tdarr Server UI. The operator checked
Argo CD and found an image-pull failure reporting DNS resolution trouble
reaching the GitHub container registry. Detection was manual; there was no
alert notifying the operator that the expected worker was absent.

## Investigation and recovery

1. Checked deployment state after observing the missing worker.
2. Connected to the affected machine over SSH and verified DNS resolution
   was working at the time of investigation.
3. Deleted the affected pod. Its managed replacement successfully obtained
   the image and started, according to the operator.

Exact commands and error strings were not supplied and are not reconstructed.
A newly pulled image does not establish that a newer application version was
installed; no before/after digest or tag was recorded.

## Interpretation and limits

The reported immediate failure was DNS resolution during image retrieval.
A transient startup networking/resolver issue is a hypothesis, not an
established root cause. Successful resolution later does not prove which
component failed initially. Recreating the pod was a recovery action, not a
confirmed permanent DNS fix.

Kubernetes normally retries failed image pulls with backoff, up to a five-minute
retry interval. It is unknown whether waiting would have recovered this pod.
On recurrence, preserve pod events and node/runtime logs before deleting it.
Host DNS tests alone do not prove every runtime registry request will succeed;
check the actual pull outcome too.

## Follow-up design (not implemented by this documentation change)

Monitor pod waiting reasons and unavailable Deployment replicas. Correlate
with node readiness and expected worker registration in Tdarr. Suppress or
adjust alerts for intentionally powered-off workers, and allow a measured
startup grace period. Route alerts to an actionable owner.

Container health probes are a separate improvement: no container is running
to answer a probe while image retrieval is failing. A readiness probe gates
service readiness; a liveness probe can restart a running unhealthy container.
Neither is a substitute for image-pull and workload-availability alerting.

Capture time to detection/recovery, exact registry error, DNS/runtime evidence,
image identity, and a completed test job on the next occurrence or controlled
test. No downtime, performance improvement, or data-loss claims are inferred.

References: [Image pull retries](https://kubernetes.io/docs/concepts/containers/images/#imagepullbackoff),
[Probe behavior](https://kubernetes.io/docs/concepts/workloads/pods/probes/).
