# Brief: crimevid — annotated videos proving Sauron catches real criminals (hackathon repo)
William: "find videos of criminals online and show that we can catch them with our setup. I think we use jev for this?
… it should be a video annotated with our AI models." ASAP — first finished video within ~45 min, more after.

## What exists (reuse, don't rebuild)
- The real judge = netra-ask dispatch: Jev strip judge (ask/dispatch/judge.py: 4-frame strip every 2 s → facts weapon/
  violence/menace/break_in/theft/tampering/trespass/vandalism/normal + ONE subject box) → Policy (E, verdict
  none/watch/deploy/urgent) → caption (caption.py) → subject snapped to a YOLO person (subject.py). Docs: docs/dispatch.md.
- Offline harness: netra-ask tools/dispatch-eval/ (clipcheck runs, demo/run_demo.py + README — it already built a 6-clip
  demo page https://claude.ai/artifact/DqVaeP1fFDkhkZrt8SUCXb). ask/dispatch/clipcheck.py = pluggable judge over clips.
- Clips already on disk: ~/sauron-data/dispatch-clips/*.mp4 (11 YouTube outdoor crimes, clips.csv, event-labels.json).
  Labelled corpus notes in memory: break-in is the priority (burglary, forced doors/windows/gates, lock cutting, fence
  climbing, bike/car tampering); shoplifting out of headlines.
- Jev key ~/.config/netra/typesafe.env. yt-dlp works (needs ejs+node+DEVNULL stdin).

## Deliverable
1. 3-6 clips of REAL crimes from real fixed CCTV-style cameras (YouTube/news/police releases; prefer outdoor break-ins,
   bike/car theft, forced entry), plus 1-2 benign clips to show it stays quiet. Reuse the on-disk ones first, fetch new
   ones only if they're better. Keep a sources table (URL, what happens, at what second).
2. Run OUR models on each: YOLO person boxes + track ids every frame (same weights as the edge: yolo11s), and the real
   Jev judge with the DEPLOYED policy at its real cadence (strip every 2 s). No hand-placed boxes, no edited scores.
3. Render an annotated MP4 per clip: person boxes with ids; Jev's subject highlighted; a side/bottom HUD with the live
   facts bars, E, verdict (none → watch → deploy/urgent) and Jev's caption; a clear "SAURON: DEPLOY DRONE → <subject>"
   moment at the exact time the policy fired; a timeline strip under the video marking the true event time vs the
   deploy time (= detection latency). Benign clips show it never deploys.
4. A page (Artifact, HTML) with the videos embedded + per-clip result table (caught? seconds after the event started,
   false deploys) and an honest summary (misses included). Videos: H.264, ≤ 15 MB each (artifact limit); publish them
   as the page's files. Also commit the renderer + run scripts to this repo under crimevid/ (not the videos; put the
   videos in R2 netra-lake _work/hackathon/crimevid/).

## Rules
- Jev: OK up to $15 total without asking (estimate first; $0.042/M input tokens, ~$0.00037 per strip).
- Laptop has 16 GB shared with 6 agents: ONE CPU model job at a time, `free -g` first, run YOLO sequentially. If it's too
  slow, you may run YOLO on a RunPod pod ≤ $0.60/h that self-exits — NOT the production edge pod <pod-id>.
- Never post these as live incidents (mode=replay only, never forwarded; better: don't touch the droplet at all).
- Honest: if Jev misses a clip, show the miss. Real numbers only.
Done = artifact link + status/crimevid.md DONE with the table. Post the first finished video path in status as soon as it exists.
