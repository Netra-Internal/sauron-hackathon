WORKING: PTZ + Day/Night are LIVE on /hack/ and tested on the real Axis — MANAGER: please merge hack-launch @ f9261ee into main (it already contains origin/main fec8f4d). Browser latency check + screenshot in progress.

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
