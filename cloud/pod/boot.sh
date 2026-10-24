#!/bin/bash
# Cloud edge pod boot (RunPod, runpod/pytorch image). Runs netra-ask's edge (ask/edge, unmodified) for every camera in
# camera whose stream is pushed here (RTSPS, mediamtx :8322, user "pusher", path = camera id) on a GPU.
#   EDGE_MODE=shadow  the edge talks to cloud/shadowsink.py on 127.0.0.1:8470 (camera ids renamed <id>-cloud, buckets
#                     kept on the pod and shipped to R2); nothing reaches production.
#   EDGE_MODE=prod    the edge talks to ASK_URL (production) under the real camera ids.
# Env (presigned R2 GETs unless noted): CODE_URL CLOUD_URL FULL_URL TILE_URL SIGLIP_URL POSE_URL, LOG_PUT_URL +
# SHADOW_PUT_URL (presigned PUTs), ASK_WORKER_TOKEN, PUSH_PASS, EDGE_MODE. No camera list: see cloud/pod/supervise.py.
# Idempotent: a container restart re-uses /workspace (downloads, venv, engine) and just starts the services again.
W=/workspace/edge; mkdir -p $W/models $W/bin $W/logs $W/shadow && cd $W
exec > >(tee -a $W/logs/boot.log) 2>&1
echo "== boot $(date -u) mode=${EDGE_MODE:=shadow}"

ship() {   # logs every 60 s, shadow records every 5 min, to R2 (the pod has no inbound file path but SSH)
  local n=0
  while true; do
    { echo "== $(date -u)"; nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader
      df -h /workspace | tail -1; for f in $W/logs/*.log; do echo "== $f"; tail -n 40 "$f"; done; } > $W/shipped.log 2>&1
    curl -s -X PUT -T $W/shipped.log "$LOG_PUT_URL" >/dev/null
    if [ "$EDGE_MODE" = shadow ] && [ $((n % 5)) = 0 ] && [ -n "$SHADOW_PUT_URL" ]; then
      tar czf $W/shadow.tgz -C $W/shadow . && curl -s -X PUT -T $W/shadow.tgz "$SHADOW_PUT_URL" >/dev/null
    fi
    n=$((n + 1)); sleep 60
  done
}
ship &

get() { [ -s "$2" ] && return 0; curl -fsSL --retry 5 -o "$2.part" "$1" && mv -f "$2.part" "$2"; }
set -x
get "$CODE_URL" code.tgz && tar xzf code.tgz --no-same-owner                 # netra-ask ask/ at a pinned commit (git archive)
curl -fsSL --retry 5 -o cloud.tgz "$CLOUD_URL" && tar xzf cloud.tgz --no-same-owner   # this repo's cloud/ (always fresh)
get "$FULL_URL" models/yolo11s-1280.onnx
get "$TILE_URL" models/yolo11s-640.onnx
get "$POSE_URL" models/yolo11s-pose-320.onnx
get "$SIGLIP_URL" models/siglip-vision.onnx
if [ ! -x bin/ffmpeg ]; then
  curl -fsSL https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz | tar xJ -C bin --strip-components=1
fi
if [ ! -x bin/mediamtx ]; then
  curl -fsSL https://github.com/bluenviron/mediamtx/releases/download/v1.9.3/mediamtx_v1.9.3_linux_amd64.tar.gz | tar xz -C bin mediamtx
fi
if [ ! -d venv ]; then
  python3 -m venv --system-site-packages venv
  venv/bin/pip install -q "onnxruntime-gpu[cuda,cudnn]" opencv-python-headless numpy pyyaml tensorrt-cu12 cuda-python
fi
PY=$W/venv/bin/python
$PY -c "import onnxruntime as o; o.preload_dlls(); print('ort', o.__version__, o.get_available_providers())"
[ -s models/siglip-vision.engine ] || $PY cloud/pod/build_trt.py models/siglip-vision.onnx models/siglip-vision.engine
[ -s tls.key ] || openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj "/CN=netra-cloud-edge" -keyout tls.key -out tls.crt
set +x
sed "s|@PUSH_PASS@|$PUSH_PASS|; s|@W@|$W|g" cloud/pod/mediamtx.yml > mediamtx.yml

export PYTHONPATH=$W ASK_BACKEND=ort ASK_POSE=1 \
  ASK_ONNX_FULL=$W/models/yolo11s-1280.onnx ASK_ONNX_TILE=$W/models/yolo11s-640.onnx ASK_ONNX_POSE=$W/models/yolo11s-pose-320.onnx \
  ASK_ENGINE_SIGLIP=$W/models/siglip-vision.engine \
  ASK_MODEL_TAG="yolo11s-coco@1280+tiles@640/ort-cuda + siglip-b16-224/trt" \
  EDGE_FFMPEG=$W/bin/ffmpeg EDGE_RING_ROOT=$W/ring EDGE_RING_MAX_GB=${EDGE_RING_MAX_GB:-20} EDGE_RING_RESERVE_GB=${EDGE_RING_RESERVE_GB:-5}
keep() { local name=$1; shift; while true; do "$@" >> $W/logs/$name.log 2>&1; echo "$(date -u) $name exited $?" >> $W/logs/$name.log; sleep 5; done; }

keep mediamtx bin/mediamtx mediamtx.yml &
if [ "$EDGE_MODE" = shadow ]; then
  keep shadowsink $PY -u cloud/shadowsink.py --port 8470 --out $W/shadow &
  export ASK_URL=http://127.0.0.1:8470
else
  export ASK_URL=${ASK_URL:-https://internal.netralabs.net/ask}
fi
sleep 2
keep supervise $PY -u cloud/pod/supervise.py &      # one edge per configured camera whose stream is live here
keep serve $PY -u -m ask.edge.serve --bind 127.0.0.1 --port 8450 &
echo "== services up $(date -u)"
wait
