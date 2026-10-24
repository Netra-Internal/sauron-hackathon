DONE: Non-live cameras are hidden everywhere (wall, top-bar count, Move-camera buttons, camera auto-pick, calib feed pickers); deployed from hack-dash and pushed — MANAGER: please merge hack-dash into main now.

- Branch hack-dash: daf96d5 (code; contains origin/main at deploy time) + screenshot commit, pushed. Deployed with deploy/install.sh from daf96d5.
- Verified live in Playwright (right now axis-q6215 is the only live camera; jetson-c920 and node3-c920 are not live):
  - top bar pill "1 camera live" (was "N/M cameras live"); none live -> "No camera live"
  - wall: "Cameras · 1 live", 1 tile; none live -> "No camera is live right now."
  - "Move <cam>" top-bar buttons only for PTZ cameras that are live (redrawn when that set changes)
  - #cam= hash / single-live auto-open only picks a live camera
  - calib.js: "Freeze from…" and "Add camera" feed pickers list only live feeds (filtered by the page's S.cams)
- Left as is on purpose: calib's "camera record" picker still lists saved site records (e.g. "Camera 1 · jetson-c920") — those are calibrations, not feeds; hiding them would hide saved work.
- Screenshot: plans/dash-live.png.
- Still open for the manager (from before): jetson-c920 repointed into the lab (outdoor calibration invalid), lag 17–23 s, duplicate boxes per person.
