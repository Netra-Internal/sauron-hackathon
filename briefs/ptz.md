# Brief: ptz — manual pan/tilt/zoom for the Axis from /hack/ (agent `launch` takes this)
William: "Axis camera is now connected — get the AI to use that. I would like to control it manually to make it look at
the right place with the right zoom."
- Camera: AXIS Q6215-LE PTZ (30x), creds ~/.config/netra/axis-q6215.env (PTZ_CAM_HOST/USER/PASS, was <camera-ip>),
  VAPIX: /axis-cgi/com/ptz.cgi (continuouspantiltmove=x,y / continuouszoommove=z / move=stop / rzoom / areazoom /
  query=position / gotoserverpresetname / setserverpresetname), digest auth. Prior integration: ~/netra/netra-ptz-wt-axis
  (rig axis, hardware.py) + memory netra-axis-q6215-connection (zoom cal tele 2.88°).
- WHERE it is plugged in is being confirmed with William (not on the Jetson's wired port, not on the laptop right now).
  Design for "camera next to some box we can SSH to": a tiny `ptzd` HTTP service on that box (localhost-only, VAPIX
  proxy with a fixed allowlist of commands) reached from the droplet through the existing SSH/tunnel pattern, or
  hackdash running `ssh <box> curl --digest …` per command if that's fast enough (<500 ms). Pick the fastest robust one.
- UI (hackdash, coordinate with agent dash, hack.js): on the open camera view for axis-q6215: hold-to-move arrow pad
  (continuous pan/tilt while held, stop on release), zoom in/out (hold) + zoom level readout, click-on-frame = center
  there (areazoom), "Save as Home" + "Go Home" (server preset), live position readout. Keyboard: arrows + +/-.
- Tell the operator honestly that moving the camera invalidates its calibration (show a warning chip when the position
  differs from the calibrated preset).
- Code in this repo: hackdash/ptz.py (router), ptzd/ (if needed), UI in hack.js (minimal, tell dash which lines).
- Test against the REAL camera once it is reachable; until then build + unit-test, no fake camera in the product.
Done = moving the real Axis from https://internal.netralabs.net/hack/ with measured command latency; status/ptz.md DONE.
