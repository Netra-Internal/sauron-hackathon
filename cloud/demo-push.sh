#!/bin/bash
# Push one camera from any internet-connected box straight to the cloud pod (no SSH, no install beyond ffmpeg).
# The pod's mediamtx user "demo" may publish only path jetson-c920; the pod's edge + Jev dispatch pick it up within 15 s.
#   PASS=<demo password> ./demo-push.sh /dev/video0            # USB webcam: x264 1080p 5 fps, 1 s GOP, ~1.5 Mbit/s
#   PASS=<demo password> ./demo-push.sh rtsp://user:pw@cam/...  # IP camera: stream copy (set the camera's GOP to ~1 s)
# POD=<pod>:<public port for 8322> (changes when the pod restarts). Loops: reconnects every 3 s if it drops.
SRC=$1; POD=${POD:?set POD=<pod-ip>:<pod-port>}; CAM=${CAM:-jetson-c920}
OUT="rtsps://demo:$PASS@$POD/$CAM"
while true; do
  case $SRC in
    /dev/*) ffmpeg -hide_banner -loglevel warning -f v4l2 -input_format mjpeg -video_size 1920x1080 -i "$SRC" -vf fps=5 \
              -c:v libx264 -preset ultrafast -tune zerolatency -g 5 -b:v 1500k -maxrate 2M -bufsize 2M -pix_fmt yuv420p -an \
              -f rtsp -rtsp_transport tcp "$OUT" ;;
    *)      ffmpeg -hide_banner -loglevel warning -rtsp_transport tcp -i "$SRC" -map 0:v:0 -c copy -an \
              -f rtsp -rtsp_transport tcp "$OUT" ;;
  esac
  echo "$(date -u +%T) push exited $?; retrying"; sleep 3
done
