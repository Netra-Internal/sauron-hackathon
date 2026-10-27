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

# a boot that cannot finish exits (ending the container) instead of idling as a billed pod with no edge
fail() { echo "== BOOT FAILED $(date -u): $*"; tail -n 60 $W/logs/boot.log > $W/shipped.log; curl -s -X PUT -T $W/shipped.log "$LOG_PUT_URL" >/dev/null; exit 1; }
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
if [ ! -e venv/.ok ]; then
  python3 -m venv --system-site-packages venv
  venv/bin/pip install -q "onnxruntime-gpu[cuda,cudnn]" opencv-python-headless numpy pyyaml tensorrt-cu12 cuda-python && touch venv/.ok
fi
PY=$W/venv/bin/python
$PY -c "import onnxruntime as o; o.preload_dlls(); print('ort', o.__version__, o.get_available_providers())" || fail "onnxruntime"
[ -s models/siglip-vision.engine ] || $PY cloud/pod/build_trt.py models/siglip-vision.onnx models/siglip-vision.engine
[ -s tls.key ] || openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj "/CN=netra-cloud-edge" -keyout tls.key -out tls.crt
set +x
for f in ask/edge/main.py cloud/pod/supervise.py models/yolo11s-1280.onnx models/yolo11s-640.onnx models/yolo11s-pose-320.onnx \
         models/siglip-vision.engine bin/ffmpeg bin/mediamtx venv/.ok tls.key; do [ -s $f ] || [ -e $f -a $f = venv/.ok ] || fail "missing $f"; done
# the droplet's edge tunnel key (port-forward to edge-serve only), like netra-ask-edge-tunnel to the Jetson
mkdir -p /root/.ssh; grep -qf cloud/pod/authorized_keys /root/.ssh/authorized_keys 2>/dev/null || cat cloud/pod/authorized_keys >> /root/.ssh/authorized_keys
sed "s|@PUSH_PASS@|$PUSH_PASS|; s|@DEMO_PASS@|${DEMO_PASS:-$(openssl rand -hex 16)}|; s|@W@|$W|g" cloud/pod/mediamtx.yml > mediamtx.yml

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
  # /workspace/edge/ask_url (if present) overrides: e.g. https://internal.netralabs.net/hack/relay (answers buckets at once)
  [ -s $W/ask_url ] && ASK_URL=$(cat $W/ask_url)
  export ASK_URL=${ASK_URL:-https://internal.netralabs.net/ask}
fi
sleep 2
keep supervise $PY -u cloud/pod/supervise.py &      # one edge per configured camera whose stream is live here
keep serve $PY -u -m ask.edge.serve --bind 127.0.0.1 --port 8450 &
# ring -> R2 archiver (_ephemeral/footage/, 12-day expiry) for the cameras in $W/archive_cams; URLs from the droplet's presigner
[ -s $W/archive_cams ] && keep archive $PY -u cloud/pod/archive.py &
# Jev key: /workspace is a FUSE volume that ignores chmod (files show 0666), so the key is kept there only encrypted
# (dispatch.secret.enc, passphrase = ASK_WORKER_TOKEN from the pod env) and decrypted to the container disk at 600.
# A plaintext TYPESAFE_API_KEY line found in dispatch.env* is moved into the encrypted file and removed.
SECRET=/root/dispatch.secret; ENC=$W/dispatch.secret.enc
( umask 077
  plain=$(grep -h '^TYPESAFE_API_KEY=' $W/dispatch.env $W/dispatch.env.* 2>/dev/null | head -1)   # live file first
  if [ -n "$plain" ]; then
    printf '%s\n' "$plain" | openssl enc -aes-256-cbc -pbkdf2 -salt -pass env:ASK_WORKER_TOKEN -out $ENC.new && mv -f $ENC.new $ENC \
      && sed -i '/^TYPESAFE_API_KEY=/d' $W/dispatch.env* && echo "== Jev key moved from dispatch.env into $ENC"
  fi
  [ -s $ENC ] && openssl enc -d -aes-256-cbc -pbkdf2 -pass env:ASK_WORKER_TOKEN -in $ENC -out $SECRET.new \
    && grep -q '^TYPESAFE_API_KEY=.' $SECRET.new && mv -f $SECRET.new $SECRET \
    || { rm -f $SECRET.new; echo "== WARNING: no Jev key for the dispatch watchers ($ENC missing or not decryptable with ASK_WORKER_TOKEN)"; } )
# Jev dispatch watcher per camera in $DISPATCH_CAMS + $W/dispatch_cams (key: $SECRET, tuning: $W/dispatch.env).
# The file adds cameras without update-pod (an env change restarts the container and RunPod remaps its public ports).
for c in $(echo ${DISPATCH_CAMS:-} $(cat $W/dispatch_cams 2>/dev/null) | tr ' ' '\n' | sort -u); do setsid bash cloud/pod/dispatch.sh "$c" < /dev/null > /dev/null 2>&1 & done
echo "== services up $(date -u)"
wait
