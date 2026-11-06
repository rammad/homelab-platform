# Public bases and private deployment overlays

The public repository contains application definitions, setup tools and operational
examples. A separate private repository selects these definitions and patches
site-specific settings: domain names, NFS addresses/paths, node selectors and Argo
repository locations. Kubernetes Secret values stay out of both plaintext trees.

```text
public homelab-platform               private deployment repository
  cluster/apps/<app>/                   overlays/<app>/kustomization.yaml
  cluster/infrastructure/               site patches + Argo registrations
  bootstrap/                           cluster Secrets provisioned separately
  docs/
```

A private overlay references a pinned public commit, for example:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - https://github.com/REPLACE_ME/homelab-platform.git//cluster/apps/emby?ref=FULL_COMMIT_SHA
patches:
  - target:
      kind: PersistentVolume
      name: REPLACE_WITH_VOLUME_NAME
    patch: |-
      - op: replace
        path: /spec/nfs/server
        value: REPLACE_WITH_PRIVATE_NAS_IP
```

This is a structural example; inspect the chosen app for its real resource names
and all required settings. The public documentation uses `example.com`, TEST-NET
addresses, `application-pool`, `storage-pool`, `control-plane` and `gpu-worker`.
Do not apply these unchanged. Preserve resource names/namespaces during handoff.

For existing installations, render the private overlay and compare it with the
current desired resources before changing an Argo source path. Keep the same Argo
Application owner, review its diff, and change one application at a time. Do not
create a second Application managing the same resources. The old paths can stay
active until this handoff is complete.

Argo must have read access to the private repository and network access to the
pinned public base. Sibling-directory references are useful for local validation
but are not deployable by Argo when repositories are checked out separately.

The bootstrap toolkit reads manifests from its own checkout. Use its read-only
help/list/guide commands to learn the structure. For production setup, run the
existing private toolkit or an appropriately customized checkout; this candidate
does not automatically merge a separate private overlay when registering apps.
Secret prompts provision cluster Secrets; neither domain names nor NFS paths can
be substituted everywhere using Kubernetes Secret references.
