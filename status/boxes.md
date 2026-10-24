DONE: relay LIVE at https://internal.netralabs.net/hack/relay (deployed 22:21 UTC, hack-boxes 815cbbf, merged with origin/main). Agent cloud can point the RunPod edge's ask base URL there now.

## Relay (22:21 UTC)
- POST /hack/relay/api/edge/bucket: checks the worker token (bad token -> 401), spools the raw request to /var/lib/sauron-hack/relay (netra, 700),
  feeds live.OBS and answers 200 at once. One background worker forwards to http://127.0.0.1:8400/ask/api/edge/bucket (not through nginx,
  so no mirror loop) in order, with the same body, content-type and Authorization. Backoff 1/2/5/10/30 s, retrying forever.
  A permanent 4xx from netra-ask moves the bucket to relay/rejected/; nothing is deleted unforwarded. Over 2000 MB of spool -> 503,
  so the edge keeps the bucket. Backlog is logged in journalctl -u sauron-hack ("relay: backlog N").
- GET /hack/relay/api/edge/config and POST /hack/relay/api/edge/heartbeat: synchronous pass-through.
  Verified on the public URL with the real token: config 200 in 0.53 s.
- GET /hack/relay/status (internal login): backlog, oldest_age_s, forwarded, retries, rejected, last_error.
- The Jetson mirror path /hack/api/_edge/bucket is unchanged (feed only).
- Tested locally against a fake slow, flaky netra-ask (0.3 s per POST, 25% 503s): 20 buckets were answered in 0.64 s total and all 20 arrived
  in order after 4 retries.
- REAL buckets, 22:23 UTC: the RunPod edge (63.141.33.141) posts buckets about 1/s plus heartbeats; every one got 200 at once.
  28 were forwarded to netra-ask in 30 s, the backlog stayed at 0-3 (0.2 MB), 0 were rejected, and the netra-ask journal shows the ingests.
- app.py: a minimal edit. It mounts hackdash.relay at /hack/relay and adds the 3 relay edge paths to NO_LOGIN.


## For the manager (re your deploy message)
- PUSHED: origin/hack-boxes 824d48b (live.py, nginx snippet, tests). The names launch.py imports are unchanged: OBS.by_cam (5-tuple t, uuid, box, conf, kind;
  launch.py already unpacks 5), FRAMES.edge_frame, labels_for, _cam.
- I ALREADY removed the temp mirror (nginx restored to the original and reloaded) and stopped hack-boxes-test on :8511 at 21:31 UTC.
  Nothing is left to retire. Apply hackdash/nginx-edge-mirror.conf (it already points at :8500).
- Lag follow-up PUSHED: 1901d02 prefetches the frame as soon as a bucket arrives, while /live was polled in the last 15 s. Same names, safe to deploy.
  This saves up to one poll interval. It is NOT measured yet: my test unit and the mirror are gone, so I will measure on :8500 after your deploy.
  Lag budget (measured): edge obs arrive t + 1.2-2.8 s, the ring /frame fetch takes about 0.65 s, so a fresh frame is about 2-3.5 s old.
  It then ages until the next bucket, and the Jetson posts one about every 3 s even though flush_s is 1. The real remaining lever is that
  edge post cadence (Jetson poster / HTTPS round trips). That is Jetson-side, not mine to change without you.

## Box source (measured 2026-10-24 ~21:20-21:31 UTC)
| Candidate | Boxes? | Fresh? | Verdict |
|---|---|---|---|
| SQL `tracks` | no: `path` holds foot points subsampled to 25, plus sparse crop boxes | t_end about 5-7 s behind | unusable for boxes |
| SQL `site_track_links` | edge uuid -> site track only | about 9-10 s behind (final state) | used for site_track_id + labels |
| edge-serve :8450 | /frame, /clip, /health only; no boxes route | - | frames only |
| netra-ask HTTP /sites/{id}/live, /people | map dots / site tracks, no boxes; need the user cookie | - | no |
| **nginx mirror of POST /ask/api/edge/bucket** | yes: `positions[].obs` every frame, the same track uuids sitefuse binds | arrival = t + 1.2-2.8 s (one 3.8 s); the Jetson posts a bucket about every 3 s | **chosen** |

## Done check (droplet, temp unit :8511 + temp mirror; both removed afterwards, nginx restored)
`curl 127.0.0.1:8511/hack/api/cameras/jetson-c920/live` returned:
  t_ns 1792877297486346183, frame_url .../frame.jpg?t=<same>, src 1920x1080, judge_on false,
  boxes [{track_uuid cfb13fe3…, kind person, box [1298.2,656.2,1311.8,676.5], conf 0.279, site_track_id ee9af3ab…, label null}]
Alignment: I drew the boxes on the returned frame. Person 396-421 x 868-922 is inside its box (person walking on the sidewalk).
Lag series with people present (15 polls at 1 Hz): lag_s 2.9-6.4. Components: obs arrival 1.2-2.8 s, ring /frame fetch 0.54-0.80 s (one 1.72 s),
then up to one bucket interval (~3 s) until the next bucket. The empty-scene series (30 polls) cycles 3.0 -> 7.7 s.
/cameras: jetson-c920 live 6.2 fps, calibrated, test_rig true, site ucsd-design-innovation-building-c1dd; node3-c920 and axis-q6215 not live.
Labels: 0 dispatch_incidents and 0 dispatch_watch rows exist and the judge is off (netra-dispatch@jetson-c920 inactive), so every label is null.
The label SQL ran against the real tables. The label shape is unit-tested only.
Tests: `python3 -m pytest -q tests` -> 7 passed.

## To deploy (manager / dash)
1. nginx: add hackdash/nginx-edge-mirror.conf inside the internal server block, then `nginx -t && systemctl reload nginx`. It shadows only
   `location = /ask/api/edge/bucket`, with the same proxy settings as /ask, plus a mirror to :8500. This touches the /ask owner's ingress path.
   I tested it live for 5 min: netra-ask kept answering 200 to every bucket.
2. sauron-hack.service runs as user **netra** (peer auth to netra_ask; netra's ssh key reaches the Jetson for the judge check).
   Env: ASK_WORKER_TOKEN (same as /etc/netra-ask.env), ASK_EDGE_URL=http://127.0.0.1:8450, ASK_DATABASE_URL=postgresql:///netra_ask.
   Optional: ASK_SITES_YAML (default /opt/netra/netra-ask/ask/sites.yaml), HACK_TEST_RIGS, HACK_JUDGE_SSH.
3. app.py login middleware: exempt exactly POST /hack/api/_edge/bucket. It checks the worker Bearer token itself.
   I sent this to agent dash via hagent.
Uses the netra-ask venv deps (fastapi, httpx, psycopg 3, python-multipart, pyyaml).

## Caveats
- Boxes come from confirmed edge tracks only. A new person is backfilled once confirmed, and their site_track_id shows up about 10 s after they appear.
- Payload extras beyond ARCH: kind, why (when there is no frame), obs_arrival_lag_s, frame_fetch_s, buckets_rx; label.kind = incident|watch.
- dispatch_watch has no close: a watch label counts as current for 120 s after opened_at.
