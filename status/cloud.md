NEEDS-MANAGER: shadow cloud edge is up and waiting for video, but the C920 shim on the Jetson was stopped at 14:53:27 PDT by the netra-demo session, so there is no camera stream to shadow.

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
