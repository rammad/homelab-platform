> Historical rollout record. The 2026-11-05 [edge consolidation](case-studies/truenas-to-k3s.md)
> supersedes the separate edge application ownership described below.

# Traefik edge rollout through Argo CD

Status: operator reports public Traefik cutover and application checks complete,
NPM stopped, HTTP redirects working, and fresh phone-session location restored
following the source-IP change (2026-10-21). Remote throughput comparisons remain
inconclusive. The auto-sync policy below is a local review change until pushed.

## Current operating policy after cutover

The parent and all eight edge children now declare automated sync enabled,
with self-healing enabled and pruning and empty-app allowance explicitly disabled.
Reviewed Git pushes can deploy resource changes automatically after these
Application policies reconcile. Deleting a manifest does not automatically
delete the corresponding live resource. Self-healing restores managed live resources to Git when drift occurs, even
without a new commit. The operator explicitly prefers fixes through Git over
direct Kubernetes edits. Existing non-edge apps are
outside this policy edit and retain their current settings.

The parent is bootstrap-owned, not self-managed. The operator reports enabling
its live auto-sync in the UI; verify its options match bootstrap/edge-applications.yaml.
Pushing that file alone does not reconcile the parent. Once the live parent
syncs the child definitions, each child auto-syncs its own workload resources.
Preserve all existing sync options, especially server-side apply for Argo settings.

The staged manual-sync instructions below describe initial installation and
remain relevant to a rebuild: temporarily keep automation disabled until CRDs,
credentials, certificates and cutover prerequisites are ready. Do not bootstrap
all auto-sync apps into a fresh cluster without those dependency gates.


## Git is the deployment source

The root Application is defined in `bootstrap/edge-applications.yaml`. It watches
`argocd/edge-applications`, containing eight child Application definitions.
Each child watches one permanent manifest directory. During initial rollout, Applications omitted `syncPolicy.automated` and
required manual Sync. The post-cutover policy above supersedes that setting. No automated pruning or deletion
finalizers are configured. FailOnSharedResource prevents accidental takeover
of another Argo application's resources.

Do not copy manifests to the VM or use kubectl apply for the workloads.
There is one initial registration step after the reviewed commit is pushed:
in Argo's New App UI create `edge-applications`, project `default`, repository
`https://github.com/REPLACE_ME/homelab-platform.git`, revision `HEAD`, path
`argocd/edge-applications`, destination `https://kubernetes.default.svc`, namespace
`argocd`, manual sync. Match bootstrap/edge-applications.yaml, including the
FailOnSharedResource sync option. Alternatively register that root definition
once through an existing bootstrap process. The root itself is bootstrap-owned;
its definition changes require reconciling that bootstrap object. It does not
manage itself. Child definitions and all workloads are subsequently Git-driven.

Sync the root to register child Applications. This does NOT sync their workloads.
Do not use Sync All, enable auto-sync, or enable pruning during this migration.
Existing namespaces are managed by the existing namespaces app. Immich and Tracearr keep their existing Argo owners. Their existing Ingresses
become HTTPS-only and each app gains certificate.yaml. Emby and Jellyseerr alone
use external-backend edge Applications until they migrate to Kubernetes.

## Order and review boundaries

| Step | Application | Gate before manual Sync |
|---|---|---|
| 1 | edge-cert-manager | Kubernetes compatibility and absence of another installation verified |
| 2 | edge-certificate-issuers | Controller/CRDs/webhook ready; scoped Cloudflare Secret provisioned |
| 3 | edge-emby, edge-jellyseerr | Issuer ready; backend addresses verified |
| 3 | existing immich and tracearr | Publish app TLS changes only after certificate CRDs/issuer are ready; auto-sync may deploy immediately |
| 4 | edge-redirects | Remote HTTPS tests pass; admin routes secured; router cutover coordinated |

A HelmChart resource becoming Synced is NOT proof its installation job completed.
Wait for cert-manager deployments/webhook and CRDs before step 2. Argo cannot
infer these cross-Application dependencies from sync waves; gates are explicit.
Cloudflare credentials remain out of Git. Manage them via a secure secret process;
this is the one external credential prerequisite, not a manually maintained manifest.

