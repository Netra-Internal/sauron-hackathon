WORKING: axis-q6215 is LIVE on /hack/ from the pod (frame verified 15:56 PDT, field + viaduct view) but slow: pod edge analyses only ~1.5 fps (infer 500-740 ms) → lag 7-11 s; debugging. jetson-c920: no camera (C920 unplugged; Linovision not yet seen).

## Axis via the pod (manager GO 15:46 PDT)
- Jetson: Axis reachable at 192.168.0.90 via enP8p1s0 (192.168.0.10, added by the manager). Stream checked with ffprobe:
  H.264 1280x720 @ 5 fps (matches sites.yaml axis-q6215). Added `axis-q6215=rtsp://root:***@192.168.0.90/axis-media/media.amp?videocodec=h264&resolution=1280x720&fps=5`
  to STREAMS in ~/cloud/push.env (creds from the laptop's axis-q6215.env, URL-encoded); restarted netra-cloud-push 22:48:04 UTC.
  Guard: `ip route add unreachable 192.168.0.0/24 metric 2000` (runtime) like 192.168.1.0/24.
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
- Jetson wired port enP8p1s0: new NM profile `netra-linovision` = static 192.168.1.20/24, never-default, no DNS,
  route metric 900, IPv6 off, autoconnect priority 50 (beats the DHCP "Wired connection 1"). Routes checked after:
  default still only via wlP1p1s0; nothing via lte0. Plus `ip route add unreachable 192.168.1.0/24 metric 2000` (runtime
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
3. 22:21 Jetson push.env POD=63.141.33.141:22127 (restarted my netra-cloud-push). Droplet: `systemctl stop
   netra-ask-edge-tunnel`; new transient unit **netra-ask-cloud-tunnel** = ssh -N -p 22126 -L 127.0.0.1:8450:127.0.0.1:8450
   root@63.141.33.141 (key /root/.ssh/cloudedge_ed25519). /health through it lists the pod ring `jetson-c920`.
4. Relay (manager, 22:22): pod edge ASK base → https://internal.netralabs.net/hack/relay (config 200 through it).
   Switched live without a pod restart (so ports stay put): 22:22:57 edge ready, posted 7 / failed 0; feed_health worker
   `f16ede3d5cc2:6057`, infer 34-38 ms, frame_age 1.06-1.12 s; 20 buckets in 30 s in `segments`.
   ⚠️ my mistake: I stopped the old supervisor before relaunching → edge down ~70 s (22:21:50-22:22:57).
   Persisted: /workspace/edge/ask_url on the pod; boot.sh reads it on any restart.
Verified /hack/ (signed in, 15:23:33-15:23:48 PDT, 4 polls of /hack/api/cameras/jetson-c920/live): lag_s 3.29, 2.93,
3.25, 2.47; boxes 0/2/0/0 (people come and go); frame.jpg 200, 87 KB, 0.17 s — real DIB-window view (viaduct, field).

## If anything breaks during the demo: rollback (≈1 min)
Jetson `sudo systemctl start netra-edge@jetson-c920`; droplet `systemctl stop netra-ask-cloud-tunnel; systemctl start
netra-ask-edge-tunnel`; then stop the pod edge (pod-action stop on izuotrrx9igtpk) so two edges never post one id.
⚠️ A pod restart remaps its public ports: then update POD= in the Jetson ~/cloud/push.env (RTSPS port) and the
`-p` of netra-ask-cloud-tunnel (SSH port) from get-pod.

## Not done
- Shadow side-by-side was skipped (manager: go fast). Pod alone in shadow 22:16-22:19: 5.0 fps, infer 50-60 ms (Jetson
  75-86 ms), SigLIP embeddings on 15/15 tracks, pose on 6. Data in R2 _work/sauron-cloud/pod/shadow.tgz.
- Jetson GPU: nothing of ours on it now (capture shim is CPU x264).

## Earlier (before the go)
## Blocker (not mine to fix)
- A separate session (tailnet tag:ssh-tag 100.124.77.56, log /root/netra-demo/CHANGES.log on the Jetson) ran
  `systemctl stop netra-edge@axis-q6215 netra-edge@jetson-c920 netra-edge@node3-c920 netra-c920-rtsp netra-edge-serve`
  at 14:53:27 PDT to free the Jetson GPU for its drone demo (ground_rx.py + RF-DETR TRT, ~965 MB). That means
  **production jetson-c920 is down too** (no buckets, no /frame for /hack/).
- Its own restart line: `sudo systemctl start netra-edge@axis-q6215 netra-edge@jetson-c920 netra-edge@node3-c920 netra-c920-rtsp netra-edge-serve`
- **Ask:** start ONLY `netra-c920-rtsp` (the capture shim: mediamtx + x264, CPU only, ~170 MB, no GPU). ground_rx reads its
  video from tcp://100.126.164.49:8554, not /dev/video0, so the C920 is free. My push picks the stream up automatically
  and the pod does the perception — which is exactly the point of this move: the Jetson GPU stays free for the drone demo.
  For the shadow comparison I also need the Jetson edge running (`netra-edge@jetson-c920`) for ≥10 min, which uses the
  GPU (~86% GR3D) — your call vs the demo. Without it I can still report pod fps/lag/boxes, just no side-by-side.

## What is running (mine)
- RunPod pod **izuotrrx9igtpk** `sauron-cloud-edge`: RTX A5000, Secure Cloud, CA-MTL-1, **$0.27/h**, public IP 63.141.33.141.
  mediamtx (RTSPS :8322 → public **22156**, user `pusher`; SSH → 22155; ports remap on container restart), shadow sink (127.0.0.1:8470, records to the pod, posts nothing
  to production), supervisor (starts an edge per configured camera whose stream is live), edge-serve. SigLIP TRT engine built.
  Idle until video arrives. If abandoned: stop/terminate it.
- Jetson: transient unit `netra-cloud-push` (cloud/push.sh; new unit, existing units untouched): stream-copies
  rtsp://127.0.0.1:8556/c920 → SSH tunnel through the droplet → pod. Retrying every 5 s until the shim is back.
  Wi-Fi-only guard (kills the push if the route leaves wlP1p1s0). Remove: `sudo systemctl stop netra-cloud-push`.
- Droplet: new system user `cloudrelay` (nologin, key restricted to `port-forwarding,permitopen="63.141.33.141:22160"`).
  Needed because the office egress only allows ports 22/80/443/5000/8000/8080/8443/10000 — RunPod's random port 22160
  is blocked from the Jetson, and the tailnet path Jetson↔droplet is DERP-relayed (389 ms). Remove: `userdel -r cloudrelay`.
- Droplet key `/root/.ssh/cloudedge_ed25519` (pod allows it port-forward to 127.0.0.1:8450 only). Tested 22:13 UTC:
  `ssh -N -p 22155 -L 127.0.0.1:8459:127.0.0.1:8450 root@63.141.33.141` → pod edge-serve `/health` 200 through it.
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
   `systemd-run --unit netra-ask-cloud-tunnel -p Restart=always -p RestartSec=10 /usr/bin/ssh -N -i /root/.ssh/cloudedge_ed25519 -o BatchMode=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes -p <pod ssh port> -L 127.0.0.1:8450:127.0.0.1:8450 root@63.141.33.141`
   — same loopback port, so netra-ask (ASK_EDGE_URL) and /hack/ need no restart. Ring history before cutover stays on
   the Jetson (not served after the switch).
4. Verify: feed_health for jetson-c920 shows worker `<pod hostname>:pid`, fps ~5, frame_age < 3 s; `/hack/` shows boxes + frame.
5. Optional: if the shadow shows a stable extra delay D, set jetson-c920 `edge.latency_ms: 1000 + D` in sites.yaml.
Rollback (≈1 min): pod env `EDGE_MODE=shadow` (or stop the pod) → Jetson `sudo systemctl start netra-edge@jetson-c920`
→ droplet `systemctl stop netra-ask-cloud-tunnel; systemctl start netra-ask-edge-tunnel`.
After cutover the Jetson runs only capture (netra-c920-rtsp) + netra-cloud-push; its GPU is free (the drone demo wants it).
