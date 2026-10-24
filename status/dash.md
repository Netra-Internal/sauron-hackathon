BLOCKED: /hack/ is live on the droplet (page + app + nginx + unit); waiting for hackdash.live (boxes) and hackdash.launch (launch) to land before the real-frame screenshot.

Branch hack-dash @ a6c8552 (pushed). Files: hackdash/app.py, hackdash/static/{index.html,hack.css,hack.js}, deploy/{install.sh,sauron-hack.service,nginx-hack.conf}, requirements.txt.

Live now (checked 14:28 PDT):
- https://internal.netralabs.net/hack/ -> 303 to /map/login when signed out; signed in, the page renders and says
  "live-view API (hackdash.live) isn't deployed yet" / "launch API isn't deployed yet" / "droplink isn't deployed yet" (no mock data).
- sauron-hack.service active on 127.0.0.1:8500, user netra, code /opt/netra/sauron-hack, venv .venv (fastapi 0.115.12, uvicorn 0.34.2, httpx, psycopg, pillow).
- nginx: /hack/ block added to /etc/nginx/sites-available/internal between ">>> /hack/" markers; nginx -t ok; backup /root/internal.nginx.bak-20261024-212740.
- /hack/api/health (signed in) lists which routers mounted and the import error of any that didn't.

For boxes / launch (API shapes are as in ARCH.md; the page reads exactly those fields):
- app.py mounts hackdash.live.router and hackdash.launch.router under /hack/api, tolerantly (missing module -> 404s, logged).
- Login middleware covers every /hack path; request.state.user = the signed-in user (use it for audit).
  EXEMPT: exactly /hack/api/_edge/bucket (boxes checks the worker Bearer token itself).
- Unit env: EnvironmentFile=-/etc/netra-ask.env then /etc/sauron-hack.env (ours overrides). So ASK_WORKER_TOKEN,
  ASK_EDGE_URL=http://127.0.0.1:8450, ASK_DATABASE_URL=postgresql:///netra_ask, DISPATCH_WEBHOOK_SECRET, ASK_DRONE_TOKEN are all present.
  Runs as netra -> peer auth to netra_ask works.
- Jetson read-only check: netra's own key works (verified: `systemctl is-active netra-dispatch@jetson-c920` -> inactive).
  Use env HACK_JETSON_SSH = "ssh -o BatchMode=yes -o ConnectTimeout=5 -o UserKnownHostsFile=/var/lib/sauron-hack/known_hosts netra@100.102.178.107"
  (known_hosts seeded by install.sh from root's).
- Page assumptions to keep: GET /incidents (no ?open) returns ALL demo incidents (array, or {incidents:[...]}) with
  id,status ("closed" when closed),camera_id,opened_at,updated_at,closed_at,located,lat,lon,radius_m,loc_source,site_track_id,
  forwarded:[{at,type?,status|error}],why_label. GET /drone/messages?since=<seq>: `seq` must be droplink's own monotonic
  sequence (the page sends max seq seen); messages match an incident by incident_id. frame_url may be absolute or relative to /hack/api.
- Extra pip deps: add to requirements.txt; install.sh pip-installs it.

Deploy: `deploy/install.sh [CHECKOUT]` from the laptop. It rsyncs hackdash/, deploy/, requirements.txt WITHOUT --delete
(so a deploy from one branch doesn't wipe another agent's router), restarts only sauron-hack, and adds the nginx block once.
Manager: deploy from the integrated checkout once live.py/launch.py merge; I'll then take plans/dash-live.png.

For the manager (not mine to change):
- The nginx `mirror` of /ask/api/edge/bucket -> /hack/api/_edge/bucket that boxes wants goes in the /ask location (netra-ask's block).
- After login, /map/login won't send you back to /hack/ (netra-internal common.auth NEXT_OK lacks "/hack"); you land on /map. One-word add there if wanted.
- Map with fused people (nice-to-have) not built; centre shows the opened camera live instead of the map.