After rollout, normal reviewed Git commits update each child application's desired
state. Manual Sync deploys those changes. Automatic sync can be enabled later by
changing the child Application in Git and syncing the root, as a separate decision.
Do not enable it for edge-redirects before the cutover gates are satisfied.

## Commit sequencing and accepted interruption

The operator accepted Immich/Tracearr downtime on 2026-10-21. Their current
Applications may auto-sync on push: this is different from the eight new manual
Applications. Prefer two reviewable commits/pushes: first infrastructure, external
edge routes and Application definitions; install controller/issuers through Argo.
Then push cluster/apps/immich/{ingress,certificate}.yaml and the corresponding
Tracearr files. Do not publish those app Certificate resources before cert-manager
CRDs exist, or their current syncs can fail. Even with CRDs ready, HTTPS-only routes
will interrupt existing NPM HTTP forwarding until cutover. Downtime permission
is not permission to skip certificate or admin exposure checks.

If the earlier draft Applications were ever registered, remove their desired
Application definitions and verify they own no resources before consolidation.
This task has not registered or deployed them. Do not allow two apps to own the
same Ingress or Certificate.

## Observed baseline

Operator command output: K3s/Kubernetes v1.35.5+k3s1; Traefik 3.6.13;
chart 39.0.701+up39.0.7; LoadBalancer 192.0.2.10 on ports 80/443;
externalTrafficPolicy Cluster; no HelmChartConfig or cert-manager CRDs/deployments.
Only existing HTTP Immich/Tracearr Ingresses, the legacy Argo IngressRoute,
and no IngressRouteTCPs were reported. Argo NodePorts are 31786 HTTP and 30973 HTTPS.
These are operator-provided observations, not a guarantee of future state.
Argo UI inspection found four existing apps tracking HEAD in cluster/apps/immich,
cluster/apps/tracearr, cluster/apps/tdarr and cluster/namespaces. Immich auto-sync
was confirmed. No existing child watches the new directories.

## Design

Router TCP 443 -> verified Traefik endpoint -> HTTP application backends.
Router TCP 80 -> same Traefik endpoint -> redirects for the four listed names.
Cloudflare remains DNS-only. Existing public URLs remain unchanged.
Emby and Jellyseerr stay on TrueNAS; selectorless Services and EndpointSlices
route directly to 192.0.2.30:9096 and :30043, bypassing Nginx.
Immich and Tracearr use their existing Kubernetes Services.
HTTPS terminates at Traefik; backend HTTP is on the trusted LAN/cluster,
matching existing backend transport. This does not add backend TLS or network isolation.

No buffering, compression, authentication middleware, custom timeout, or
forwarded-header trust overrides are added. Native WebSockets should work;
verify with the actual clients. Do not globally trust client-supplied forwarded
headers. Verify Emby's remote-client classification and configure only the
actual trusted proxy addresses if required; never classify all remote users as LAN.

Traefik is already installed by K3s. No second controller or replacement
HelmChartConfig is introduced without knowing its current chart values.
Immich/Tracearr ingress names are preserved but now use websecure only. Their
old NPM HTTP upstreams will stop working until the edge cutover (downtime accepted
by operator). External Emby/Jellyseerr routes are additive; their NPM paths remain
unchanged. No separate edge-immich or edge-tracearr Applications are needed.

## Required live checks (not established by Argo app view)

Run read-only commands on the K3s administration host, retaining sanitized output:

```sh
kubectl version
kubectl -n kube-system get deployment traefik -o wide
kubectl -n kube-system get service traefik -o yaml
kubectl -n kube-system get helmchart traefik -o yaml
kubectl -n kube-system get helmchartconfig traefik -o yaml
kubectl get ingress,ingressroute -A
kubectl get clusterissuer,certificate -A
kubectl -n argocd get applications -o yaml
```

