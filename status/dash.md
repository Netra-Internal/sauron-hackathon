DONE: dash sent NO PTZ commands in the last 15 min (or ever) and has no PTZ test running; live-video change is deployed (hack-dash 3eff3cb, pushed) — MANAGER: please merge hack-dash into main.

PTZ (William's hard rule acknowledged: never move the Axis; read-only position queries only):
- Commands I sent to the Axis in the last 15 min: none. I have never sent move/stop/center/home/preset/areazoom/daynight.
- My Playwright runs in that window only loaded /hack/, waited/evaluated, fetched the HLS manifest and took screenshots. No clicks (the earlier click at ~22:55 was the Calibrate chip on the camera card, which opens the map calibration screen and does not touch the camera).
- My page code sends no PTZ command on its own: hack.js only calls GET /hack/api/ptz (read-only reachability = GET /position). The POST commands live in ptz.js and run only after a person clicks "Move axis-q6215" and uses its controls.
- Nothing of mine is running that could move it (the only local processes are the shared Playwright MCP servers, idle; my Playwright session is disconnected).
- FYI from the sauron-hack journal (read-only check): POST /hack/api/ptz/axis-q6215/{move,stop,daynight} came in at 22:55:46–22:56:12, 22:59:44–22:59:50 and 23:04:27–23:04:33, all from 69.196.39.231 (the lab's shared public IP, via the tunnel). Not from me; last one 23:04:33, none since as of my check.

Live video (previous task): open camera plays /hack/stream/<cam>/ (WHEP 404 -> LL-HLS via hls.js 1.5.20), playing ~3 s after load on axis-q6215; ring stills only as fallback. Boxes from /live are ~14–25 s older than the video.
