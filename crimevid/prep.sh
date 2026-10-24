#!/usr/bin/env bash
# Clean sources BEFORE the models see them: crop away burned-in news / app graphics and cut non-CCTV segments.
# Each choice was made from contact sheets of the clip (see crimevid/README.md). Output: $SRC/<id>.mp4 (H.264, crf 18).
set -euo pipefail
SRC=${SRC:-$HOME/sauron-data/crimevid/src}
C=$HOME/sauron-data/dispatch-clips/yt
mkdir -p "$SRC"
cut() {  # id input start end crop(w:h:x:y or -)
  local vf=(); [ "$5" != "-" ] && vf=(-vf "crop=$5")
  ffmpeg -v error -y -ss "$3" -to "$4" -i "$2" "${vf[@]}" -an -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p "$SRC/$1.mp4"
  echo "$1 $(ffprobe -v error -show_entries stream=width,height:format=duration -of csv=p=0 "$SRC/$1.mp4" | tr '\n' ' ')"
}
# news lower third "TOP STORIES / ATTEMPTED BIKE THEFT" + inset from y=505 down, full width: keep the top 500 rows
# (the CCTV date stamp sits under the banner at y~695 and cannot be kept by a rectangle; "CAMERA10" top-left stays)
cut bike-lock   "$C/Z-5VBVAGUME.mp4" 0 41.75 1280:500:0:0
# camera-app icons (snapshot / record / speaker) along the right edge x>=525; an editor's green highlight box in 0-1 s
cut car-breakin "$C/LNA3EOR2W6c.mp4" 1.0 46.5  520:480:0:0
# one fixed camera 0-41 s; at ~41.7 s the upload cuts to a second camera angle
cut atm-rip     "$C/wWEHimK-bNw.mp4" 0 41.0   -
