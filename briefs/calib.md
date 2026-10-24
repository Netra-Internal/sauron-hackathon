# Brief: calib — calibrate a camera from the Send drone dashboard (hackathon repo)
William: "I need to be able to go calibrate a camera easily from this dashboard (we basically have a map overlay where
we create boundaries, put camera position and angle by adjusting using points from the cam view to a real map)."

That tool exists in netra-ask's Sites page (`/ask/sites`, setup `#/site/<id>/setup`, calibration `#/site/<id>/cam/<cid>`;
code ~/netra/netra-ask/ask/static/sites.{html,js,css}, backend ask/api.py:763-930, model ask/camgeo.py, ask/sitemap.py).
Build the same workflow INSIDE /hack/ in this repo, as a "Calibrate" screen reachable in one click from each camera
card (and a "Site setup" entry for the boundary). Nothing in netra-ask is edited.
- Backend: call netra-ask's EXISTING site/camera/frame/project/calibration routes (they write `sites`/`site_cameras`, which
  sitefuse and pixel_to_latlon read — so a calibration made here immediately changes person→coordinate). Proxy them from
  a new router `hackdash/calib.py` forwarding the operator's own Cookie/Authorization (same pattern as launch.py's abort,
  so the audit names the operator). Use the service account hack_launch (~/.config/netra/hack-launch.env) only for tests.
- Frontend: new files `hackdash/static/calib.{js,css}` (copy/adapt from sites.js — MapLibre 4.7.1 + Esri imagery, same
  as /ask/sites). Must do: freeze a frame from the live camera, click frame point ↔ map point pairs, live fit with the
  leave-one-out ground error shown, camera position + view cone drawn on the map, drag/adjust and refit, save; draw/edit
  the site boundary polygon; after saving, show the current live person boxes projected as dots on the map so the
  operator can eyeball the fit against reality. Show the fit error honestly (LOO metres, at_limit warnings).
- Wiring: add ONE tolerant mount line for `hackdash.calib` in hackdash/app.py and ONE "Calibrate" button per camera card
  in hack.js (agent `dash` also edits hack.js right now for another change — keep your hack.js edit to a minimal hook,
  commit early, and say in status exactly which lines you touched).
- ⚠️ Do NOT overwrite the production calibration of camera-1-5621 (jetson-c920) while testing: test on a NEW camera
  record you create and then delete, or save only when William does it. The site_cameras.points are in the 960×540
  frozen-frame px (frame.width/height), not source px.
- Deploy with deploy/install.sh from a tree containing origin/main (the script enforces it). Done = Playwright screenshots
  of the calibrate screen with a real frozen frame + map (plans/calib-*.png), round-trip test on a throwaway camera
  record, status/calib.md DONE.