Confirm Traefik supports EndpointSlices and has websecure on a reachable 443.
Confirm cert-manager is absent before installing it. Chart v1.21.2 is pinned
from official installation documentation; check its Kubernetes compatibility
against the live version before deployment. If a supported cert-manager is
already present, use it instead of creating a second installation.
Merge any needed Traefik tuning into its existing HelmChartConfig; do not
replace existing values or edit K3s-generated traefik.yaml.
Confirm namespaces media, data, tools already exist (managed by namespaces app).
Confirm TrueNAS ports and firewall reachability from Traefik, and inventory ALL
Nginx hosts before retiring it. Storage and speedtest are not migrated here;
public cutover must wait for a decision/routes for those hosts too.

## Phase 1: certificate controller

After review, manually sync edge-cert-manager in Argo. The K3s Helm controller then installs the versioned chart.
Wait for the Helm installation and all cert-manager deployments/webhook to be
Ready before applying CRs. Installation is cluster-wide; do not reinstall if
another controller already owns it. Establish one GitOps owner per resource.

## Phase 2: DNS credentials and issuers

Create a Cloudflare API token restricted to example.com with Zone DNS Edit
and Zone Read. Store it out of Git as Secret cloudflare-dns-token in namespace
cert-manager with key api-token. Do not commit a real Secret or token file.
ClusterIssuers use the default cluster-resource namespace cert-manager; verify
that the existing controller has not overridden it. ACME contact email is
optional and omitted; add an operator-approved address if desired.

Sync edge-certificate-issuers only after the secret and controller exist. Validate staging
with a disposable Certificate/secret before requesting production certs.
Never serve the staging certificate to normal users. The app manifests use
letsencrypt-production and distinct per-application TLS secrets. DNS-01 works
without moving public 80/443. Keep certificate renewal and Secret ownership
with cert-manager; do not copy NPM private keys into Git.

## Phase 3: direct HTTPS routes and testing

Sync the two external edge apps and deploy the existing apps' TLS changes after production issuer readiness. Wait for all four
Certificates to report Ready=True; do not accept Traefik's default certificate.
Verify EndpointSlice ports/addresses and service routing with server-side dry-run
before apply. A ready EndpointSlice is static configuration, not a health probe.

Test locally, preserving hostname/SNI and normal certificate validation:

```sh
curl --resolve stream.example.com:443:192.0.2.10 https://stream.example.com/ -I
curl --resolve request.example.com:443:192.0.2.10 https://request.example.com/ -I
```

Use .180 only if the live Service confirms it as a usable ingress endpoint.
Check login, seeking, subtitles, WebSockets and long playback. Check requests
login, media search and callback/base-URL behavior. Verify Immich uploads and
Tracearr before cutover. Do not infer streaming success from HTTP 200 alone.
A temporary external test port may map to Traefik 443 after separate router
approval; users explicitly testing it include that port. Repeat direct/NPM/
Traefik sequential tests from affected households. Do not change other variables.
Traefik on the NAS-hosted VM still shares physical resource constraints.

## Admin exposure gate â€” mandatory before WAN forwarding

On 2026-10-21, terminal inspection found a legacy bootstrap-owned HTTP Argo
IngressRoute matching Host(192.0.2.10), with no access middleware or Argo
tracking marker. The former checked-in manifest used 192.0.2.10 instead.
Host matching is NOT access control; a bare-IP 404 did not establish safety.
The bootstrap script now creates private administration NodePort 31786 instead
of an IngressRoute, and the standalone legacy manifest has been removed.
NodePort is not inherently LAN-only: firewall/router rules must prevent WAN
access on every node. Use an authenticated VPN or SSH tunnel on untrusted networks.

This Git change does not delete the existing bootstrap-owned live route.
After verifying the existing private Argo UI works, perform this one-time cleanup
on the K3s VM (do not rerun bootstrap on the existing cluster):

```sh
sudo kubectl -n argocd get ingressroute argocd-server -o yaml > ~/argocd-ingressroute-before-removal.yaml
sudo kubectl -n argocd delete ingressroute argocd-server
sudo kubectl -n argocd get ingressroute
```

