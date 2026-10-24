DONE: PTZ writes are now OPERATOR-ONLY (deployed 23:1x UTC): hack_launch and every non-William account get 403 "PTZ is operator-only"; PTZ lock toggle in the UI (default OFF). Tested the 403 path only; ZERO commands reached the camera. MANAGER: merge hack-launch @ 3024292 (= main f01a741 + 1 commit).

## Guard (hackdash/ptz.py, deployed; sha256 of ptz.py / ptz.js / ptz.css on the droplet == 3024292)
- Every camera write goes through _cmd() -> write_guard() BEFORE anything reaches ptzd: move, stop, center (areazoom),
  home, home/save (preset), daynight, and the lock itself. Allowed: users in PTZ_OPERATORS (default "william"). Denied
  always: PTZ_NEVER (default "hack_launch"), even if listed as an operator. Everyone else (landon, pranay, tanay, any test
  account) gets 403 too. Reads stay open: /ptz, /state, /snapshot.jpg, GET /daynight.
- PTZ lock: POST /ptz/{cam}/lock {locked}, operators only. While ON, every write is 403 "PTZ is locked (by ..)" for everyone,
  William included. Default OFF. Stored in /var/lib/sauron-hack/ptz-lock.json (survives restarts).
- /state now returns can_write, locked and user. The Move camera screen disables every control, key and click-on-picture
  when the user can't write or the lock is on, and says why. The "PTZ lock: OFF/ON" button is in the top bar of that screen.
- Tests: tests/test_ptz_guard.py (7): non-operators x 4 users x 7 writes -> 403 and the ptzd stub is never called;
  hack_launch denied even if listed; reads open for hack_launch; operator write ok; lock blocks every write, then unlock.
  Suite 36 passed.
- Live 403 check on the droplet as hack_launch (no camera command possible): GET /state -> can_write false, locked null;
  POST lock / move / stop / center / home / home/save / daynight -> all 403 "PTZ is operator-only"; sauron-hack logged
  7 "write refused"; ptzd's command log stayed at 236 lines before and after (nothing reached the camera).
