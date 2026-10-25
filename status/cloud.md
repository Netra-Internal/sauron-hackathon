WORKING (demo-node + Jev on the pod): pod ready for a jetson-c920 push from demo-node (command below); Jev dispatch watchers running on the pod for axis-q6215 + jetson-c920, no verdict on /hack/ yet (nobody in view of the Axis; demo-node not pushing yet). LL-HLS still live at /hack/stream/axis-q6215/index.m3u8.

## PUSHED 3bf8e87
Branch hack-cloud, Netra-Internal/sauron-hackathon. Everything I built/deployed today is under `cloud/` (README: `cloud/README.md`):
pod boot/mediamtx/supervisor/dispatch launcher/TRT build, box push + `push.env.example`, `demo-push.sh`, droplet tunnel units,
nginx `/hack/stream/` snippet, shadow sink + compare tool, R2/stage scripts; plan `plans/cloud-edge.md`. Secrets are placeholders
only (scanned: no push/demo password, Jev key or camera creds in the repo).

## demo-node push (17:25 PDT)
The pod accepts the push **directly on its public RTSPS port** (checked open from the internet: <pod>:<port>, self-signed TLS),
so demo-node needs only ffmpeg — no SSH key, no relay. Login `demo` is a new mediamtx user that may publish **only** path
`jetson-c920` (cannot touch axis-q6215). **Paste-ready lines with the real password: `~/.config/netra/demo-node-push.txt`
on the laptop (mode 600)** — the same as below with `<DEMO_PASS>` filled in:
```
# USB webcam (Linux):
while true; do ffmpeg -hide_banner -loglevel warning -f v4l2 -input_format mjpeg -video_size 1920x1080 -i /dev/video0 -vf fps=5 -c:v libx264 -preset ultrafast -tune zerolatency -g 5 -b:v 1500k -maxrate 2M -bufsize 2M -pix_fmt yuv420p -an -f rtsp -rtsp_transport tcp "rtsps://demo:<DEMO_PASS>@<pod>:<port>/jetson-c920"; sleep 3; done
# RTSP camera (stream copy; set the camera's keyframe interval to ~1 s):
while true; do ffmpeg -hide_banner -loglevel warning -rtsp_transport tcp -i "rtsp://USER:PASS@CAMERA_IP/PATH" -map 0:v:0 -c copy -an -f rtsp -rtsp_transport tcp "rtsps://demo:<DEMO_PASS>@<pod>:<port>/jetson-c920"; sleep 3; done
```
(or `PASS=<DEMO_PASS> cloud/demo-push.sh /dev/video0|rtsp://...` from the repo). Notes:
- Use a 16:9 source: jetson-c920 is configured 1920x1080 in sites.yaml and the edge scales to that (a 4:3 webcam would be stretched).
  Change `/dev/video0` to the right device; if the webcam has no MJPEG mode drop `-input_format mjpeg`.
- If demo-node's network blocks outbound port 22127 (the office network does), fall back to the droplet relay: they run
  `ssh-keygen -t ed25519 -N "" -f ~/.ssh/cloudrelay_ed25519` and send me the `.pub`; I authorize it on `cloudrelay` and they add
  `ssh -fN -i ~/.ssh/cloudrelay_ed25519 -L 127.0.0.1:18322:<pod>:<port> <droplet>` and push to `127.0.0.1:18322`.
- RTSP pull instead: not viable — the tailnet path droplet→demo-node is DERP (lax, 121 ms, "direct connection not established").
- Within 15 s of the stream arriving the pod's supervisor starts the jetson-c920 edge (boxes on /hack/), and the Jev watcher picks it
  up (it retries every few s). Not tested end to end: I did not publish anything to jetson-c920 myself (no synthetic data).
- If the pod restarts, the port changes (see `POD=` notes in plans/cloud-edge.md).

## Jev dispatch on the pod (17:25 PDT)
`ask.dispatch.watch --camera <cam> --gate on` (netra-ask 6417b5f, unmodified; = netra-dispatch@<cam>, live mode) runs on the pod for
**axis-q6215** and **jetson-c920** (`cloud/pod/dispatch.sh`), reading `rtsp://127.0.0.1:8554/<cam>` (the pod's mediamtx, no extra camera
session), person gate = YOLO11s 1280 ORT-CUDA, Jev key from the laptop's typesafe.env in `/workspace/edge/dispatch.env` (600), posting
incidents/watch to `https://internal.netralabs.net/ask` with the worker token. No netra-dispatch runs on the Jetson, so no duplicates.
- axis-q6215: running since 00:25:41 UTC, a strip every 2 s, all **gated** so far (no person in view), so Jev hasn't been called and
  nothing is shown yet — /hack/ gets a label when Jev's verdict reaches watch/deploy. Cost: Jev only while someone is in view.