Refresh the private Argo UI afterward. Terminal inspection on 2026-10-21 confirmed deletion and no remaining
IngressRoutes in the argocd namespace. The operator confirmed the private
Argo UI still works.
The backup is for recovery only; do not restore an unrestricted admin route
while Traefik is WAN-facing.
Audit other admin/dashboard routes and firewall rules. From outside, requests
with forged private Host headers must not reach Argo or other administration.
Do not rely on IP allowlisting until source-IP preservation/SNAT is verified.

## Phase 4: coordinated cutover

Only after all preceding gates and remaining public-host inventory are resolved:
1. Record existing router rules and keep NPM running for rollback.
2. Point public TCP 443 and 80 to the verified Traefik endpoint, not NPM.
3. Sync edge-redirects. Do NOT apply this while NPM still forwards HTTP
   to Traefik: it could cause redirect loops for the current public paths.
4. Test normal URLs without ports, external HTTP redirects, certificate chains,
   all affected clients and renewal status. Do not enable HSTS during migration.
5. After a stable observation window, remove temporary test forwards and retire
   unused NPM routes. Keep secrets/backups under existing retention practices.

No global HTTP redirect is added: only the four explicit hostnames redirect.
Unknown hosts should return 404; this is not a substitute for the admin audit.

## Rollback

First remove the edge-http-redirect IngressRoute (or revert/sync its approved
GitOps source). Revert Immich and Tracearr ingress.yaml to their pre-migration
HTTP configurations in Git and wait for their existing Applications to sync;
otherwise NPM HTTP upstreams will remain broken. Restore recorded router
forwards to NPM. Keep external Emby/Jellyseerr routes and certificates for
diagnosis; no media/app data was migrated.
Do not blindly uninstall cert-manager or delete TLS secrets/CRDs on rollback.

## Review and validation

No live dry-run, chart rendering against installed Traefik, or performance test
has been performed from this workstation. Local YAML/reference checks are not
cluster validation. Before deploy, run kubectl apply --dry-run=server separately
on each phase after its CRDs exist, inspect diffs, then use manual sync.
Keep the root and child Applications manual-sync during rollout. Do not broadly auto-sync cluster/.

References:
- https://docs.k3s.io/networking/networking-services
- https://docs.k3s.io/add-ons/helm
- https://cert-manager.io/docs/installation/helm/
- https://cert-manager.io/docs/configuration/acme/dns01/cloudflare/
- https://kubernetes.io/docs/concepts/services-networking/service/#services-without-selectors
- https://doc.traefik.io/traefik/reference/routing-configuration/kubernetes/ingress/

## EndpointSlice discovery prerequisite

Argo excluded EndpointSlices, so the initial Emby sync created no backend slice
and HTTPS returned 503 despite a valid certificate. See
`cluster/infrastructure/argocd-settings/README.md` for the Git-managed partial
ConfigMap fix and sync sequence. Sync edge-argocd-settings before the external
backend apps. All other supplied resource exclusions are retained.

## Operator decisions and next validation — 2026-10-21

- Storage and speedtest should eventually remain public, but their Traefik routes
  are explicitly deferred by the operator. Track both as follow-up work. A main
  80/443 cutover before those routes exist will interrupt their current public
  access; confirm that consequence at cutover. NPM remains available for rollback.
- The operator reported unplugging the B580 worker and intends to reconnect it.
  Tdarr worker recovery is not yet verified; no migration fault was established.
- Next: controlled remote HTTPS playback through a temporary router TCP port
  forwarded to Traefik 443, leaving current public 80/443 on NPM. Confirm an
  unused external port before adding a rule. Compare the same media/client
  sequentially through NPM and Traefik. Keep edge-redirects unsynced until cutover.

### Speedtest brought forward — 2026-10-21

The operator requested a direct/NPM/Traefik throughput comparison before playback.
Speedtest is now prepared as edge-speedtest (manual sync, tools namespace);
The former backend TLS exception was retired by the later in-cluster migration;
current configuration is in ../cluster/apps/openspeedtest/.
This supersedes its earlier deferral. Storage remains deferred. These new files
are local review changes, not evidence of deployment or a performance improvement.

