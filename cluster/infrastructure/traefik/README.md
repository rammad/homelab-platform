# Traefik source-address preservation

Traefik receives incoming web requests and routes them to application Services.
The current settings keep it on `control-plane`, preserve incoming client IPs
with `externalTrafficPolicy: Local`, enable structured access logs, and select
BBR (a TCP congestion-control algorithm) inside its pod.

This HelmChartConfig extends K3s's existing Helm release. It does not install a
second Traefik or take ownership of the generated Deployment/Service in Argo.
Local policy preserves source addresses at the Service ingress; pinning to the
router-target node keeps a local endpoint available across rescheduling.
Other nodes without a local Traefik endpoint will not serve this ingress.
The master remains a single point of failure. No forwarded-header trust changes.

## Review and deploy

1. Verify the hostname label before sync:
   `sudo kubectl get node control-plane -L kubernetes.io/hostname`
   It must equal control-plane. Reconfirm router forwards to 192.0.2.10.
2. Review, commit, push; sync edge-applications, then edge-traefik-config.
   Changing the pod selector causes a rollout and may interrupt active streams.
3. Wait for K3s Helm reconciliation, then check:

```sh
sudo kubectl -n kube-system get helmchart traefik
sudo kubectl -n kube-system rollout status deployment/traefik --timeout=180s
sudo kubectl -n kube-system get pods -l app.kubernetes.io/name=traefik -o wide
sudo kubectl -n kube-system get service traefik -o jsonpath='{.spec.externalTrafficPolicy}{"\n"}'
```

Argo Synced alone does not prove Helm reconciliation finished. Verify Local,
a ready pod on the master, all public HTTPS routes and HTTP redirects. Then
start a NEW cellular/remote Emby session: check public client address and remote
classification, then Tracearr location (geolocation can still be imprecise).
If the address remains private, inspect actual forwarded headers and Emby's
proxy-header handling; do not enable blanket trust or classify remote users LAN.
Do not use a home NAT-loopback session to prove internet client identity.

## Rollback

Change externalTrafficPolicy back to Cluster in Git and manually sync the app;
keep node pinning unless separately reverting it. Wait for Helm reconciliation
and verify route recovery. Deleting the Application without pruning does not
remove HelmChartConfig or reliably revert Helm values. Retain private Argo
NodePort access for recovery.

References:
- https://docs.k3s.io/networking/networking-services
- https://docs.k3s.io/add-ons/helm
- https://kubernetes.io/docs/tutorials/services/source-ip/

## Access logs

JSON access logs are enabled through the HelmChartConfig. Keep response status,
bytes, client addresses and origin/downstream timing for correlation with Emby
sessions and TCP samples. Request paths, lines, authority and headers are omitted
to avoid logging authentication material. Streaming request duration is not
buffering time; interpret it alongside playback progress and socket counters.

The desktop collector reads bounded pod-log tails through its existing read-only
helper. Verify a fresh HTTPS request produces JSON records after Helm rollout.
The log buffer holds 100 entries; wait for traffic to fill it before concluding
that logging is broken. Pod-log rotation and bounded collection can lose records.
Rollback through Git by setting logs.access.enabled=false and checking rollout.

## BBR configuration

Repo configuration requests BBR in Traefik's pod network namespace. This applies
across Traefik TCP routes, including Emby and speedtest, not HTTP/3/UDP. Host TCP
defaults are unchanged. The operator later reported the pod using BBR during migration. A causal
streaming-performance improvement has not been established.

Fresh rebuild: follow the [bootstrap toolkit guide](../../../bootstrap/README.md).
The guided entry point no longer installs anything automatically. Use explicit
host package/install/feature commands. Run `host features` on the intended
Traefik node and schedule the k3s restart before syncing the BBR manifest.
Choose the node name deliberately to match the Traefik selector; update the
selector/router forwarding together if it changes. Requires K3s >=1.32 and
a Linux kernel providing tcp_bbr. Repeat preparation on future ingress nodes.

For a rebuild or an intentional prerequisite change on an existing master, run
the following only in a maintenance window; this is not a pending migration step:
from the updated repo checkout on that master:

```sh
sudo apt-get install -y python3-yaml
sudo bash bootstrap/configure-traefik-bbr.sh
sudo systemctl restart k3s
sudo kubectl wait --for=condition=Ready node/control-plane --timeout=180s
```

Allow a maintenance window for the service restart and Traefik rollout; streams
may disconnect. The helper is repeatable, preserves existing drop-in allowances,
and does not restart services. It uses K3s's default kubelet config directory;
custom config-dir paths or command-line allowed-unsafe-sysctls overrides must
be reconciled separately. Argo cannot install node files merely from Git.

After pushing, wait for Helm reconciliation and the new Deployment revision
before checking rollout status (an old revision may still report ready):

```sh
sudo kubectl -n kube-system get deployment traefik -o yaml
sudo kubectl -n kube-system rollout status deployment/traefik --timeout=180s
sudo kubectl -n kube-system exec deployment/traefik -- cat /proc/sys/net/ipv4/tcp_congestion_control
```

The rendered pod must request the sysctl and the live value must be bbr. If pods
fail admission, inspect events for SysctlForbidden and check the node allowlist.
Verify public HTTPS, remote client IP reporting, and actual new client TCP sockets
in the pod network namespace; then repeat remote HTTPS throughput and playback
observations. A host sysctl read alone does not verify Traefik.

Rollback: explicitly set the Helm pod sysctl value to cubic in Git, reconcile,
and verify the new pod and live value. Keep the node prerequisite installed
through the trial. Removing the Application with pruning off is not a rollback.

References:
- https://docs.k3s.io/installation/configuration#kubelet-configuration-files
- https://kubernetes.io/docs/tasks/administer-cluster/sysctl-cluster/
