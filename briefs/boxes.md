# Brief: boxes — live frame + person boxes + real suspicion (hackathon repo)
Read ~/hack-2026-10-24/ARCH.md and plans/click-to-dispatch.md (§1, §3). Own `hackdash/live.py` (FastAPI APIRouter,
`router`) + tests. Implement GET /cameras, /cameras/{cam}/live, /cameras/{cam}/frame.jpg per ARCH.md WITHOUT editing
netra-ask. In netra-ask the live boxes sit only in-process (sitefuse Fuser.recent), so find a source we can read:
candidates — read-only SQL on `netra_ask` (tracks/positions tables, how fresh?), the Jetson edge-serve via the droplet
tunnel http://127.0.0.1:8450 (/frame?camera&t; check for any boxes/positions route in ~/netra/netra-ask/ask/edge/serve.py),
netra-ask's existing HTTP APIs (/ask/api/sites/{id}/live, people endpoints; worker token in /etc/netra-ask.env). MEASURE
freshness/lag of each and pick the best; the frame and the boxes must be from the same moment. Frame fetch: one request
in flight per camera, cache by t, 404 → retry t−0.2 s (ffmpeg on the Jetson, ~1 s per frame).
Labels: from open `dispatch_incidents` / `dispatch_watch` rows bound to the box's site track (record.site_track_id);
otherwise null. `judge_on` = netra-dispatch@<cam> active on the Jetson (read-only check; never start it).
Camera-agnostic: list cameras from netra-ask's sites/site_cameras + sites.yaml; jetson-c920 marked test_rig.
Done = curl on the droplet returns real boxes for jetson-c920 with measured lag in status/boxes.md.