## Corrected phone comparison — 2026-10-21

Operator correction during live troubleshooting: the Nginx test on external
44343 reporting roughly 60 Mbps download / 138 Mbps upload (later upload near
180) was on HOME WI-FI, not cellular. The earlier inference that changing the
same port from Traefik to Nginx restored cellular performance is withdrawn.

Reported phone results (approximate Mbps; sequential, not controlled benchmarks):

| Connection | Destination/path | Download | Upload |
|---|---|---:|---:|
| Cellular | Traefik via external 44343 | 6–10 | 5–6 |
| Cellular | Nginx normal HTTPS 443, later run | 115 | 100–130 |
| Cellular | Direct HTTPS bypass, earlier run | 110 | 150 |
| Home Wi-Fi | Traefik via external 44343 | 50 | 75 |
| Home Wi-Fi | Nginx normal HTTPS 443 | 90 | 130 |
| Home Wi-Fi | Direct local backend | 85–90 | 110–120 |
| Home Wi-Fi | Nginx via external 44343 | 60 | 138 (later near 180) |
| Cellular, corrected repeat | Nginx via external 44343 | 8 | 15–20 |

The operator confirmed external 44343 now points to NAS 192.0.2.30 (Nginx),
not the K3s VM. Assistant verified the NAS HTTPS listener on port 443 serves
speedtest with HTTP 200 and valid TLS before the rule change. Router destination
confirmation is operator-reported, not independently inspected.

Terminal samples during earlier Traefik tests showed CPU 1–56 millicores,
memory 140–146 MiB, resources {}, and no recent log output. These are sampled
resource observations, not request/access traces or proof of no packet loss.
Local HTTP/1.1 bounded downloads through Traefik reached roughly 470–856 Mbps;
home-workstation-to-public-domain download reached roughly 332 Mbps. Neither
is a remote-user measurement or equivalent to the phone browser's test.

Current conclusion: cellular slowness through external 44343 occurs with BOTH
proxy destinations. Traefik-only attribution is unsupported; router handling,
carrier/network treatment, browser behavior and temporal variability remain
unresolved. Next compare Nginx normal 443 and Nginx 44343 sequentially on the
same phone with Wi-Fi off, repeat in reverse order without changing forwarding.
Do not cut over production or tune Traefik based on the invalid comparison.

## Client-address follow-up — 2026-10-21

Operator reports public cutover, NPM stopped, apps working and redirects synced
and verified. Remote sessions are classified local with address 10.42.0.1.
Prepared edge-traefik-config for manual review/sync; see
../cluster/infrastructure/traefik/README.md for observations, rollout and rollback.
This change is not yet deployed or proven to resolve the symptom.

## Emby HTTP/1.1 follow-up — 2026-10-21

After speedtest was restricted to HTTP/1.1, operator cellular comparisons showed
URL downloads 19.8–44.7 Mbps and uploads 106.4–119.0 Mbps versus direct downloads
12.5–25.2 and uploads 23.7–36.4. The operator subsequently reported their remote
friend's URL download was at least as good as direct. This supports retaining
the speedtest change; it does not establish the precise HTTP/2 failure mechanism
or prove an Emby improvement.

At the operator's request, Emby now has a local proposed media/emby-http1
TLSOption referenced only by its Ingress, offering HTTP/1.1 with TLS 1.2 minimum.
HTTPS certificate verification, source-IP preservation, backend address/transport,
and other hostnames are unchanged. No global protocol override is introduced.

Review and push deploys this through edge-emby auto-sync. After reconciliation,
verify ALPN negotiates HTTP/1.1 when a client offers both h2 and http/1.1, normal
TLS validation succeeds, and login, playback, seeking and WebSockets work on a
fresh client connection. Existing persistent connections may retain their old
protocol until reconnected. The change is not live-verified by this local edit.

Rollback: remove the Emby router.tls.options annotation in Git and deploy.
The unused TLSOption may remain because pruning is disabled; remove it through
an explicit reviewed cleanup if desired. Keep the independent speedtest option.
