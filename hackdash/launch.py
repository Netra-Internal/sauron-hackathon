"""Send drone, abort, incident state and what the drone received, for the send-drone page.

Nothing here decides a launch itself: POST /launch builds an operator incident (verdict deploy, why operator_launch) and
posts it through netra-ask's existing worker endpoint POST /ask/api/dispatch/incidents, so netra-ask's store.accept
locates it, binds it to the sitefuse site track, signs it and forwards it to DISPATCH_WEBHOOK exactly as it does the
watcher's incidents. Sauron's own autonomous launches are untouched (their ids have no `-op-`).

Person boxes come from hackdash.live (the edge bucket obs, same track uuids as sitefuse). The record's track point is
an exact edge obs, so netra-ask's track_at binds it (±0.5 s, IoU).

Lifecycle: no watcher ever posts to an operator incident, so a 1 Hz loop re-posts each open one of ours: a new track point
while the person (edge track, or any edge track of the same site track) is still seen, and always a fresh updated_at.
Once the person has had no point for DISPATCH_SUBJECT_LOST_S (30 s) netra-ask closes it subject_lost and sends `end`.

Abort: netra-ask's abort route needs the internal login, so the operator's own Cookie / Authorization is passed through
(no service account; the audit names the operator). For our incidents the incident is then closed through the worker
endpoint (close_reason dismissed, aborted_by): that stops the loop and makes netra-ask send `end` as well, so no later
update can re-trigger a launch.

Drone messages: read from droplink (droplink/, 127.0.0.1:8510), our stand-in for the drone's receiver.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import secrets
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone

import psycopg
from fastapi import APIRouter, HTTPException, Request
from psycopg.rows import dict_row
from pydantic import BaseModel

log = logging.getLogger("hackdash.launch")
router = APIRouter()

ASK_URL = os.environ.get("ASK_URL", "http://127.0.0.1:8400/ask")
WORKER_TOKEN = os.environ.get("ASK_WORKER_TOKEN", "")
DATABASE_URL = os.environ.get("ASK_DATABASE_URL", "postgresql:///netra_ask")
DROPLINK_URL = os.environ.get("DROPLINK_URL", "http://127.0.0.1:8510")
SOURCE = "sauron-hackathon"       # record.judge.source of the incidents this demo launched
TICK_S = 1.0
TRACKED_S = 10.0                  # a clicked track whose newest obs is older than this (vs the camera's newest) is gone
KEEP_POINTS = 30                  # track points kept on the record (netra-ask reads the last one, and first/last for heading)
NS = 1_000_000_000
DERIVED = ("lat", "lon", "radius_m", "located", "loc_source", "radius_kind", "loc_at", "site_track_id", "speed_mps",
           "cov_en_m2", "heading_deg", "moved_m", "site_id")   # store.locate_record recomputes these on every post


class LaunchBody(BaseModel):
    camera_id: str
    track_uuid: str
    t_ns: int


# ---------------------------------------------------------------- helpers

def _live():
    try:
        from hackdash import live
        return live
    except Exception as e:                           # noqa: BLE001 — answered as 503 below
        log.warning("hackdash.live unavailable: %s", e)
        return None


def _user(req: Request) -> str | None:
    return getattr(req.state, "user", None)          # set by hackdash.app's login middleware


def db_rows(sql: str, *args) -> list[dict]:
    with psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=True) as c:
        return c.execute(sql, args).fetchall()


def iso(t_ns: int | None = None) -> str:
    t = datetime.now(timezone.utc) if t_ns is None else datetime.fromtimestamp(t_ns / NS, timezone.utc)
    return t.isoformat()


def _ns(at: str | None) -> int:
    try:
        return int(datetime.fromisoformat(str(at).replace("Z", "+00:00")).timestamp() * NS)
    except ValueError:
        return 0


def _http(method: str, url: str, body: bytes | None = None, headers: dict | None = None, timeout: float = 15) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"detail": raw.decode("utf-8", "replace")[:300]}


def post_incident(rec: dict, files: dict[str, bytes] | None = None) -> dict:
    """POST /ask/api/dispatch/incidents (multipart: result + evidence files) with the worker token."""
    b = "----hack" + uuid.uuid4().hex
    parts = [f'--{b}\r\nContent-Disposition: form-data; name="result"\r\n\r\n'.encode() + json.dumps(rec).encode() + b"\r\n"]
    for name, data in (files or {}).items():
        parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{name}"; filename="{name}"\r\n'
                     f"Content-Type: image/jpeg\r\n\r\n".encode() + data + b"\r\n")
    parts.append(f"--{b}--\r\n".encode())
    code, out = _http("POST", f"{ASK_URL}/api/dispatch/incidents", b"".join(parts),
                      {"Content-Type": f"multipart/form-data; boundary={b}", "Authorization": f"Bearer {WORKER_TOKEN}"})
    if code != 200:
        raise RuntimeError(f"netra-ask {code}: {out.get('detail', out)}")
    return out


def newest_obs(live, cam: str, uuids: set[str]) -> tuple[int, str, list[float]] | None:
    """The newest edge obs (t, track uuid, box) of any of these edge tracks."""
    best = None
    for t, tid, box, _conf, _kind in list(live.OBS.by_cam.get(cam, ())):
        if tid in uuids and (best is None or t > best[0]):
            best = (t, tid, box)
    return best


def obs_at(live, cam: str, uuid_: str, t_ns: int) -> list[float] | None:
    for t, tid, box, _conf, _kind in list(live.OBS.by_cam.get(cam, ())):
        if tid == uuid_ and t == t_ns:
            return box
    return None


def evidence(jpeg: bytes | None, box: list[float], src_w: int, src_h: int) -> dict[str, bytes]:
    """frame.jpg with the clicked box drawn, crop.jpg around it. Never blocks the launch: {} on any failure."""
    if not jpeg:
        return {}
    try:
        from PIL import Image, ImageDraw
        im = Image.open(io.BytesIO(jpeg)).convert("RGB")
        sx, sy = im.width / (src_w or im.width), im.height / (src_h or im.height)
        x1, y1, x2, y2 = box[0] * sx, box[1] * sy, box[2] * sx, box[3] * sy
        w, h = x2 - x1, y2 - y1
        crop = im.crop((max(0, int(x1 - 0.25 * w)), max(0, int(y1 - 0.15 * h)),
                        min(im.width, int(x2 + 0.25 * w)), min(im.height, int(y2 + 0.15 * h))))
        ImageDraw.Draw(im).rectangle((x1, y1, x2, y2), outline=(255, 48, 48), width=3)
        out = {}
        for name, img in (("frame.jpg", im), ("crop.jpg", crop)):
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=85)
            out[name] = buf.getvalue()
        return out
    except Exception as e:                           # noqa: BLE001
        log.warning("evidence failed: %s", e)
        return {"frame.jpg": jpeg}


def summary(row: dict, commands: list[dict] | None = None) -> dict:
    r = row["record"]
    fwd = row.get("forwarded") or []
    return {"id": row["id"], "camera_id": row["camera_id"], "site_id": row["site_id"], "status": row["status"],
            "verdict": row["verdict"], "why": row["why"], "close_reason": r.get("close_reason"),
            "opened_at": iso_of(row["opened_at"]), "updated_at": iso_of(row["updated_at"]), "closed_at": iso_of(row["closed_at"]),
            "located": bool(r.get("located")), "lat": row["lat"], "lon": row["lon"], "radius_m": row["radius_m"],
            "loc_source": r.get("loc_source"), "site_track_id": r.get("site_track_id"), "edge_track": r.get("edge_track"),
            "operator": (r.get("judge") or {}).get("operator"), "aborted_by": r.get("aborted_by"),
            "track_points": len(r.get("track") or []), "last_seen": (r.get("track") or [{}])[-1].get("at"),
            "evidence": {n: f"/ask/api/dispatch/evidence/{row['id']}/{n}" for n in (row.get("evidence") or [])},
            "forwarded": {"attempts": len(fwd), "delivered": sum(1 for f in fwd if 200 <= (f.get("status") or 0) < 300),
                          "last": fwd[-1] if fwd else None},
            "commands": commands or []}


def iso_of(v) -> str | None:
    return v.isoformat() if isinstance(v, datetime) else v


def _row(iid: str) -> dict | None:
    rows = db_rows("SELECT * FROM dispatch_incidents WHERE id=%s", iid)
    return rows[0] if rows else None


def _commands(ids: list[str]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    if not ids:
        return out
    for c in db_rows("""SELECT incident_id, command_id, command, delivery_status, issued_at, body->'reason' AS reason
                        FROM dispatch_commands WHERE incident_id = ANY(%s) ORDER BY seq""", ids):
        out.setdefault(c["incident_id"], []).append(
            {"command_id": c["command_id"], "command": c["command"], "delivery_status": c["delivery_status"],
             "issued_at": iso_of(c["issued_at"]), "reason": c["reason"]})
    return out


def _site_tracks(live, cam: str, uuids: list[str]) -> dict[str, str]:
    """edge track uuid -> site track id (persisted sitefuse links, via hackdash.live)."""
    try:
        return live.labels_for(cam, uuids)[0]
    except Exception as e:                           # noqa: BLE001
        log.warning("site track lookup %s: %s", cam, e)
        return {}


def _open_for(cam: str, uuid_: str, st: str | None) -> dict | None:
    """An open live incident (ours or Sauron's) already on this person."""
    rows = db_rows("""SELECT * FROM dispatch_incidents WHERE status='open' AND mode='live' AND camera_id=%s
                      AND (record->>'edge_track' = %s OR (%s::text IS NOT NULL AND record->>'site_track_id' = %s))
                      ORDER BY updated_at DESC LIMIT 1""", cam, uuid_, st, st)
    return rows[0] if rows else None


# ---------------------------------------------------------------- launch

_launch_lock = asyncio.Lock()
_stopped: set[str] = set()       # aborted here: the loop never posts to them again


@router.post("/launch")
async def launch(body: LaunchBody, req: Request):
    live = _live()
    if live is None:
        raise HTTPException(503, "live boxes not available")
    if not WORKER_TOKEN:
        raise HTTPException(503, "ASK_WORKER_TOKEN is not set")
    user = _user(req) or "unknown"
    cam = body.camera_id
    newest_cam = max((o[0] for o in list(live.OBS.by_cam.get(cam, ()))), default=0)
    nb = newest_obs(live, cam, {body.track_uuid})
    if nb is None or newest_cam - nb[0] > TRACKED_S * NS:
        raise HTTPException(409, "person no longer tracked")
    ensure_loop()
    async with _launch_lock:
        st = (await asyncio.to_thread(_site_tracks, live, cam, [body.track_uuid])).get(body.track_uuid)
        dup = await asyncio.to_thread(_open_for, cam, body.track_uuid, st)
        if dup:
            r = dup["record"]
            return {"id": dup["id"], "located": bool(r.get("located")), "lat": dup["lat"], "lon": dup["lon"],
                    "loc_source": r.get("loc_source"), "site_track_id": r.get("site_track_id"), "already_dispatched": True}
        click_box = obs_at(live, cam, body.track_uuid, body.t_ns)
        t_click, box_click = (body.t_ns, click_box) if click_box else (nb[0], nb[2])
        c = live._cam(cam)
        src_w, src_h = int(c.get("width") or 0), int(c.get("height") or 0)
        jpeg = None
        try:
            jpeg = await asyncio.wait_for(live.FRAMES.edge_frame(cam, t_click), 4)
        except Exception as e:                       # noqa: BLE001 — launch anyway, with no evidence
            log.warning("evidence frame %s @%d: %s", cam, t_click, e)
        files = await asyncio.to_thread(evidence, jpeg, box_click, src_w, src_h)
        now = iso()
        track = [{"at": iso(t_click), "box": box_click}]
        if nb[0] > t_click:
            track.append({"at": iso(nb[0]), "box": nb[2]})
        iid = f"{cam}-op-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{secrets.token_hex(2)}"
        rec = {"id": iid, "camera_id": cam, "mode": "live", "status": "open", "verdict": "deploy", "why": "operator_launch",
               "why_label": "operator launch", "opened_at": now, "updated_at": now, "facts": {}, "evidence_e": None,
               "box": box_click, "box_conf": None, "frame_w": src_w, "frame_h": src_h, "subject_track": None,
               "subject_confirmed": True, "edge_track": nb[1], "op_site_track": st, "track": track,
               "caption": None, "caption_text": None, "judge": {"operator": user, "source": SOURCE}}
        t0 = time.monotonic()
        try:
            await asyncio.to_thread(post_incident, rec, files)
        except RuntimeError as e:
            raise HTTPException(502, str(e))
        post_s = round(time.monotonic() - t0, 3)
        row = await asyncio.to_thread(_row, iid)
    r = row["record"]
    log.info("operator launch %s by %s: %s %s,%s (%s) in %.3f s", iid, user, cam, row["lat"], row["lon"], r.get("loc_source"), post_s)
    return {"id": iid, "located": bool(r.get("located")), "lat": row["lat"], "lon": row["lon"],
            "loc_source": r.get("loc_source"), "site_track_id": r.get("site_track_id"), "already_dispatched": False,
            "post_s": post_s, "evidence": sorted(files)}


# ---------------------------------------------------------------- lifecycle loop

def _ours_open() -> list[dict]:
    return db_rows("""SELECT * FROM dispatch_incidents WHERE status='open' AND mode='live' AND id LIKE '%%-op-%%'
                      AND record->'judge'->>'source' = %s""", SOURCE)


def follow(live, row: dict, now_iso: str) -> dict:
    """The next record for one open operator incident: a new track point if the person is still seen, a fresh updated_at."""
    rec = {k: v for k, v in row["record"].items() if k not in DERIVED}
    cam = rec["camera_id"]
    st = row["record"].get("site_track_id") or rec.get("op_site_track")
    uuids = {rec["edge_track"]}
    if st:
        recent = sorted({o[1] for o in list(live.OBS.by_cam.get(cam, ()))})
        uuids |= {u for u, s in _site_tracks(live, cam, recent).items() if s == st}
    track = [{"at": p["at"], "box": p["box"]} for p in rec.get("track") or [] if p.get("at") and p.get("box")]
    nb = newest_obs(live, cam, uuids)
    if nb and (not track or nb[0] > _ns(track[-1]["at"])):
        track.append({"at": iso(nb[0]), "box": nb[2]})
        rec["edge_track"] = nb[1]
    rec.update({"track": track[-KEEP_POINTS:], "updated_at": now_iso, "op_site_track": st})
    return rec


async def _tick():
    live = _live()
    rows = await asyncio.to_thread(_ours_open)
    for row in rows:
        if row["id"] in _stopped:
            continue
        try:
            rec = await asyncio.to_thread(follow, live, row, iso()) if live else \
                {**{k: v for k, v in row["record"].items() if k not in DERIVED}, "updated_at": iso()}
            out = await asyncio.to_thread(post_incident, rec)
            if out.get("close_reason"):
                log.info("operator incident %s closed: %s", row["id"], out["close_reason"])
        except Exception as e:                       # noqa: BLE001 — next tick tries again
            log.warning("follow %s: %s", row["id"], e)


_loop_task: asyncio.Task | None = None


async def _loop():
    while True:
        t0 = time.monotonic()
        try:
            await _tick()
        except Exception as e:                       # noqa: BLE001
            log.warning("lifecycle tick: %s", e)
        await asyncio.sleep(max(0.05, TICK_S - (time.monotonic() - t0)))


def ensure_loop():
    global _loop_task
    if WORKER_TOKEN and (_loop_task is None or _loop_task.done()):
        _loop_task = asyncio.get_running_loop().create_task(_loop())


@router.on_event("startup")
async def _startup():
    ensure_loop()           # resumes the open incidents of a previous run


# ---------------------------------------------------------------- abort, state, drone messages

@router.post("/incidents/{iid}/abort")
async def abort(iid: str, req: Request):
    """netra-ask's abort (the drone gets `abort`), as the operator; then our own incident is closed (the drone gets `end`)."""
    fwd = {k: req.headers[k] for k in ("cookie", "authorization") if k in req.headers}
    code, out = await asyncio.to_thread(_http, "POST", f"{ASK_URL}/api/dispatch/incidents/{iid}/abort", b"", fwd)
    if code != 200:
        raise HTTPException(code, out.get("detail", out))
    row = await asyncio.to_thread(_row, iid)
    closed = None
    if row and row["status"] == "open" and (row["record"].get("judge") or {}).get("source") == SOURCE:
        _stopped.add(iid)
        now = iso()
        rec = {**{k: v for k, v in row["record"].items() if k not in DERIVED}, "status": "closed", "closed_at": now,
               "updated_at": now, "close_reason": "dismissed", "aborted_by": _user(req) or "unknown"}
        try:
            closed = (await asyncio.to_thread(post_incident, rec)).get("close_reason")
        except RuntimeError as e:
            _stopped.discard(iid)                    # the loop keeps it alive; the abort itself went out
            log.warning("close after abort %s: %s", iid, e)
    return {**out, "closed": closed}


@router.get("/incidents")
async def incidents(open: int = 0, limit: int = 50):
    def q():
        rows = db_rows(f"""SELECT * FROM dispatch_incidents WHERE mode='live' AND record->'judge'->>'source' = %s
                           {"AND status='open'" if open else ""} ORDER BY opened_at DESC LIMIT %s""", SOURCE, min(limit, 200))
        cmds = _commands([r["id"] for r in rows])
        return [summary(r, cmds.get(r["id"])) for r in rows]
    return {"incidents": await asyncio.to_thread(q)}


@router.get("/incidents/{iid}")
async def incident(iid: str):
    row = await asyncio.to_thread(_row, iid)
    if not row:
        raise HTTPException(404, "no such incident")
    return summary(row, (await asyncio.to_thread(_commands, [iid])).get(iid))


@router.get("/drone/messages")
async def drone_messages(since: int = 0, limit: int = 500, incident_id: str | None = None):
    code, out = await asyncio.to_thread(_http, "GET", f"{DROPLINK_URL}/messages?since={int(since)}&limit={int(limit)}", None, None, 5)
    if code != 200:
        raise HTTPException(502, f"droplink {code}")
    ms = out["messages"]
    if incident_id:
        ms = [m for m in ms if m["incident_id"] == incident_id]
    return {"messages": [{"seq": m["seq"], "received_at": m["received_at"], "type": m["type"],
                          "incident_id": m["incident_id"], "msg_seq": m["msg_seq"], "verified": m["verified"],
                          "duplicate": m["duplicate"], "why": m["why"], "body": m["body"]} for m in ms]}
