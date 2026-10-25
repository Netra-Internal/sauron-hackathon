#!/bin/bash
# Jev dispatch watcher for one camera on the pod: netra-ask's ask.dispatch.watch unmodified, the same as
# netra-dispatch@<cam> on the Jetson (person gate on, live mode), but reading the pod's own mediamtx path for the camera
# and posting incidents/watch records straight to the droplet (/ask), so labels show on /hack/.
#   usage: dispatch.sh <camera-id>     key: TYPESAFE_API_KEY in the env or /workspace/edge/dispatch.env (mode 600)
cam=$1; W=/workspace/edge; cd $W
while IFS= read -r -d "" kv; do export "$kv"; done < /proc/1/environ     # pod env (ASK_WORKER_TOKEN) when run by hand
[ -f $W/dispatch.env ] && { set -a; . $W/dispatch.env; set +a; }
export PYTHONPATH=$W ASK_BACKEND=ort ASK_ONNX_FULL=$W/models/yolo11s-1280.onnx EDGE_FFMPEG=$W/bin/ffmpeg \
       ASK_URL=https://internal.netralabs.net/ask DISPATCH_SOURCE_ENV=DISPATCH_SRC DISPATCH_SRC=rtsp://127.0.0.1:8554/$cam \
       DISPATCH_LOG_DIR=$W/dispatch/$cam OMP_NUM_THREADS=2
mkdir -p $W/dispatch/$cam
while true; do $W/venv/bin/python -u -m ask.dispatch.watch --camera $cam --gate on >> logs/dispatch-$cam.log 2>&1
  echo "$(date -u) dispatch $cam exited $?" >> logs/dispatch-$cam.log; sleep 15; done
