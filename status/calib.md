DONE (23:3x UTC): calibration fix DEPLOYED (hack-calib 0871f90, deploy e68ca78 = hack-calib + origin/hack-dash + origin/main). Tell William: reload /hack/, then freeze a new frame and re-place his points (steps below). No PTZ command sent.

## What was wrong (ours), reproduced on real data
- His Axis record was left at the SITE CENTRE (where "Add camera" put it), ~300 m from the DIB window, and the fit only moves the
  camera with 6+ pairs AND a box ticked. Real camera-1-5621 pairs fitted from the site centre: 226 px rms, LOO 136 m, height pinned
  at the 200 m limit = "huge error / wrong direction". (camgeo already searches yaw every 10°: the yaw was not the problem.)
- Fixed: a multi-start position fit. With 6+ pairs, a camera that was never placed is found from the pairs (auto-ticked).
  It tries starts in a ring around the pairs at 2 heights, keeps the best, then runs netra-ask's own fit + leave-one-out from there.
  Live: the same 9 pairs from the site centre -> 32.8794801,-117.2322504 at 13.5 m, yaw 70.3 = exactly camera-1-5621's surveyed pose,
  15.5 px rms, LOO 7.2 m median; ~8 s per fit. Save sends that position, and netra-ask's refit converges to the same pose.
- New red step "Camera not placed" with a "Place camera" button (next map click moves it), or drag the blue marker.
- hfov: a PTZ freeze now seeds the lens width from the zoom curve (hackdash/ptz_zoomcal.json) at the frozen zoom. netra-ask's
  camgeo bounds hfov at 5-150° and I did NOT widen them: netra-ask's refit on Save would clamp anyway, and netra-ask is not ours to edit.
  The curve hits 5° at about 12-13x zoom, so beyond that the screen warns "zoom out a bit". 2.6x = 23.5°: fine.
- Frame px: fine. The Axis freeze is the camera's own 1280x720 snapshot = its source size (scale 1). Pairs are in frozen px.
- I could NOT test on his actual 8 pairs: drafts lived only in his page and /fit bodies weren't logged. From now on the server
  keeps each operator's last draft (/var/lib/sauron-hack/calib/drafts.json; only my hack_launch test draft so far).
- Edge-serve /frame 500 for axis-q6215: the live tile / ring, not the calibrate freeze.

## Tell William (the camera moved, so: re-freeze + re-place)
1. BEFORE reloading, in his open page: tick/untick "Also fit the camera position" once. That sends his 8 map points to the server
   (his old page can't save drafts any other way). Then reload https://internal.netralabs.net/hack/ -> Calibrate / site setup -> Axis -> Calibrate.
2. Click "Restore my map points" (the 8 map points come back as white markers), then "Freeze a new frame" (the current zoomed view).
3. Click each white marker's spot in the new frame (the map pans to it; "Skip this one" if it's out of view).
4. With 6+ pairs the camera position is found automatically. Check that ±X m is small and no "checked" value is red, then Save.
   Save stores pan/tilt/zoom with the calibration. Afterwards "PTZ at calibrated view" shows; it turns red if the camera moves.
- If he skips step 1: he re-adds the pairs from scratch. Dragging the blue marker to the DIB window first gives a good start.

WORKING (23:15 UTC): cause of William's "calibration not working" FOUND (ours); fixing + deploying without losing his draft.

## Cause (read-only: netra-ask record + nginx log; no camera call, no write)
- Record axis-q6215-le-bench-ptz-c58f (created 23:08:41) sits at lat/lon 32.876307,-117.231613 = the SITE CENTRE. That is the default
  "Add camera" puts it at, ~300 m from the DIB building. Every /calib/fit (7 between 23:09:20 and 23:12:20, all 200) solves pose with the
  camera in the wrong place: the position is only fitted with 6+ pairs AND the "Also fit the camera position" box. So the residuals and LOO are huge.
  Secondary: with < 3 pairs hfov is held at the 60° default; the Axis at zoom 2.6x is ~23.5° (hackdash.ptz zoom curve). hfov bounds are 5-150°: fine.
