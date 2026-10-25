DONE: rerun on the deployed fix (main 555872e) passed: real tracked person -> launch -> signed incident -> abort -> `end` + closed + `abort`, and NO open update after the abort.

## Rerun with the fix, 21:39 UTC (tools/click_path_test.py on the droplet, real person on jetson-c920 test rig)
    21:38:33 waiting up to 1500 s for a tracked person on jetson-c920
    21:39:00 live: {"t_ns": 1792877936092192578, "lag_s": 4.167, "n_boxes": 1, "clicked": {"track_uuid": "6bcfea4d7c5249558870edbe684e4304", "kind": "person", "box": [1503.8, 672.0, 1515.0, 699.8], "conf": 0.285, "site_track_id": "ddc5c00cc294806aa67188fd0f775c6e", "label": null}}
    21:39:01 POST /launch -> 200 {"id": "jetson-c920-op-20261024T213901Z-1b1c", "located": true, "lat": 32.879466869378305, "lon": -117.23127809921526, "loc_source": "sitefuse", "site_track_id": "ddc5c00cc294806aa67188fd0f775c6e", "already_dispatched": false, "post_s": 0.794, "evidence": ["crop.jpg", "frame.jpg"]}
    21:39:02 POST /launch again (idempotent) -> 200 {"id": "jetson-c920-op-20261024T213901Z-1b1c", "located": true, "lat": 32.879466869378305, "lon": -117.23127809921526, "loc_source": "sitefuse", "site_track_id": "ddc5c00cc294806aa67188fd0f775c6e", "already_dispatched": true}
    21:39:03 droplink first incident message after 2.78 s: {"seq": 20, "type": "netra.dispatch.incident", "verified": true, "dup": false, "msg_seq": 1, "status": "open", "verdict": "deploy", "located": true, "lat": 32.879466869378305, "lon": -117.23127809921526}
    21:39:09 GET /incidents/{id} -> 200 {"status": "open", "located": true, "lat": 32.87946617383138, "lon": -117.23128221331, "loc_source": "pixel_to_latlon", "site_track_id": null, "track_points": 6, "last_seen": "2026-10-24T21:38:57.495336+00:00", "forwarded": {"attempts": 4, "delivered": 4, "last": {"at": "2026-10-24T21:39:07.879635+00:00", "to": "127.0.0.1", "seq": 4, "netloc": "127.0.0.1:8510", "status": 200, "attempt": 1, "verdict": "deploy", "delivery_id": "a0c1ca01-8b80-49ba-b237-e6657541ab6e", "incident_status": "open"}}, "evidence": {"crop.jpg": "/ask/api/dispatch/evidence/jetson-c920-op-20261024T213901Z-1b1c/crop.jpg", "frame.jpg": "/ask/api/dispatch/evidence/jetson-c920-op-20261024T213901Z-1b1c/frame.jpg"}}
    21:39:12 POST /incidents/jetson-c920-op-20261024T213901Z-1b1c/abort -> 200 {"ok": true, "created": true, "command_id": "jetson-c920-op-20261024T213901Z-1b1c:abort:2", "seq": 2, "expires_at": "2026-10-24T21:49:12.768048+00:00", "delivery_status": "pending", "closed": "dismissed"}
    21:39:13 droplink messages for jetson-c920-op-20261024T213901Z-1b1c
        {"seq": 20, "type": "netra.dispatch.incident", "verified": true, "dup": false, "msg_seq": 1, "status": "open", "verdict": "deploy", "located": true, "lat": 32.879466869378305, "lon": -117.23127809921526}
        {"seq": 21, "type": "netra.dispatch.incident", "verified": true, "dup": false, "msg_seq": 2, "status": "open", "verdict": "deploy", "located": true, "lat": 32.87946617383138, "lon": -117.23128221331}
        {"seq": 22, "type": "netra.dispatch.incident", "verified": true, "dup": false, "msg_seq": 3, "status": "open", "verdict": "deploy", "located": true, "lat": 32.87946617383138, "lon": -117.23128221331}
        {"seq": 23, "type": "netra.dispatch.incident", "verified": true, "dup": false, "msg_seq": 4, "status": "open", "verdict": "deploy", "located": true, "lat": 32.87946617383138, "lon": -117.23128221331}
        {"seq": 24, "type": "netra.dispatch.incident", "verified": true, "dup": false, "msg_seq": 5, "status": "open", "verdict": "deploy", "located": true, "lat": 32.87946617383138, "lon": -117.23128221331}
        {"seq": 25, "type": "netra.dispatch.command", "verified": true, "dup": false, "msg_seq": 1, "command": "end", "reason": {"code": "dismissed"}}
        {"seq": 26, "type": "netra.dispatch.incident", "verified": true, "dup": false, "msg_seq": 6, "status": "closed", "verdict": "deploy", "located": true, "lat": 32.87946617383138, "lon": -117.23128221331, "close_reason": "dismissed"}
        {"seq": 27, "type": "netra.dispatch.command", "verified": true, "dup": false, "msg_seq": 2, "command": "abort", "reason": {"by": "hack_launch", "code": "operator_abort"}}
    21:39:13 final incident: {"status": "closed", "close_reason": "dismissed", "aborted_by": "hack_launch", "operator": "hack_launch", "commands": [{"command_id": "jetson-c920-op-20261024T213901Z-1b1c:end:1", "command": "end", "delivery_status": "delivered", "issued_at": "2026-10-24T21:39:10.422361+00:00", "reason": {"code": "dismissed"}}, {"command_id": "jetson-c920-op-20261024T213901Z-1b1c:abort:2", "command": "abort", "delivery_status": "delivered", "issued_at": "2026-10-24T21:39:12.768048+00:00", "reason": {"by": "hack_launch", "code": "operator_abort"}}]}

