# Argo EndpointSlice discovery

Historical external-backend setup. The 2026-11-05 edge consolidation retires
the Emby/Seerr static EndpointSlices; this shared Argo setting remains unchanged.

Operator supplied the complete resource.exclusions value on 2026-10-21.
Only EndpointSlice is removed. Endpoints, Lease, auth review, certificate request,
Cilium and Kyverno exclusions remain. Repeated kinds keys in pasted text were
normalized into one key. No credentials are included.

This is a PARTIAL argocd-cm, not a full Argo installation. The manual-sync
edge-argocd-settings Application uses server-side apply with client-side migration
disabled to avoid adopting unrelated existing ConfigMap fields. Never apply this
with Replace, Force, or ordinary client-side apply. Preserve all other live data
keys; review the diff before syncing. Prune/Delete are disabled for this shared
bootstrap ConfigMap. An independent Argo installation upgrade must retain this
setting rather than restoring the upstream EndpointSlice exclusion.

For a deliberate settings change, review the single ConfigMap diff and manually
sync `edge-argocd-settings`. Preserve unrelated live keys. The old instructions
to sync external Emby/Jellyseerr EndpointSlices no longer apply: those routes
now use in-cluster Services. Reassess whether this exception is still needed in
a separate configuration change; this documentation cleanup retains it.

This enables watching EndpointSlices cluster-wide, including controller-generated
ones, and may increase cache events. Existing other exclusions are unchanged.
Rollback via Git restores the EndpointSlice exclusion, but again hides management
of these external-backend slices; do not use that as a playback fix.
