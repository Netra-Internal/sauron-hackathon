#!/usr/bin/env bash
# Stage a cloud edge pod: netra-ask ask/ (git archive of NETRA_ASK_REF, unmodified) + this repo's cloud/ to R2, then
# write the pod env (presigned URLs, tokens) to ~/.config/netra/cloud-edge-pod.json (secrets: never commit it).
# usage: cloud/stage.sh [shadow|prod] [cameras]      e.g. cloud/stage.sh shadow jetson-c920
set -euo pipefail
cd "$(dirname "$0")/.."
MODE=${1:-shadow}; CAMS=${2:-jetson-c920}; REF=${NETRA_ASK_REF:-origin/main}; NA=${NETRA_ASK:-$HOME/netra/netra-ask}
SECRETS=$HOME/.config/netra/cloud-edge.env
[ -f "$SECRETS" ] || { umask 077; echo "PUSH_PASS=$(openssl rand -hex 16)" > "$SECRETS"; }
. "$SECRETS"
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
git -C "$NA" fetch -q origin
SHA=$(git -C "$NA" rev-parse --short "$REF")
git -C "$NA" archive --format=tar.gz "$REF" ask > "$TMP/code.tgz"
tar czf "$TMP/cloud.tgz" cloud
cloud/r2.sh put pod/code.tgz < "$TMP/code.tgz"
cloud/r2.sh put pod/cloud.tgz < "$TMP/cloud.tgz"
cloud/r2.sh put pod/boot.sh < cloud/pod/boot.sh
M=_work/netra-ask/models
TOKEN=$(ssh -o BatchMode=yes "${DROPLET:?set DROPLET=root@<droplet>}" 'grep ^ASK_WORKER_TOKEN= /etc/netra-ask.env | cut -d= -f2-')
python3 - "$MODE" "$CAMS" "$SHA" "$TOKEN" "$PUSH_PASS" \
  "$(cloud/r2.sh url pod/boot.sh)" "$(cloud/r2.sh url pod/code.tgz)" "$(cloud/r2.sh url pod/cloud.tgz)" \
  "$(cloud/r2.sh url $M/yolo11s-1280-nms.onnx)" "$(cloud/r2.sh url $M/yolo11s-640-nms.onnx)" \
  "$(cloud/r2.sh url $M/siglip-base-patch16-224-vision.onnx)" "$(cloud/r2.sh url $M/yolo11s-pose-320.onnx)" \
  "$(cloud/r2.sh url pod/logs/boot.log put)" "$(cloud/r2.sh url pod/shadow.tgz put)" > "$HOME/.config/netra/cloud-edge-pod.json" <<'PY'
import json, sys
k = ["EDGE_MODE", "EDGE_CAMERAS", "NETRA_ASK_SHA", "ASK_WORKER_TOKEN", "PUSH_PASS", "BOOT_URL", "CODE_URL", "CLOUD_URL",
     "FULL_URL", "TILE_URL", "SIGLIP_URL", "POSE_URL", "LOG_PUT_URL", "SHADOW_PUT_URL"]
print(json.dumps(dict(zip(k, sys.argv[1:])), indent=1))
PY
chmod 600 "$HOME/.config/netra/cloud-edge-pod.json"
echo "staged netra-ask $SHA, mode=$MODE cameras=$CAMS -> ~/.config/netra/cloud-edge-pod.json"
