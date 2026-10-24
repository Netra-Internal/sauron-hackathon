BLOCKED: PTZ control is built and unit-tested (branch hack-launch @ 41bc4b0) but the Axis is not reachable from any box I can reach. I need to know which box it's plugged into, and its IP if it isn't 192.168.0.90.

## Where I looked (read-only, 21:5x UTC)
- laptop WSL: no 192.168.0.x link (the ASIX USB adapter isn't up); ping 192.168.0.90 fails.
- jetson-cloud: no route to it; netra-edge@axis-q6215 inactive.
- netra-node (tailnet): no route. netra-node4 / pi-drone: no SSH from here (host key). toaster: SSH times out.

## ⚠️ Conflict to resolve before the camera comes back (William / manager decide)
The old autonomous Axis tracker is STILL RUNNING on the laptop as WSL user units: netra-ptz-axis.service (node_main --rig axis),
netra-cv-tunnel.service, and netra-ptz-watch.timer (it restarts the node when it looks idle). It retries the camera every few s.
If the Axis is plugged into the laptop again, that tracker will patrol and zoom it by itself and fight manual control.
Stop it with: `systemctl --user stop netra-ptz-watch.timer netra-ptz-axis` (or `deploy/axis/wsl/install.sh --remove` in
~/netra/netra-ptz-wt-axis-v7). I have not touched it.

## Built
- ptzd/ptzd.py: stdlib service on the box next to the camera, 127.0.0.1:8530, bearer token. It speaks VAPIX ptz.cgi with
  digest auth and offers only a fixed command set: position, continuous move (speeds clamped to ±100), stop, areazoom centre,
  goto/save of the preset "hack-home" only, image.cgi snapshot at 3 allowed resolutions. No raw VAPIX passthrough.
  DEADMAN: any continuous move not refreshed within 0.8 s is stopped, so a lost mouse-up or a dropped tunnel can't leave
  the camera turning.
- ptzd/install.sh BOX forward|reverse: installs ptzd (systemd, DynamicUser, /etc/ptzd.env root 600 with the creds from
  ~/.config/netra/axis-q6215.env) plus the tunnel. In forward mode the droplet dials the box (like netra-ask-edge-tunnel);
  in reverse mode the box dials the droplet with its own key, authorised for that one port forward only. Token in droplet
  /etc/ptzd-token (root:netra 640).
- hackdash/ptz.py (/hack/api/ptz...): list, state (pose, zoom × and HFOV from the measured Oct 12 zoom curve, calibration
  check), move (-1..1), stop, center (click, optional zoom), home, home/save, snapshot.jpg. It reports latency per command.
  Calibration check: netra-ask's site_cameras frame.ptz pose for the camera. Axis has NO calibration row today, so the chip
  says "Not calibrated". If it gets one, the chip goes red "Moved off calibration: map positions wrong" when the pose
  differs by more than 0.5° or 50 zoom steps.
- UI hackdash/static/ptz.{js,css}: full-screen "Move camera" screen. Live camera JPEG; click = centre, shift-click =
  centre + 2× zoom. Hold-to-move pad and zoom in/out (re-sent every 250 ms while held, stop on release / blur / tab
  hidden), arrow keys and + / −, speed slider, Go Home / Save as Home, pose + zoom readout, latency readout (median).
- Tests: tests/test_ptz.py (ptzd against a recording ptz.cgi stub: auth, clamping, deadman, refresh, allowlist; zoom
  curve; calibration check). Suite: 27 passed.

## For dash / manager: lines touched outside my files
- hackdash/app.py line 39: added `"ptz": "hackdash.ptz"` to ROUTERS.
- hackdash/static/hack.js: renderWall, after the Calibrate chip (+5 lines): a "Move camera" chip on PTZ cameras' tiles.
  After the "Calibrate / site setup" topbar line (+11 lines): openPtz() loader, then a fetch of /api/ptz that adds a
  "Move <cam>" top-bar button per PTZ camera, because the Axis isn't on the wall while it isn't live.
- Not deployed: it goes live with the next sauron-hack deploy (until ptzd is installed, /ptz reports reachable:false).

## Next, once I know the box
`bash ptzd/install.sh <box> forward|reverse ...`, then move the real Axis from https://internal.netralabs.net/hack/ and
measure command latency (page→camera and droplet→camera), screenshot, DONE.
