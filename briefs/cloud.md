# Brief: cloud — move edge compute off the Jetson onto RunPod (hackathon repo)
William: "move us off of jetson edge compute and on to some kind of cloud compute (runpod)".

## Today (verify, don't trust)
- Jetson `jetson-cloud` (ssh <jetson>, Orin 7.5 GB, ~2.5 GB free, GR3D ~86% with c920 alone) runs per camera
  `netra-edge@<cam>` (netra-ask ask/edge/: RTSP pull → YOLO TRT person/vehicle boxes + tracks → 1 s buckets POSTed to
  the droplet /ask/api/edge/bucket, crops, preview.jpg) and `netra-edge-serve` (ring buffer 48 GB + /frame /clip, reached
  by the droplet through `netra-ask-edge-tunnel` at 127.0.0.1:8450). Cameras: jetson-c920 = USB C920 → mediamtx shim
  rtsp://127.0.0.1:8556/c920 on the Jetson (the only live one); axis-q6215 + node3-c920 dead. Config: netra-ask
  ask/sites.yaml, /etc/netra-edge.env. Deploy scripts netra-ask deploy/jetson-*.sh.
- Downstream that MUST keep working unchanged: netra-ask sitefuse/Sites monitor, dispatch, and our /hack/ page (which
  gets boxes from an nginx mirror of the bucket POST and frames from edge-serve via 127.0.0.1:8450 on the droplet).
- Prior art: memory says a RunPod perception worker existed for Netra Ask (since STOPPED) and the node3 feed was relayed
  through the droplet (mediamtx). Look for that code/setup before designing (netra-ask feed/, deploy/, docs/).

## Target
Jetson (or any camera box) only captures and streams video up. A RunPod GPU pod runs the edge pipeline (the SAME netra-ask
edge code, unmodified, configured from this repo) for every camera, posts the same buckets, and serves /frame from a ring
on the pod (or the droplet). Adding a camera = adding a stream, no new hardware compute.

## Steps
1. Measure first, write plans/cloud-edge.md (short): uplink bandwidth from the Jetson on its Wi-Fi (NOT LTE: lte0 is capped
   25 MB/h — never route video over it), required bitrate per camera (1080p H.264 at the fps the edge uses), latency
   budget vs today (frame → bucket at droplet), how the video gets to the pod (push via the droplet mediamtx relay /
   SRT / pod on the tailnet — pick one, justify), GPU choice and $/h, pod persistence (network volume for the ring?).
2. Build in SHADOW: the pod runs the edge for jetson-c920 under a shadow camera id posting to a separate place (e.g. a
   shadow endpoint in hackdash or a test site) — never double-post into the production camera id. Compare boxes/fps/lag
   vs the Jetson for ≥10 min with real people.
3. Cutover plan (manager executes or approves): point production at the pod, stop netra-edge@jetson-c920 on the Jetson,
   rollback = restart the Jetson unit. Do NOT stop/restart Jetson units or netra-ask yourself.

## Rules
- RunPod: use the runpod MCP tools / ~/bin/podsh. State GPU type + $/h in status BEFORE creating. Pre-approved: ONE pod,
  ≤ $0.60/h; anything more → NEEDS-MANAGER. Pod SSH needs -tt + stdin, no scp — move files via R2 (rclone) or git.
  The pod is a long-running service here, but if you abandon it, STOP it; never leave idle pods. Record pod id in status.
- New code/config/scripts live in this repo (e.g. cloud/). netra-ask code runs unmodified on the pod.
- No synthetic video: test with the real camera stream.
- Laptop: 16 GB shared with 4 agents — no local model runs.
Done = shadow comparison numbers + the cutover plan in status/cloud.md (NEEDS-MANAGER for the cutover go).
