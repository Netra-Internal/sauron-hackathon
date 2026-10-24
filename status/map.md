DONE: click-to-dispatch map + plan written (~/hack-2026-10-24/plans/click-to-dispatch.md); UI section is now William's "current Sites monitor + Send drone on a person box", with a screenshot and an annotated sketch.

Files:
- plans/click-to-dispatch.md: the plan (§2 = the monitor addition, exact monitor.js lines and the POST body)
- plans/monitor-now.png: Playwright screenshot of /ask/sites, UCSD DIB site, 14:13 PDT
- plans/send-drone-sketch.png: annotated screenshot (A) + the real Camera 1 lightbox with the Send drone box sketched in (B, labelled SKETCH)

Key facts (measured today, read-only):
- Only jetson-c920 (the desk rig, outdoor DIB window view) is both live and calibrated. axis-q6215 has had 0 frames for days (RTSP connection refused). node3 is offline. -> WILLIAM DECIDES: demo on the test rig, or no live demo.
- The monitor has NO person boxes today: camera tiles and the lightbox show preview.jpg (~30 s old); people are map dots only. No Abort button for incidents in the UI (API only).
- Droplet runs Oct 23 code: no drone/commands/positions modules or their tables; DISPATCH_WEBHOOK/SECRET/ASK_DRONE_TOKEN unset; 0 incidents ever. Jetson code is Oct 23 too; watcher stopped since Oct 22.
- The Jetson ring /frame through the droplet tunnel takes ~1 s per frame -> monitor boxes ~1 fps, ~2.5-3 s behind live.
- sauron_link (PR #21) launches on signed live deploy/urgent located incidents; it does not apply positions yet (flies to the launch point only); it listens on 127.0.0.1 by default.

Proposed parallel items: W1 camera-boxes API, W2 operator launch (ask/dispatch/operator.py), W3 monitor.js addition, W4 deploy (manager), W5 Pranay receiver.
