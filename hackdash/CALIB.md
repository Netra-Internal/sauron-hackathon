# Calibrate (hackdash/calib.py, static/calib.{js,css})

Camera calibration and site setup inside /hack/, reusing netra-ask's Sites workflow.
It writes nothing of its own to the DB except pan/tilt/zoom on save.

- **Backend** `hackdash/calib.py`, mounted at `/hack/api/calib`.
  - Proxies netra-ask's site, camera, frame and project routes, forwarding only the operator's Cookie/Authorization.
  - Freezes frames from three sources:
    - the edge ring;
    - the netra-ask preview, as a fallback;
    - for PTZ cameras, the camera's own snapshot. It reads the position before and after and gives 409 if the camera moved. **It never moves the camera.**
  - The draft fit uses netra-ask's own `ask/camgeo.py`, loaded from `ASK_DIR` (default `/opt/netra/netra-ask`).
    - The camera position is fitted from several starting points, so a camera left at the site centre still fits.
    - For a PTZ camera, the lens width (hfov) starts from `ptz_zoomcal.json`.
  - Frozen frames and each user's last draft are kept in `$HACK_STATE/calib` (default `/var/lib/sauron-hack/calib`).
- **Frontend** `static/calib.js`: a full-screen overlay opened from the "Calibrate" chip on each tile, or from "Calibrate / site setup" in the top bar.
  - *Camera tab:* freeze a frame, pair frame clicks with map clicks, see the live fit with leave-one-out error, drag to refit, Save. Live person dots appear after save.
  - *Site setup tab:* draw the boundary, add a camera from the live feeds, remove a camera (with a confirm).
- **Wiring:** one line in `app.py` (`"calib": "hackdash.calib"`) and the `openCalib` hook in `static/hack.js`.
- **Deploy:** `deploy/install.sh` (shared). Needs `numpy` (in `requirements.txt`) and a netra-ask checkout at `ASK_DIR`. No extra env vars or secrets.
- **Tests:**
  - `pytest tests/test_calib.py` (needs a netra-ask checkout).
  - `tools/calib_roundtrip.py` is an API round trip on a throwaway site.
  - `tools/calib_shots.js` and `tools/calib_sitesetup_check.js` are Playwright checks: production is read-only and edits go to a throwaway site.
  - The tests take their credentials from `~/.config/netra/hack-launch.env`; see `tools/hack-launch.env.example`.
  - None of them sends a PTZ command.
- **Screenshots:** `plans/calib-*.png`.
