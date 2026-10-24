DONE: Sauron hackathon deck (11 slides, claude.ai Slides artifact, private, not shared): https://claude.ai/artifact/DYN11dp3UtpFUi8ic2Pn7n

## What's in it
1 cover (SAURON — sees, judges, sends a drone) · 2 problem · 3 what we built today (6-step chain) · 4 architecture (camera → Jetson capture → RunPod A5000 $0.27/h → droplet → /hack/ + droplink; edge→cloud cutover 22:19 UTC)
5 live /hack/ screenshot (plans/dash-live.png, 4:25 PM) · 6 real crime clips (3 stills + table) · 7 judge: facts → policy → verdict (catalytic still)
8 person → coordinate (plans/calib-camera.png, ±6.6 m LOO median, worst 21.7 m, test rig) · 9 measured numbers · 10 what's next · 11 close (team: Pranay CEO, Landon CTO, William COO)
Speaker notes on every slide. Look: near-black, one ember accent (#FF6A1A), Space Grotesk + IBM Plex Mono. Downloads as .pptx / PDF from the page.

## Numbers and where they come from
- crime: ~/sauron-data/crimevid/out/*/timeline.json. fence-climb +3.5 s, bike-lock +5.5 s, catalytic +11.5 s.
  ⚠ The brief said bike lock +3.5 s; the rendered timeline (and status/crimevid.md) say +5.5 s, so the deck says +5.5 s.
  Gaps stated on the slide: atm-rip unfinished, car-breakin and normal clips not scored (no false-alarm rate), 0 police in these 3.
- launch: status/launch.md (click → droplink 2.78 s, click → netra-ask 0.79 s, abort ordering end → closed → abort).
- PTZ ~0.5 s median: status/ptz.md. Pod 5 fps / 40-43 ms (Axis), 34-46 ms vs Jetson 75-86 ms, HLS cold start 0.78-1.57 s: status/cloud.md.
- Box lag 2.9-6.4 s: status/boxes.md. Calibration: status/calib.md + calib-camera.png.

## Not done / notes
- Not visually checked in the renderer (the Slides type says not to verify unless asked); open the link and skim for overflow.
- Only read files; no camera, droplet or other agents' files touched.
- William must share it from the page's Share menu before anyone else can open it.
