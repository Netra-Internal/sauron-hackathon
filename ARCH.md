# Send-drone demo: architecture (hackathon repo only)

William's decisions (Oct 24, 14:20 PDT):
- Everything lives in THIS repo. Nothing in netra-ask is edited. We read from netra-ask (its HTTP APIs with tokens,
  read-only SQL on its Postgres `netra_ask`, the Jetson edge-serve tunnel) and post through its EXISTING endpoints.
- Camera: jetson-c920 for now; everything keyed by camera id so more cameras plug in later. Show "test rig" on it.
- dwone and sauron_link are OFF LIMITS (Pranay's). We run our own receiver (`droplink`) for the signed webhook.
- netra-ask main (dispatch PRs #1-#8) is deployed on the droplet as of 14:25 PDT. DISPATCH_WEBHOOK_SECRET and
  ASK_DRONE_TOKEN are set in /etc/netra-ask.env; DISPATCH_WEBHOOK is still UNSET (the manager sets it to droplink).

## Pieces (one owner each)
| Dir / file | Owner | What |
|---|---|---|
| `hackdash/app.py`, `hackdash/static/*`, `deploy/` | agent `dash` | FastAPI app (mounts the two routers below), the page, droplet unit + nginx location |
| `hackdash/live.py` | agent `boxes` | APIRouter: cameras, live frame + person boxes + suspicion labels |
| `hackdash/launch.py`, `droplink/` | agent `launch` | APIRouter: send drone / abort / incident state; droplink receiver service |

## Runtime (droplet flywheel-01, root@104.131.163.205)
- `sauron-hack.service`: uvicorn hackdash.app:app on 127.0.0.1:8500, code in /opt/netra/sauron-hack, env /etc/sauron-hack.env.
- Public at https://internal.netralabs.net/hack/ (nginx location, behind the same internal login as /ask; check how /ask
  is protected and reuse it).
- `droplink.service`: 127.0.0.1:8510, receives netra-ask's signed webhook; DISPATCH_WEBHOOK=http://127.0.0.1:8510/sauron/v1/messages.
- Never `pkill -f` on the droplet; use systemd units. Never restart netra-ask (manager only).

## API contract (all under /hack/api)
```
GET  /cameras                         -> [{camera_id, name, site_id, live, fps, calibrated, test_rig}]
GET  /cameras/{cam}/live              -> {t_ns, frame_url, src_w, src_h, lag_s, judge_on,
                                          boxes:[{track_uuid, box:[x1,y1,x2,y2], conf, site_track_id|null,
                                                  label:null|{verdict, why_label, e, facts:{..top2}, caption, incident_id}}]}
GET  /cameras/{cam}/frame.jpg?t=<ns>  -> JPEG (ring frame at t)
POST /launch {camera_id, track_uuid, t_ns} -> {id, located, lat, lon, loc_source, site_track_id, already_dispatched}
                                          409 {"detail": "..."} when the person is no longer tracked etc.
POST /incidents/{id}/abort            -> {command_id, ...}
GET  /incidents?open=1                -> incidents this demo launched (+ forwarded delivery state)
GET  /drone/messages?since=<seq>      -> what droplink received: [{received_at, type, incident_id, seq, verified, body}]
```
Labels are REAL or null: a box gets a label only if it is bound to an open incident/watch from the real judge.
No mock, sample or synthetic data anywhere (develop against the live droplet data).
