"""Real click-path test, run on the droplet: wait for a real tracked person on the camera, POST /launch, see the incident
in netra-ask and the signed message in droplink, abort, see `abort` + `end` in droplink. Prints a transcript.

  HACK_LAUNCH_USER=.. HACK_LAUNCH_PASSWORD=.. python3 click_path_test.py [camera] [wait_s]
"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

API = os.environ.get("HACK_API", "http://127.0.0.1:8500/hack/api")
AUTH = "Basic " + base64.b64encode(f"{os.environ['HACK_LAUNCH_USER']}:{os.environ['HACK_LAUNCH_PASSWORD']}".encode()).decode()
CAM = sys.argv[1] if len(sys.argv) > 1 else "jetson-c920"
WAIT_S = float(sys.argv[2]) if len(sys.argv) > 2 else 1800


def call(method, path, body=None):
    req = urllib.request.Request(API + path, method=method, headers={"Authorization": AUTH, "Content-Type": "application/json"},
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")
    except urllib.error.URLError as e:              # sauron-hack restarting: one retry after 3 s
        time.sleep(3)
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def messages(iid, since=0):
    return [m for m in call("GET", f"/drone/messages?since={since}")[1]["messages"] if m["incident_id"] == iid]


def short(m):
    b = m["body"] if isinstance(m["body"], dict) else {}
    inc = b.get("incident") or {}
    return {k: v for k, v in {"seq": m["seq"], "type": m["type"], "verified": m["verified"], "dup": m["duplicate"],
                              "msg_seq": m["msg_seq"], "command": b.get("command"), "reason": b.get("reason"),
                              "status": inc.get("status"), "verdict": inc.get("verdict"), "located": inc.get("located"),
                              "lat": inc.get("lat"), "lon": inc.get("lon"), "close_reason": inc.get("close_reason")}.items()
            if v is not None}


start_seq = max([m["seq"] for m in call("GET", "/drone/messages")[1]["messages"]], default=0)
deadline = time.time() + WAIT_S
log(f"waiting up to {WAIT_S:.0f} s for a tracked person on {CAM}")
while True:
    code, live = call("GET", f"/cameras/{CAM}/live")
    boxes = live.get("boxes") or [] if code == 200 else []
    boxes = [b for b in boxes if b.get("kind", "person") == "person"]
    if boxes:
        b = sorted(boxes, key=lambda b: (b.get("site_track_id") is None, -b["conf"]))[0]
        if b.get("site_track_id") or time.time() > deadline - WAIT_S + 20:
            break
    if time.time() > deadline:
        log("no tracked person appeared; nothing launched"); sys.exit(1)
    time.sleep(1)
log("live:", json.dumps({"t_ns": live["t_ns"], "lag_s": live["lag_s"], "n_boxes": len(boxes), "clicked": b}))
t0 = time.time()
code, out = call("POST", "/launch", {"camera_id": CAM, "track_uuid": b["track_uuid"], "t_ns": live["t_ns"]})
log(f"POST /launch -> {code}", json.dumps(out))
if code != 200:
    sys.exit(1)
iid = out["id"]
code2, again = call("POST", "/launch", {"camera_id": CAM, "track_uuid": b["track_uuid"], "t_ns": live["t_ns"]})
log(f"POST /launch again (idempotent) -> {code2}", json.dumps(again))
got = []
while time.time() - t0 < 20 and not any(m["type"] == "netra.dispatch.incident" and m["verified"] for m in got):
    time.sleep(0.25)
    got = messages(iid, start_seq)
first = next((m for m in got if m["type"] == "netra.dispatch.incident"), None)
log(f"droplink first incident message after {time.time() - t0:.2f} s:", json.dumps(short(first)) if first else None)
time.sleep(6)                                       # let the 1 Hz loop post a few track points / updates
code, inc = call("GET", f"/incidents/{iid}")
log("GET /incidents/{id} ->", code, json.dumps({k: inc.get(k) for k in ("status", "located", "lat", "lon", "loc_source",
    "site_track_id", "track_points", "last_seen", "forwarded", "evidence")}))
code, ab = call("POST", f"/incidents/{iid}/abort")
log(f"POST /incidents/{iid}/abort -> {code}", json.dumps(ab))
ta = time.time()
while time.time() - ta < 30:
    got = messages(iid, start_seq)
    cmds = {(m["body"] or {}).get("command") for m in got if m["type"] == "netra.dispatch.command" and m["verified"]}
    if {"abort", "end"} <= cmds:
        break
    time.sleep(0.5)
log("droplink messages for", iid)
for m in messages(iid, start_seq):
    print("   ", json.dumps(short(m)))
code, inc = call("GET", f"/incidents/{iid}")
log("final incident:", json.dumps({k: inc.get(k) for k in ("status", "close_reason", "aborted_by", "operator", "commands")}))
