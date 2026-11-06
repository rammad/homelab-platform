# Emby observed configuration and playback diagnostics

Observed 2026-10-25 through authenticated API readback. This is a TrueNAS-native
application, not an Argo-managed workload. The accompanying
configuration snapshot (retained privately) records server, encoding,
library and Diagnostics settings plus installed plugin versions. It excludes
credentials, user accounts/client preferences, and plugin-specific secrets.
It is a review/recreation reference, not a complete disaster-recovery backup.

## Current configuration

- Emby 4.10.2.0; Diagnostics PlugIn 4.8.0.81.
- TrueNAS backend HTTP 192.0.2.30:9096. Public TLS terminates at Traefik.
  `cluster/apps/emby/edge.yaml` defines HTTP/1.1 ALPN with TLS >=1.2.
- Live server API: `EnableHttps=false`, `RequireHttps=false`,
  `IsBehindProxy=false`, `ProxyHeaderMode=AllAddresses`, no configured local
  subnets, `RemoteClientBitrateLimit=0`. These are observations, not an endorsement
  of trusting all forwarded-header senders. Backend exposure and proxy trust
  deserve separate review; do not change client classification during diagnosis.
- Transcode directory: `/media-data/.emby-transcode-diagnostic-20261018`.
  Verify this exact path remains excluded from Tdarr (do not assume the shorter
  historical `.emby-transcode` description is the complete path).
- Hardware encoding and hardware tone mapping enabled; software tone mapping off.
  QSV H.264/HEVC encoders retained. VC-1 QSV decoder disabled after repeat failure.
- Baseline October25: throttling enabled, BySegmentRequest, buffer120 seconds, hysteresis8.
  October26 trial disables EnableThrottling; see trial notes below.
  Encoding threads -1; extraction threads 1; maximum width 0; HEVC output enabled.
- Subtitle extraction and on-the-fly attachment extraction enabled.
  Diagnostics: DisableHlsSubtitles=false, DisableStreamSubtitles=false,
  ForceSubtitleBurnIn=false, DisableHardwareSubtitleOverlay=true,
  DisableSubtitleFiltering=true. The last two matched the plugin's reported
  DefaultObject; they were not toggled as a repair in this investigation.
- Server debug logging off, normal transcoding log level Info, log retention
  three days. Database cache 128 MB, SQLite MMIO disabled.
- AniList/AniSearch remain installed, but were removed from metadata/image
  fetchers in Anime (Movies) and Anime (Shows). No scan was triggered.

## VC-1: supported software path versus advertised decoder

Hardware decode support depends on the installed GPU and driver, not just the
FFmpeg build. The observed VC-1 initialization failure and successful software
fallback motivated retaining software decode for that codec while using hardware
encoding. Check the vendor support matrix for the target hardware before forcing
hardware input decoding; this finding does not explain every Tdarr failure.

Keep VC-1 software decoding and supported QSV encoding. For Tdarr, inspect the
actual job/node command before changing a flow: remove forced VC-1 hardware
input decoding for that codec, preserving GPU output encoding. Do not disable all
hardware decoding or transcode/replace a whole library as a diagnostic action.
Source: https://github.com/intel/media-driver#decodingencoding-features

## Subtitle failure and rejected global workaround

A bounded local playback probe reproduced `Too many packets buffered for output
stream 1:1` followed by `Conversion failed!` on the HLS subtitle output at the
same source position as an affected remote session. Output 1 is the subtitle
mux, not proof that the video QSV encoder failed. An external-subtitle profile
avoided this failure in the equivalent test; real-client subtitle rendering
was not validated.

The global Diagnostics DisableHlsSubtitles=true experiment made an HLS-only
profile fall back to burn-in. Its first segment timed out after 15 seconds and
FFmpeg logged `Failed to load fontconfig fonts!`. The flag was reverted to false.
This is a demonstrated compatibility risk, not merely a lack of testing.
Burn-in can require video transcoding, font setup and more processing; style
overrides do not fix a mux-queue failure. Forced/default tracks can be selected
without a viewer intentionally enabling subtitles. Inspect selected track and
actual delivery mode before attributing another stall to subtitles.

Diagnostics options are volatile and can reset. Do not blindly reapply them at
startup. The collector checks the HLS flag every minute. We have not established
a shared cause for all remote buffering sessions.

## Recreation and verification

1. Restore Emby app data from its separate private backup and recreate original
   TrueNAS mounts/GPU access. This snapshot does not contain databases, users,
   secrets, app deployment definition or client-specific preferences.
