#!/usr/bin/env bash
# Run the REAL dispatch pipeline (netra-ask main: PersonGate YOLO11s + Jev strip judge every 2 s + default PolicyConfig,
# the same policy file-free config as the deployed edge units) over the crimevid clips, replay mode, nothing posted.
# Output: $OUT/<id>/timeline.json (+ incidents/ evidence). Then render.py draws the annotated video.
set -euo pipefail
OUT=${OUT:-$HOME/sauron-data/crimevid/out}
ASK=${ASK:-$HOME/netra/netra-ask}
C=$HOME/sauron-data/dispatch-clips/yt
L=$HOME/sauron-data/lockneg/seg
specs=(
  "bike-lock|$C/Z-5VBVAGUME.mp4|2|12|crime|Bike lock cut outside a police building"
  "catalytic|$C/93r5PSP2rI4.mp4|2|62|crime|Catalytic converter sawn off a parked Prius"
  "atm-rip|$C/wWEHimK-bNw.mp4|4|40|crime|ATM front ripped off with a chain and pickup"
  "car-breakin|$C/LNA3EOR2W6c.mp4|8|30|crime|Night car break-in in a parking lot"
  "fence-climb|$C/DzQTLgqtWmY.mp4|0|12|crime|Trespasser climbs a wooden fence"
  "owner-car-1|$L/mevadoor-G340-03-07-16-50-3108.mp4|||benign|Owner opens their own car (MEVA CCTV)"
  "owner-car-2|$L/mevadoor-G505-03-07-10-55-7236.mp4|||benign|Owner opens their own car (MEVA CCTV)"
)
[ $# -gt 0 ] && specs=("$@")
R=$(cd "$(dirname "$0")" && pwd)
# one CPU model job at a time: pipeline for a clip, then its render-time tracker + render, then the next clip
for spec in "${specs[@]}"; do
  id=${spec%%|*}
  [ -f "$OUT/$id/timeline.json" ] || (rm -rf "${OUT:?}/$id" && cd "$ASK" && ASK_BACKEND=ort "$ASK/.venv/bin/python" tools/dispatch-eval/demo/run_demo.py "$OUT" "$spec")
  [ -f "$OUT/$id/annotated.mp4" ] || "$HOME/sauron-venv/bin/python" "$R/render.py" "$OUT/$id"
done
