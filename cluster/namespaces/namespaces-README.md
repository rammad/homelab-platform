# cluster/namespaces

Declarative definitions for the three application namespaces. System components
also use namespaces such as `kube-system`, `argocd` and `cert-manager`.
Current application manifests do not use `default` as a migration destination.

| File | Namespace | Apps |
|---|---|---|
| `media.yaml` | `media` | Emby, Sonarr, Radarr, Prowlarr, Unpackerr, Tdarr, qBittorrent, NZBGet |
| `data.yaml` | `data` | Nextcloud, Immich |
| `tools.yaml` | `tools` | Seerr, Tracearr, TiasTube, Cloudflare DDNS, OpenSpeedTest |

## Bootstrapping via Argo CD

After installing Argo through the [toolkit](../../bootstrap/README.md) and connecting the repo,
create an Application pointing here so namespaces are managed declaratively
instead of via ad-hoc `kubectl create namespace`:

- **Application Name:** `namespaces`
- **Project:** `default`
- **Sync Policy:** Manual initially; review lifecycle before enabling automation. Do not enable namespace pruning casually.
- **Repository URL:** `https://github.com/REPLACE_ME/homelab-platform.git`
- **Revision:** `master`
- **Path:** `cluster/namespaces`
- **Cluster URL:** `https://kubernetes.default.svc`
- **Namespace:** (leave blank — these manifests are cluster-scoped)

Once synced, individual app Applications (e.g. `tracearr`) can target these
namespaces directly instead of relying on `CreateNamespace=true` sync
options, which keeps namespace lifecycle independent of any single app.

## One-off manual apply (if Argo isn't up yet)

```bash
kubectl apply -f cluster/namespaces/
```