2. Compare server and library settings against the JSON. Preserve library IDs;
   avoid bulk POSTing a historical snapshot into a different server version.
3. Re-detect hardware codecs on new hardware; `devid22182` is observed device
   identity, not a portable constant. Keep unsupported VC-1 QSV disabled on Arc.
4. Compare volatile Diagnostics settings separately. Do not enable the rejected
   HLS switch. Validate direct playback, transcode, seek and subtitles.
5. Check remote IP classification, TLS and request timing through the public
   route. Synced Argo applications alone do not validate playback.

## Logging gaps and prepared collection

The desktop collector remains the central store outside Git. The K3s fixed
no-argument root-owned helper is installed and verified: kernel journal, process
I/O/wait channels, Traefik namespace TCP counters/socket details and container-log
tails. No unrestricted sudo or cluster-admin credentials were granted.

The analogous NAS installation failed because `/usr/local/sbin` is read-only.
Do not remount TrueNAS writable or rerun that installer there. TrueNAS container
logs are collected through its supported `apps logs` API; detailed Emby server
and FFmpeg logs continue over existing SSH access. Restricted NAS kernel journal
and per-process I/O remain uncollected. The API search did not establish a bounded
supported kernel-log endpoint. A supported remote syslog configuration could
address kernel/system events later, but would not supply per-process I/O.

Access-log tails overlap; deduplicate by file, request timestamp/RequestCount
rather than counting each poll as a new request. Tails are bounded and can miss
high-volume bursts or rotations. TrueNAS container tails are bounded to 200 rows
per minute; duplicate suppression is in memory and resets with the collector.

The pending Traefik HelmChartConfig change enables unfiltered JSON access logs
on stdout: successes are needed as a baseline, not only errors. It retains
client addresses, response bytes, origin/downstream status and timing; request
paths/lines and headers are dropped to avoid authentication material. Correlate
with Emby session/server logs by time and client address. Access logs finish at
request completion, so long-lived requests need socket sampling as well.
A buffer of 100 reduces synchronous log writes but can lose buffered records on
crash. Pod logs rotate; the collector is not a permanent log platform.

Commit/push of the logging change triggers a Traefik rollout through Argo/K3s;
review first and expect possible brief stream disruption. Check Helm reconciliation
and rollout, make one HTTPS request, and verify JSON fields actually appear.
Rollback: set logs.access.enabled=false in Git. This does not disable normal logs.

Still not collected: router WAN queue/drop counters, modem signal/error history,
and client buffer occupancy. These gaps remain even after installing helpers;
a clean server error log does not rule out stalled network delivery.

## Logging deployment and maintenance window — 2026-10-26

User authorized deployment during an idle window. Commit e7e5eb5 enables
Traefik JSON access logging; the new pod emitted117 access records in the
verification tail at15:48:39UTC. All110 bounded Emby HTTPS checks returned200.
The existing collector process remains running. No global subtitle settings or
client bitrate limits changed. An external-subtitle synthetic-profile test
completed138 video segments (202280292bytes) and cleaned up its test encoder;
actual client subtitle rendering still needs validation.

Operator confirms Tdarr06:00–10:00 America/New_York is accepted maintenance
(03:00–07:00 America/Los_Angeles). Leave its workload and schedule unchanged.
The overnight app-storage/API incident overlaps that window and is likely Tdarr
per the operator; individual-writer attribution remains unproven.

## Playback experiment — 2026-10-26, 09:00 Pacific

User requested an actual reversible playback adjustment. Changed the standard
encoding setting `EnableThrottling` from true to false through Emby API and
verified readback. New transcodes may run ahead without the throttle/resume
cycle. This may reduce readiness delays if that cycle contributes; it is not
a proven cause or a client buffer-size change. Direct-streamed playback is
unaffected. GPU/CPU use and temporary-media writes can increase, including
encoding video the viewer never watches. Tdarr maintenance remains unchanged.

A preceding buffer trial (encoding ThrottleBufferSize=300, then Diagnostics
ThrottleOptions.OverrideThrottleBufferSize=300) was accepted by the APIs but
fresh HLS streams still logged TargetBufferSize120s. Both buffer overrides
were restored to baseline before this trial. Subtitle options remain unchanged.

Rollback: GET System/Configuration/encoding, set only EnableThrottling=true,
POST the resulting object and verify readback. Do not restore a full historical
snapshot over unrelated later changes. Private pre-trial backup is retained
with the desktop observer state under changes-20261026.

