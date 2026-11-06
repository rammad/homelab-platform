# Argo EndpointSlice discovery

This shared Argo configuration allows it to watch EndpointSlices: Kubernetes
objects describing the network endpoints behind Services. Other resource
exclusions remain unchanged. Application routes now target in-cluster Services;
whether this exception is still needed is a separate configuration review.

This is a PARTIAL argocd-cm, not a full Argo installation. The manual-sync
edge-argocd-settings Application uses server-side apply with client-side migration
disabled to avoid adopting unrelated existing ConfigMap fields. Never apply this
with Replace, Force, or ordinary client-side apply. Preserve all other live data
keys; review the diff before syncing. Prune/Delete are disabled for this shared
bootstrap ConfigMap. An independent Argo installation upgrade must retain this
setting rather than restoring the upstream EndpointSlice exclusion.

For a deliberate settings change, review the single ConfigMap diff and manually
sync `edge-argocd-settings`. Preserve unrelated live keys. Reassess this exception before changing it.

This enables watching EndpointSlices cluster-wide, including controller-generated
ones, and may increase cache events. Existing other exclusions are unchanged.
Reintroducing the EndpointSlice exclusion changes what Argo can observe; it is
not a general playback troubleshooting step.
