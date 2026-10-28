#!/usr/bin/env bash
# Camera box -> cloud edge pod. Stream-copies every local camera in STREAMS (no re-encode; the C920 1080p5 shim is
# ~1.4 Mbit/s) to the pod's mediamtx as path <camera id>, over RTSPS inside one SSH tunnel through the droplet
# (office egress allows only a few ports, e.g. 22/443, never RunPod's random ones; the droplet account `cloudrelay` may
# only port-forward to the pod's RTSPS port). Adding a camera on this box = one more "id=rtsp://..." word in STREAMS.
# A camera may list fallbacks, "id=rtsp://first|rtsp://second": each (re)connect tries them in order.
# Wi-Fi only: the route to the relay must leave through one of $WIFI_IF (a list, "wlan0|wlan1" or "wlan0 wlan1") AND that
# interface must be a wireless one (/sys/class/net/<if>/wireless), checked before connecting and every 10 s. A move to
# another listed Wi-Fi interface rebuilds the tunnel on the new route; a move off Wi-Fi
# (Wi-Fi down, default route on LTE: lte0 is capped at 25 MB/h) kills everything and nothing is sent until it's back.
#   env (/etc/netra-cloud-push.env): STREAMS="jetson-c920=rtsp://127.0.0.1:8556/c920 [id=url ...]"  POD=ip:port
#        PUSH_PASS  RELAY=cloudrelay@<droplet>  RELAY_KEY=~/.ssh/cloudrelay_ed25519 (no passphrase; the droplet
#        restricts it to port-forwarding to POD)  WIFI_IF=wlP1p1s0  EDGE_FFMPEG=/opt/ffmpeg/ffmpeg
#        PUSH_VCODEC (optional, default "-c copy"): video args for a camera whose stream is too big for the uplink,
#        e.g. "-vf fps=10 -c:v h264_v4l2m2m -b:v 1500k -g 10 -bf 0 -pix_fmt yuv420p" (Pi 4 hardware encoder)
# Exactly one ffmpeg per camera, and "running but not publishing" is a failure (demo-node2 incident, Oct 27-28: an
# orphaned fallback ffmpeg plus a wedged Pi encoder kept the unit "active" for 18 h with nothing reaching the pod):
#   - before every launch, any ffmpeg of this user still publishing to this camera's path is killed (TERM, KILL after
#     10 s), then 3 s pass before the next one opens the encoder (the Pi 4 bcm2835 codec driver oopsed when a new
#     h264_v4l2m2m session started while a killed one was still being torn down);
#   - stop_all stops each camera loop BEFORE killing its ffmpeg, so a loop can never start its next fallback source
#     in between and leave it orphaned (the old order did exactly that);
#   - ffmpeg reports its output frame count (-progress); a camera whose count has not grown for STALL_S (60) is killed
#     and relaunched. $PROG_DIR/<cam>.alive = "<frames> <uptime s of the last growth>" is read by
#     node/pi/netra-node-push-health, which tests the encoder and can switch VCODEC_OVERRIDE (e.g. to libx264).
set -u
FF=${EDGE_FFMPEG:-/opt/ffmpeg/ffmpeg}; WIFI_IF=${WIFI_IF:-wlP1p1s0}; RELAY=${RELAY:?set RELAY=cloudrelay@<droplet>}
LPORT=${LPORT:-18322}; RELAY_IP=${RELAY#*@}
route_dev() { ip route get "$RELAY_IP" 2>/dev/null | sed -n 's/.* dev \([^ ]*\).*/\1/p' | head -1; }
via_wifi() {   # prints the Wi-Fi interface the relay route uses; fails for any non-listed or non-wireless interface
  local d; d=$(route_dev); [ -n "$d" ] && [ -d "/sys/class/net/$d/wireless" ] || return 1
  case " ${WIFI_IF//[|,]/ } " in *" $d "*) echo "$d" ;; *) return 1 ;; esac
}
PROG_DIR=${PROG_DIR:-${RUNTIME_DIRECTORY:-/tmp/netra-cloud-push-$(id -u)}}; STALL_S=${STALL_S:-60}
VCODEC_OVERRIDE=${VCODEC_OVERRIDE:-/run/netra-push-health/vcodec}   # one line of video args; overrides PUSH_VCODEC
mkdir -p "$PROG_DIR"
cams=(); for s in $STREAMS; do cams+=("${s%%=*}"); done
cam_ffmpegs() {   # pids of this user's ffmpegs publishing to camera $1 (matched on the exact output URL argument)
  local p; for p in $(pgrep -u "$(id -u)" -x "$(basename "$FF")"); do
    tr '\0' '\n' < "/proc/$p/cmdline" 2>/dev/null | grep -qx "rtsps://pusher:.*@127\.0\.0\.1:$LPORT/$1" && echo "$p"
  done
}
up() { cut -d. -f1 /proc/uptime; }   # monotonic: the Pi has no RTC and boots with a stale clock until NTP
kill_cam() {   # TERM, then KILL whatever is left after 10 s; then let the encoder settle
  local p i; p=$(cam_ffmpegs "$1"); [ -n "$p" ] || return 0
  kill $p 2>/dev/null
  for i in $(seq 10); do sleep 1; p=$(cam_ffmpegs "$1"); [ -z "$p" ] && break; done
  [ -n "$p" ] && { echo "$(date -u +%T) $1: ffmpeg $p ignored TERM for 10 s; KILL"; kill -9 $p 2>/dev/null; }
  sleep 3
}
progress() {   # ffmpeg -progress lines on stdin -> $PROG_DIR/$1.alive "<frames> <uptime of last growth>" (overwritten)
  local l f=0 last=0; while IFS= read -r l; do   # only real output frames (>0) count
    case $l in frame=*) f=${l#frame=} ;; progress=*) [ "$f" -gt "$last" ] 2>/dev/null && { last=$f; echo "$f $(up)" > "$PROG_DIR/$1.alive"; } ;; esac
  done
}
pids=()
stop_all() {
  local p c
  for p in "${pids[@]}"; do kill "$p" 2>/dev/null; done   # loops first: each exits as soon as its ffmpeg is gone
  for c in "${cams[@]}"; do kill_cam "$c"; done
  wait 2>/dev/null; pids=()
}
trap 'stop_all; exit 0' TERM INT
while true; do
  dev0=$(via_wifi) || dev0=""
  if [ -z "$dev0" ]; then echo "$(date -u +%T) no Wi-Fi route to the relay $RELAY_IP; waiting"; sleep 10; continue; fi
  ssh -N -i "${RELAY_KEY:-$HOME/.ssh/cloudrelay_ed25519}" -o BatchMode=yes -o ExitOnForwardFailure=yes -o ServerAliveInterval=10 -o ServerAliveCountMax=3 \
      -o StrictHostKeyChecking=accept-new -L "127.0.0.1:$LPORT:$POD" "$RELAY" &
  pids=($!); sleep 3
  for s in $STREAMS; do
    cam=${s%%=*}; src=${s#*=}
    ( trap 'exit 0' TERM   # deferred until the running ffmpeg is gone; then no next source is started
      while true; do
        IFS='|' read -ra srcs <<< "$src"
        for one in "${srcs[@]}"; do
          kill_cam "$cam"   # never two publishers for one camera
          vc=$(head -1 "$VCODEC_OVERRIDE" 2>/dev/null); vc=${vc:-${PUSH_VCODEC:--c copy}}
          echo "$(date -u +%T) $cam trying ${one//:*@/://***@} ($vc)"
          up > "$PROG_DIR/$cam.launch"
          "$FF" -hide_banner -loglevel warning -nostdin -rtsp_transport tcp -timeout 5000000 -i "$one" -map 0:v:0 $vc -an \
                -stats_period 5 -progress pipe:3 \
                -f rtsp -rtsp_transport tcp "rtsps://pusher:${PUSH_PASS}@127.0.0.1:$LPORT/$cam" 3> >(progress "$cam")
          echo "$(date -u +%T) $cam push from ${one//:*@/://***@} exited $?"
        done
        sleep 5
      done ) &
    pids+=($!); echo "$(date -u +%T) pushing $cam (${src//:*@/://***@}) -> pod $POD via $RELAY on $dev0"
  done
  while kill -0 "${pids[0]}" 2>/dev/null && [ "$(via_wifi)" = "$dev0" ]; do
    sleep 10; now=$(up)
    for c in "${cams[@]}"; do   # running but not publishing: no new output frame for STALL_S since launch -> relaunch
      a=$(cut -d' ' -f2 "$PROG_DIR/$c.alive" 2>/dev/null || echo 0); l=$(cat "$PROG_DIR/$c.launch" 2>/dev/null || echo "$now")
      [ "$a" -gt "$l" ] 2>/dev/null || a=$l
      if [ $((now - a)) -ge "$STALL_S" ]; then
        echo "$(date -u +%T) $c: no output frame for $((now - a)) s; killing its ffmpeg ($(cam_ffmpegs "$c" | tr '\n' ' '))"
        up > "$PROG_DIR/$c.launch"; kill_cam "$c"
      fi
    done
  done
  echo "$(date -u +%T) tunnel down or route left $dev0 (now: $(route_dev)); stopping all pushes"; stop_all; sleep 5
done
