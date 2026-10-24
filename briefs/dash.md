# Brief: dash — the Send drone page (hackathon repo)
Read ~/hack-2026-10-24/ARCH.md and plans/click-to-dispatch.md (§2) and look at plans/sketch.jpg + monitor-now.jpg.
Build `hackdash/app.py` (FastAPI, mounts `hackdash.live.router` and `hackdash.launch.router` under /hack/api — import
them lazily/tolerantly so the app runs before the other agents merge) and the page `hackdash/static/` served at /hack/.
- Look and feel: a copy of the Sites monitor's look (read ~/netra/netra-ask/ask/static/monitor.js, sites.css, sites.html
  for structure and style; copy what you need into this repo, don't import from netra-ask). Map with fused people is
  nice-to-have; the must-have is: camera tile(s) → open camera → live frame (~1 fps) with a canvas of person boxes, each
  with a chip `#id conf · suspicion|—` and a **Send drone** button → inline "Send drone to #id? Yes / Cancel" → POST
  /hack/api/launch → toast + incident panel (state, location, forwarded/delivered, drone messages from
  /hack/api/drone/messages) + **Abort drone** button. Show "≈N s behind live", "judge off", and "test rig" for jetson-c920.
- Write `deploy/`: install script + `sauron-hack.service` + nginx location for /hack/ on the droplet (reuse the /ask
  auth; `nginx -t` before reload; don't touch netra-ask's unit or files). You may deploy and redeploy YOUR service.
- Coordinate API shapes via ARCH.md only; if you need a change, write it in status/dash.md and tell the manager.
Done = page live at https://internal.netralabs.net/hack/ showing the real jetson-c920 frame and real boxes (once `boxes`
lands), Playwright screenshot in plans/dash-live.png.
