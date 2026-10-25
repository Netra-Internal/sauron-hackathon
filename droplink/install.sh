#!/usr/bin/env bash
# Install / update droplink on the droplet (run from a laptop checkout): bash droplink/install.sh
# Copies droplink.py + the unit, writes /etc/droplink.env with ONLY the webhook secret (taken from /etc/netra-ask.env),
# restarts droplink.service and checks /health. Never touches netra-ask.
set -euo pipefail
HOST=${HOST:-${HACK_HOST:?set HACK_HOST=root@<droplet>}}
cd "$(dirname "$0")"
ssh "$HOST" 'mkdir -p /opt/netra/droplink'
scp -q droplink.py "$HOST":/opt/netra/droplink/droplink.py
scp -q droplink.service "$HOST":/etc/systemd/system/droplink.service
ssh "$HOST" 'set -e
  umask 077
  grep "^DISPATCH_WEBHOOK_SECRET=" /etc/netra-ask.env > /etc/droplink.env
  chown root:root /etc/droplink.env; chmod 600 /etc/droplink.env
  systemctl daemon-reload
  systemctl enable --now droplink.service >/dev/null 2>&1
  systemctl restart droplink.service
  for i in 1 2 3 4 5; do curl -fsS http://127.0.0.1:8510/health && echo && exit 0; sleep 1; done
  systemctl status droplink.service --no-pager; exit 1'
