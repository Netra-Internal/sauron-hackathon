# Brief: map "camera view → boxes + suspicion → click a box → drone launches on that person"

Goal for today's demo (William): an operator sees a live camera view with a bounding box on every person, each box
labelled with Sauron's suspicion (whatever Jev / the dispatch judge actually outputs: facts like weapon/violence/
forced_entry/taking, E, verdict none|watch|deploy|urgent, caption). The operator CLICKS a box and a drone is dispatched
onto THAT person.

Your job is a MAP + PLAN, not the build. Read code and probe live systems READ-ONLY. Do not edit repos, restart units,
deploy, or start the Jev watcher (tokens). Deliver ~/hack-2026-10-24/plans/click-to-dispatch.md, then update
status/map.md and stop.

## What the plan must answer, with file:line references and measured numbers where you can get them
1. **Today's real path, stage by stage**: camera (RTSP: axis-q6215, jetson-c920, node3 offline) → Jetson edge unit
   (`ask/edge/`, netra-edge@<cam>, YOLO person boxes + track ids, 1 Hz foot points) → droplet (sitefuse, Ask API) →
   dispatch watcher (`ask/dispatch/watch.py`, judge.py, subject.py: Jev strip → facts → Policy → verdict, Jev box
   snapped to a YOLO track) → incident in `dispatch_incidents` → webhook `netra.dispatch.incident` (signed, PRs #3-#8)
   → `sauron_link` on `dwone` (sauron-autonomy PR #21 branch `c1-sauron-link`, NOT merged) → mission node.
   For each stage: what data comes out (fields), rate, latency, where it lives, and whether it runs today.
2. **What the operator UI can show today**: Sites monitor (`ask/static/monitor.js`, `/ask/sites#/site/<id>`), the camera
   wall, Ask feed previews, the Sauron live viewer (netra-training branch sauron-bench `src/sauron/viewer/`, :8060).
   Which of them already draws per-person boxes on live video, and at what latency? Which one should the demo use?
3. **Per-person suspicion**: Jev today scores a STRIP and returns ONE subject box, not a score per person. Say exactly
   what is available per box (track id, conf, Jev subject match, facts) and the cheapest honest way to put a suspicion
   value on each box (e.g. the incident's facts on the matched track only; others show "—"). No made-up scores: if
   there is no real number for a box, it shows none.
4. **Click → dispatch**: what the drone needs to launch on a person (read `sauron_link` on origin/c1-sauron-link and
   the contract ~/reports/sauron-link-answers-2026-10-22.md: lat/lon/radius, caption, crop URL, track id, position
   stream). Design the operator-launch path: a click on track T creates (or upgrades) an incident for T with
   mode=live, verdict deploy, reason operator_launch, subject_track=T, crop from the frame, lat/lon via
   `ask.sitemap.pixel_to_latlon` (needs a calibrated camera — check which cameras are calibrated in the droplet DB:
   `ssh root@104.131.163.205 'sudo -u netra psql netra_ask'`, tables sites/site_cameras), then forwards through the
   existing signed channel so the position stream (#6) follows T. NOTE (William's rule): autonomous launch stays — this
   click is an EXTRA trigger, never an approval gate on Sauron's own launches.
5. **Gaps and the smallest path to a working demo today**, ordered, with an estimate each, and a split into 3-5 work
   items that separate agents can build in parallel without editing the same files (name files/branches per item).
   Include deploy steps (droplet: what is NOT deployed yet — PRs #1-#8 are merged but the droplet runs older code,
   tables missing, DISPATCH_WEBHOOK/SECRET/ASK_DRONE_TOKEN unset; Jetson: watcher paused), and what Pranay's side
   must provide (dwone receiver up, webhook URL, shared secret).
6. **Demo risks**: which camera has a calibrated, outdoor, real view right now; Jetson memory (~2.5 GB available);
   latency budget click → drone receives command; what to rehearse.

Keep it tight: tables and short lines, one recommendation per question, say what you checked vs assumed.
