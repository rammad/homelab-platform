# OpenSpeedTest

The `openspeedtest` Argo Application owns the workload, Service, certificate,
ingress route and TLS settings. Public HTTPS routes directly to the application's
Service in `tools` on port 3000. The TLS option limits negotiation to HTTP/1.1.

Its registration is in `argocd/edge-applications/openspeedtest.yaml`, managed by
the `edge-applications` parent. That directory groups registrations; it does not
create a second edge proxy or a separate route owner.

Review changes in Argo, then test the public page and an intentional speed test.
A speed test consumes network capacity, so choose an appropriate time. No
persistent application data needs to be restored for this service.
