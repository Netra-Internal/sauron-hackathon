# Click-to-dispatch: map + plan (agent `map`, 2026-10-24 ~13:55 PDT)

Goal: the operator sees live video with a box on every person, each box labelled with Sauron's real suspicion. They click
a box and the drone launches on that person. The click is an EXTRA trigger. Sauron's own autonomous launch stays as it is.

Code refs are netra-ask `origin/main` @ 6417b5f unless a path says otherwise. sauron_link refs are sauron-autonomy
`origin/c1-sauron-link`, file `ros2/src/netra_autonomy/netra_autonomy/sauron_link.py` (written **SL:n** below).
**[M]** = measured today, **[C]** = read in code/config, **[A]** = assumed.

## TL;DR
- **Only one camera can do this today: jetson-c920.** It is the only camera that is both live and calibrated. It is an
  outdoor view out of the DIB window (viaduct, field, road), calibrated to 8.7 m ground error. axis-q6215 has been down
  for at least 2 days with RTSP connection refused, and it is an uncalibrated indoor bench PTZ anyway. node3 is offline.
  jetson-c920 is the "desk test rig" (William's rule: never headline evidence). **William decides:** demo on it,
  labelled as a test rig, or no live demo today.
- **Nothing on the dispatch side is deployed.** The droplet runs Oct 23 code. It has no `drone.py`, `commands.py` or
  `positions.py`, and no `drone_status`, `dispatch_commands` or `dispatch_watch` tables. `dispatch_incidents` has no
  `fwd_seq` column. `DISPATCH_WEBHOOK`, `DISPATCH_WEBHOOK_SECRET` and `ASK_DRONE_TOKEN` are unset. There are 0 incidents
  ever. The Jetson checkout is also Oct 23, and the watcher has been stopped since Oct 22 14:03.
- **The monitor has no person boxes anywhere today (map dots only).** The Sauron viewer does draw boxes (its own YOLO), but its
  box ids are not our edge track ids, it has no click handling, and its host netra-ptz is offline.
- **Recommendation (William, 13:59): the current Sites monitor + ONE addition.** In the existing camera lightbox
  (`openCamera`, `monitor.js:326`):
  - a ~1 fps ring frame, taken at the exact time of the newest edge boxes (measured about 1 s per fetch, so the picture
    runs about 2.5–3 s behind live);
  - the edge YOLO boxes drawn over it, each with a real suspicion label or "—";
  - a **Send drone** button on each box → `POST /ask/api/dispatch/launch`. That creates an operator incident through
    the existing `store.accept`, which binds, locates, signs and forwards it.
- **Estimate:** about 1 day of build in 3 parallel items, plus deploy and rehearsal. Pranay's side needs no code for a
  fly-to-point launch. It needs sauron_link reachable from the droplet, the shared secret, and the drone token.

---

## 1. Today's path, stage by stage

| # | Stage | Output (fields) | Rate / latency | Where | Runs today? |
|---|---|---|---|---|---|
| 1 | Camera RTSP | H.264 1080p (c920 through the mediamtx shim, `netra-c920-rtsp`) | 5 fps pulled | Jetson | **jetson-c920 yes.** axis-q6215 **no**: `ended (0 frames)`, connection refused on 127.0.0.1:8554 [M]. node3 **no** (0 fps [M]) |
| 2 | Edge unit `netra-edge@<cam>` (`ask/edge/main.py`, `pipeline.py`) | Bucket every `flush_s`: `tracks[]` (open + closed, crops), `positions[]` = `{track_uuid, edge_tid, kind, conf, closed, obs:[[t_ns,x1,y1,x2,y2,conf]...]}` for every frame of every confirmed track (`pipeline.py:106-117`), `preview.jpg` only every 150 frames, about 30 s (`pipeline.py:88`), `complete_ns` | c920: 5.2 fps analysed, infer 65–71 ms, `flush_s: 1` (`sites.yaml:124`). Frame stamp = read − 1000 ms (`sites.yaml:123`). Heartbeat `frame_age_s` 1.16 [M]. Jetson→droplet HTTPS 0.16–0.40 s, one 1.96 s outlier in 5 [M] | Jetson → `POST /ask/api/edge/bucket` | **Yes**, c920: posted=49402, failed=384 [M] |
| 2b | Edge ring + `netra-edge-serve` (`ask/edge/serve.py`) | `/frame?camera&t` → JPEG 1280 px at any ring time (`serve.py:93-104`); `/clip` | `/frame` at now−1.5 s: 200 OK in 0.96 s; at now−3 s: 1.35 s; at now−2 s: one 404 [M]. Droplet reaches it through `netra-ask-edge-tunnel` at 127.0.0.1:8450 | Jetson, ring 48 GB | **Yes** |
| 3 | Droplet ingest → sitefuse (`ask/sitefuse.py`) | Per site: fused site tracks `{id, lat, lon, radius_m (p95), speed, heading_deg, silent_s, cam_tracks:[edge uuids], conf}` (`sitefuse.py:618-633`). Raw edge boxes for the last 60 s per camera in `Fuser.recent` = `(t_ns, track_uuid, box)` (`sitefuse.py:652, 685`) | Display state about 1 Hz. Box latency at the droplet ≈ 1.0 s stamp + ≤1 s flush + 0.2 s post ≈ 1.5–2.5 s [C+M] | droplet `netra-ask` (uvicorn, 1 worker) | **Yes** for the UCSD DIB site: 42 site tracks and 151 c920 tracks in the last hour [M] |
| 4 | Dispatch watcher `netra-dispatch@<cam>` (`ask/dispatch/watch.py`) | Its OWN RTSP pull at 4 fps (`watch.py:480`). Person gate: YOLO full frame + 2×2 tiles, 1 Hz, **its own tracker ids** (`presence.py`, `subject.py:249-281`). A Jev strip (4 frames, 0.5 s apart) every 2 s while a person was seen in the last 30 s → `facts{weapon, violence, menace, break_in, theft, tampering, trespass, vandalism, normal}` + ONE subject box (`judge.py:129-139`) → Policy → `e`, `verdict none/watch/deploy/urgent`, `why` (`judge.py:98-126`). The Jev box is snapped to a YOLO person (`subject.py:234-246`), giving `subject_track` (the watcher's own id) and `subject_confirmed` | Jev strip about 0.3 s, caption about 0.5 s (docs/dispatch.md:263). Person check 365 ms (grid 2, Oct 22 journal) [M]. Cost about 15.7 M input tokens per camera-hour ≈ **$0.66/h** at $0.042/M (docs/dispatch.md:263-264) | Jetson | **No.** Unit `disabled`, last ran Oct 22 13:59; the Jetson code is Oct 23 (327-line watch.py, no watch or reappear logic) [M] |
| 5 | Incident upsert `POST /api/dispatch/incidents` → `store.accept` (`store.py:380-435`) | Record: `id, camera_id, mode, verdict, why, facts, evidence_e, box, subject_track, subject_confirmed, caption, track[]` + evidence `frame/crop/strip*.jpg`. `locate_record` (`store.py:137-168`): pixel lift through `sitemap.pixel_to_latlon`; if confirmed and live, bind to a sitefuse track with `track_at(cam, at_ns, box)`: ±0.5 s, IoU ≥ 0.3 or foot < 0.5 box h (`sitefuse.py:83, 793-811`) → `site_track_id`, lat/lon/radius from the fused track | Watcher posts one per strip (2 s) | droplet `dispatch_incidents` | Table exists with 0 rows. **The deployed store.py is older** (13.6 KB, no `fwd_seq`) [M] |
| 6 | Webhook `netra.dispatch.incident` (`store.py:607+`), `.position` (`positions.py`, 1 Hz, bound incidents only, `positions.py:80-99`), `.command` end/abort (`commands.py`), `.watch` | Envelope `{type, delivery_id, seq, emitted_at, incident}`, `X-Netra-Signature: t=..,v1=HMAC-SHA256(secret, "t.body")` (`store.py:547-549`). Retry backoff 1/2/5/10/30 s up to 300 s (`store.py:539-540`) | First attempt starts as soon as the upsert commits [C] | droplet → `$DISPATCH_WEBHOOK` | **No.** The code is not deployed and the env is unset [M] |
| 7 | `sauron_link` (dwone, PR #21, NOT merged, targets `ros2-port`) | HTTP `POST /sauron/v1/messages`, default **127.0.0.1:8765** (SL:404, 472). Verifies HMAC with `SAURON_LINK_SECRET`, 300 s skew (SL:58-71). **Launches only if** `mode==live`, verdict deploy/urgent, `located is True` with finite lat/lon, `updated_at`/`emitted_at` ≤ 60 s old, not closed, drone not busy (SL:256-294) → `MissionGoal{incident_id, lat, lon, radius_m}` on `/mission/goal` (SL:507-513). Does NOT read caption, crop, subject_track, box or heading. **Positions are accepted but not applied** (`position_not_used_yet`, SL:194-200). `end`/`abort` → `MissionCommand end` | No numbers measured | dwone | **Unknown.** Not checked; Pranay's machine [A] |
| 8 | Mission node | Flies to the point. The radius is ignored (`mission.py:189`). A second goal while busy is refused (`mission.py:193`) | — | dwone, PX4 | Sim only: `ros2/sim/run.sh --scenario http_fly_to_and_back` |

Calibration (droplet `site_cameras`) [M]: one row only. `camera-1-5621` → live `jetson-c920`, site
`ucsd-design-innovation-building-c1dd`, fit err 8.7 m, fitted Oct 21. The site boundary is set.

## 2. Operator UI = the current Sites monitor + ONE addition: "Send drone" on a person box

William (13:59 update): no new dashboard. The demo UI is the Sites monitor (`ask/static/monitor.js`,
`/ask/sites#/site/<id>`) as it is, plus a "Send drone" option on a person box.

Screenshot of the monitor now: `monitor-now.png`. Annotated sketch: `send-drone-sketch.png` (both in this folder).
The screenshot was taken 14:13 PDT on the UCSD DIB site: 1/1 cameras live, 3 people on site, "All quiet".

**What renders today** [C, checked against the screenshot]

| Area | Code | What it shows | Per-person boxes? |
|---|---|---|---|
| Left: queue/detail | `renderDetail` `monitor.js:177-224` | Incident: evidence frame with the Jev subject boxed (a static JPEG), facts, Forwarded. **No Abort or Dismiss button for incidents.** Those exist only as API routes (`api.py:573, 585`). The Confirm/Dismiss buttons are for watch alerts | no |
| Centre: map | `drawPeople` `monitor.js:403-411`, polled by `pollPeople` every 1 s (`monitor.js:27, 58`) | Fused site tracks as green dots + 95% ellipse + trail (layer `people-dot`, `monitor.js:43`). No click handler | one dot per person, no box |
| Right: camera wall | `renderWall` `monitor.js:278-314`, `tileImg` `:260` | `preview.jpg`, regenerated every 150 frames (about 30 s, `pipeline.py:88`) | no |
| Camera lightbox | Click a tile once to select it, again to open it: `monitorSelectCam` `:250` → `openCamera` `:326-332` → `lightbox` `:418` | The same `preview.jpg` at 960×540, the caption line, and a "Calibration" link | no |

**So there is no person box anywhere in the monitor today.** The addition has two parts: the boxes, and the button on
them. Both go inside `openCamera`. Nothing else in the monitor changes.

**Where the addition goes**
1. **`openCamera(c)` (`monitor.js:326-332`).** For a camera with `c.source.camera_id`, the lightbox switches from the
   static preview to a small live loop:
   - `GET /ask/api/cameras/{camera_id}/live` returns
     `{t_ns, frame_url, src_w, src_h, boxes:[{track_uuid, box, conf, site_track_id, label|null}], judge_on}`;
   - set `<img src=frame_url>` (the ring frame at exactly `t_ns`);
   - draw the boxes on a `<canvas>` over the image, scaled from `src_w × src_h` to 960×540;
   - repeat when the image loads (about 1 fps);
   - stop when the lightbox closes (`closeLightbox`, `:419`).
2. **Per box: a label chip and a "Send drone" button.** The chip shows `#short-id conf`, then the suspicion:
   - for the person bound to an open incident: verdict colour, `why_label`, E, top facts, caption;
   - otherwise "—" (§3).
   - A caption line under the image says "≈N s behind live" and "judge off" when `judge_on` is false.
3. **Click "Send drone"** → an inline confirm in the chip ("Send drone to #id? Yes / Cancel"). This confirms the
   operator's own click only. It is not a gate on Sauron's launches. Then:
   ```
   POST /ask/api/dispatch/launch
   {"camera_id": "jetson-c920", "track_uuid": "<box.track_uuid>", "t_ns": <payload t_ns>}
   → 200 {"id": "jetson-c920-op-…", "located": true, "lat": …, "lon": …, "loc_source": "sitefuse",
          "site_track_id": "…", "already_dispatched": false}
   → 409 {"detail": "person no longer tracked"} | {"detail": "no dispatch webhook is configured"}
   ```
   - A toast confirms.
   - `monitorSelect("inc:<id>")` opens the incident in the left pane: it is now an open live incident, so it shows in
     the existing queue, in "Forwarded" and on the map.
   - The chip turns red, "drone sent".
   - Auth: the existing internal login cookie (`need_user`), audited.
4. **Optional, same handler (+20 min):** the same Send drone control in a popup on the map's `people-dot`. That needs a
   `map.on("click", "people-dot", …)` handler in `ensureMonitorLayers` (`monitor.js:33-46`), and the body is
   `{site_track_id}`. Leave it out unless William wants it.
5. **Recommended small extra:** an "Abort drone" button on an open, forwarded incident in `renderDetail` (`:191-201`,
   next to "Show on map") → existing `POST /ask/api/dispatch/incidents/{id}/abort`. Without it, the only way to recall
   the drone from the UI is to wait for `subject_lost`.

**Why not the Sauron viewer (:8060):** it does draw boxes (its own YOLO, WebSocket JPEG), but its ids are not
edge/sitefuse ids, it has no click handling, its host netra-ptz is offline, and William chose the monitor.

## 3. Per-person suspicion: what is real per box

| Per box (edge track) | Source | Available? |
|---|---|---|
| track uuid, box, conf, time | `Fuser.recent` / bucket `positions.obs` | yes, every frame |
| site track id, lat/lon, radius, speed | sitefuse `cam_tracks` → site track | yes, if the person is in the calibrated region |
| verdict, why, E, facts, caption | Open `dispatch_incidents` row (or `dispatch_watch` row) whose `record.site_track_id` = this box's site track | **only for the one subject Jev pointed at**, and only while the watcher runs and the verdict is ≥ watch |
| a score per person | — | **does not exist.** Jev scores the strip and returns one box |

**Cheapest honest labelling:**
- The box whose site track = an open incident's `site_track_id` shows that incident's `verdict` (colour), `why_label`,
  `E`, the top two facts, and `caption_text`. Mark it "scene facts · Jev pointed at this person".
- A watch episode's box gets the same treatment, in amber.
- Every other box shows `#id conf` and "—" for suspicion.
- When the watcher is paused, every box shows "—" and a banner says "judge off".

Note: the watcher's `subject_track` is the watcher's own id (`subject.py:249`) and must not be shown as an edge id.
The binding to edge boxes is the droplet's geometric `site_track_id` (`store.py:114-134`).

## 4. Click → dispatch

**What the drone actually needs** (SL:256-294): a signed `netra.dispatch.incident` with `mode=live`, `verdict` deploy or
urgent, `located=true`, a finite `lat`/`lon` (`radius_m` is passed but ignored), and fresh `updated_at`/`emitted_at`
(≤ 60 s). Caption, crop and track are informational only for now. Following the person (positions) is not applied by
sauron_link yet (unit C4), so for today the drone flies to the launch point.

**Design: `POST /ask/api/dispatch/launch`** (internal login; audited as `dispatch.operator_launch`)

Body: `{camera_id, track_uuid, t_ns}`. These are the exact obs the operator clicked, taken from the live-view payload.

1. Find `(t, track_uuid, box)` in `Fuser.recent[camera_id]`. Not found → 409 "person no longer tracked".
2. If an open live incident already has the same `site_track_id`, return it (`already_dispatched`). The click upgrades
   nothing and launches nothing twice. Never touch a watch id: the watcher may reuse it for its own incident
   (`watch.py:234`), and the upsert would then overwrite the record.
3. Get the frame at `t` with `ingest._edge_get("/frame?camera=..&t=..")` (`ingest.py:313` pattern). Build
   `frame.jpg = caption.draw_box(...)` and `crop.jpg = caption.crop_box(...)` (`watch.py:249-252`). If the frame fetch
   fails, launch anyway with no evidence. Never block the launch on it.
4. Build the record:
   - `id = f"{cam}-op-{UTC stamp}-{hex4}"` (matches `ID_RE`, `store.py:31`)
   - `mode: live`, `status: open`, `verdict: deploy`, `why: operator_launch`, `why_label: "operator launch"`
   - `opened_at = updated_at = now`
   - `facts`: copy from the bound incident or watch if there is one, else `{}`. `evidence_e`: the same, else null.
   - `box`, `frame_w/h` = camera source size, `subject_track: null`, `subject_confirmed: true`, `edge_track: track_uuid`
   - `track: [{at: iso(t), box}]`, `caption: null`, `caption_text: null`, `judge: {operator: user}`
5. Call `store.accept(rec, files)`. The existing code then does the rest:
   - `locate_record` binds the sitefuse track. lat/lon is the fused estimate *now*, which absorbs the 2.5–3 s
     display lag.
   - It writes the row.
   - `_maybe_forward` signs and sends `netra.dispatch.incident` (deploy has not been sent for this id yet).
   - `positions.tick` then streams the site track at 1 Hz once the incident is 2xx-acked (`positions.py:80-99`).
   - If the track does not bind, location falls back to the pixel lift (`loc_source: pixel_to_latlon`). It still
     launches if located.
6. Return `{id, located, lat, lon, loc_source, site_track_id, forwarded}`. The UI opens the new incident in the
   existing left pane (Forwarded row shows delivery).

**Lifecycle gap to close:**
- No watcher ever posts to an operator incident. That means `subject_lost` (`store.py:196-208`, "checked when the
  watcher posts") never fires, and the incident would stay open forever.
- **Fix:** a 1 Hz droplet loop in `ask/dispatch/operator.py`. For open `*-op-*` incidents:
  - append a `track` point from `sitefuse.live_track` each second, throttled through the normal `accept`;
  - close with `subject_lost` once the site track has been gone for `SUBJECT_LOST_S`;
  - the close then sends `end` automatically (`commands.py`).
- The operator can end it sooner through the existing abort/dismiss API routes (`api.py:573, 585`). There is no
  monitor button for them yet; see §2 item 5.

**Autonomy stays:**
- The watcher's incidents are untouched. Its ids have no `-op-`.
- If both fire on one person, the drone takes the first and refuses the second as `busy`, which sauron_link records
  as handled (SL:256-294). That is the correct outcome.

## 5. Gaps and smallest path to a working demo today

| # | Gap | Fix | Est. |
|---|---|---|---|
| G1 | Droplet on Oct 23 code: missing tables and endpoints | Manager deploys `main` 6417b5f to the droplet. `schema.sql` runs at startup (`db.py:42`), which creates the tables and `fwd_seq`. Set `DISPATCH_WEBHOOK`, `DISPATCH_WEBHOOK_SECRET` and `ASK_DRONE_TOKEN` in `/etc/netra-ask.env`, then restart `netra-ask` | 30 min |
| G2 | Jetson watcher: old code, stopped | `deploy/jetson-dispatch.sh jetson-c920` (rsync main), but **start only in the demo window** (Jev tokens, ≈ $0.66/h). Memory: watcher peak 1013 MB vs 2460 MB available [M]. Freeing room is optional: stopping the dead `netra-edge@axis-q6215` and `@node3-c920` units would return about 1.9 GB RSS; both have had 0 frames for days. Needs the manager's OK | 20 min |
| G3 | No person boxes in the monitor | W1 + W3 below | 3–4 h |
| G4 | No operator launch | W2 below | 3 h |
| G5 | Drone receiver | Pranay: run sauron_link on dwone with `--listen 0.0.0.0:8765`, give us a URL the droplet can reach (the droplet's tailnet ACL allows only SSH to the Jetson today, so either a public HTTPS endpoint or an ACL change), set `SAURON_LINK_SECRET` = our `DISPATCH_WEBHOOK_SECRET`, `SAURON_DRONE_TOKEN` = our `ASK_DRONE_TOKEN`, `SAURON_URL=https://internal.netralabs.net`, `SITE_ID=ucsd-design-innovation-building-c1dd`, then `--fetch-boundary`. Mission node + PX4 SITL running (`ros2/sim/run.sh`). **Contract note:** positions need `delivery_id`; ours has one (`positions.py:160`) | Pranay, about 1 h |
| G6 | End-to-end never run | Rehearsal, below | 1 h |

**Parallel work items** (each agent in its own worktree off `origin/main`; no two items touch the same file, except the
small `api.py` route blocks in W1 and W2, which the manager merges):

| Item | Branch | Files | What |
|---|---|---|---|
| **W1 camera-boxes API** | `hack-liveview-api` | `ask/sitefuse.py` (add `Fuser.boxes(camera_id)` + module `live_boxes(camera_id)`: newest obs per track uuid at the newest common `t`, with `site_track_id` from `cam_tracks`); new `ask/livecam.py` (frame proxy with one request in flight per camera, cache keyed on `t`, 404 → retry at `t − 0.2 s`; attaches the incident/watch label per §3); `ask/api.py`: new block `# live view` with `GET /api/cameras/{cam}/live` → `{t_ns, frame_url, src_w, src_h, boxes:[{track_uuid, box, conf, site_track_id, label|null}], judge_on}` and `GET /api/cameras/{cam}/frame.jpg?t=`; tests `tests/test_livecam.py` | 3 h |
| **W2 operator launch** | `hack-operator-launch` | new `ask/dispatch/operator.py` (`launch()` per §4 + the 1 Hz lifecycle loop); `ask/api.py`: one route `POST /api/dispatch/launch` in the dispatch block, plus starting the loop thread next to `dispatch_positions.loop` (`api.py:82`); tests `tests/test_dispatch_operator.py` (bind, idempotent click, fallback location, close on lost track, never touches watch ids); a line in `docs/dispatch.md` | 3 h |
| **W3 monitor addition** | `hack-send-drone-ui` | `ask/static/monitor.js` only: `openCamera` (`:326-332`) gets the live loop, box canvas, label chip, Send drone + confirm (§2), a stop hook in `closeLightbox` (`:419`), and the Abort button in `renderDetail` (`:191-201`); plus a few rules in `ask/static/sites.css`. No new page and no new JS file. Develop against the W1/W2 endpoints on a dev server; no mock data in the product | 2.5 h |
| **W4 deploy + ops** (manager) | — | G1, G2, and later deploying W1–W3 from one integrated checkout (rsync `--delete` hazard) | 1 h |
| **W5 drone side** (Pranay) | sauron-autonomy `c1-sauron-link` | G5. No code change is needed for fly-to-point. Follow-the-person = his unit C4 | — |

## 6. Demo risks

| Risk | Status | Mitigation |
|---|---|---|
| Camera | Only jetson-c920 is live **and** calibrated [M]. It is the desk rig: William's rule says no headline evidence | William decides. If yes, label it "test rig" on screen. Stage the person on the near **walkway/road** zone: in the field, people are 10–40 px tall (`sites.yaml:101`) and the 8.7 m calibration error dominates |
| Jetson memory | 2460 MB available. Watcher peak 1013 MB [M] | OK as is. Optionally stop the 2 dead edge units (+1.9 GB) with the manager's OK |
| Jetson GPU | GR3D 86% with c920 edge alone [M]. The watcher adds YOLO 1280 + tiles at 1 Hz (365 ms) | Watch edge `fps_analysed` during rehearsal. If it drops below 4, set `DISPATCH_GATE_TILES=0` |
| Ring-frame fetch load | Each `/frame` spawns ffmpeg on the Jetson: about 1 s per frame, 1 in 3 got a 404 near segment edges [M] | One request in flight; ≤1 fps; retry at t−0.2 s |
| Display lag | Video about 2.5–3 s behind live at about 1 fps [M+C] | Show the lag on screen. The launch point comes from sitefuse *now*, not the stale pixel |
| Click → drone receives incident | Droplet side < 0.5 s [C/A]: route + `accept` + first signed attempt. Then the network to dwone [A]. Total estimated ≈ 1 s, **never measured** | Measure in rehearsal: `forwarded[].at` vs sauron_link log |
| Drone follows person | **No**: positions are not applied (SL:194-200) | Say "flies to the launch point" in the demo; do not claim tracking |
| Watcher off → no suspicion labels | Expected | Start `netra-dispatch@jetson-c920` only for the window. Breaking-in behaviour on this view (bike or car tampering by the road) is what produces facts |
| Two launches on one person | sauron_link refuses the second as busy | Expected; the UI shows the refusal from `forwarded` |

**Rehearse, in this order:**
1. Deploy G1. `curl` a signed test incident from the droplet to sauron_link and see `MissionGoal` in SITL.
2. Open Camera 1 in the monitor with a person on the walkway: boxes line up on the frame and the lag reads ≤ 3 s.
3. Click → incident row with `loc_source=sitefuse` and a `site_track_id` → `forwarded` 2xx → SITL drone takes off →
   positions are streaming.
4. Abort → `end` reaches SITL.
5. Start the watcher, do a staged break-in on a parked bike → the box turns amber/red with real facts. That launches
   autonomously with no click (proves the click is not a gate).
6. The person walks out of view → the operator incident closes `subject_lost` within about 30 s and `end` is sent.

## Checked vs assumed
- **Checked live (read-only):**
  - droplet: tables, `site_cameras`, incident count, file mtimes, env var *names*, units, `feed_health`, tracks per hour,
    ring `/frame` timing through the tunnel;
  - Jetson: `free`, `tegrastats`, unit states and journals, process RSS, checkout mtimes, Jetson→droplet RTT.
- **Read in code:** everything with a file:line ref. sauron_link and the viewer were read by a sub-agent with `git show`
  on `origin/c1-sauron-link` and `sauron-bench`.
- **Assumed:**
  - dwone network reachability and sauron_link's runtime state (not checked: Pranay's machine);
  - the click → drone latency;
  - that the fused display state lags by about 1 s more than the raw boxes (it is in-process; there was no
    authenticated read of `/people`).
