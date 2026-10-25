"""Cameras, the live ring frame and the edge person boxes at that frame's exact time, with real suspicion labels.

Box source: the Jetson edge unit's bucket POST (`positions[]`, every obs of every confirmed track, `[t_ns, x1, y1, x2,
y2, conf]` in source px). netra-ask keeps those only in memory (sitefuse Fuser.recent); the `tracks` table holds a
foot point path subsampled to 25 points, so it has no boxes. nginx mirrors the bucket POST to POST /_edge/bucket here
(token-checked like netra-ask's need_worker), so we hold the same obs with the same track uuids sitefuse binds on.

Frame: the edge ring through the droplet tunnel (`/frame?camera&t`, ffmpeg on the Jetson, about 1 s). /live returns
the newest frame time we hold boxes for AND have the JPEG of, so the picture and the boxes are one moment. One fetch in
flight per camera; JPEGs cached by t; a 404 (ring not written yet) falls back to the next older frame time >= 0.2 s back.

Labels: only from open live `dispatch_incidents` (red) / recent `dispatch_watch` (amber) rows whose record.site_track_id
is the box's site track (`site_track_links`, the fuser's persisted final state, ~10 s behind). Otherwise null.
judge_on: `systemctl is-active netra-dispatch@<cam>` on the Jetson over ssh (read-only; never started from here).
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import subprocess
import time
from collections import OrderedDict, deque
from pathlib import Path

import httpx
import psycopg
import yaml
from fastapi import APIRouter, HTTPException, Request, Response
from psycopg.rows import dict_row

log = logging.getLogger("hackdash.live")
router = APIRouter()

EDGE_URL = os.environ.get("ASK_EDGE_URL", "http://127.0.0.1:8450")
WORKER_TOKEN = os.environ.get("ASK_WORKER_TOKEN", "")
DATABASE_URL = os.environ.get("ASK_DATABASE_URL", "postgresql:///netra_ask")
SITES_YAML = Path(os.environ.get("ASK_SITES_YAML", "/opt/netra/netra-ask/ask/sites.yaml"))
TEST_RIGS = set(os.environ.get("HACK_TEST_RIGS", "jetson-c920").split(","))
# sites.yaml node_id -> ssh target for the judge check
JUDGE_SSH = dict(kv.split("=", 1) for kv in os.environ.get("HACK_JUDGE_SSH", "").split(",") if "=" in kv)
KNOWN_HOSTS = os.environ.get("HACK_KNOWN_HOSTS", "/tmp/sauron-hack-known_hosts")
KINDS = set(os.environ.get("HACK_BOX_KINDS", "person").split(","))   # edge track kinds drawn (person; others for testing)

KEEP_S = 60                 # obs kept per camera
LIVE_FEED_S = 30            # a camera is live if its newest heartbeat is this recent and it analyses frames
WATCH_LIVE_S = 120          # a dispatch_watch row has no close; treat it as current this long after it opened
FALLBACK_NS = 200_000_000   # 404 at t -> try the newest frame time at least this much older
MAX_TRIES = 3
NS = 1_000_000_000


class Obs:
    """Per camera: the edge person obs of the last KEEP_S, by frame time."""

    def __init__(self):
        self.by_cam: dict[str, deque] = {}     # cam -> (t_ns, track_uuid, box, conf, kind), appended in arrival order
        self.rx: dict[str, float] = {}         # cam -> wall time of the newest bucket
        self.arrival_lag: dict[str, float] = {}  # cam -> wall rx - newest obs t of that bucket (s)
        self.buckets: dict[str, int] = {}      # cam -> buckets received since start
        self.complete: dict[str, deque] = {}   # cam -> complete_ns - 1 per bucket: a frame time whose obs are all sent

    def push(self, cam: str, positions: list[dict], complete_ns: int | None = None, now: float | None = None):
        now = time.time() if now is None else now
        q = self.by_cam.setdefault(cam, deque())
        newest = 0
        self.buckets[cam] = self.buckets.get(cam, 0) + 1
        for p in positions:
            if p.get("kind") not in KINDS:
                continue
            for o in p.get("obs") or []:
                t = int(o[0])
                q.append((t, str(p["track_uuid"]), [float(v) for v in o[1:5]],
                          float(o[5]) if len(o) > 5 else float(p.get("conf") or 0), p["kind"]))
                newest = max(newest, t)
        self.rx[cam] = now
        if newest:
            self.arrival_lag[cam] = round(now - newest / NS, 3)
        cq = self.complete.setdefault(cam, deque(maxlen=KEEP_S))
        if complete_ns:
            cq.append(int(complete_ns) - 1)
        cut = max([x[0] for x in q] + list(cq), default=0) - KEEP_S * NS
        while q and q[0][0] < cut:
            q.popleft()

    def times(self, cam: str) -> list[int]:
        """Frame times we know the full confirmed-box set of, newest first: every obs time, plus complete_ns - 1 of each
        bucket (complete_ns = last stepped frame + 1, or a tentative track's first frame; no obs before it comes later),
        so an empty scene still advances with zero boxes instead of freezing on the last frame that had a person."""
        return sorted({x[0] for x in self.by_cam.get(cam, ())} | set(self.complete.get(cam, ())), reverse=True)

    def at(self, cam: str, t: int) -> list[dict]:
        out = {}
        for tt, tid, box, conf, kind in self.by_cam.get(cam, ()):
            if tt == t:
                out[tid] = {"track_uuid": tid, "kind": kind, "box": [round(v, 1) for v in box], "conf": round(conf, 3)}
        return list(out.values())


OBS = Obs()


def candidates(times: list[int], tried: int | None = None) -> int | None:
    """The frame time to fetch: the newest, or after a 404 at `tried`, the newest at least FALLBACK_NS older."""
    if tried is None:
        return times[0] if times else None
    return next((t for t in times if t <= tried - FALLBACK_NS), None)


# ---------------------------------------------------------------- sources: sites.yaml, Postgres, Jetson

def yaml_cameras() -> list[dict]:
    out = []
    for s in yaml.safe_load(SITES_YAML.read_text())["sites"]:
        for c in s["cameras"]:
            out.append({**c, "yaml_site": s["id"]})
    return out


def db_rows(sql: str, *args) -> list[dict]:
    with psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=True) as conn:
        return conn.execute(sql, args).fetchall()


_ttl: dict = {}


def cached(key, ttl_s: float, fn):
    hit = _ttl.get(key)
    if hit and time.monotonic() - hit[0] < ttl_s:
        return hit[1]
    v = fn()
    _ttl[key] = (time.monotonic(), v)
    return v


def judge_on(cam: dict) -> bool | None:
    """netra-dispatch@<cam> active on its Jetson; None when we cannot tell (no ssh mapping, ssh failed)."""
    target = JUDGE_SSH.get(cam.get("node_id") or "")
    if not target:
        return None

    def check():
        try:
            r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=4", "-o", "StrictHostKeyChecking=accept-new",
                                "-o", f"UserKnownHostsFile={KNOWN_HOSTS}", target, "systemctl", "is-active",
                                f"netra-dispatch@{cam['id']}"], capture_output=True, text=True, timeout=8)
        except (OSError, subprocess.TimeoutExpired):
            return None
        state = r.stdout.strip()
        return True if state == "active" else False if state in ("inactive", "failed", "activating", "deactivating") else None
    return cached(("judge", cam["id"]), 10, check)


def camera_list() -> list[dict]:
    cams = yaml_cameras()
    ids = [c["id"] for c in cams]
    sc = {r["cid"]: r for r in db_rows("""SELECT DISTINCT ON (source->>'camera_id') source->>'camera_id' AS cid, site_id, name,
                                              fit IS NOT NULL AS calibrated FROM site_cameras WHERE source->>'camera_id' = ANY(%s)
                                              ORDER BY source->>'camera_id', (fit IS NOT NULL) DESC, updated_at DESC""", ids)}
    beats = {r["camera_id"]: r for r in db_rows("""SELECT DISTINCT ON (camera_id) camera_id, received_at, fps_analysed,
                                                     extract(epoch FROM now() - received_at) AS age_s
                                                   FROM feed_health WHERE camera_id = ANY(%s)
                                                   ORDER BY camera_id, received_at DESC""", ids)}
    out = []
    for c in cams:
        s, b = sc.get(c["id"]), beats.get(c["id"])
        live = bool(b and b["age_s"] < LIVE_FEED_S and (b["fps_analysed"] or 0) > 0)
        out.append({"camera_id": c["id"], "name": c.get("name") or c["id"], "site_id": s["site_id"] if s else None,
                    "live": live, "fps": (b["fps_analysed"] if live else 0) if b else None,
                    "calibrated": bool(s and s["calibrated"]), "test_rig": c["id"] in TEST_RIGS,
                    "src_w": c.get("width"), "src_h": c.get("height")})
    return out


def _cam(cam_id: str) -> dict:
    c = next((c for c in yaml_cameras() if c["id"] == cam_id), None)
    if c is None:
        raise HTTPException(404, "no such camera")
    return c


def top_facts(facts: dict | None, n: int = 2) -> dict:
    num = {k: v for k, v in (facts or {}).items() if isinstance(v, (int, float)) and k != "normal"}
    return dict(sorted(num.items(), key=lambda kv: -kv[1])[:n])


def labels_for(cam_id: str, uuids: list[str]) -> tuple[dict, dict]:
    """(edge track uuid -> site track id, site track id -> label) from Postgres."""
    if not uuids:
        return {}, {}
    links = db_rows("""SELECT DISTINCT ON (cam_track_id) cam_track_id, site_track_id FROM site_track_links
                       WHERE camera_id=%s AND cam_track_id = ANY(%s) ORDER BY cam_track_id, (t_unbind IS NULL) DESC, t_bind DESC""",
                    cam_id, uuids)
    st_of = {r["cam_track_id"]: r["site_track_id"] for r in links}
    sts = sorted(set(st_of.values()))
    if not sts:
        return st_of, {}
    lab = {}
    for r in db_rows("""SELECT id, 'watch' AS verdict, record->>'why' AS why, record, record->>'site_track_id' AS st
                        FROM dispatch_watch WHERE record->>'site_track_id' = ANY(%s)
                        AND opened_at > now() - make_interval(secs => %s) ORDER BY opened_at""", sts, WATCH_LIVE_S):
        lab[r["st"]] = _label(r, "watch")
    for r in db_rows("""SELECT id, verdict, why, record, record->>'site_track_id' AS st FROM dispatch_incidents
                        WHERE status='open' AND mode='live' AND record->>'site_track_id' = ANY(%s) ORDER BY updated_at""", sts):
        lab[r["st"]] = _label(r, "incident")         # an open incident outranks a watch episode
    return st_of, lab


def _label(r: dict, kind: str) -> dict:
    rec = r["record"] if isinstance(r["record"], dict) else json.loads(r["record"])
    return {"kind": kind, "verdict": r["verdict"], "why_label": rec.get("why_label") or r["why"], "e": rec.get("evidence_e"),
            "facts": top_facts(rec.get("facts")), "caption": rec.get("caption_text"), "incident_id": r["id"]}


# ---------------------------------------------------------------- frames

class Frames:
    """Ring JPEGs by (cam, t); one edge fetch in flight per camera."""

    def __init__(self, keep: int = 32):
        self.jpeg: OrderedDict = OrderedDict()
        self.keep = keep
        self.locks: dict[str, asyncio.Lock] = {}
        self.fetch_s: dict[str, float] = {}      # cam -> duration of the last successful fetch
        self.client: httpx.AsyncClient | None = None

    def put(self, cam: str, t: int, data: bytes):
        self.jpeg[(cam, t)] = data
        self.jpeg.move_to_end((cam, t))
        while len(self.jpeg) > self.keep:
            self.jpeg.popitem(last=False)

    async def edge_frame(self, cam: str, t: int) -> bytes | None:
        """One fetch, None on 404. Raises on any other failure."""
        if (cam, t) in self.jpeg:
            return self.jpeg[(cam, t)]
        if self.client is None:
            self.client = httpx.AsyncClient(timeout=20)
        async with self.locks.setdefault(cam, asyncio.Lock()):
            if (cam, t) in self.jpeg:
                return self.jpeg[(cam, t)]
            t0 = time.monotonic()
            r = await self.client.get(f"{EDGE_URL}/frame", params={"camera": cam, "t": t},
                                      headers={"Authorization": f"Bearer {WORKER_TOKEN}"})
            if r.status_code == 404:
                return None
            r.raise_for_status()
            self.fetch_s[cam] = round(time.monotonic() - t0, 3)
            self.put(cam, t, r.content)
            return r.content


FRAMES = Frames()
_current: dict[str, int] = {}                    # cam -> newest frame time that has both JPEG and boxes
_task: dict[str, asyncio.Task] = {}
_watched: dict[str, float] = {}                  # cam -> monotonic time of the last /live poll
WATCH_S = 15                                     # prefetch on bucket arrival only while someone polled this recently


async def _advance(cam: str):
    """Fetch the newest box frame time (falling back on 404) and make it current when it is newer."""
    tried = None
    for _ in range(MAX_TRIES):
        t = candidates(OBS.times(cam), tried)
        if t is None or t <= _current.get(cam, 0):
            return
        try:
            if await FRAMES.edge_frame(cam, t) is not None:
                _current[cam] = t
                return
        except Exception as e:
            log.warning("edge frame %s @%d: %s", cam, t, e)
            return
        tried = t


def on_bucket(cam: str):
    """A new bucket arrived (mirror or relay): fetch its frame now, not at the next poll, while someone is watching."""
    if time.monotonic() - _watched.get(cam, -1e9) < WATCH_S:
        kick(cam)


def kick(cam: str) -> asyncio.Task | None:
    t = _task.get(cam)
    if t is None or t.done():
        _task[cam] = t = asyncio.create_task(_advance(cam))
    return t


# ---------------------------------------------------------------- routes

@router.get("/cameras")
async def cameras():
    return await asyncio.to_thread(lambda: cached("cameras", 2, camera_list))


@router.get("/cameras/{cam}/live")
async def live(cam: str, request: Request):
    c = _cam(cam)
    _watched[cam] = time.monotonic()
    task = kick(cam)
    if cam not in _current and task is not None:
        try:
            await asyncio.wait_for(asyncio.shield(task), 4)
        except asyncio.TimeoutError:
            pass
    jo = await asyncio.to_thread(judge_on, c)
    t = _current.get(cam)
    base = {"camera_id": cam, "src_w": c.get("width"), "src_h": c.get("height"), "judge_on": jo,
            "obs_arrival_lag_s": OBS.arrival_lag.get(cam), "buckets_rx": OBS.buckets.get(cam, 0), "frame_fetch_s": FRAMES.fetch_s.get(cam)}
    if t is None:
        why = "no edge buckets received (is the nginx mirror on?)" if not OBS.buckets.get(cam) else \
            "no complete frame time from the edge in the last minute" if not OBS.times(cam) else "no ring frame yet"
        return {**base, "t_ns": None, "frame_url": None, "lag_s": None, "boxes": [], "why": why}
    boxes = OBS.at(cam, t)
    st_of, lab = await asyncio.to_thread(labels_for, cam, [b["track_uuid"] for b in boxes])
    for b in boxes:
        b["site_track_id"] = st_of.get(b["track_uuid"])
        b["label"] = lab.get(b["site_track_id"]) if b["site_track_id"] else None
    prefix = request.scope.get("root_path", "") + request.url.path.rsplit("/live", 1)[0]
    return {**base, "t_ns": t, "frame_url": f"{prefix}/frame.jpg?t={t}", "lag_s": round(time.time() - t / NS, 3),
            "boxes": boxes}


@router.get("/cameras/{cam}/frame.jpg")
async def frame(cam: str, t: int):
    _cam(cam)
    for tt in (t, t - FALLBACK_NS):
        try:
            data = await FRAMES.edge_frame(cam, tt)
        except Exception as e:
            raise HTTPException(502, f"edge frame failed: {type(e).__name__}")
        if data is not None:
            return Response(data, media_type="image/jpeg", headers={"Cache-Control": "max-age=3600", "X-Frame-T": str(tt)})
    raise HTTPException(404, "no footage at that time")


@router.post("/_edge/bucket")
async def edge_bucket(request: Request):
    """The nginx mirror of the Jetson's POST /ask/api/edge/bucket. Same token as netra-ask's need_worker."""
    got = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not WORKER_TOKEN or not hmac.compare_digest(got, WORKER_TOKEN):
        raise HTTPException(401, "bad worker token")
    form = await request.form()
    result = json.loads(form["result"])
    cam = str(result["camera_id"])
    OBS.push(cam, result.get("positions") or [], result.get("complete_ns"))
    on_bucket(cam)
    return {"ok": True}
