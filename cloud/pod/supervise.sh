#!/bin/bash
# Restart only the edge supervisor by hand (what runs on the pod now; boot.sh starts it the same way at boot):
# takes the pod env from PID 1 so a restart keeps ASK_WORKER_TOKEN etc.   setsid nohup cloud/pod/supervise.sh &
W=/workspace/edge; cd $W
while IFS= read -r -d "" kv; do export "$kv"; done < /proc/1/environ
export PYTHONPATH=$W ASK_BACKEND=ort ASK_POSE=1 ASK_ONNX_FULL=$W/models/yolo11s-1280.onnx ASK_ONNX_TILE=$W/models/yolo11s-640.onnx \
  ASK_ONNX_POSE=$W/models/yolo11s-pose-320.onnx ASK_ENGINE_SIGLIP=$W/models/siglip-vision.engine \
  ASK_MODEL_TAG="yolo11s-coco@1280+tiles@640/ort-cuda + siglip-b16-224/trt" EDGE_FFMPEG=$W/bin/ffmpeg \
  EDGE_RING_ROOT=$W/ring EDGE_RING_MAX_GB=20 EDGE_RING_RESERVE_GB=5
# live pod also had PYTHONPATH=$W/cloudsite:$W (cloud/pod/cloudsite: ORT thread cap) and EDGE_FFMPEG=ffmpeg-ring-flush;
# neither changed anything measurable (the Axis slowness was its 12 s GOP), so they are not on by default.
export ASK_URL=$( [ -s $W/ask_url ] && cat $W/ask_url || echo https://internal.netralabs.net/ask )
while true; do $W/venv/bin/python -u cloud/pod/supervise.py >> logs/supervise.log 2>&1; echo "$(date -u) supervise exited $?" >> logs/supervise.log; sleep 5; done
