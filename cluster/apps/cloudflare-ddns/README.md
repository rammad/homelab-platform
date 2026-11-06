# Cloudflare DDNS

One updater in `tools`, with no PVC, Service or Ingress. The manifest uses host
networking, IPv4-only updates for `example.com`, and `PROXIED=false`. The image
is pinned by digest. The API token comes from Secret `tools/cloudflare-ddns`,
key `CLOUDFLARE_API_TOKEN`; keep it out of Git and command history.

## Operate

The checked-in registration is `bootstrap/cloudflare-ddns-application.yaml`.
The toolkit can check or prepare its required Secret; registration does not
replace an existing Argo Application. Review live sync policy before changes.

```bash
sudo k3s kubectl -n tools rollout status deployment/cloudflare-ddns
sudo k3s kubectl -n tools logs deployment/cloudflare-ddns --tail=60 -f
```

Logs should show the detected public IPv4, successful authentication and a
successful update or already-current record. Check a subsequent polling cycle
as well. Pod readiness alone does not establish successful DNS updates.

## Evidence and recovery

During the 2026-11-04 migration, operator logs showed the expected record was
already current and another check was scheduled. This is a dated observation,
not continuous DNS monitoring. Host networking was retained from the old app.

Run only the intended updater. If moving it again, stop the existing instance
before starting its replacement, accounting for Argo reconciliation. No
application database needs copying; restore the API credential and reviewed
manifest. Existing DNS records remain subject to the configured updater policy.

[Upstream project](https://github.com/favonia/cloudflare-ddns) ·
[Migration case study](../../../docs/case-studies/truenas-to-k3s.md)
