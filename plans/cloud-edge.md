# Cloud edge: perception off the Jetson, onto a RunPod GPU

Goal (William): camera boxes only capture and stream; one GPU pod runs netra-ask's edge (`ask/edge`, unmodified) for
every camera and posts the same buckets. Adding a camera = one config entry + one stream.

## Measured (Oct 24, 14:50-15:10 PDT)
| What | Value | How |
|---|---|---|
| C920 stream (shim on the Jetson) | 1080p, 5 fps, x264 ultrafast, **1.43 Mbit/s** (≈ 640 MB/h, 15 GB/day) | 20 s stream copy + ffprobe |
| Jetson uplink on Wi-Fi (wlP1p1s0) | **64-93 Mbit/s** up, 87 Mbit/s down, 8 ms RTT to 1.1.1.1 | 25 MB POST to speed.cloudflare.com ×2 |
| Headroom | ~40 cameras at 1.4 Mbit/s before Wi-Fi uplink is the limit | |
| Jetson edge today | 5.1 fps analysed, infer 75-86 ms/frame, GR3D ~86% with one camera | feed_health heartbeats |
| Bucket lag today (t_to → droplet done_at) | p50 **1.04 s**, p90 7.9 s, max 33.6 s (1256 buckets, 21:20-21:53 UTC) | `segments` (lane edge) |
| Office egress | only TCP 22, 80, 443, 5000, 8000, 8080, 8443, 10000 open; RunPod's mapped ports (22159/22160) and 8554 **blocked** | /dev/tcp probes to portquiz.net |
| Tailnet Jetson↔droplet | DERP relay (lax), 389 ms — not usable for video (the Oct 10 scp over it took the box offline) | `tailscale ping` |

## Path chosen: box → SSH tunnel via the droplet → pod mediamtx (RTSPS)
```
camera ──RTSP──> box (Jetson/Pi/any) ── ffmpeg -c copy ──> ssh -L (port 22, Wi-Fi only) ──> droplet sshd (cloudrelay,
   may only forward to the pod's RTSPS port) ──TCP──> pod mediamtx :8322 (RTSPS, user pusher) ──> ask.edge.main per camera
   ──> buckets to /ask/api/edge/bucket (prod) or the shadow sink (shadow)
```
Why: the box can only get out on 22/443, so a direct push to the pod's random public port is impossible from the office,
and the tailnet path is DERP. The droplet is the one fixed public host the box already reaches on 22; a restricted
`cloudrelay` account (`restrict,port-forwarding,permitopen="<pod>:<port>"`, nologin) forwards TCP only — no mediamtx or
ffmpeg on the droplet, ~0 CPU. RTSPS inside SSH: authenticated twice, encrypted. Rejected: pod on the tailnet (DERP again,
needs an auth key in the pod), SRT/UDP (RunPod maps TCP only), droplet mediamtx (more moving parts on a 4 GB box for no gain).
Cost of the relay: droplet transfer 1.43 Mbit/s out per camera ≈ 0.46 TB/month — fine for a handful of cameras; past ~8
move the relay to a small box that takes 443 (or get the office to open the pod's port and drop the hop).

**LTE guard:** `cloud/push.sh` checks every 10 s that the route to the relay leaves through `wlP1p1s0`; if Wi-Fi drops and
the default route moves to lte0 (25 MB/h cap) every push is killed until Wi-Fi is back.

**Pod ports move on every container restart** (RunPod remaps them: 22159/22160 became 22155/22156). The relay rule
allows any port on the pod IP; after a restart update `POD=` in each box's push env (and the droplet tunnel's `-p`).
A stable endpoint for production = keep the pod running, or front it with a fixed host.

