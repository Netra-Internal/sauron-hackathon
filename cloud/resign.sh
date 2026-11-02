#!/usr/bin/env bash
# Re-sign the cloud edge pod's R2 links (7 days, the SigV4 maximum) and set its start command so that a restart never
# depends on them again: the command keeps the last good boot.sh in /workspace/edge/boot.sh and boots from it when
# BOOT_URL has expired; boot.sh already skips every cached download (code.tgz, models) and keeps the extracted cloud/
# when CLOUD_URL fails. Fresh links matter only for a NEW volume.
# ⚠️ Changing a pod's env or start command RESETS the pod (RunPod), and RunPod remaps its public ports on a reset:
# re-point the droplet tunnels (-p) and every box pushing to the old port afterwards (see plans/cloud-edge.md).
# usage: DROPLET=root@<droplet> cloud/resign.sh <pod id> [secrets json = ~/.config/netra/cloud-edge-pod-2.json]
# The RunPod key is read on the droplet (/etc/netra-catalog.env) and the secrets from the local json; nothing is printed.
set -euo pipefail
cd "$(dirname "$0")/.."
POD=${1:?pod id}; SECRETS=${2:-$HOME/.config/netra/cloud-edge-pod-2.json}; D=${DROPLET:?set DROPLET=root@<droplet>}
M=_work/netra-ask/models; L=${LOGDIR:-pod2}
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT; umask 077
python3 - "$SECRETS" \
  "$(cloud/r2.sh url pod/boot.sh)" "$(cloud/r2.sh url pod/code.tgz)" "$(cloud/r2.sh url pod/cloud.tgz)" \
  "$(cloud/r2.sh url $M/yolo11s-1280-nms.onnx)" "$(cloud/r2.sh url $M/yolo11s-640-nms.onnx)" \
  "$(cloud/r2.sh url $M/siglip-base-patch16-224-vision.onnx)" "$(cloud/r2.sh url $M/yolo11s-pose-320.onnx)" \
  "$(cloud/r2.sh url $L/logs/boot.log put)" "$(cloud/r2.sh url $L/shadow.tgz put)" > "$TMP/body.json" <<'PY'
import json, sys
env = json.load(open(sys.argv[1]))
k = ["BOOT_URL", "CODE_URL", "CLOUD_URL", "FULL_URL", "TILE_URL", "SIGLIP_URL", "POSE_URL", "LOG_PUT_URL", "SHADOW_PUT_URL"]
env.update(dict(zip(k, sys.argv[2:])))
json.dump(env, open(sys.argv[1], "w"), indent=1)          # keep the local copy in step with the pod
cmd = ('nohup /start.sh > /root/start.log 2>&1 & B=/workspace/edge/boot.sh; mkdir -p /workspace/edge; '
       'curl -fsSL --retry 5 "$BOOT_URL" -o $B.new && [ -s $B.new ] && mv -f $B.new $B; rm -f $B.new; '
       '[ -s $B ] || exit 1; exec bash $B')
print(json.dumps({"env": env, "dockerEntrypoint": ["/bin/bash", "-c"], "dockerStartCmd": [cmd]}))
PY
ssh -o BatchMode=yes "$D" "set -a; . /etc/netra-catalog.env; set +a; curl -sS -X PATCH https://rest.runpod.io/v1/pods/$POD \
  -H \"Authorization: Bearer \$RUNPOD_API_KEY\" -H 'Content-Type: application/json' --data-binary @- \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get(\"id\"), d.get(\"desiredStatus\"), (d.get(\"dockerStartCmd\") or [\"?\"])[0][:60], d.get(\"error\",\"\"))'" < "$TMP/body.json"
echo "re-signed $POD (links valid 7 days); the pod resets now: re-point its ports (plans/cloud-edge.md)"