Result: after the abort, droplink got, in order: `end` (dismissed) -> incident CLOSED (dismissed) -> `abort` (by hack_launch). No open incident message after the abort; 0 messages for the incident in the 16 s after (checked 21:39:29). All verified, no duplicates.
Click -> netra-ask accepted 0.79 s; click -> first signed incident in droplink 2.78 s.
Note: this person (far, conf 0.29) bound to sitefuse at launch (loc_source sitefuse) but had dropped to pixel_to_latlon by 21:39:09 (the edge track's binding was lost), so netra-ask streamed no position messages this time; positions stream only for sitefuse-bound incidents (the 21:34 run streamed them at 1 Hz).

# Earlier run (21:34, before the fix)

Fix merged in main 555872e and deployed (sauron-hack launch.py sha256 ad78f479... = main, service restarted 21:38:20 UTC). Rerun below.

## Service account (manager-approved)
- `hack_launch` (users.py allows only identifier names, so `hack-launch` was not possible). Created with netra-internal deploy/add-user.sh.
- Password: droplet /root/hack-launch.pw (root 600), laptop ~/.config/netra/hack-launch.env (600). No cookie minted.
- netra-ask's audit / the commands record `by: hack_launch` for the test abort.

## Click-path test, 21:34 UTC (tools/click_path_test.py, run on the droplet against :8500 with basic auth)
    21:34:32 waiting up to 1800 s for a tracked person on jetson-c920
    21:34:33 live: {"t_ns": 1792877668697239674, "lag_s": 4.652, "n_boxes": 1, "clicked": {"track_uuid": "332cf2e50327473dac8a13c0b0c4b646", "kind": "person", "box": [190.7, 845.2, 210.0, 898.5], "conf": 0.69, "site_track_id": "66d170c9fca0bc65962b8c984838926f", "label": null}}
    21:34:37 POST /launch -> 200 {"id": "jetson-c920-op-20261024T213434Z-d0c2", "located": true, "lat": 32.87975802064769, "lon": -117.23189516134633, "loc_source": "sitefuse", "site_track_id": "66d170c9fca0bc65962b8c984838926f", "already_dispatched": false, "post_s": 3.066, "evidence": ["crop.jpg", "frame.jpg"]}
    21:34:38 POST /launch again (idempotent) -> 200 {"id": "jetson-c920-op-20261024T213434Z-d0c2", "located": true, "lat": 32.87975802064769, "lon": -117.23189516134633, "loc_source": "sitefuse", "site_track_id": "66d170c9fca0bc65962b8c984838926f", "already_dispatched": true}
    21:34:38 droplink first incident message after 5.55 s: {"seq": 1, "type": "netra.dispatch.incident", "verified": true, "dup": false, "msg_seq": 1, "status": "open", "verdict": "deploy", "located": true, "lat": 32.87975802064769, "lon": -117.23189516134633}
    21:34:46 GET /incidents/{id} -> 200 {"status": "open", "located": true, "lat": 32.879702059657525, "lon": -117.23189046699945, "loc_source": "sitefuse", "site_track_id": "66d170c9fca0bc65962b8c984838926f", "track_points": 4, "last_seen": "2026-10-24T21:34:35.891856+00:00", "forwarded": {"attempts": 3, "delivered": 3, "last": {"at": "2026-10-24T21:34:44.867580+00:00", "to": "127.0.0.1", "seq": 10, "netloc": "127.0.0.1:8510", "status": 200, "attempt": 1, "verdict": "deploy", "delivery_id": "8a6b8cc4-9932-4502-89dc-997e60fc0bba", "incident_status": "open"}}, "evidence": {"crop.jpg": "/ask/api/dispatch/evidence/jetson-c920-op-20261024T213434Z-d0c2/crop.jpg", "frame.jpg": "/ask/api/dispatch/evidence/jetson-c920-op-20261024T213434Z-d0c2/frame.jpg"}}
    21:34:51 POST /incidents/jetson-c920-op-20261024T213434Z-d0c2/abort -> 200 {"ok": true, "created": true, "command_id": "jetson-c920-op-20261024T213434Z-d0c2:abort:1", "seq": 1, "expires_at": "2026-10-24T21:44:49.293568+00:00", "delivery_status": "pending", "closed": "dismissed"}
    (script crashed after this: sauron-hack.service was restarted by someone else at 21:34:47, mid-test; the abort was still served)

droplink /messages for the incident (all verified HMAC, no duplicates, no unverified):
     1 21:34:37.577 netra.dispatch.incident  msg_seq=1   open deploy located 32.879758,-117.231895
     2-6,8-9,11-14  netra.dispatch.position  1 Hz (msg_seq 2..14)
     7,10,15        netra.dispatch.incident  open (throttled updates as the loop added track points)
    16 21:34:49.326 netra.dispatch.command   msg_seq=1  abort {'by': 'hack_launch', 'code': 'operator_abort'}
    17 21:34:50.958 netra.dispatch.incident  msg_seq=16 open          <- BUG, fixed in d85fee4 (see below)
    18 21:34:51.742 netra.dispatch.command   msg_seq=2  end {'code': 'dismissed'}
    19 21:34:51.771 netra.dispatch.incident  msg_seq=17 closed dismissed

netra-ask DB after:
    jetson-c920-op-20261024T213434Z-d0c2 | closed | dismissed | aborted_by hack_launch | judge {source: sauron-hackathon, operator: hack_launch}
    :abort:1 delivered {by: hack_launch, code: operator_abort}    :end:2 delivered {code: dismissed}

Numbers: click -> netra-ask accepted 3.07 s (includes the ring-frame fetch for evidence, about 1 s+); click -> first signed
incident in droplink 5.55 s from script start of POST (the POST itself returned at +4 s). Bound to sitefuse track
66d170c9..., loc_source sitefuse. Second click on the same person -> already_dispatched true, same id.

## Bug found and fixed (d85fee4, not deployed yet)
Message 17: an OPEN incident update reached the drone after the `abort`. The loop stopped only after netra-ask's abort
returned, so a 1 Hz re-post slipped in (and netra-ask can also flush its own 2 s throttled update). A drone could read an
open deploy after an abort as a new launch. Now abort = stop the loop (waits out a post in flight) -> close our incident
(drone gets the closed state + `end`) -> netra-ask's abort as the operator (drone gets `abort`). No open update can
follow. Unit tests 8/8. After the redeploy I can rerun tools/click_path_test.py to show it.

## /hack as a login destination
netra-internal: NEXT_OK += "/hack" (one line, branch hack-launch-next-ok @ 71d5695, pushed; that repo's remote has no
main, so it's branched off ask-login-and-map). Deployed: only common/auth.py copied (it was identical to the branch before),
backup /root/auth.py.bak-20261024, netra-map restarted, healthz 200. POST /map/login next=/hack/ -> 302 Location /hack/.
netra-ask and sauron-hack also import common.auth (user_of only); they pick the file up on their next restart, which is harmless.

## Earlier notes (droplink, launch.py design): see git log / hackdash/launch.py docstring
- droplink.service 127.0.0.1:8510, /etc/droplink.env holds only DISPATCH_WEBHOOK_SECRET; sqlite /var/lib/droplink/messages.sqlite.

## Repo push (00:30 UTC)
PUSHED 524e375 (hack-launch = origin/main 4e33b75 + 1 commit: droplink/README.md, ptzd/README.md, env templates with placeholders, ptzd/deployed/*.service). Everything I built or deployed today is on the branch: droplink/, ptzd/, hackdash/launch.py, hackdash/ptz.py, static/ptz.{js,css}, ptz_zoomcal.json, tools/click_path_test.py, ptz_test.py, ptz_shots.js, tests/test_{droplink,launch,ptz,ptz_guard}.py. Outside this repo: netra-internal branch hack-launch-next-ok @ 71d5695 (/hack in NEXT_OK).
INCIDENT: at 00:27 the live /opt/netra/sauron-hack/hackdash/ptz.py was an OLD copy WITHOUT the operator-only guard (someone deployed a stale tree; main itself has the guard). I restored it from main (sha e5ca429e…, = main), restarted sauron-hack, and checked as hack_launch: move, stop, home, home/save and lock returned 403, and ptzd's command count stayed at 187 → 187 (zero camera commands). Stale copy saved at droplet /root/ptz.py.stale-*. WHOEVER DEPLOYS: deploy from current main and check `sha256sum hackdash/ptz.py` = e5ca429ee395d808….