- jetson-c920: waiting for demo-node's stream (404 from mediamtx until it arrives).
- The mediamtx config reload for the `demo` user did not interrupt the Axis push or HLS (path stayed ready).
- NO PTZ commands sent (nothing in this path talks to the camera except the one existing RTSP push).


## PTZ audit (William's rule, 16:08 PDT) — cloud sent NO PTZ commands, ever
- Zero pan/tilt/zoom/home/preset/areazoom/day-night/VAPIX/ISAPI commands from me, in the last 15 min or at any time.
  I have no test, script or Playwright run that talks to any camera control API; nothing to kill.
- Everything I sent to the Axis (<camera-ip>), all RTSP video reads (DESCRIBE/SETUP/PLAY), no control calls:
  1. ~22:47 UTC one ffprobe (≤15 s) to check codec/size.
  2. netra-cloud-push RTSP session: started 22:48:04, restarted 22:56:57 (dropping jetson-c920) and ~23:04 with
     `videokeyframeinterval=5` added to the media.amp URL. That is a per-stream encoder parameter for that RTSP session only (1 s keyframes);
     it does not move the camera or change its saved settings.
- Running now against the camera: exactly ONE ffmpeg (the push, pid 1808610 on the Jetson), read-only video.
- The view changed between 22:50 (blurry grey) and 22:56 (field) without any command from me.


## For dash (relay please)
- URL per camera: `https://internal.netralabs.net/hack/stream/<camera_id>/index.m3u8` (now: `axis-q6215`). Same login as
  /hack/ (cookie or basic; nginx auth_request to /hack/api/health, cached 30 s). 401 without login. Same origin as the
  page, so no CORS. Media playlist `video1_stream.m3u8`, fMP4, H.264 1280x720 @ 5 fps, 1.0 s segments, 0.2 s LL-HLS parts.
- Player: hls.js with `{lowLatencyMode: true, liveSyncDurationCount: 1, maxLiveSyncPlaybackRate: 1.5}`; Safari plays it natively.
- Boxes stay on the existing /hack/api/cameras/<cam>/live poll (edge positions); frame.jpg no longer needed for the view.
- WHEP/WebRTC: not done. It needs a UDP or extra TCP port reachable from the viewer straight to the pod; RunPod gives
  random TCP ports, which the office egress blocks (only 22/80/443/... allowed), so WebRTC would fail exactly where we demo.
  LL-HLS through 443 meets the targets.

## Measured (16:05:57-16:06:11 PDT, laptop → Cloudflare → droplet → tunnel → pod, 6 runs)
- Cold start = master + media playlist + init + newest part: 1.57, 1.05, 0.81, 0.85, 0.90, 0.78 s (target < 2 s ✔).
  Before the auth cache it was 2.2-7.8 s (each request did a hackdash auth subrequest).
- Newest part end vs wall clock: 0.51, 0.16, -0.03, 0.24, 0.18, 0.16 s (stamped at pod receive; add camera→Jetson→droplet→pod
  transport, ~0.2-0.5 s est.). A player holding ~3 parts adds ~0.6 s → expect ~1-2 s glass-to-glass (target < 3 s ✔).

## What changed (16:00-16:06 PDT)
- Axis RTSP URL in the Jetson push now asks for `videokeyframeinterval=5` (1 s GOP; was ~12.4 s → 12 s HLS segments and
  a 12 s first picture). One RTSP session to the camera (checked: 1 ffmpeg). push.env backups: push.env.bak-gop, .bak-c920-axis.
- STREAMS is now ONLY axis-q6215 (jetson-c920 dropped as asked: C920 + Linovision gone). netra-cloud-push restarted only.
- Pod mediamtx: HLS on 127.0.0.1:8888 (lowLatency, always remux); pod authorized_keys lets the droplet key forward 8888.
- Droplet: new transient unit `netra-cloud-hls-tunnel` (ssh -p 22126 -L 127.0.0.1:8460:127.0.0.1:8888 <pod>);
  nginx `location /hack/stream/` + auth cache (backups /root/internal.nginx.bak-*; snippet in repo cloud/nginx-hack-stream.conf).
  `nginx -t` ok, reload ok; /hack/ still 200.