## Latency budget (vs today's p50 1.04 s)
Extra hop: Jetson (Chicago) → droplet (NYC) → pod (Montreal), TCP, ≈ 30-60 ms one way + one more decode on the pod.
Bucket POST pod → droplet ≈ 15 ms RTT. Expected cloud lag ≈ today + 0.1-0.3 s. Measured number: see the shadow section in
`status/cloud.md` (track-start offset, same person, Jetson vs pod). Note the edge stamps frames at pod arrival − 1000 ms
(`latency_ms` was calibrated for the Jetson's local decode); if the shadow shows a stable extra offset, set that camera's
`edge.latency_ms` to 1000 + offset at cutover so ring frames and boxes stay aligned.

## GPU and cost
- **RTX A5000 24 GB, Secure Cloud, CA-MTL-1, $0.27/h** (≈ $197/month always-on), 9 vCPU, 50 GB RAM. Cheapest in-stock
  Secure GPU with public TCP ports near the US Northeast (RTX 2000 Ada $0.24 was EU-only; A4000/4000 Ada out of stock).
- Work per camera is small (YOLO11s 1280 + tiles, pose 320, SigLIP B/16 on new crops at 5 fps); the limit will be CPU
  (one ffmpeg decode of 1080p per camera + Python per frame). Estimate 8-10 cameras per A5000; measure as cameras arrive.
- Models: ONNX Runtime CUDA (`ASK_BACKEND=ort`, the backend the old RunPod worker used) for YOLO and pose; SigLIP is a
  TensorRT engine built on the pod (`cloud/pod/build_trt.py`, TRT 11.4, fp32: newer wheels dropped the FP16 flag) so the
  unmodified `SiglipTRT` path loads it, like the Jetson.
- Persistence: a 60 GB host-local `/workspace` holds venv, models, engine and the ring (20 GB cap per camera ≈ 31 h).
  For 7-day rings (≈ 105 GB/camera) move `/workspace` to a network volume in CA-MTL-1 (≈ $0.07/GB/month → ~$7/camera/month).

## What a new camera needs (whatever box it's plugged into)
1. **Config** (one entry): the camera in `netra-ask/ask/sites.yaml` with its `edge:` block exactly as today
   (`source_env: ANY_NAME`, fps, ring_days, latency_ms, zones). Deployed to the droplet by the manager. The pod needs no
   change: `cloud/pod/supervise.py` reads `/api/edge/config` every 15 s and sets that `source_env` to the camera's stream.
2. **Stream** (one word): on the box the camera is reachable from (any box on its LAN: Jetson, Pi, NUC), add
   `<camera-id>=<rtsp url>` to `STREAMS` in that box's push env and restart its `netra-cloud-push`. A USB camera first gets
   the mediamtx shim (`netra-ask/feed/node3-rtsp`, 1.5 Mbit/s x264); an IP camera's own RTSP URL is used as is.
   The pod's mediamtx path is the camera id; the supervisor starts its edge as soon as the path is live.
3. **Only for a box that has never pushed:** copy `cloud/push.sh`, make a no-passphrase key
   (`ssh-keygen -t ed25519 -N "" -f ~/.ssh/cloudrelay_ed25519`) and append its public key to
   `/var/lib/cloudrelay/.ssh/authorized_keys` on the droplet with the same `restrict,port-forwarding,permitopen=` prefix.
No new compute anywhere; bandwidth +1.4 Mbit/s on that box's uplink and the droplet.

## Shadow (step 2) and cutover (step 3)
- Shadow: pod runs with `EDGE_MODE=shadow`; edges talk to `cloud/shadowsink.py` on the pod, which serves production's
  config with every camera renamed `<id>-cloud` and records buckets/heartbeats to `/workspace/edge/shadow` (shipped to
  R2 `_work/sauron-cloud/pod/shadow.tgz` every 5 min). Nothing is posted to production.
- Cutover plan + rollback: `status/cloud.md`.

## Files (this repo, `cloud/`)
`pod/boot.sh` (pod entry, idempotent), `pod/mediamtx.yml`, `pod/supervise.py`, `pod/build_trt.py`, `shadowsink.py`,
`push.sh` (box side), `stage.sh` (code + models to R2, pod env), `r2.sh` (R2 via the droplet's creds).
