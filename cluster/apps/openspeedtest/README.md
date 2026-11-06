# OpenSpeedTest

The openspeedtest Argo Application owns the workload, Service, Certificate,
Ingress and TLSOption. Public HTTPS routes directly to tools/openspeedtest:3000.
The HTTP/1.1 TLS option is retained from the existing deployment.

Ownership consolidation completed 2026-11-05, with public routes verified by
the operator. The live legacy owner was `open-speedtest`; `edge-speedtest` was
also present in earlier repository definitions. See the
[handoff record](../../../docs/case-studies/truenas-to-k3s.md).
