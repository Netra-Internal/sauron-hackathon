# Brief: deck — Sauron hackathon slide deck
William: "make a slide deck for this. It should be designed around Sauron."
Build it as a claude.ai **Slides** Artifact (use your Artifact tool: action quickstart, intent "slides", then follow the type's
instructions; it downloads as .pptx/PDF). Share nothing; give the link in status/deck.md. Assume a hackathon demo audience,
8–12 slides, ~5 min talk. Visual identity designed around Sauron (the all-seeing watcher: dark, precise, one strong accent);
real screenshots, no stock art, no lorem, no invented numbers.

## Story (use what was actually built today; read the repo + status files for facts)
1. Sauron: autonomous site security — sees, judges, sends a drone. (Spec: Notion "Sauron — System Specification",
   "Product Design — Autonomous Site Security".)
2. Problem: guards/remote monitoring don't scale; response is slow.
3. What we built today (Oct 24): live camera feeds → person boxes → Sauron judge (Jev facts → policy → verdict) → person →
   map coordinate (calibrated camera, sitefuse) → one click (or autonomous) Send drone → signed launch + 1 Hz position stream.
4. Architecture diagram: camera (Axis PTZ / C920) → Jetson (capture only) → RunPod GPU pod (detection, A5000 $0.27/h) →
   droplet (Sites/dispatch, relay) → /hack/ dashboard + droplink (signed drone receiver). Edge→cloud move was today.
5. Live demo slide: screenshot of https://internal.netralabs.net/hack/ (plans/dash-live.png and newer; calib screenshots in
   ~/netra/sauron-hackathon-wt-calib/plans/calib-*.png).
6. Catching real crime: frames from crimevid renders (~/sauron-data/crimevid/out/*/annotated.mp4; extract stills with ffmpeg)
   — bike lock cut: deploy +3.5 s after crime start; catalytic: +11.5 s; results table from status/crimevid.md (only the
   numbers it reports; include misses honestly). Police get their own label.
7. Person → coordinate: calibration from frame↔map pairs, measured error (C920 fit ~7 m LOO; say test rig).
8. Measured numbers: click → signed launch in droplink 2.8 s; abort → end ordering; PTZ command ~0.5 s; pod detection rates.
   Source every number from status/*.md; don't round up.
9. What's next: drone integration (sauron_link / PX4), more cameras, site model, judge speed.
Team: Netra (William is COO, Pranay CEO, Landon CTO — never label William CEO).
Rules: don't touch the camera, the droplet services or other agents' files; only read. Write status/deck.md DONE + link.
