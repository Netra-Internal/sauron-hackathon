# dash: the Send-drone page (`/hack/`)

Built by agent `dash` (hackathon 2026-10-24). Lives at https://internal.netralabs.net/hack/ behind the internal login
(the `/map/login` cookie or HTTP basic, same as `/ask`).

**What it is**
- `hackdash/app.py`: FastAPI app. Serves the page and mounts the API routers under `/hack/api`, importing them
  tolerantly (`/hack/api/health` reports which mounted). `hackdash.live` is boxes' piece, `hackdash.launch` is launch's.
  calib, ptz and relay are other agents' pieces.
- `hackdash/static/{index.html,hack.js,hack.css}`: the page. The look is copied from netra-ask's Sites monitor.
  - Open camera: live video from `/hack/stream/<cam>/`. It tries WHEP first, else LL-HLS through hls.js 1.5.20 from cdnjs.
    If the stream fails, it falls back to the ring JPEGs.
  - Person boxes come from `/hack/api/cameras/<cam>/live`, drawn on a canvas over the video. Each box has a chip:
    `#id conf · suspicion`, plus **Send drone**, then an inline confirm, then `POST /hack/api/launch`.
    `t_ns` is sent as raw digits, because JS numbers can't hold it.
  - While a drone is out (an open incident), a compact "Drone sent → #id · located ±m · time" card with
    **Abort drone** appears. The Cameras list shows only live cameras.
- `deploy/`
  - `install.sh [SRC]`: ships to the droplet. It refuses a tree without origin/main or one with uncommitted changes.
    It rsyncs, builds the venv, and installs the unit. It inserts the nginx block once, runs `nginx -t`, and restores
    the backup if that fails. Then it checks health.
  - `sauron-hack.service`: uvicorn on 127.0.0.1:8500 as user netra.
  - `nginx-hack.conf`: the `/hack/` location for the internal server block.
  - `sauron-hack.env.example`: the env template (placeholders only).

**Deploy**: `git merge origin/main && deploy/install.sh`. Use a static-only deploy when the service must not restart:
`rsync -rlt hackdash/static/ root@<droplet>:/opt/netra/sauron-hack/hackdash/static/ && chown -R netra:netra …`.

**Local dev**: `HACK_NO_AUTH=1 uvicorn hackdash.app:app --port 8500`, then open http://127.0.0.1:8500/hack/.

**Rules**: never send PTZ commands to the real Axis from tests. Never restart netra-ask.