Evaluate ordinary transcoded sessions separately from direct streams and the
03:00–07:00 Pacific maintenance window. Compare segment availability, player
restarts/progress deficits, CPU/GPU pressure and temporary-storage use. Revert
if added resource use coincides with worse playback, or no benefit emerges.

## Remaining subtitle failures — 2026-10-26 retest

Known HLS failure log maps input forced-English subtitle0:2 to output1:0 and
video0:0 copied to helper output1:1; normal English and SDH also generate
separate HLS subtitle outputs. Output1:1 queue overflow kills the entire FFmpeg
process. This is a server packaging failure, not evidence of insufficient WAN
capacity. A matching firsthand Emby report has later recurrence despite its
initial solved badge: https://emby.media/community/topic/127710-strange-behaviour-with-forced-subtitles/

A test-only Encode subtitle profile on October26 at16:14:10UTC, using the NAS
LAN endpoint and60s client timeout, returned HTTP500. Hardware burn-in exited137
after~15s; software fallback also exited137 after~15s, with FfRunException
Error starting ffmpeg. Fontconfig warnings occurred, but one output initialized
before termination; those warnings alone do not establish the root cause.
Sampled Emby memory.events shows oom=0 and oom_kill=0. Timing suggests a server
startup deadline; code137 alone does not prove OOM or who sent the kill.
The diagnostic encoding was stopped in cleanup. No global subtitle options
changed. This confirms the fallback remains unsuitable for a blanket rollout.

Next isolate embedded subtitle initialization versus a pre-extracted subtitle
input, including source read delays and font initialization. Preserve originals.
The separate subtitle-free direct-stream interruptions need delivery/client
investigation and are not explained by these failures.

## Isolated sidecar comparison — 2026-10-26

Added a uniquely named non-forced English diagnostic SRT sidecar only to the
affected movie Normal(2026), extracted from embedded forced track2 via Emby's
subtitle stream API (1963bytes,34cues,1.285s extraction). Original video and
embedded tracks untouched; refreshed only that item with metadata/image
ValidationOnly. Indexed external subtitle5, displayed English(SRT).

At the same6:18 seek position with throttling off, sidecar burn-in delivered
first segment in0.507s,108segments/158333600bytes in the bounded test;
QSV output sustained~10.9x real time. Fontconfig warning also appears in this
successful test, so it is not independently fatal. Embedded burn-in previously
failed hardware/software startup and returned500. This implicates embedded
subtitle initialization/file-reading, not proven GPU or font incapability.

HLS-profile sidecar selection did NOT fix muxing: FFmpeg still generated
embedded subtitle outputs and failed output1:1.138 downloaded segments were
already available, so transfer completion alone was a false-pass signal. The
local playback probe now checks matched FFmpeg logs for fatal markers and labels
unmatched logs inconclusive. Do not claim a general HLS fix from the sidecar.

The forced track has a gap from03:14.236 to48:05.550. Starting at06:18 is deep
inside the gap; starting from the beginning encounters cues quickly. Sparse
subtitle packets delaying mux initialization is a supported hypothesis, not
yet a completed controlled A/B. Real phone test started from the beginning
and was generating ahead without a mux failure at observation; user-visible
playback/subtitle rendering confirmation pending. Next compare fresh seeks
inside gap versus near48:00 while holding client/profile constant.

Rollback sidecar: remove only the created .en.observer-test.srt file and refresh
that movie. No global subtitle preferences changed. Keep the sidecar until user
testing completes; it contains forced dialogue only, not full captions.

### Controlled seek A/B and user result

User confirms Pixel7 playback and translated dialogue render correctly with the
new English(SRT) sidecar, starting from beginning. Encoder reached100percent.
Controlled synthetic HLS comparison held original embedded track2, movie, client
profile and throttling-off setting constant: start48:00 (five seconds before the
next cue) completed138segments/202284616bytes with no selected fatal markers in
matched FFmpeg logc7b1d622-e9b5-44a1-afda-60dddad110a4. Start06:19.448 inside
the cue gap again produced Too many packets buffered and Conversion failed in
logbd8b5091-e05f-4ba0-983f-2d3babed30ff, despite138segments downloaded.
The exact previous probe position is06:19.448; references to06:18 denote the
FFmpeg keyframe/input seek position or the rounded user test instruction.

This is repeatable start-position-dependent HLS subtitle failure on LAN. Sparse
forced-subtitle initialization is strongly implicated; do not claim it explains
all buffering. Sidecar selection alone does not stop Emby generating embedded
HLS subtitle outputs. A compatibility copy with subtitle streams externalized
is a candidate next test, not an applied library-wide change.


