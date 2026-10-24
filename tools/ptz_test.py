"""Real-camera PTZ test through https://internal.netralabs.net/hack/api (basic auth, ~/.config/netra/hack-launch.env).
Saves the current pose as Home, holds pan / tilt / zoom, lets the deadman stop a move, centres on a click, goes Home, and
prints the measured latency of every command. HACK_LAUNCH_USER=.. HACK_LAUNCH_PASSWORD=.. python3 ptz_test.py [cam]"""
import base64
import os as _os
import sys as _sys
if _os.environ.get("PTZ_TEST_WILLIAM_ASKED") != "1":     # HARD RULE (William, Oct 24): this MOVES the camera
    _sys.exit("ptz_test.py moves the Axis. Never run it unless William asked directly (then PTZ_TEST_WILLIAM_ASKED=1, and an operator login: hack_launch gets 403).")
import json
import os
import statistics
import sys
import time
import urllib.request

API = os.environ.get("HACK_API", "https://internal.netralabs.net/hack/api")
CAM = sys.argv[1] if len(sys.argv) > 1 else "axis-q6215"
AUTH = "Basic " + base64.b64encode(f"{os.environ['HACK_LAUNCH_USER']}:{os.environ['HACK_LAUNCH_PASSWORD']}".encode()).decode()
LAT: dict[str, list] = {}


def call(method, path, body=None):
    req = urllib.request.Request(f"{API}/ptz/{CAM}{path}", method=method, data=json.dumps(body or {}).encode() if method == "POST" else None,
                                 headers={"Authorization": AUTH, "Content-Type": "application/json", "User-Agent": "netra-ptz-test/1"})
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=10) as r:
        out = json.loads(r.read()) if r.headers.get_content_type() == "application/json" else r.read()
    ms = (time.monotonic() - t0) * 1000
    LAT.setdefault(path.split("?")[0], []).append((ms, out.get("ms") if isinstance(out, dict) else None))
    return out


def pose():
    s = call("GET", "/state")
    return {k: s[k] for k in ("pan", "tilt", "zoom")}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def hold(v, secs):
    t_end = time.monotonic() + secs
    while time.monotonic() < t_end:
        call("POST", "/move", v)
        time.sleep(0.25)
    call("POST", "/stop")
    time.sleep(0.6)


start = pose(); log("start", start)
call("POST", "/home/save"); log("saved start pose as Home (hack-home)")
hold({"pan": 0.5}, 1.5); p1 = pose(); log("pan right 1.5 s @0.5 ->", p1, "dpan", round(p1["pan"] - start["pan"], 2))
hold({"tilt": 0.5}, 1.5); p2 = pose(); log("tilt up 1.5 s @0.5 ->", p2, "dtilt", round(p2["tilt"] - p1["tilt"], 2))
hold({"zoom": 1.0}, 1.5); p3 = pose(); log("zoom in 1.5 s ->", p3, "dzoom", round(p3["zoom"] - p2["zoom"]), call("GET", "/state")["zoom_info"])
call("POST", "/move", {"pan": -0.3}); t0 = time.monotonic(); a = pose(); time.sleep(0.4); b = pose()
time.sleep(1.4); c = pose(); time.sleep(0.8); d = pose()
log("deadman: one /move then nothing. pan at +0.0/+0.4 s:", a["pan"], b["pan"], "| +1.8/+2.6 s (stopped?):", c["pan"], d["pan"],
    "->", "STOPPED" if abs(d["pan"] - c["pan"]) < 0.05 else "STILL MOVING")
before = pose(); call("POST", "/center", {"x": 0.75, "y": 0.5}); time.sleep(2.5); after = pose()
log("click centre at x=0.75,y=0.5 ->", after, "dpan", round(after["pan"] - before["pan"], 2))
snap = call("GET", "/snapshot.jpg"); log("snapshot", len(snap), "bytes")
call("POST", "/home"); time.sleep(4); home = pose()
log("Go Home ->", home, "vs start", start, "ok" if abs(home["pan"] - start["pan"]) < 0.3 and abs(home["tilt"] - start["tilt"]) < 0.3 else "OFF")
print("\nlatency (ms): laptop -> https /hack/api -> droplet -> tunnel -> Jetson ptzd -> camera, and the droplet->camera part")
for k, v in LAT.items():
    tot = [x[0] for x in v]; dro = [x[1] for x in v if x[1] is not None]
    print(f"  {k:12s} n={len(v):3d}  median {statistics.median(tot):6.0f}  p90 {sorted(tot)[int(len(tot) * .9)]:6.0f}"
          + (f"  | droplet->camera median {statistics.median(dro):5.0f}" if dro else ""))
