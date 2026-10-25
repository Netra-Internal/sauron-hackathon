DONE: Left pane removed; only while a drone is out (open incident) a compact "Drone sent → #id · located ±m · time" card with Abort drone sits over the video. Static files deployed WITHOUT restarting sauron-hack; hack-dash pushed — MANAGER: please merge hack-dash into main.

- Branch hack-dash: 773e272 (code, contains origin/main) + screenshot commit, pushed.
- Deploy: rsync hackdash/static/ -> /opt/netra/sauron-hack/hackdash/static/, chown netra; md5 of hack.js/hack.css/index.html match the branch. sauron-hack NOT restarted (ActiveEnterTimestamp 23:17:31 UTC is not mine). The page picks the new files up without a restart (index.html is read per request, asset URLs versioned by mtime).
- Removed from the main page: the "Drones sent" history (incl. closed/dismissed), the incident detail view, the droplink message list (seq/signature/raw bodies), and the per-box "Incident" button. Tiny "Debug" link in the top bar -> /hack/api/incidents (raw JSON).
- Layout: two columns (camera | Cameras list); the video gets the freed width (1268 px at a 1600 px window).
- Verified on the real page with a read-only headless run (navigate, read DOM, screenshot; NO clicks, no PTZ): no left pane, live video playing (HLS), 1 person boxed, no drone card because no incident is open. plans/dash-live.png.
- NOT verified live: the drone card itself (that needs an open incident; I did not launch a drone to test it).

## Repo push
PUSHED 1597371
- Branch hack-dash in Netra-Internal/sauron-hackathon. It contains everything dash built or deployed today, and origin/main.
  - code: hackdash/app.py and hackdash/static/{index.html,hack.js,hack.css}
  - deploy: deploy/{install.sh,sauron-hack.service,nginx-hack.conf}, plus the new deploy/sauron-hack.env.example
    (placeholders only, no secrets) and deploy/README.md (the README section for my piece)
  - tool: tools/dash_shot.js (the read-only page check)
  - screenshot: plans/dash-live.png
  - requirements.txt
- No secrets in the tree: the real /etc/sauron-hack.env holds only a comment, and the tokens live in netra-ask's env on the droplet.
