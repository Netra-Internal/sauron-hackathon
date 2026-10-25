"""Shadow vs production for one camera over one window, from real records only.

  pod side:  buckets.jsonl / heartbeats.jsonl from the shadow sink (R2 _work/sauron-cloud/pod/shadow.tgz, untarred)
  prod side: netra_ask Postgres on the droplet (segments.stats per bucket, feed_health, tracks), read-only via ssh+psql

usage: compare.py <shadow_dir> <camera> <from_utc> <to_utc>     e.g. compare.py /tmp/sh jetson-c920 21:30 21:45
Prints per side: buckets, analysed fps, detections/frame, infer ms, person/vehicle tracks (≥ min_hits, as stored),
and, when both saw people, the start-time offset of matched person tracks (pod − Jetson: the extra delay of the cloud
path, since both edges stamp frames at their own arrival time − latency_ms)."""
from __future__ import annotations

import datetime as dt
import json
import os
import statistics as st
import subprocess
import sys

D = os.environ.get("DROPLET") or os.environ["HACK_HOST"]  # root@<droplet>


def psql(sql: str) -> list[list[str]]:
    out = subprocess.run(["ssh", "-o", "BatchMode=yes", D, f"sudo -u netra psql netra_ask -At -F '\t' -c \"{sql}\""],
                         capture_output=True, text=True, check=True).stdout
    return [r.split("\t") for r in out.splitlines() if r]


def q(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))] if xs else None


def main():
    sdir, cam, t0, t1 = sys.argv[1:5]
    day = dt.datetime.now(dt.timezone.utc).date().isoformat()
    a = dt.datetime.fromisoformat(f"{day}T{t0}+00:00") if "T" not in t0 else dt.datetime.fromisoformat(t0)
    b = dt.datetime.fromisoformat(f"{day}T{t1}+00:00") if "T" not in t1 else dt.datetime.fromisoformat(t1)
    a_ns, b_ns = int(a.timestamp() * 1e9), int(b.timestamp() * 1e9)
    span = (b_ns - a_ns) / 1e9

    # ---- pod (shadow)
    bk = [json.loads(l) for l in open(os.path.join(sdir, "buckets.jsonl"))]
    bk = [r for r in bk if a_ns <= r["result"]["t_to_ns"] < b_ns and r["result"]["camera_id"] == f"{cam}-cloud"]
    hb = [json.loads(l) for l in open(os.path.join(sdir, "heartbeats.jsonl"))]
    hb = [h for h in hb if a_ns <= h["recv_ns"] < b_ns and h["camera_id"] == f"{cam}-cloud"]
    pod_tracks = {}
    for r in bk:
        for t in r["result"]["tracks"]:
            pod_tracks[t["uuid"]] = t
    pod = {"buckets": len(bk), "analysed": sum(r["result"]["stats"]["analysed"] for r in bk),
           "detections": sum(r["result"]["stats"]["detections"] for r in bk),
           "infer_ms": [h["infer_ms"] for h in hb if h.get("fps_analysed")],
           "fps_in": [h["fps_in"] for h in hb], "frame_age": [h["frame_age_s"] for h in hb],
           "tracks": [(t["kind"], t["t_start_ns"]) for t in pod_tracks.values()]}

    # ---- production (Jetson)
    seg = psql(f"select stats from segments where camera_id='{cam}' and lane='edge' and end_ns >= {a_ns} and end_ns < {b_ns}")
    seg = [json.loads(s[0]) for s in seg]
    fh = psql(f"select fps_in, fps_analysed, infer_ms, frame_age_s from feed_health where camera_id='{cam}' "
              f"and received_at >= '{a.isoformat()}' and received_at < '{b.isoformat()}'")
    tr = psql(f"select kind, extract(epoch from t_start) from tracks where camera_id='{cam}' "
              f"and t_start >= '{a.isoformat()}' and t_start < '{b.isoformat()}'")
    prod = {"buckets": len(seg), "analysed": sum(s.get("analysed", 0) for s in seg),
            "detections": sum(s.get("detections", 0) for s in seg),
            "infer_ms": [float(r[2]) for r in fh if float(r[1] or 0) > 0], "fps_in": [float(r[0]) for r in fh],
            "frame_age": [float(r[3]) for r in fh], "tracks": [(k, int(float(s) * 1e9)) for k, s in tr]}

    print(f"camera {cam}, {a:%H:%M:%S}-{b:%H:%M:%S} UTC ({span / 60:.1f} min)")
    print(f"{'':28}{'Jetson (prod)':>16}{'pod (shadow)':>16}")
    for name, f in [("buckets", lambda s: s["buckets"]),
                    ("analysed fps", lambda s: round(s["analysed"] / span, 2)),
                    ("detections / frame", lambda s: round(s["detections"] / max(s["analysed"], 1), 2)),
                    ("infer ms p50", lambda s: q(s["infer_ms"], .5)),
                    ("infer ms p90", lambda s: q(s["infer_ms"], .9)),
                    ("frame age s p50", lambda s: q(s["frame_age"], .5)),
                    ("person tracks", lambda s: sum(k == "person" for k, _ in s["tracks"])),
                    ("vehicle tracks", lambda s: sum(k != "person" for k, _ in s["tracks"]))]:
        print(f"{name:28}{str(f(prod)):>16}{str(f(pod)):>16}")
    # matched person tracks: each Jetson track start to the nearest pod track start within 3 s
    js = sorted(t for k, t in prod["tracks"] if k == "person")
    ps = sorted(t for k, t in pod["tracks"] if k == "person")
    offs = []
    for t in js:
        near = min(ps, key=lambda p: abs(p - t), default=None)
        if near is not None and abs(near - t) <= 3e9:
            offs.append((near - t) / 1e9)
    if offs:
        print(f"matched person tracks {len(offs)}/{len(js)}: start offset pod−Jetson p50 {st.median(offs):+.2f} s, "
              f"p10 {q(offs, .1):+.2f}, p90 {q(offs, .9):+.2f}")
    else:
        print("matched person tracks: none (no people on one side)")


if __name__ == "__main__":
    main()