- Note: the 500s seen 23:03-23:04 UTC were sauron-hack being restarted by someone (clean stop/start), not this change.

## Still open
- RESOLVED: pod edge for axis-q6215 was ~1.5-3 fps (infer 270-740 ms) with the camera's ~12.4 s keyframe interval; since
  the 1 s keyframe change it runs 5.0-5.1 fps analysed, infer 40-43 ms (pod heartbeats 23:06:01-23:06:44 UTC).
- /frame for the Axis can be 20-70 s stale (ring .mkv written in 256 KB chunks at the Axis's low bitrate); the HLS
  stream replaces frame polling for the view.


## Axis via the pod (manager GO 15:46 PDT)
- Jetson: Axis reachable at <camera-ip> via enP8p1s0 (<lan-ip>, added by the manager). Stream checked with ffprobe:
  H.264 1280x720 @ 5 fps (matches sites.yaml axis-q6215). Added `axis-q6215=rtsp://<user>:<pass>@<camera-ip>/axis-media/media.amp?videocodec=h264&resolution=1280x720&fps=5`
  to STREAMS in ~/cloud/push.env (creds from the laptop's axis-q6215.env, URL-encoded); restarted netra-cloud-push 22:48:04 UTC.
  Guard: `ip route add unreachable <lan-ip>/24 metric 2000` (runtime) like <lan-ip>/24.
- Jetson's own netra-edge@axis-q6215 stays inactive (checked) → only the pod posts axis-q6215.
- Pod: mediamtx path axis-q6215 ready 22:48:10; supervisor started edge axis-q6215 22:48:16 (no config change needed:
  the camera was already in sites.yaml) → production feed_health worker f16ede3d5cc2:<pid>, fps_in 5.1.
- /hack/ (signed in) 15:56:13-21 PDT: frame.jpg 200 (201 KB), real view of the field/viaduct; boxes 0 (field empty);
  lag_s 7.8 / 7.2 / 11.0.
- Open problem: pod edge for the Axis analyses 1.3-3 fps (infer 270-740 ms) vs 35-60 ms for the C920 earlier on the
  same pod. Detector alone on Axis frames: 40 ms (PNG) / 134-274 ms (live stream, while competing). Tried: thread caps
  (OMP/OpenCV env, and an onnxruntime sitecustomize: 2 threads, no spinning) — no change in the live process.
  cgroup shows CPU throttling (quota 7.65 CPU, container sees 96). Still investigating; boxes will appear when people do,
  just 7-11 s late.


## Linovision prep (15:30-15:34 PDT)
- Jetson wired port enP8p1s0: new NM profile `netra-linovision` = static <lan-ip>/24, never-default, no DNS,
  route metric 900, IPv6 off, autoconnect priority 50 (beats the DHCP "Wired connection 1"). Routes checked after:
  default still only via wlP1p1s0; nothing via lte0. Plus `ip route add unreachable <lan-ip>/24 metric 2000` (runtime
  only) so camera creds never go out the Wi-Fi default route while the cable is out.
- netra-cloud-push source (~/cloud/push.env, backup push.env.c920): `jetson-c920 = Linovision main
  /Streaming/Channels/101 (stream copy) | fallback rtsp://127.0.0.1:8556/c920`; each reconnect tries Linovision first.
  Camera id stays jetson-c920 (no sites.yaml / netra-ask change). Creds from /etc/netra-ptz.env, URL-encoded, file 600;
  logs redact them.
- Why main stream copy: 16.8 Mbit/s fits the Wi-Fi uplink (64-93 Mbit/s); the pod edge samples 5 fps itself. Costs:
  ~7.5 GB/h through the droplet relay and the pod ring (20 GB cap ≈ 2.7 h). After the demo, set the camera to 1080p
  5-10 fps / ~4 Mbit/s (ISAPI) or switch to the sub-stream if quality allows.
- Still DOWN: the C920 is unplugged (15:24:56), so /hack/ has no live frame until the Linovision streams.


## Live incident 15:25 PDT
- Pod edge, relay and tunnel are all still up and healthy; pod feed_health at 22:29:11 UTC: fps 0, frame_age 255 s
  because the shim on the Jetson has no device (`Cannot open video device /dev/video0`, runOnInit exits 254 every 5 s).
- Fix = plug the C920 back into the Jetson USB. netra-c920-rtsp retries by itself, my push retries every 5 s, the pod
  edge resumes on its own (no action needed from anyone else). /hack/ recovers within ~30 s.
- If the camera was moved to ANOTHER box for the demo: that box needs the shim + `cloud/push.sh` with
  STREAMS="jetson-c920=<its rtsp>" (or a new camera id + sites.yaml entry) and its key in the droplet's cloudrelay — tell me which box.


## Cutover executed (manager GO, 22:19 UTC) — each step verified
1. 22:19:33 Jetson `sudo systemctl stop netra-edge@jetson-c920` → inactive. Untouched and still active: netra-c920-rtsp,
   netra-edge-serve, netra-cloud-push. (The other units belong to netra-demo / were stopped by it; not touched.)
2. 22:20 pod env EDGE_MODE=prod (update-pod, read back) + restart. New ports: SSH **22126**, RTSPS **22127**.
   22:21:32 pod edge `jetson-c920` ready, posting to production: feed_health worker `f16ede3d5cc2:280`, 5 fps, infer 46 ms,
   frame_age 1.05 s; 16 buckets/min.
3. 22:21 Jetson push.env POD=<pod>:<port> (restarted my netra-cloud-push). Droplet: `systemctl stop
   netra-ask-edge-tunnel`; new transient unit **netra-ask-cloud-tunnel** = ssh -N -p 22126 -L 127.0.0.1:8450:127.0.0.1:8450
   <pod> (key /root/.ssh/cloudedge_ed25519). /health through it lists the pod ring `jetson-c920`.
4. Relay (manager, 22:22): pod edge ASK base → https://internal.netralabs.net/hack/relay (config 200 through it).
   Switched live without a pod restart (so ports stay put): 22:22:57 edge ready, posted 7 / failed 0; feed_health worker
   `f16ede3d5cc2:6057`, infer 34-38 ms, frame_age 1.06-1.12 s; 20 buckets in 30 s in `segments`.
   ⚠️ my mistake: I stopped the old supervisor before relaunching → edge down ~70 s (22:21:50-22:22:57).
   Persisted: /workspace/edge/ask_url on the pod; boot.sh reads it on any restart.
Verified /hack/ (signed in, 15:23:33-15:23:48 PDT, 4 polls of /hack/api/cameras/jetson-c920/live): lag_s 3.29, 2.93,
3.25, 2.47; boxes 0/2/0/0 (people come and go); frame.jpg 200, 87 KB, 0.17 s — real DIB-window view (viaduct, field).

## If anything breaks during the demo: rollback (≈1 min)
Jetson `sudo systemctl start netra-edge@jetson-c920`; droplet `systemctl stop netra-ask-cloud-tunnel; systemctl start
netra-ask-edge-tunnel`; then stop the pod edge (pod-action stop on <pod-id>) so two edges never post one id.
⚠️ A pod restart remaps its public ports: then update POD= in the Jetson ~/cloud/push.env (RTSPS port) and the
`-p` of netra-ask-cloud-tunnel (SSH port) from get-pod.

## Not done
- Shadow side-by-side was skipped (manager: go fast). Pod alone in shadow 22:16-22:19: 5.0 fps, infer 50-60 ms (Jetson
  75-86 ms), SigLIP embeddings on 15/15 tracks, pose on 6. Data in R2 _work/sauron-cloud/pod/shadow.tgz.
- Jetson GPU: nothing of ours on it now (capture shim is CPU x264).

## Earlier (before the go)
## Blocker (not mine to fix)
- A separate session (tailnet tag:ssh-tag <tailnet-ip>, log /root/netra-demo/CHANGES.log on the Jetson) ran
  `systemctl stop netra-edge@axis-q6215 netra-edge@jetson-c920 netra-edge@node3-c920 netra-c920-rtsp netra-edge-serve`
  at 14:53:27 PDT to free the Jetson GPU for its drone demo (ground_rx.py + RF-DETR TRT, ~965 MB). That means
  **production jetson-c920 is down too** (no buckets, no /frame for /hack/).
- Its own restart line: `sudo systemctl start netra-edge@axis-q6215 netra-edge@jetson-c920 netra-edge@node3-c920 netra-c920-rtsp netra-edge-serve`
- **Ask:** start ONLY `netra-c920-rtsp` (the capture shim: mediamtx + x264, CPU only, ~170 MB, no GPU). ground_rx reads its
  video from tcp://<tailnet-ip>:8554, not /dev/video0, so the C920 is free. My push picks the stream up automatically
  and the pod does the perception — which is exactly the point of this move: the Jetson GPU stays free for the drone demo.
  For the shadow comparison I also need the Jetson edge running (`netra-edge@jetson-c920`) for ≥10 min, which uses the
  GPU (~86% GR3D) — your call vs the demo. Without it I can still report pod fps/lag/boxes, just no side-by-side.

## What is running (mine)
- RunPod pod **<pod-id>** `sauron-cloud-edge`: RTX A5000, Secure Cloud, CA-MTL-1, **$0.27/h**, public IP <pod>.
  mediamtx (RTSPS :8322 → public **22156**, user `pusher`; SSH → 22155; ports remap on container restart), shadow sink (127.0.0.1:8470, records to the pod, posts nothing
  to production), supervisor (starts an edge per configured camera whose stream is live), edge-serve. SigLIP TRT engine built.
  Idle until video arrives. If abandoned: stop/terminate it.
- Jetson: transient unit `netra-cloud-push` (cloud/push.sh; new unit, existing units untouched): stream-copies
  rtsp://127.0.0.1:8556/c920 → SSH tunnel through the droplet → pod. Retrying every 5 s until the shim is back.
  Wi-Fi-only guard (kills the push if the route leaves wlP1p1s0). Remove: `sudo systemctl stop netra-cloud-push`.
- Droplet: new system user `cloudrelay` (nologin, key restricted to `port-forwarding,permitopen="<pod>:<port>"`).
  Needed because the office egress only allows ports 22/80/443/5000/8000/8080/8443/10000 — RunPod's random port 22160
  is blocked from the Jetson, and the tailnet path Jetson↔droplet is DERP-relayed (389 ms). Remove: `userdel -r cloudrelay`.
- Droplet key `/root/.ssh/cloudedge_ed25519` (pod allows it port-forward to 127.0.0.1:8450 only). Tested 22:13 UTC:
  `ssh -N -p 22155 -L 127.0.0.1:8459:127.0.0.1:8450 <pod>` → pod edge-serve `/health` 200 through it.
- Pod verified up to the stream: YOLO 1280/640 on CUDAExecutionProvider, pose on, SigLIP TRT engine built, edge "ready"
  and heartbeating; it gets 404 from mediamtx only because no camera is pushing.

## Measured
- C920 stream 1080p5 x264 1.43 Mbit/s; Jetson Wi-Fi uplink 64-93 Mbit/s; Jetson edge infer 75-86 ms @ 5.1 fps.

## Cutover plan (manager executes; I do not touch Jetson units or netra-ask)
Pre: shadow numbers below are acceptable; `netra-cloud-push` is streaming (pod mediamtx path `jetson-c920` ready).
1. Jetson: `sudo systemctl stop netra-edge@jetson-c920` (stop the Jetson perception first: never two edges posting one id).
2. Pod to prod: `cloud/stage.sh prod` then update the pod env `EDGE_MODE=prod` (pod restarts, ~1 min, ports remap —
   read the new ones with get-pod, put them in the Jetson `~/cloud/push.env` POD= and step 3's -p). The supervisor then
   runs `ask.edge.main --camera jetson-c920` against https://internal.netralabs.net/ask with JETSON_RTSP_URL pointed at
   the pod stream. No netra-ask code or sites.yaml change.
3. Droplet /frame: `systemctl stop netra-ask-edge-tunnel` then
   `systemd-run --unit netra-ask-cloud-tunnel -p Restart=always -p RestartSec=10 /usr/bin/ssh -N -i /root/.ssh/cloudedge_ed25519 -o BatchMode=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes -p <pod ssh port> -L 127.0.0.1:8450:127.0.0.1:8450 <pod>`
   — same loopback port, so netra-ask (ASK_EDGE_URL) and /hack/ need no restart. Ring history before cutover stays on
   the Jetson (not served after the switch).
4. Verify: feed_health for jetson-c920 shows worker `<pod hostname>:pid`, fps ~5, frame_age < 3 s; `/hack/` shows boxes + frame.
5. Optional: if the shadow shows a stable extra delay D, set jetson-c920 `edge.latency_ms: 1000 + D` in sites.yaml.
Rollback (≈1 min): pod env `EDGE_MODE=shadow` (or stop the pod) → Jetson `sudo systemctl start netra-edge@jetson-c920`
→ droplet `systemctl stop netra-ask-cloud-tunnel; systemctl start netra-ask-edge-tunnel`.
After cutover the Jetson runs only capture (netra-c920-rtsp) + netra-cloud-push; its GPU is free (the drone demo wants it).
