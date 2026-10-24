"""Round trip of /hack/api/calib on the deployed app, on a THROWAWAY site + still-only camera (never a production record):
create site -> camera -> freeze a real frame -> draft fit -> save (frame upload + PATCH) -> netra-ask's stored fit ==
the draft -> /project of a pair pixel lands on its map point -> boundary save -> delete camera + site -> gone.
The pairs: the production camera's real pairs (read only), re-scaled onto the frozen frame's size, since the frozen
frame is the same fixed camera. Credentials: ~/.config/netra/hack-launch.env (service account hack_launch).
"""
import json
import math
import os
import sys
import urllib.request
from base64 import b64encode
from pathlib import Path

ENV = dict(l.split("=", 1) for l in Path.home().joinpath(".config/netra/hack-launch.env").read_text().split() if "=" in l)
B = os.environ.get("HACK_URL", "https://internal.netralabs.net/hack/api")
AUTH = "Basic " + b64encode(f"{ENV['HACK_LAUNCH_USER']}:{ENV['HACK_LAUNCH_PASSWORD']}".encode()).decode()
PROD_SITE, PROD_CAM, FEED = "ucsd-design-innovation-building-c1dd", "camera-1-5621", "jetson-c920"


def call(method, path, body=None):
    req = urllib.request.Request(B + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Authorization": AUTH, "User-Agent": "calib-roundtrip/1", **({"Content-Type": "application/json"} if body is not None else {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return r.status, json.loads(raw) if raw and r.headers.get("content-type", "").startswith("application/json") else raw
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]


def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        raise SystemExit(1)


def metres(a, b):
    k = math.pi / 180 * 6371008.8
    return math.hypot((a[1] - b[1]) * k * math.cos(math.radians(a[0])), (a[0] - b[0]) * k)


st, prod = call("GET", f"/calib/sites/{PROD_SITE}")
pc = next(c for c in prod["cameras"] if c["id"] == PROD_CAM)
prod_before = {k: pc[k] for k in ("updated_at", "points", "fit")}
st, site = call("POST", "/calib/sites", {"name": "calib roundtrip (delete me)", "lat": pc["lat"], "lon": pc["lon"], "zoom": 19})
ok(st == 200 and site["id"], f"throwaway site {site['id']}")
sid = site["id"]
try:
    st, cam = call("POST", f"/calib/sites/{sid}/cameras", {"name": "roundtrip still", "lat": pc["lat"], "lon": pc["lon"], "yaw": pc["yaw"], "source": {"kind": "upload"}})
    ok(st == 200 and cam["source"] == {"kind": "upload"}, f"still-only camera {cam['id']} (no live link: can't take over {FEED}'s projection)")
    cid = cam["id"]
    st, fz = call("POST", f"/calib/freeze/{FEED}")
    ok(st == 200, f"froze a real {FEED} frame {fz.get('width')}x{fz.get('height')} from {fz.get('source')}, {fz.get('age_s')} s old")
    sx, sy = fz["width"] / pc["frame"]["width"], fz["height"] / pc["frame"]["height"]
    pts = [{"u": p["u"] * sx, "v": p["v"] * sy, "lat": p["lat"], "lon": p["lon"]} for p in pc["points"]]
    model = {k: cam[k] for k in ("lat", "lon", "height_m", "yaw", "pitch", "roll", "hfov")}
    st, d = call("POST", "/calib/fit", {"model": model, "frame": {"width": fz["width"], "height": fz["height"]}, "points": pts, "fit_position": False})
    ok(st == 200 and d["fit"]["n"] == len(pts), f"draft fit: {d['fit']['n']} pairs, {d['fit']['rms_px']:.1f} px rms, LOO median {d['fit']['loo']['median_m']} m, max {d['fit']['loo']['max_m']} m, at_limit {d['fit']['at_limit']}")
    st, c1 = call("POST", f"/calib/sites/{sid}/cameras/{cid}/frame?frozen={fz['token']}")
    ok(st == 200 and c1["frame"]["width"] == fz["width"] and not c1["points"], f"save 1: frame uploaded to netra-ask ({c1['frame']['file']}, {c1['frame']['from']})")
    st, c2 = call("PATCH", f"/calib/sites/{sid}/cameras/{cid}", {**d["model"], "points": pts, "fit_position": False, "refit": True})
    ok(st == 200 and c2["calibrated"], f"save 2: PATCH -> calibrated, stored LOO median {c2['fit']['loo']['median_m']} m")
    ok(c2["fit"]["loo"] == d["fit"]["loo"] and abs(c2["fit"]["rms_px"] - d["fit"]["rms_px"]) < 1e-6, "netra-ask's stored fit == the draft shown before saving")
    st, re = call("GET", f"/calib/sites/{sid}")
    c3 = next(c for c in re["cameras"] if c["id"] == cid)
    ok(c3["points"] == c2["points"] and c3["fit"]["n"] == len(pts), "re-read from netra-ask: pairs + fit persisted")
    st, img = call("GET", f"/calib/sites/{sid}/cameras/{cid}/frame.jpg")
    ok(st == 200 and img[:2] == b"\xff\xd8", f"saved frame served back ({len(img)} bytes JPEG)")
    best = min(range(len(pts)), key=lambda i: c2["fit"]["per_point"][i]["m"] or 1e9)
    st, pr = call("POST", f"/calib/sites/{sid}/cameras/{cid}/project", {"pixels": [[pts[best]["u"], pts[best]["v"]]], "space": "frame"})
    g = pr["points"][0]
    off = metres((g["lat"], g["lon"]), (pts[best]["lat"], pts[best]["lon"]))
    ok(abs(off - c2["fit"]["per_point"][best]["m"]) < 0.05, f"/project pair {best + 1}'s pixel -> {g['lat']:.6f},{g['lon']:.6f} ±{g['radius_m']} m, {off:.2f} m from its map point (= per_point m {c2['fit']['per_point'][best]['m']})")
    st, pe = call("GET", f"/calib/sites/{sid}/cameras/{cid}/people")
    ok(st == 200 and pe["people"] == [] and "no live feed" in pe["why"], f"people on a still-only record: {pe['why']}")
    ring = [[pc["lat"] + a, pc["lon"] + b] for a, b in ((3e-4, -3e-4), (3e-4, 3e-4), (-3e-4, 3e-4), (-3e-4, -3e-4))]
    st, s2 = call("PATCH", f"/calib/sites/{sid}", {"boundary": ring})
    ok(st == 200 and s2["boundary"] == ring, "boundary saved (4 corners)")
    st, _ = call("DELETE", f"/calib/sites/{sid}/cameras/{cid}")
    ok(st == 204, "camera record deleted")
finally:
    st, _ = call("DELETE", f"/calib/sites/{sid}")
    print(("PASS " if st == 204 else "FAIL ") + f"throwaway site deleted ({st})")
st, gone = call("GET", f"/calib/sites/{sid}")
ok(st == 404, "site is gone (404)")
st, prod2 = call("GET", f"/calib/sites/{PROD_SITE}")
pc2 = next(c for c in prod2["cameras"] if c["id"] == PROD_CAM)
ok({k: pc2[k] for k in prod_before} == prod_before, f"production {PROD_CAM} untouched (updated_at {pc2['updated_at']})")
