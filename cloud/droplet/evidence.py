"""Keep the footage around each real incident: copy it out of the expiring archive into evidence/ (no lifecycle rule).

Runs on the droplet every 10 min (netra-cloud-evidence.timer). For every live dispatch_incidents row of the last 12 days
(the _ephemeral/footage/ lifecycle), the window is opened_at - 2 min .. (closed_at or opened_at) + 2 min, capped at
30 min. Every archived 60 s segment overlapping it is copied server-side, footage key
_ephemeral/footage/<camera>/<date>/<epoch>.mkv -> evidence/<camera>/<incident_id>/<epoch>.mkv, plus manifest.json. An
incident is done (STATE file) once the camera's archive holds a segment starting after the window end, i.e. the pod's
archiver (oldest first, hourly) has passed it; until then it is retried. Cameras without footage are skipped.
  evidence.py              run once        evidence.py --dry-run --camera C --at EPOCH   window + keys, copies nothing
Env (/etc/netra-ask-relay.env): S3_ENDPOINT S3_ACCESS_KEY_ID S3_SECRET_ACCESS_KEY; DB: ASK_DATABASE_URL (peer auth).
"""
from __future__ import annotations

import argparse
import json
import os
import time

import boto3
import psycopg

BUCKET, FOOT, EVID = "netra-lake", "_ephemeral/footage", "evidence"
PAD_S, MAX_S, SEG_S, KEEP_DAYS = 120, 1800, 60, 12
STATE = os.environ.get("EVIDENCE_STATE", "/var/lib/netra-cloud-evidence/done.txt")
s3 = boto3.client("s3", endpoint_url=os.environ["S3_ENDPOINT"], region_name="auto",
                  aws_access_key_id=os.environ["S3_ACCESS_KEY_ID"],
                  aws_secret_access_key=os.environ["S3_SECRET_ACCESS_KEY"])


def footage(cam: str, t0: float, t1: float) -> tuple[list[tuple[int, str]], int]:
    """(epoch, key) of archived segments overlapping [t0, t1], and the newest archived epoch on those days."""
    days = sorted({time.strftime("%Y-%m-%d", time.gmtime(t)) for t in (t0 - SEG_S, t1, t1 + 86400)})
    segs, newest = [], 0
    for day in days:
        for pg in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=f"{FOOT}/{cam}/{day}/"):
            for o in pg.get("Contents", []):
                stem = o["Key"].rsplit("/", 1)[1][:-4]
                if not stem.isdigit():
                    continue
                e = int(stem)
                newest = max(newest, e)
                if t0 - SEG_S < e < t1:
                    segs.append((e, o["Key"]))
    return sorted(segs), newest


def window(opened: float, closed: float | None) -> tuple[float, float]:
    t1 = (closed or opened) + PAD_S
    return opened - PAD_S, min(t1, opened - PAD_S + MAX_S)


def keep(inc: dict, dry: bool) -> bool:
    """Copy one incident's window; True once complete."""
    cam, iid = inc["camera_id"], inc["id"]
    t0, t1 = window(inc["opened"], inc["closed"])
    segs, newest = footage(cam, t0, t1)
    if dry:
        print(json.dumps({"camera": cam, "window": [t0, t1], "archived_until": newest, "complete": newest >= t1,
                          "keys": [k for _, k in segs]}, indent=1))
        return False
    for e, k in segs:
        s3.copy_object(Bucket=BUCKET, Key=f"{EVID}/{cam}/{iid}/{e}.mkv", CopySource={"Bucket": BUCKET, "Key": k})
    complete = newest >= t1
    s3.put_object(Bucket=BUCKET, Key=f"{EVID}/{cam}/{iid}/manifest.json", ContentType="application/json",
                  Body=json.dumps({"incident": iid, "camera": cam, "verdict": inc["verdict"], "why": inc["why"],
                                   "opened_at": inc["opened"], "closed_at": inc["closed"], "window": [t0, t1],
                                   "segments": [f"{e}.mkv" for e, _ in segs], "complete": complete}, indent=1))
    print(f"{iid} {cam}: {len(segs)} segments copied, complete={complete}", flush=True)
    return complete


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--camera")
    ap.add_argument("--at", type=float, help="dry run: incident open time (epoch s)")
    a = ap.parse_args()
    if a.dry_run:
        keep({"camera_id": a.camera, "id": "dry-run", "opened": a.at, "closed": None, "verdict": "", "why": ""}, True)
        return
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    done = set(open(STATE).read().split()) if os.path.exists(STATE) else set()
    with psycopg.connect(os.environ.get("ASK_DATABASE_URL", "postgresql:///netra_ask")) as c:
        rows = c.execute("""SELECT id, camera_id, verdict, why, extract(epoch FROM opened_at), extract(epoch FROM closed_at)
                            FROM dispatch_incidents WHERE mode = 'live' AND opened_at > now() - make_interval(days => %s)
                            ORDER BY opened_at""", (KEEP_DAYS,)).fetchall()
    cams = {p["Prefix"].split("/")[2] for p in s3.list_objects_v2(Bucket=BUCKET, Prefix=f"{FOOT}/", Delimiter="/")
            .get("CommonPrefixes", [])}
    for iid, cam, verdict, why, opened, closed in rows:
        if iid in done or cam not in cams:
            continue
        inc = {"id": iid, "camera_id": cam, "verdict": verdict, "why": why, "opened": float(opened),
               "closed": float(closed) if closed is not None else None}
        try:
            if keep(inc, False):
                with open(STATE, "a") as f:
                    f.write(iid + "\n")
        except Exception as e:  # noqa: BLE001 - retried next run
            print(f"{iid} {cam}: failed: {e}", flush=True)


if __name__ == "__main__":
    main()
