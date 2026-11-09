# What the first K3s alerts found

On November 9, 2026, I deployed kube-prometheus-stack with Argo CD to a
two-node K3s homelab. Prometheus collects metrics and evaluates rules.
Grafana provides dashboards, and Alertmanager delivers notifications to
Discord. The public base pins the Helm chart. A private Kustomize overlay
sets storage, retention, LAN access, and notification routing. Alertmanager
reads the Discord webhook from a Kubernetes Secret.

I first rendered the Application from local checkouts and synced it manually.
All seven monitoring pods became ready and all three storage claims bound.
Grafana showed recent Prometheus data. I then moved the Application definition
under Git management, with a separate Argo CD Application managing the
registration and the existing Application managing the Helm workloads.

## A worker ahead of the control plane

The first Discord warning, `KubeVersionMismatch`, reported two versions.
`kubectl get nodes -o wide` showed the control plane at `v1.35.5+k3s1`
and the worker at `v1.36.3+k3s1`. Both nodes reported Ready. The version
comparison identified the control plane as the first upgrade target because
the worker kubelet was already a minor release ahead of the API server.
The upgrade and resolved notification were pending at the time of review.

## Failed setup Jobs still present

A grouped `KubeJobFailed` notification flagged five failed backup Jobs.
Sorting the Job list by creation time showed five manual setup and diagnostic
attempts followed by three successful scheduled runs for each of the five
backup CronJobs. The most recent backup-monitor Job had also completed.

The appropriate cleanup was to preserve any needed logs and remove just the
five obsolete Job objects. Cleanup and alert resolution were pending at the
time of review. Successful Job status confirms execution completed. Restore
validation is a separate check.

The firing notifications verified the path from Kubernetes metrics through
Prometheus and Alertmanager to Discord. The monitoring stack runs inside the
cluster. Independent outage monitoring is deferred.
