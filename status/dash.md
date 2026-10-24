DONE: https://internal.netralabs.net/hack/ shows the real jetson-c920 ring frame with real edge person boxes, chips, Send drone, incidents + droplink messages; screenshot plans/dash-live.png.

Branch hack-dash @ 0eef97a (pushed; contains origin/main 555872e incl. launch's abort-ordering fix d85fee4).
Deployed from that merged tree with deploy/install.sh at 21:41 UTC; deployed hackdash/launch.py md5 == origin/main's.
/hack/api/health (signed in): routers live=ok, launch=ok, auth=internal login.

Screenshot (plans/dash-live.png, 14:40 PDT, real data, nothing staged): C920 DIB window frame, 1 person in view,
box + chip "#9310 0.28 · —" + Send drone; "≈3.8 s behind live", "judge off", "test rig"; left pane = 2 real operator
incidents launched earlier by the manager/launch tests (closed, dismissed; forwarded 6/6 · 200; drone got 8 / 19) and
the droplink messages (signature ok, abort/end/incident summaries). Measured lag in the page: 3.3-6.0 s.

Fixed from real data:
- t_ns (~1.8e18) lost precision as a JS number, so /launch's exact obs match (launch.obs_at) silently fell back to the
  newest box. The page now keeps t_ns as the raw digit string and posts it unquoted (verified: t_ns == frame_url's t).
- /incidents shape: forwarded is {attempts, delivered, last{...}}, plus commands[], evidence{"frame.jpg","crop.jpg"},
  edge_track. The panel crashed on it (`.at is not a function`); it now shows delivered/attempts, last status, commands,
  evidence crop/frame, the person id from edge_track. "operator_launch" title -> "Operator launch".
- An operator-launch label was shown as "scene facts · Jev pointed at this person"; it no longer claims a judge verdict.
- Not-live cameras showed days-old previews (node3 indoor desk); they now show "Not live: no current picture". Live first.
- Drone messages: one-line summary (status · verdict · lat,lon ±m / command · reason), signed body folded.
- Asset URLs are versioned by mtime (a redeploy was hidden by the browser cache).
- install.sh now REFUSES a tree that doesn't contain origin/main or has uncommitted hackdash/deploy changes, and waits
  for the app to answer after restart.

Not done / notes:
- I did not press Send drone myself (the manager/launch tests already exercised launch -> droplink -> abort -> end;
  visible in the screenshot). The confirm UI is: Send drone -> "Send drone to #id? Yes / Cancel".
- Map with fused people (nice-to-have) not built.
- After /map/login you land on /map, not /hack/ (netra-internal common.auth NEXT_OK lacks "/hack").
- People on this view are 10-50 px tall in the field; boxes are small at 1280 px display.
