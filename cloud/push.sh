#!/usr/bin/env bash
# Camera box -> cloud edge pod. Stream-copies every local camera in STREAMS (no re-encode; the C920 1080p5 shim is
# ~1.4 Mbit/s) to the pod's mediamtx as path <camera id>, over RTSPS inside one SSH tunnel through the droplet
# (office egress allows only a few ports, e.g. 22/443, never RunPod's random ones; the droplet account `cloudrelay` may
# only port-forward to the pod's RTSPS port). Adding a camera on this box = one more "id=rtsp://..." word in STREAMS.
# A camera may list fallbacks, "id=rtsp://first|rtsp://second": each (re)connect tries them in order.
# Wi-Fi only: the route to the relay must leave through $WIFI_IF, checked before connecting and every 10 s; if it moves
# (Wi-Fi down, default route on LTE: lte0 is capped at 25 MB/h) everything is killed and nothing is sent until it's back.
#   env (/etc/netra-cloud-push.env): STREAMS="jetson-c920=rtsp://127.0.0.1:8556/c920 [id=url ...]"  POD=ip:port
#        PUSH_PASS  RELAY=cloudrelay@104.131.163.205  RELAY_KEY=~/.ssh/cloudrelay_ed25519 (no passphrase; the droplet
#        restricts it to port-forwarding to POD)  WIFI_IF=wlP1p1s0  EDGE_FFMPEG=/opt/ffmpeg/ffmpeg
set -u
FF=${EDGE_FFMPEG:-/opt/ffmpeg/ffmpeg}; WIFI_IF=${WIFI_IF:-wlP1p1s0}; RELAY=${RELAY:-cloudrelay@104.131.163.205}
LPORT=${LPORT:-18322}; RELAY_IP=${RELAY#*@}
via_wifi() { ip route get "$RELAY_IP" 2>/dev/null | grep -q " dev $WIFI_IF "; }
pids=()
stop_all() { for p in "${pids[@]}"; do pkill -P "$p" 2>/dev/null; kill "$p" 2>/dev/null; done; wait 2>/dev/null; pids=(); }
trap 'stop_all; exit 0' TERM INT
while true; do
  if ! via_wifi; then echo "$(date -u +%T) no Wi-Fi route to the relay $RELAY_IP; waiting"; sleep 10; continue; fi
  ssh -N -i "${RELAY_KEY:-$HOME/.ssh/cloudrelay_ed25519}" -o BatchMode=yes -o ExitOnForwardFailure=yes -o ServerAliveInterval=10 -o ServerAliveCountMax=3 \
      -o StrictHostKeyChecking=accept-new -L "127.0.0.1:$LPORT:$POD" "$RELAY" &
  pids=($!); sleep 3
  for s in $STREAMS; do
    cam=${s%%=*}; src=${s#*=}
    ( while true; do
        IFS='|' read -ra srcs <<< "$src"
        for one in "${srcs[@]}"; do
          echo "$(date -u +%T) $cam trying ${one//:*@/://***@}"
          "$FF" -hide_banner -loglevel warning -nostdin -rtsp_transport tcp -timeout 5000000 -i "$one" -map 0:v:0 -c copy -an \
                -f rtsp -rtsp_transport tcp "rtsps://pusher:${PUSH_PASS}@127.0.0.1:$LPORT/$cam"
          echo "$(date -u +%T) $cam push from ${one//:*@/://***@} exited $?"
        done
        sleep 5
      done ) &
    pids+=($!); echo "$(date -u +%T) pushing $cam (${src//:*@/://***@}) -> pod $POD via $RELAY"
  done
  while kill -0 "${pids[0]}" 2>/dev/null && via_wifi; do sleep 10; done
  echo "$(date -u +%T) tunnel down or route left $WIFI_IF; stopping all pushes"; stop_all; sleep 5
done
