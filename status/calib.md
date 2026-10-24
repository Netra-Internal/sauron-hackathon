WORKING: Site setup Add/Remove camera DEPLOYED + checked (22:5x UTC); now doing PTZ-in-calibrate. Merge hack-calib to main (deployed from hack-calib + origin/hack-dash, since dash's live-video hack.js is deployed but not in main).

## Add / remove a camera (William's report, fixed)
- Calibrate / site setup -> Site setup tab: "Cameras on this site" has Calibrate + "Remove camera" (inline "Yes, remove / Cancel") on every record.
  "Add a camera" lists every netra-ask feed not on the site yet (now: "+ Add Axis Q6215-LE · bench PTZ (axis-q6215)"):
  one click adds it at the map centre and opens its calibration (drag the blue marker to where it's mounted).
- Checked with Playwright as hack_launch on the deployed page (tools/calib_sitesetup_check.js): Axis button visible -> added
  (axis-q6215-le-bench-ptz-7edb) -> calibration opened -> Remove -> confirm -> removed; Axis back in the Add list.
  Camera 1 untouched. Screenshots plans/calib-addcam-{1-site,2-opened,3-remove-confirm}.png. I did NOT remove Camera 1: William's call.

(earlier status, still true)
DONE: Calibrate screen live at https://internal.netralabs.net/hack/ (top bar "Calibrate / site setup", or the "Calibrate" chip on a live camera tile); recalibrating an existing camera works, verified without saving over camera-1-5621.

## How to recalibrate the C920 (William)
1. Open https://internal.netralabs.net/hack/, click "Calibrate / site setup" (top bar), then the "Camera 1" card (camera-1-5621 · jetson-c920). Its current frame, 9 pairs and fit load.
2. Click "Freeze a new frame". The 9 old MAP points are kept: the map pans to the white marker, so click that same spot in the new frame. Use "Skip this one" for points the camera no longer sees.
3. "Add point pairs" adds new ones: click a ground point in the frame, then the same point on the map (either order). Use kerb corners, paint and drain covers, near and far. You need 5+ pairs for a leave-one-out check.
4. Watch the box: ±X m is the typical ground error on a point the fit didn't see. A red "checked" value or an amber warning means a mis-click: drag that point (frame or map) or click × to remove it. Everything stays an unsaved draft.
5. Click "Save calibration". netra-ask stores it, and sitefuse / pixel_to_latlon use it at once. Once the edge feed is back, green dots show where the live people land on the map.

## Before William starts: the edge is DOWN
All netra-edge@* units on jetson-cloud were stopped at 14:53:27 PDT (not by me; probably the cloud/RunPod work). With the edge down there are:
- no ring frames and no live boxes, so no green dots on the map;
- no live jetson-c920 tile (dash's page lists live cameras only), so use the top-bar button.
"Freeze" falls back to netra-ask's newest preview and shows an amber "N min old" warning. Right now that preview is from 14:53 (the indoor room).
**Restart netra-edge@jetson-c920 + netra-edge-serve before William freezes**, or he calibrates on a stale picture.

## What's built (branch hack-calib, pushed)
- hackdash/calib.py, the router at /hack/api/calib/*:
  - Proxies netra-ask's existing sites / cameras / frame / project routes, passing the operator's own Cookie / Authorization. netra-ask's audit names the caller (seen: hack_launch rows 247-253).
  - Draft fit with netra-ask's own ask/camgeo.py, loaded by path from /opt/netra/netra-ask; no DB. It reproduces camera-1-5621's stored fit exactly: pose, 15.5 px, LOO 6.59/21.7 m.
  - Frozen frames are held in memory until Save. Save = multipart frame upload, then PATCH points + refit.
  - /people projects the live boxes' foot points with the SAVED calibration.
- hackdash/static/calib.{js,css} (copied and adapted from sites.js, MapLibre 4.7.1 + Esri). It does all of these:
  - freeze;
  - frame↔map pairs, with re-placing the old points after a re-freeze;
  - a live draft fit showing LOO m, per-point px/m/checked, at_limit and >15 px warnings;
  - camera drag, plus a heading handle and hand pose when there are fewer than 2 pairs;
  - Save / Discard;
  - green live-people dots after a save;
  - Site setup tab: draw / edit (drag; double-click deletes a corner) / clear the boundary, set the site centre;
  - "Add camera" from the netra-ask pipeline camera list (or still only), with a warning when the feed already has a calibrated record (netra-ask's newest one wins).
- requirements.txt: + numpy==2.5.3, the same version as netra-ask's venv. Already pip-installed on the droplet by install.sh.

### hack.js / app.py lines I touched (for the dash agent)
- app.py: the ROUTERS line only, adding "calib": "hackdash.calib".
- hack.js renderWall: 3 lines after `t.onclick = () => openCamera(c.camera_id);`, which append a "Calibrate" chip to `.tchips`.
- hack.js: before the "the open camera, live (centre)" section, an `openCalib(cam, tab)` lazy loader (5 lines) plus one line adding a "Calibrate / site setup" button after `#topbar .grow`.

## Tests (run, real outputs)
- `python3 -m pytest -q tests`: 22 passed. That includes tests/test_calib.py: the fit recovers a known camera, a mis-click shows in LOO, under 2 pairs gives no fit, bad drafts get 400, frozen frames are bounded, only auth headers are forwarded.
- tools/calib_roundtrip.py on the deployed API, on a THROWAWAY site + still-only camera. Every step PASS:
  - create site and camera, freeze a real jetson-c920 frame, draft fit;
  - save (frame upload, then PATCH); netra-ask's stored fit == the draft; the pairs persist on re-read;
  - frame.jpg is served back; /project of pair 1 lands 0.05 m from its map point (= per_point);
  - boundary saved; camera and site deleted, the site now 404s;
  - camera-1-5621 untouched (updated_at 2026-10-21T22:14:07).
- tools/calib_shots.js (Playwright, real UI):
  - A: production, read only. Site tab; the camera with its saved frame, pairs and fit; recalibration as a draft (re-freeze, re-place 4 points), then Discard → back to 9 saved pairs.
  - B: throwaway site via the UI. Add camera by clicking the map, freeze, click 7 frame/map pairs, draft LOO 11.27 m, Save → netra-ask holds the same LOO, then deleted.
  - Production camera and boundary untouched.
- Screenshots: plans/calib-site.png, calib-camera.png, calib-recal.png, calib-draft.png, calib-saved.png.

## Deploy
- Deployed with deploy/install.sh from a local merge of hack-calib + origin/hack-dash + origin/main. dash had deployed an unmerged hack.js at 21:50, and a plain hack-calib deploy would have reverted it.
- The manager should merge hack-calib (and hack-dash) to main.
- Health: routers live=ok, launch=ok, calib=ok.

## Notes
- The current camera-1-5621 fit is poor (15.5 px rms, LOO 6.6 m median, 21.7 m worst; pairs 2-4 are far off). The screen says so honestly.
- Not verified: the green live-people dots with real people, because the edge is down. The /people code path is exercised only on a still-only record ("no live feed").
