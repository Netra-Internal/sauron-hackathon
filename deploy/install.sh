#!/usr/bin/env bash
# Deploy the sauron-hack service (the /hack/ page + API) to the droplet. Run from a laptop checkout:
#   deploy/install.sh [SRC_DIR]      SRC_DIR = repo checkout to ship (default: this script's repo)
# Ships hackdash/, deploy/ and requirements.txt into /opt/netra/sauron-hack WITHOUT --delete, so a deploy from a
# branch that lacks another agent's router doesn't wipe it. Touches only our own files, unit and nginx block;
# never netra-ask's unit or files.
set -euo pipefail
HOST=${HACK_HOST:-root@104.131.163.205}
SRC=$(cd "${1:-$(dirname "$0")/..}" && pwd)
DEST=/opt/netra/sauron-hack

# every deploy must contain origin/main (the manager's integrated routers), or it ships stale code over them
git -C "$SRC" fetch -q origin
if ! git -C "$SRC" merge-base --is-ancestor origin/main HEAD; then
  echo "refusing: $SRC does not contain origin/main ($(git -C "$SRC" rev-parse --short origin/main)); git merge origin/main first" >&2; exit 1
fi
if [ -n "$(git -C "$SRC" status --porcelain -- hackdash deploy requirements.txt)" ]; then
  echo "refusing: uncommitted changes under hackdash/, deploy/ or requirements.txt; commit them first" >&2; exit 1
fi
echo "== ship $SRC -> $HOST:$DEST ($(git -C "$SRC" rev-parse --abbrev-ref HEAD 2>/dev/null) $(git -C "$SRC" rev-parse --short HEAD 2>/dev/null))"
ssh "$HOST" "mkdir -p $DEST"
rsync -rlt --exclude __pycache__ --exclude .venv "$SRC/hackdash" "$SRC/deploy" "$SRC/requirements.txt" "$HOST:$DEST/"

ssh "$HOST" bash -s <<'REMOTE'
set -euo pipefail
DEST=/opt/netra/sauron-hack
chown -R netra:netra $DEST
[ -x $DEST/.venv/bin/python ] || sudo -u netra python3 -m venv $DEST/.venv
sudo -u netra $DEST/.venv/bin/pip install -q -r $DEST/requirements.txt

if [ ! -f /etc/sauron-hack.env ]; then
  printf '# sauron-hack overrides (read after /etc/netra-ask.env)\n' > /etc/sauron-hack.env
  chown root:netra /etc/sauron-hack.env; chmod 640 /etc/sauron-hack.env
fi
mkdir -p /var/lib/sauron-hack && chown netra:netra /var/lib/sauron-hack
KH=/var/lib/sauron-hack/known_hosts      # the Jetson's host key, copied from root's (already trusted) known_hosts
if ! ssh-keygen -F 100.102.178.107 -f $KH >/dev/null 2>&1; then
  ssh-keygen -F 100.102.178.107 -f /root/.ssh/known_hosts | grep -v '^#' >> $KH || true
  chown netra:netra $KH; chmod 644 $KH
fi

install -m 644 $DEST/deploy/sauron-hack.service /etc/systemd/system/sauron-hack.service
systemctl daemon-reload
systemctl enable sauron-hack >/dev/null 2>&1
systemctl restart sauron-hack

SITE=/etc/nginx/sites-available/internal
if ! grep -q '>>> /hack/' $SITE; then
  cp $SITE /root/internal.nginx.bak-$(date +%Y%m%d-%H%M%S)
  BAK=$(ls -t /root/internal.nginx.bak-* | head -1)
  # insert our block before the server block's closing brace (the last "}" in the file)
  python3 - "$SITE" "$DEST/deploy/nginx-hack.conf" <<'PY'
import sys
site, snip = sys.argv[1], open(sys.argv[2]).read()
s = open(site).read(); i = s.rstrip().rfind("}")
open(site, "w").write(s[:i] + "\n" + snip + s[i:])
PY
  if nginx -t; then systemctl reload nginx; echo "nginx: /hack/ added (backup $BAK)"
  else cp "$BAK" $SITE; echo "nginx -t failed: restored $BAK"; exit 1; fi
else echo "nginx: /hack/ block already present"; fi

for i in $(seq 30); do [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8500/hack/api/health)" = 401 ] && break; sleep 0.5; done
systemctl is-active sauron-hack
echo "unauthenticated /hack/api/health -> $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8500/hack/api/health) (401 expected)"
echo "unauthenticated /hack/ -> $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/hack/) (303 to login expected)"
journalctl -u sauron-hack -n 8 --no-pager
REMOTE
