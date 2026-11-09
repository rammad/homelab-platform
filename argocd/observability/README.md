# K3s observability base

This Kustomize base produces an Argo CD Application for the pinned
`kube-prometheus-stack` Helm chart. The chart supplies Prometheus, Alertmanager,
Grafana dashboards, kube-state-metrics, Linux node metrics, and default alerting
and recording rules. Argo CD renders the chart and applies it on manual sync.

The base disables separate controller-manager, scheduler, kube-proxy, and etcd
scrapes for this K3s baseline. Grafana uses an internal service by default.
Keep site-specific storage, retention, hostname, access policy, and notification
settings in the deployment overlay. Store notification credentials in Kubernetes
Secrets. The chart supplies the stock rules and dashboards at the pinned version.

Run `kustomize build argocd/observability` from this repo to inspect the base
Application. A site overlay can select this directory at a published commit SHA
and patch `spec.source.helm.valuesObject`. Review the rendered chart and Argo CD
diff when adopting a new chart version.
