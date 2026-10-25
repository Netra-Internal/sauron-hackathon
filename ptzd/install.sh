#!/usr/bin/env bash
# Install ptzd next to the Axis and the tunnel that lets the droplet's sauron-hack reach it on 127.0.0.1:8530.
# Run from a laptop checkout:
#   bash ptzd/install.sh BOX forward DROPLET_TARGET   the droplet dials the box: DROPLET_TARGET = ssh target as the
#                                                     droplet sees it (e.g. <jetson>, like netra-ask-edge-tunnel)
#   bash ptzd/install.sh BOX reverse                  the box dials the droplet (box behind NAT, e.g. a laptop); the box's
#                                                     key is authorised on the droplet for that one port forward only
# BOX = ssh target from this laptop, with sudo. Camera creds: ~/.config/netra/axis-q6215.env (CAM_HOST=... overrides the IP).
# The token is created once on the droplet (/etc/ptzd-token, root:netra 640; hackdash/ptz.py reads it).
set -euo pipefail
BOX=$1; MODE=$2; FWD=${3:-}
DROPLET=${DROPLET:?set DROPLET=root@<droplet>}
DROPLET_HOST=${DROPLET#*@}
CAMENV=${CAMENV:-$HOME/.config/netra/axis-q6215.env}
cd "$(dirname "$0")"
[ -f "$CAMENV" ] || { echo "no $CAMENV"; exit 1; }
TOKEN=$(ssh "$DROPLET" 'umask 027; [ -s /etc/ptzd-token ] || head -c 24 /dev/urandom | xxd -p > /etc/ptzd-token; chown root:netra /etc/ptzd-token; chmod 640 /etc/ptzd-token; cat /etc/ptzd-token')

# ---- ptzd on the box
ENVBODY=$( (grep -E '^PTZ_CAM_(HOST|USER|PASS)=' "$CAMENV" | { if [ -n "${CAM_HOST:-}" ]; then sed "s/^PTZ_CAM_HOST=.*/PTZ_CAM_HOST=$CAM_HOST/"; else cat; fi }); echo "PTZD_TOKEN=$TOKEN")
scp -q ptzd.py "$BOX":/tmp/ptzd.py
printf '%s\n' "$ENVBODY" | ssh "$BOX" 'umask 077; cat > /tmp/ptzd.env'
ssh "$BOX" 'set -e
  sudo mkdir -p /opt/netra/ptzd
  sudo install -m 644 /tmp/ptzd.py /opt/netra/ptzd/ptzd.py && rm /tmp/ptzd.py
  sudo install -m 600 -o root -g root /tmp/ptzd.env /etc/ptzd.env && rm /tmp/ptzd.env
  printf "%s\n" "[Unit]" "Description=ptzd: manual PTZ for the Axis (sauron-hackathon), 127.0.0.1:8530" "After=network-online.target" "" \
    "[Service]" "DynamicUser=yes" "EnvironmentFile=/etc/ptzd.env" \
    "ExecStart=/usr/bin/python3 -I /opt/netra/ptzd/ptzd.py --listen 127.0.0.1:8530" "Restart=always" "RestartSec=2" "" \
    "[Install]" "WantedBy=multi-user.target" | sudo tee /etc/systemd/system/ptzd.service >/dev/null
  sudo systemctl daemon-reload; sudo systemctl enable -q --now ptzd; sudo systemctl restart ptzd; sleep 1
  curl -fsS http://127.0.0.1:8530/health; echo'

# ---- tunnel
UNIT_COMMON='After=network-online.target\n\n[Service]\nRestart=always\nRestartSec=5'
SSHOPTS="-N -o BatchMode=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes -o StrictHostKeyChecking=accept-new"
if [ "$MODE" = forward ]; then
  [ -n "$FWD" ] || { echo "forward needs DROPLET_TARGET"; exit 2; }
  # two tunnels, two TCP connections: commands on 8530, snapshots on 8531, so commands never wait behind picture bytes
  for pair in ptzd-tunnel:8530 ptzd-tunnel-img:8531; do u=${pair%:*}; p=${pair#*:}
    ssh "$DROPLET" "printf '[Unit]\nDescription=ptzd tunnel: droplet 127.0.0.1:$p -> $FWD ptzd\n$UNIT_COMMON\nEnvironment=HOME=/root\nExecStart=/usr/bin/ssh $SSHOPTS -L 127.0.0.1:$p:127.0.0.1:8530 $FWD\n\n[Install]\nWantedBy=multi-user.target\n' > /etc/systemd/system/$u.service
      systemctl daemon-reload; systemctl enable -q --now $u; systemctl restart $u"
  done
elif [ "$MODE" = reverse ]; then
  PUB=$(ssh "$BOX" 'sudo test -f /root/.ssh/ptzd_tunnel || sudo ssh-keygen -q -t ed25519 -N "" -C ptzd-tunnel -f /root/.ssh/ptzd_tunnel; sudo cat /root/.ssh/ptzd_tunnel.pub')
  ssh "$DROPLET" "grep -qF '$PUB' /root/.ssh/authorized_keys || echo 'restrict,port-forwarding,permitlisten=\"127.0.0.1:8530\",command=\"/bin/false\" $PUB' >> /root/.ssh/authorized_keys"
  ssh "$BOX" "printf '[Unit]\nDescription=ptzd tunnel: $DROPLET_HOST 127.0.0.1:8530 -> local ptzd\n$UNIT_COMMON\nExecStart=/usr/bin/ssh $SSHOPTS -i /root/.ssh/ptzd_tunnel -R 127.0.0.1:8530:127.0.0.1:8530 $DROPLET\n\n[Install]\nWantedBy=multi-user.target\n' | sudo tee /etc/systemd/system/ptzd-tunnel.service >/dev/null
    sudo systemctl daemon-reload; sudo systemctl enable -q --now ptzd-tunnel; sudo systemctl restart ptzd-tunnel"
else
  echo "mode: forward | reverse"; exit 2
fi
sleep 3
ssh "$DROPLET" 'curl -fsS http://127.0.0.1:8530/health && echo && curl -fsS -H "Authorization: Bearer $(cat /etc/ptzd-token)" http://127.0.0.1:8530/position && echo'
