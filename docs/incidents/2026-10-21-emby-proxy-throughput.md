# Emby playback and remote proxy throughput investigation

Updated: 2026-10-21. Status: improving, root cause not established.
Sources: operator reports and screenshots in Emby troubleshooting chat; read-only Nginx Proxy Manager settings and log inspection on October 21. Earlier observations below are historical, not a fresh live audit.

## Changes and current baseline

- Operator disabled ASUS QoS after observing roughly 50% throughput reduction with it enabled. Reported speeds improved; controlled before/after measurements were not retained here.
- Operator reports physical server path changed from modem -> router -> access point -> 10G switch -> server to modem -> router -> 10G switch -> server. Access point is no longer inline. Exact change time relative to speed tests is unknown. This resembles the prior NYC topology; it does not establish that the AP caused latency, loss, or throughput problems.
- Emby temporary transcode storage was moved from application-pool to a dedicated media-dataset folder. Operator reported stuttering returned when restored to application-pool and requested moving back. Historical path: /media-data/.emby-transcode-diagnostic-20261018 inside Emby, /mnt/storage-pool/media-data/.emby-transcode-diagnostic-20261018 on host. Not reverified October 21.
- Tdarr exclusions include .emby-transcode in file paths; operator also removed .ts from target types. Existing queued entries may persist. Leave Tdarr schedule/workload alone per operator preference; reported heavy workload 06:00-10:00 Eastern.
- Emby throttling enabled during earlier investigation (historical buffer setting 120 seconds). Playback correction resolved the laptop's observed session; this does not identify which playback-path change was decisive.
- WebSocket support was enabled on Emby's Nginx proxy earlier. LAN playback failures bypassed that proxy, so this cannot explain every observed stall.
- Temporary direct HTTPS speed-test forwarding on external port 30117 provides a comparison against the proxied HTTPS domain. Both paths use TLS.
- Speed-test proxy HTTP/2 disabled by operator. Error log requests confirmed HTTP/1.1. Operator reported no clear improvement from this alone.
- Speed-test proxy Advanced configuration now contains `proxy_buffering off;` and `proxy_request_buffering off;`. Saved values independently inspected October 21. Cache Assets off is separate from proxy buffering.
- Operator confirmed applying the same two buffering directives to Emby's proxy October 21. Emby values and post-change playback have not yet been independently verified. HTTP/2 was already off for Emby; HTTPS and WebSockets should remain enabled.
- Earlier periodic domain probe was cancelled at operator request. Do not restart automatically.

## Observations

Public DNS checks October 21 resolved speed-test and Emby names to the origin, not a Cloudflare proxy address. Cloudflare was not observed carrying HTTP traffic; reassess if DNS/proxy state changes.

Nginx speed-test upstream was HTTPS on port 30117; Emby upstream HTTP on port 9096. Both hosts had no custom configuration before this experiment and asset caching off. NPM version observed: 2.16.0.

Initial sequential remote tests favored bypass: approximately 38.9 versus 14.2 Mbps download, then 53 versus 8-10 Mbps. After changes, screenshots showed:

| Sequential pair | Direct download/upload Mbps | Proxy download/upload Mbps |
|---|---|---|
| Domain first, direct second | 40.0 / 309.2 | 69.7 / 66.5 |
| Direct first, domain second | 66.6 / 317.3 | 78.2 / 50.0 |

Download means server-to-remote-client, the direction relevant to playback. Upload is the reverse direction. Simultaneous tests compete for bandwidth and are excluded from causal comparison. A brief 120 Mbps peak is not sustained capacity.

Speed-test error logs showed response buffering to /var/cache/nginx/proxy_temp and request buffering to /tmp/nginx/body during slow tests. Earlier displayed October 21 warnings counted 133 response spills and 172 request spills. These were warnings, not proof of storage failure. Backing storage for those container paths was not established.

Latest read-only log check: final buffering warning at 2026-10-21 17:48:31 UTC (10:48:31 Pacific). Access log continued through 17:55:15 UTC (10:55:15 Pacific), including HTTP 200 downloads/uploads, with no later displayed error entries. This supports the buffering change taking effect, but the logs lack request durations and TCP loss data. HTTP 200 alone does not prove uninterrupted delivery.

Earlier LAN tests, transcode-storage comparisons, and Samsung Tizen playback issues may represent separate problems. A successful 4 Mbps TV session and later successful direct playback do not establish permanent recovery.

## Conclusions and limits

- Latest sequential tests no longer show the earlier proxy download penalty. Proxy upload remains markedly slower.
- HTTP/2-off alone did not visibly resolve the problem according to the operator.
- Removing proxy buffering is verified for speed-test and a plausible improvement, not a proven root cause or confirmed Emby fix.
- Cabling, QoS, storage, client playback mode, and proxy changes occurred across the investigation. Their individual contributions have not been isolated.
- No evidence here justifies declaring modem, NIC, switch, AP, or disks defective, or concluding Emby/Jellyfin migration is required.
- Home-workstation-to-public-domain tests are not remote-user or ISP upload measurements.

## Next evidence and rollback

1. Verify Emby's saved buffering directives and correlate a sustained remote session using the previously problematic movie/client/quality with logs and stall timestamps.
2. Keep topology and settings stable while measuring. Record playback mode, bitrate, time, and concurrent Tdarr/storage load.
3. If needed, alternate sequential domain/direct speed tests with repeated runs. Capture request duration, upstream timing and host resource/network counters to investigate remaining upload disparity.
4. Reconsider the AP only with controlled link/error-counter evidence; do not reinsert or replace hardware merely to match a theory.
5. Buffering rollback: remove the two added directives and save. Avoid bundling this with QoS, topology or transcode-storage changes.
6. Review removal of temporary external speed-test forwarding when diagnostics are finished; no removal performed in this documentation task.

No deployment, Git push, or infrastructure change was performed while writing this record.