- tools/ptz_test.py and tools/ptz_shots.js now exit at once unless PTZ_TEST_WILLIAM_ASKED=1 (and with hack_launch they'd 403 anyway).

## Also in this deploy (written before the stop, not run against the camera since)
- Latency fix: the Jetson link is a Tailscale relay (DERP lax, no direct path) carrying only ~65-130 KB/s. Two pages
  pulling 58 KB snapshots pushed command latency to 2-6 s. Now: snapshots are 640x360 at compression 75 (~28 KB), at most
  1 camera fetch per 0.8 s shared by all viewers, and they go over their own tunnel (ptzd-tunnel-img, droplet :8531), so
  commands don't queue behind picture bytes. The page never queues a /move behind one still in flight.
  NOT re-measured on the camera (rule). Idle read latency after the change: droplet -> ptzd /position ~150 ms;
  in-browser /state median 109 ms (measured before the load spike).


## Camera commands I sent (Manager asked: last 15 min; I list everything this afternoon to be complete). Times UTC.
Attribution comes from my own session record matched to ptzd's log. The sauron-hack log can't separate senders: every request
arrives from the Cloudflare egress 69.196.39.231, mine and William's alike.
- 22:49:28-22:49:49 tools/ptz_test.py #1: Save as Home (hack-home, via ptz.cgi = no-op), pan 1.5 s @0.5, tilt 1.5 s @0.5,
  zoom-in 1.5 s, one deadman move pan -0.3, centre (areazoom x=960/1280), Go Home (failed, 502).
- ~22:50 direct VAPIX from the Jetson: absolute move pan=0.01 tilt=-44.98 zoom=1 (back to the start pose),
  ptzconfig.cgi setserverpresetname=hack-home, ptz.cgi gotoserverpresetname=hack-home.
- 22:51:36-22:52:02 tools/ptz_test.py #2: Save as Home (hack-home = pan 0 / tilt -45 / zoom 1), the same pan/tilt/zoom/
  deadman/centre sequence, Go Home (camera back at pan 0 / tilt -45 / zoom 1).
- 22:54:08 POST daynight mode=day (API). ~22:57 direct VAPIX ptz.cgi ircutfilter=on (Day). ~23:00 POST daynight night,
  then day. The camera is in DAY now.
- 22:58:5x tools/ptz_shots.js (Playwright): ArrowRight held 0.6 s, then ArrowLeft 0.6 s, speed 0.15, then the stops.
  Pan went -168.58 -> -156.38 -> -148.22 (tilt -8.78, zoom 615 unchanged).
  ⚠️ -168.58 / -8.78 / 615 was probably William's calibration spot. My nudge moved it off.
- 23:03:2x tools/ptz_shots.js again: the same 0.6 s right + 0.6 s left nudge. Pan read -157.21 then -174.62. William's page
  was also open, so the readings are mixed.
- Two other ptz_shots runs (22:58:3x, 23:02:2x) failed before sending any move. The 23:07 run was rejected and never ran.
- Not mine: the 22:54-22:55 page moves at speed 50 (the old UI default), i.e. William driving the page.
- Position NOW (read-only query, 23:07:45): pan 176.86, tilt -8.79, zoom 615. That is NOT -168.58: the pan is about 14.3 deg
  off the pose before my 22:58 nudge (wrapping through 180). I will NOT move it back. William decides.
- I also overwrote the hack-home preset twice (22:49, 22:51) and the camera's IR mode (now Day).


## Deployed (22:48–23:0x UTC) — what is where
- Jetson (jetson-cloud): ptzd.service (new unit, DynamicUser, 127.0.0.1:8530), /opt/netra/ptzd/ptzd.py, /etc/ptzd.env (root 600:
  creds from ~/.config/netra/axis-q6215.env + token). Camera 192.168.0.90 on enP8p1s0. No other Jetson unit touched.
- Droplet: ptzd-tunnel.service (new, ssh -L 127.0.0.1:8530 -> netra@100.102.178.107, same pattern as netra-ask-edge-tunnel);
  /etc/ptzd-token (root:netra 640).
- sauron-hack: I copied ONLY hackdash/ptz.py, ptz_zoomcal.json, static/ptz.{js,css} and changed the one ROUTERS line in the
  DEPLOYED app.py (the deployed tree had other agents' work, e.g. relay.py, so no full rsync). Backup /root/sauron-hack-bak-ptz-224841.
  Dash's 22:54 deploy from main put back an OLD ptz.css (no Day/Night styles); I re-copied mine. Now the deployed
  ptz.py / ptz.js / ptz.css / hack.js / app.py == hack-launch f9261ee (sha256 checked). Merge f9261ee so the next deploy keeps them.

## Real-camera test (tools/ptz_test.py, laptop -> https://internal.netralabs.net/hack/api, service account hack_launch)
    15:51:35 start {'pan': 0.0, 'tilt': -44.97, 'zoom': 1.0}
    15:51:36 saved start pose as Home (hack-home)
    15:51:40 pan right 1.5 s @0.5 -> {'pan': 136.74, 'tilt': -44.98, 'zoom': 1.0} dpan 136.74
    15:51:44 tilt up 1.5 s @0.5 -> {'pan': 136.83, 'tilt': 61.27, 'zoom': 1.0} dtilt 106.25
    15:51:48 zoom in 1.5 s -> {'pan': 136.83, 'tilt': 61.27, 'zoom': 1016.0} dzoom 1015 {'hfov_deg': 16.4, 'x': 3.73}
    15:51:53 deadman: one /move then nothing. pan at +0.0/+0.4 s: 133.15 124.77 | +1.8/+2.6 s (stopped?): 124.8 124.8 -> STOPPED
    15:51:57 click centre at x=0.75,y=0.5 -> {'pan': 132.83, 'tilt': 61.03, 'zoom': 1016.0} dpan 8.03
    15:51:57 snapshot 35179 bytes
    15:52:02 Go Home -> {'pan': 0.0, 'tilt': -44.97, 'zoom': 1.0} vs start {'pan': 0.0, 'tilt': -44.97, 'zoom': 1.0} ok
    
    latency (ms): laptop -> https /hack/api -> droplet -> tunnel -> Jetson ptzd -> camera, and the droplet->camera part
      /state       n= 12  median    504  p90    616  | droplet->camera median    84
      /home/save   n=  1  median    649  p90    649  | droplet->camera median   120
      /move        n=  9  median    501  p90    731  | droplet->camera median    97
      /stop        n=  3  median    496  p90    600  | droplet->camera median    93
      /center      n=  1  median    502  p90    502  | droplet->camera median   131
      /snapshot.jpg n=  1  median    862  p90    862
      /home        n=  1  median    518  p90    518  | droplet->camera median   114

Latency, per command:
- page -> camera answered, from the laptop over https: median ~500 ms (p90 ~600-730). The script opens a new TLS
  connection per call; a browser keeps it open (being measured).
- droplet -> tunnel -> Jetson ptzd -> camera: median ~95 ms (move 97, stop 93, state 84).
- Jetson ptzd -> camera VAPIX: 7-20 ms.
- Deadman verified on the real camera: one /move and no refresh -> camera stopped by itself (pan frozen at 124.8).

## Fixes found on the real camera
- Presets: setserverpresetname on ptz.cgi answers OK but creates nothing; it must go to ptzconfig.cgi (fixed). "hack-home" =
  pan 0.00 / tilt -44.97 / zoom 1 (the pose the camera was in when I started). Go Home verified back to it.
- Speed: 0.5 = ~90 deg/s pan (136 deg in 1.5 s) -> UI default speed 0.15, slider 0.02-1.
- Deadman 0.8 -> 1.2 s: over the internet the refreshes sometimes came >0.8 s apart and the camera paused mid-hold.

## Day / Night (William)
- This PTZ firmware has no ImageSource.DayNight param (Properties.ImageSource.DayNight=no); the IR-cut is ptz.cgi
  ircutfilter=on|off|auto. The IR LEDs (lightcontrol led0) have synchronizeDayNightMode=true, so they follow it.
- The camera does NOT report the live filter state (PTZ.Various.V1.IrCutFilter stays "off" whatever is set), so the UI shows
  the mode last set through ptzd plus "Picture now: colour / mono (IR)" measured from a snapshot (HSV saturation).
- Verified: Night -> picture mono (IR), saturation 0.0; Day -> colour, saturation 50.3. The camera is LEFT IN DAY.
- UI: Day / Night (IR) / Auto buttons under the zoom buttons in the Move camera screen.

## Note
- William is already using it (stops/snapshots from 69.196.39.231 in the sauron-hack log; camera pose changed).
- The old autonomous tracker netra-ptz-axis on the laptop WSL is still running, but it can't reach the camera (the camera
  is on the Jetson now), so no conflict while it stays there.