- The frozen frame is right: POST /calib/freeze/axis-q6215 at 23:08:45 took the PTZ path (camera snapshot, 195 KB, 1280x720 = the source size),
  after his last move/stop at 23:08:20. The frame size is not mismatched: the fit runs in frozen-frame px (1280x720).
- The edge-serve /frame 500s for axis-q6215 come from the live tile / ring (hackdash.live). The calibrate freeze does not use them.
- Moves 23:08:15-23:08:32 (move/stop/home-save) came from William's own browser (cookie login), not from tests.
- William deleted camera-1-5621 himself at 23:07:56.
- His request bodies are not logged and his pairs live only in his page (0 saved), so I can't print his residuals.

## Fix (deploying)
1. After "Add camera", the screen asks him to click the map where it's mounted, plus a red "camera not placed" warning while it sits at the site centre.
   "Place camera" button = the next map click moves it.
2. A PTZ freeze seeds hfov from the camera's measured zoom curve.
3. Frozen frames are kept on disk, so a restart no longer loses a draft frame. His frozen frame (5f8019f08bd1d4fa) is carried over.

NEEDS-MANAGER: STOPPED on William's PTZ rule. I sent NO move/stop/center/home/preset/zoom/day-night command to the Axis, ever; no test of mine is running.

## PTZ commands audit (nginx access.log on the droplet, checked 23:07 UTC)
- My headless test runs hit the API at 22:02-22:13 UTC (calib_shots.js: jetson-c920 + throwaway sites only) and
  23:05:02-23:05:13 (calib_sitesetup_check.js: add + remove an UNCALIBRATED axis-q6215 record on the DIB site, no frame,
  no PTZ call: the calib.js deployed then had no PTZ code). Neither script has any PTZ command in it.
- My PTZ calls, all READ-ONLY: one curl each of GET /hack/api/ptz, GET /ptz/axis-q6215/state, GET /ptz/axis-q6215/snapshot.jpg (~22:55).
- tools/calib_ptz_check.js (freeze from the Axis = GET /position + GET /snapshot.jpg; it would also have OPENED the ptz.js widget,
  without pressing anything) was REJECTED before it ran. I won't run it; deleted.
- NOT mine: POST /ptz/axis-q6215/move + /stop as hack_launch at 22:56:12, 22:59:45-51 (8, from HeadlessChrome 155) and
  23:04:16-33 (8: 4 answered 502, then 4 OK). They fall outside my run windows. HeadlessChrome 155.0.8059.12 is the shared
  chromium-1247 build, also used by the Playwright MCP browser (pid 94968, profile mcp-claude-profile), which another agent
  holds (it refused me at 22:01). Most likely the launch agent testing ptz.js. I did NOT kill it: it isn't mine.

## PTZ in Calibrate: DEPLOYED (7a667ca, from hack-calib + origin/hack-dash + origin/main) but NOT tested end to end
- Freeze from a PTZ camera = GET /position, GET /snapshot.jpg, GET /position (refused if the pose changed). It sends NO command.
  Save writes that pan/tilt/zoom (+ hfov, zoom x) into site_cameras.frame.ptz, with an audit row naming the operator.
- The Calibrate screen polls GET /ptz/{cam}/state every 2 s (read only) for the chips "PTZ at calibrated view" /
  "moved off calibrated view" / "moved since freeze", and asks again before saving if the camera moved since the freeze.
- "Aim / zoom the camera" opens launch's ptz.js widget over Calibrate. That widget DOES send move/stop/center/home/day-night,
  and also on arrow keys and + / - while it is open: only William should use it.
- Unit tests: 29 passed. Never run: a freeze of the real Axis view through the UI. Only read-only GETs; want me to run it?
- Branch hack-calib (pushed) has the merged origin/main. Manager: merge hack-calib (deployed together with hack-dash's unmerged live video).

(earlier)
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
