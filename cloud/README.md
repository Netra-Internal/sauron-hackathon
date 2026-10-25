# cloud — Netra edge perception on a RunPod GPU (agent "cloud", Oct 24)

Camera boxes only stream; one RunPod pod (RTX A5000, $0.27/h, CA-MTL-1) runs netra-ask's `ask/edge` **unmodified** for
every pushed camera (YOLO11s 1280 + tiles, pose, SigLIP TRT), the Jev dispatch watcher (`ask.dispatch.watch`) per
camera, and serves `/frame` and LL-HLS. Design, measurements, new-camera checklist: `plans/cloud-edge.md`.

```
camera -> box ffmpeg -c copy -> ssh -L via droplet (cloudrelay) -> pod mediamtx RTSPS :8322 (path = camera id)
   pod: supervise.py -> ask.edge.main per camera -> buckets to /hack/relay ; dispatch.sh -> Jev -> /ask incidents
   pod: mediamtx LL-HLS :8888 + ask.edge.serve :8450 <- droplet ssh tunnels <- nginx /hack/stream/<cam>/ (login)
```

| File | What |
|---|---|
| `stage.sh` | netra-ask code + models + boot to R2, writes the pod env (secrets stay in `~/.config/netra/`) |
| `r2.sh` | R2 put/get/presign through the droplet's creds |
| `pod/boot.sh` | pod entry, idempotent: ffmpeg, mediamtx, venv, TRT engine, services |
| `pod/mediamtx.yml` | ingest (RTSPS users `pusher`, `demo` = jetson-c920 only), loopback RTSP, LL-HLS |
| `pod/supervise.py` / `supervise.sh` | one edge per configured camera whose stream is live; manual restart wrapper |
| `pod/dispatch.sh` | Jev dispatch watcher for one camera (`DISPATCH_CAMS` in boot.sh) |
| `pod/build_trt.py` | SigLIP TensorRT engine build |
| `pod/authorized_keys` | droplet key, forward-only to the pod's 8450/8888 |
| `pod/ffmpeg-ring-flush.sh`, `pod/cloudsite/` | experiments that did not help (kept for the record) |
| `push.sh`, `push.env.example` | box side: all cameras in `STREAMS` over one SSH tunnel, Wi-Fi-only guard |
| `demo-push.sh` | any box with internet: webcam or RTSP straight to the pod's public RTSPS port |
| `droplet/*.service`, `nginx-hack-stream.conf` | droplet tunnels to the pod and the `/hack/stream/` location |
| `shadowsink.py`, `compare.py` | shadow mode sink and shadow-vs-Jetson comparison (shadow was skipped at cutover) |

Rollback to the Jetson edge: Jetson `sudo systemctl start netra-edge@<cam>`; droplet
`systemctl stop netra-ask-cloud-tunnel; systemctl start netra-ask-edge-tunnel`; stop the pod edge.