### Compatibility-copy result — 2026-10-26

Created separate Emby item366150, **Normal - Subtitle Compatibility Test**, under
`/media-data/libraries/movies/Normal Subtitle Compatibility Test (2026)`.
Original item348837 was not modified. Lossless remux retains video/audio and
chapters, removes embedded subtitles from this diagnostic copy, and supplies
`.en.forced.srt`. Original and remuxed video/audio packet SHA256 hashes match;
duration5491.936 seconds. Served external subtitle content matches extracted
source exactly after newline normalization (34 forced-English cues).

Same synthetic HLS profile at06:19.448,4Mbps: first video segment0.245 seconds,
138segments/202280292bytes delivered. Matched encoder log
`ffmpeg-transcode-6f514c45-f8dd-4866-a3ea-663580777a5d_1.txt` contains no selected
fatal markers and only video/audio output mappings, with no embedded subtitle
mux outputs. User subsequently reports phone playback looks normal, subtitles
work, and no buffering during the requested test. TV validation remains untested.

This supports a targeted extraction-and-remux workaround for this failure.
Extraction alone while retaining embedded tracks did not prevent the reproduced
HLS crash. No Tdarr workflow or library-wide conversion has been deployed.
A production pilot must preserve all supported languages and forced/SDH flags,
validate extraction before removing corresponding embedded tracks, preserve
originals for rollback, and avoid silently dropping bitmap/styled subtitles.
This test copy intentionally contains only the forced-English track; it is not
a production preservation policy. Remove only the diagnostic copy when testing
is complete; original movie and earlier diagnostic sidecar remain available.

The LAN reproduction demonstrates a media/subtitle-path defect independent of
cross-country routing. It does not establish why symptoms began after moving.
Changed quality/transcoding choices may expose a latent defect, but that is
unproven. Subtitle-free DirectStream interruptions remain a separate unresolved
case. Do not attribute all reported buffering to this subtitle finding.


### Late-episode HLS subtitle initialization — 2026-10-26

Observed production failure at18:50:16–18:50:47UTC on Murdoch Mysteries S20E01,
The Maltese Falconer (item363096). Requested FFmpeg seek44:09 in duration44:11.04;
embedded SRT metadata ends43:44.086. Both hardware and software attempts emitted
video/audio output initialization plus an additional embedded-SRT-to-WebVTT
output, but no normal encoding progress; each exited137 after approximately15s.
Exit137 alone does not establish OOM or a GPU defect. Server explicitly attempted
process shutdown. Matching original log: a97dd91f-c4f3-40ba-b6a8-b3b4d316db40_1.
The playback session advanced from06:41 to43:48 over approximately37minutes;
this particular failure concerns final-segment generation, not proven sustained
buffering throughout the episode. The next episode reported an explicit pause
around2s; that pause alone is not evidence of a second encoder failure.

Bounded synthetic LAN controls, same item/audio/subtitle index2,4Mbps profile:
- HLS subtitle profile at44:09: manifest returned, video request timed out15s;
  test encoder stopped in finally. Matched log1d9c24f9-4f61-4583-92ec-6303c824c3b6.
- External subtitle profile at44:09: final video segment in0.245s,778132bytes;
  matched loga644506a-0448-46b9-824f-2ef3b5241d79 has no selected fatal markers.
- HLS subtitle profile at43:20: first segment0.342s,11segments/16920564bytes;
  matched log851efc70-3250-4f99-adfa-563df358c6eb has no selected fatal markers.

Evidence supports late-seek/end-of-file HLS subtitle initialization failure,
consistent with earlier sparse-subtitle findings; exact internal deadlock is
unproven. Production used2Mbps, synthetic control4Mbps, so not an exact client
reproduction. External profile is a diagnostic client negotiation, not a deployed
sidecar or global setting. No production configuration/media modifications made.
Candidate remediation remains validated externalization and selective removal
of embedded text tracks, with originals preserved, rather than global GPU disable.

State/configuration recovery prerequisites: [application state recovery](application-state-recovery.md).

## Planned placement and scratch storage

Move Emby's temporary transcode workspace to a dedicated scratch disk and add
another GPU worker so Emby can run on either eligible host. This is planned,
not a change to the current deployment. Before enabling alternate placement,
validate GPU access, supported codecs, shared media/config paths and scratch
capacity on both workers. Keep one active Emby instance; placement flexibility
does not imply safe active-active operation or automatic ingress failover.
