#!/bin/bash
# EDGE_FFMPEG on the pod: the real ffmpeg, plus `-flush_packets 1` on the ring's segment output. Without it the in-progress
# 60 s .mkv is written in 256 KB chunks; a low-bitrate camera (the Axis at 720p5) then leaves the newest seconds unreadable
# for edge-serve /frame ("File ended prematurely" -> 500, /hack/ lag 20-70 s). Every other ffmpeg call passes through.
args=()
for a in "$@"; do
  [ "$a" = segment ] && [ "${args[-1]:-}" = -f ] && { unset 'args[-1]'; args+=(-flush_packets 1 -f); }
  args+=("$a")
done
exec "$(dirname "$0")/ffmpeg" "${args[@]}"
