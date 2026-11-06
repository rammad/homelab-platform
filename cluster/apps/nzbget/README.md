# NZBGet

Runs in namespace `media` on `control-plane`. LAN UI:
`http://192.0.2.10:30678/`; in-cluster endpoint:
`nzbget.media.svc.cluster.local:6789`.

Configuration persists on NAS NFS at `/mnt/application-pool/k3s-app-data/nzbget`,
mounted as `/config`. The shared `arr-media` claim mounts downloads and libraries
at `/media-data`. Credentials come from `nzbget-credentials`; never commit the
private configuration or credentials.

## Download performance over NFS

Operator observation, 2026-11-06: after migration, download speed stayed below
approximately 5 MB/s. Configuration showed `ArticleCache=0`, `DirectWrite=yes`,
`WriteBuffer=1024`, `DownloadRate=0`, and 20 server connections. Intermediate
files were under `/media-data/downloads/tmp`; CPU was 131m at the sampled time.

Changing **Settings → Download Queue → ArticleCache** to **512 MiB** improved
reported download speed to approximately **60 MB/s**. Leave DirectWrite and
WriteBuffer at the above values for this established baseline. The result
supports uncached writes over NFS as the bottleneck in this workload; it is not
a general storage benchmark or a guarantee for every provider/download.

This setting lives in the private persistent NZBGet configuration, not the
Deployment YAML. Preserve it when restoring configuration, and set it explicitly
for a fresh installation. Save/reload through NZBGet's UI; avoid editing its
configuration file while it is running. The cache consumes additional RAM.

No image change, node restart or Emby interruption was needed for this fix.
