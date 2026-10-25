"""Calibrate a camera from the send-drone page: netra-ask's Sites calibration, driven from /hack/.

Storage is netra-ask's: every write goes to its EXISTING site/camera/frame routes (tables `sites`, `site_cameras`,
which sitefuse and sitemap.pixel_to_latlon read), so a calibration saved here changes person -> coordinate at once.
Those calls carry the operator's own Cookie / Authorization (like launch.py's abort), so netra-ask's audit names them.

What is ours, and writes nothing:
- POST /calib/freeze/{cam}: the newest live ring frame (hackdash.live) held here as a draft picture. It reaches
  netra-ask only on Save (multipart POST .../frame), because netra-ask's own grab clears the camera's pairs and fit
  immediately, and a draft must not touch a production calibration.
- POST /calib/fit: the draft fit, with netra-ask's own fitting code (ask/camgeo.py loaded from the netra-ask checkout,
  pure numpy, no DB), the same call sitemap._fit makes on Save. So the leave-one-out error shown while clicking is
  the one netra-ask will store.
- PTZ cameras (hackdash.ptz): the freeze is the camera's own snapshot with its pan/tilt/zoom read before and after
  (refused if it moved in between), and on Save that pose is written into site_cameras.frame.ptz (netra-ask's upload
  route takes no pose; the column is the one netra-ask defines and hackdash.ptz's moved-off-calibration check reads),
  with an audit row naming the operator.
- GET /calib/sites/{sid}/cameras/{cid}/people: the live person boxes now (hackdash.live) projected by netra-ask's
  /project with the SAVED calibration: the operator eyeballs the fit against reality.
"""
from __future__ import annotations

import asyncio
import base64
import importlib.util
import io
import json
import logging
import math
import os
import secrets
import sys
import time
from collections import OrderedDict
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Request, Response

log = logging.getLogger("hackdash.calib")
router = APIRouter(prefix="/calib")

ASK_URL = os.environ.get("ASK_URL", "http://127.0.0.1:8400/ask")
ASK_DIR = Path(os.environ.get("ASK_DIR", "/opt/netra/netra-ask"))
MODEL_KEYS = ("lat", "lon", "height_m", "yaw", "pitch", "roll", "hfov")   # = ask.sitemap.MODEL_KEYS
NS = 1_000_000_000
KEEP_FROZEN = 12


def _camgeo():
    """netra-ask's ask/camgeo.py by path (not `import ask`, whose package pulls in its config and DB)."""
    spec = importlib.util.spec_from_file_location("ask_camgeo", ASK_DIR / "ask" / "camgeo.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod                    # dataclasses look their module up there
    spec.loader.exec_module(mod)
    return mod


camgeo = _camgeo()


def _live():
    from hackdash import live
    return live


# ---------------------------------------------------------------- netra-ask, as the operator

_client: httpx.AsyncClient | None = None


# anonymous (public view) reads go to netra-ask as the hack_launch service account; writes never get here anonymous
SERVICE_AUTH = "Basic " + base64.b64encode(f"{os.environ.get('HACK_LAUNCH_USER', '')}:{os.environ.get('HACK_LAUNCH_PASSWORD', '')}".encode()).decode()


def auth_headers(req: Request) -> dict:
    if not getattr(req.state, "user", None) and (req.method in ("GET", "HEAD") or req.url.path.endswith("/project")) and os.environ.get("HACK_LAUNCH_USER"):
        return {"authorization": SERVICE_AUTH}
    return {k: req.headers[k] for k in ("cookie", "authorization") if k in req.headers}


async def ask(req: Request, method: str, path: str, **kw) -> httpx.Response:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=30)
    try:
        return await _client.request(method, f"{ASK_URL}/api{path}", headers={**auth_headers(req), **kw.pop("headers", {})}, **kw)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"netra-ask unreachable: {type(e).__name__}")


def relay(r: httpx.Response) -> Response:
    """netra-ask's answer as is (status, JSON or image), so its errors reach the page unchanged."""
    if r.status_code == 204:
        return Response(status_code=204)
    return Response(r.content, status_code=r.status_code, media_type=r.headers.get("content-type", "application/json"),
                    headers={k: v for k, v in r.headers.items() if k.lower() == "cache-control"})


async def ask_json(req: Request, method: str, path: str, **kw):
    r = await ask(req, method, path, **kw)
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text)
        except ValueError:
            detail = r.text[:300]
        raise HTTPException(r.status_code, detail)
    return r.json() if r.content else None


async def _passthrough(req: Request, method: str, path: str):
    body = await req.body()
    return relay(await ask(req, method, path, content=body or None,
                           headers={"content-type": "application/json"} if body else {}))


@router.get("/sites")
async def sites(req: Request):
    return relay(await ask(req, "GET", "/sites"))


@router.post("/sites")
async def site_create(req: Request):
    return await _passthrough(req, "POST", "/sites")


@router.get("/sites/{sid}")
async def site(sid: str, req: Request):
    return relay(await ask(req, "GET", f"/sites/{sid}"))


@router.patch("/sites/{sid}")
async def site_update(sid: str, req: Request):
    return await _passthrough(req, "PATCH", f"/sites/{sid}")


@router.delete("/sites/{sid}")
async def site_delete(sid: str, req: Request):
    return relay(await ask(req, "DELETE", f"/sites/{sid}"))


@router.post("/sites/{sid}/cameras")
async def camera_create(sid: str, req: Request):
    return await _passthrough(req, "POST", f"/sites/{sid}/cameras")


@router.patch("/sites/{sid}/cameras/{cid}")
async def camera_update(sid: str, cid: str, req: Request):
    return await _passthrough(req, "PATCH", f"/sites/{sid}/cameras/{cid}")


@router.delete("/sites/{sid}/cameras/{cid}")
async def camera_delete(sid: str, cid: str, req: Request):
    return relay(await ask(req, "DELETE", f"/sites/{sid}/cameras/{cid}"))


@router.get("/sites/{sid}/cameras/{cid}/frame.jpg")
async def camera_frame_jpg(sid: str, cid: str, req: Request):
    return relay(await ask(req, "GET", f"/sites/{sid}/cameras/{cid}/frame.jpg"))


@router.post("/sites/{sid}/cameras/{cid}/project")
async def camera_project(sid: str, cid: str, req: Request):
    return await _passthrough(req, "POST", f"/sites/{sid}/cameras/{cid}/project")


@router.post("/sites/{sid}/cameras/{cid}/frame")
async def camera_frame(sid: str, cid: str, req: Request, frozen: str):
    """Save step 1: hand netra-ask the frozen draft picture (its multipart upload route). This clears the camera's
    pairs and fit there; the page PATCHes the draft pairs right after."""
    f = FROZEN.get(frozen)
    if f is None:
        raise HTTPException(409, "that frozen frame is gone (server restarted?); freeze a new one")
    r = await ask(req, "POST", f"/sites/{sid}/cameras/{cid}/frame",
                  files={"file": (f"{f['camera_id']}-{f['t_ns']}.jpg", f["jpeg"], "image/jpeg")})
    if r.status_code == 200 and f.get("ptz"):
        await asyncio.to_thread(record_ptz, sid, cid, f["ptz"], getattr(req.state, "user", None) or "unknown")
        return {**r.json(), "frame": {**r.json()["frame"], "ptz": f["ptz"]}}
    return relay(r)


def record_ptz(sid: str, cid: str, ptz: dict, user: str):
    """The PTZ pose the frame was taken at, into site_cameras.frame.ptz (+ netra-ask's audit table, as the operator)."""
    import psycopg
    with psycopg.connect(os.environ.get("ASK_DATABASE_URL", "postgresql:///netra_ask"), autocommit=True) as c:
        c.execute("UPDATE site_cameras SET frame = frame || jsonb_build_object('ptz', %s::jsonb) WHERE site_id=%s AND id=%s",
                  (json.dumps(ptz), sid, cid))
        c.execute("INSERT INTO audit (by_user, action, detail) VALUES (%s, 'site.camera.frame.ptz', %s)",
                  (user, json.dumps({"site": sid, "id": cid, "ptz": ptz, "via": "hack/calib"})))


# ---------------------------------------------------------------- frozen frames (drafts, held here only)

FROZEN: OrderedDict[str, dict] = OrderedDict()
STATE = Path(os.environ.get("HACK_STATE", "/var/lib/sauron-hack")) / "calib"
DRAFTS: dict[str, dict] = {}          # user -> their last /fit body (+ at): a reload or a redeploy doesn't lose the pairs


def _load_state():
    try:
        for meta in sorted((STATE / "frozen").glob("*.json"), key=lambda p: p.stat().st_mtime)[-KEEP_FROZEN:]:
            m = json.loads(meta.read_text())
            FROZEN[meta.stem] = {**m, "jpeg": meta.with_suffix(".jpg").read_bytes()}
        f = STATE / "drafts.json"
        if f.exists():
            DRAFTS.update(json.loads(f.read_text()))
    except Exception as e:                           # noqa: BLE001 — a bad state file must not stop the router
        log.warning("calib state not loaded: %s", e)


def _save_frozen(tok: str):
    try:
        d = STATE / "frozen"
        d.mkdir(parents=True, exist_ok=True)
        f = FROZEN[tok]
        (d / f"{tok}.jpg").write_bytes(f["jpeg"])
        (d / f"{tok}.json").write_text(json.dumps({k: v for k, v in f.items() if k != "jpeg"}))
        for old in sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime)[:-KEEP_FROZEN]:
            old.unlink(missing_ok=True); old.with_suffix(".jpg").unlink(missing_ok=True)
    except OSError as e:
        log.warning("frozen frame not kept on disk: %s", e)


def _save_draft(user: str, body: dict):
    DRAFTS[user] = {**body, "at": time.time()}
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        (STATE / "drafts.json").write_text(json.dumps(DRAFTS))
    except OSError as e:
        log.warning("draft not kept on disk: %s", e)


def jpeg_size(data: bytes) -> tuple[int, int]:
    from PIL import Image
    im = Image.open(io.BytesIO(data))
    im.verify()
    return Image.open(io.BytesIO(data)).size


def keep_frozen(camera_id: str, t_ns: int, jpeg: bytes, ptz: dict | None = None) -> dict:
    w, h = jpeg_size(jpeg)
    tok = secrets.token_hex(8)
    FROZEN[tok] = {"camera_id": camera_id, "t_ns": t_ns, "jpeg": jpeg, "width": w, "height": h, "at": time.time(), "ptz": ptz}
    while len(FROZEN) > KEEP_FROZEN:
        FROZEN.popitem(last=False)
    _save_frozen(tok)
    return frozen_view(tok)


def frozen_view(tok: str) -> dict:
    f = FROZEN[tok]
    return {"token": tok, "camera_id": f["camera_id"], "t_ns": str(f["t_ns"]), "width": f["width"], "height": f["height"],
            "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(f["t_ns"] / NS)),
            "url": f"calib/frozen/{tok}.jpg", "ptz": f.get("ptz")}


@router.post("/freeze/{cam}")
async def freeze(cam: str, req: Request):
    """The newest live ring frame of a pipeline camera, held as a draft calibration picture. When the ring has none
    (edge down), netra-ask's newest preview of the camera instead (what its own Grab freezes), with its real age."""
    ptz = _ptz()
    if ptz and cam in ptz.CAMS:
        return await freeze_ptz(ptz, cam)
    live = _live()
    live._cam(cam)
    task = live.kick(cam)
    if cam not in live._current and task is not None:
        try:
            await asyncio.wait_for(asyncio.shield(task), 6)
        except asyncio.TimeoutError:
            pass
    t = live._current.get(cam)
    data = await live.FRAMES.edge_frame(cam, t) if t is not None else None
    source = "ring"
    if data is None:
        r = await ask(req, "GET", f"/preview/{cam}.jpg")
        if r.status_code != 200:
            raise HTTPException(409, f"no live frame from {cam} right now, and netra-ask has no preview of it")
        data, source = r.content, "preview"
        lm = r.headers.get("last-modified")
        t = int(parsedate_to_datetime(lm).timestamp() * NS) if lm else time.time_ns()
    try:
        out = keep_frozen(cam, t, data)
    except Exception:
        raise HTTPException(502, "the frame isn't a readable image")
    return {**out, "source": source, "age_s": round(time.time() - t / NS, 1)}


def _ptz():
    try:
        from hackdash import ptz
        return ptz
    except Exception as e:                           # noqa: BLE001 — no PTZ router: freeze as a fixed camera
        log.warning("hackdash.ptz unavailable: %s", e)
        return None


async def freeze_ptz(ptz, cam: str) -> dict:
    """The PTZ camera's own snapshot at its current pose; refused if the pose changed while it was taken."""
    pose = lambda d: {k: float(d[k]) for k in ("pan", "tilt", "zoom")}          # noqa: E731
    p0 = pose((await ptz.ptzd(cam, "GET", "/position")).json())
    t = time.time_ns()
    jpeg = (await ptz.ptzd(cam, "GET", "/snapshot.jpg", {"resolution": f"{ptz.SNAP_W}x{ptz.SNAP_H}"})).content
    p1 = pose((await ptz.ptzd(cam, "GET", "/position")).json())
    if abs(p0["pan"] - p1["pan"]) > 0.05 or abs(p0["tilt"] - p1["tilt"]) > 0.05 or abs(p0["zoom"] - p1["zoom"]) > 1:
        raise HTTPException(409, "the camera was moving while the frame was taken: wait for it to stop and freeze again")
    zi = ptz.zoom_info(p1["zoom"])
    try:
        out = keep_frozen(cam, t, jpeg, {**p1, "hfov": zi.get("hfov_deg"), "zoom_x": zi.get("x")})
    except Exception:
        raise HTTPException(502, "the camera's snapshot isn't a readable image")
    return {**out, "source": "ptz", "age_s": 0.0}


@router.get("/frozen/{tok}.jpg")
async def frozen_jpg(tok: str):
    f = FROZEN.get(tok)
    if f is None:
        raise HTTPException(404, "frozen frame gone")
    return Response(f["jpeg"], media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


# ---------------------------------------------------------------- draft fit (netra-ask's math, no DB)

def draft_fit(body: dict) -> dict:
    """{model: {lat, lon, height_m, yaw, pitch, roll, hfov}, frame: {width, height}, points: [{u, v, lat, lon}],
    fit_position} -> {model, fit, footprint}; mirrors ask.sitemap._fit + camera_view (fit is None under 2 pairs)."""
    try:
        model = {k: float(body["model"][k]) for k in MODEL_KEYS}
        fw, fh = int(body["frame"]["width"]), int(body["frame"]["height"])
        points = [{"u": float(p["u"]), "v": float(p["v"]), "lat": float(p["lat"]), "lon": float(p["lon"])}
                  for p in body.get("points") or []]
    except (KeyError, TypeError, ValueError) as e:
        raise HTTPException(400, f"bad draft: {e}")
    fit_position = bool(body.get("fit_position"))
    cam0 = camgeo.Camera.of({**model, "width": fw, "height": fh})
    if len(points) < 2:
        return {"model": model, "fit": None, "footprint": None}
    start = None
    if fit_position and len(points) >= 6:
        cam0, start = best_start(cam0, points)
    cam, rep = camgeo.fit(cam0, points, fit_position)
    if start:
        rep["start"] = start
    fitted = {k: round(getattr(cam, k), 7 if k in ("lat", "lon") else 4) for k in MODEL_KEYS}
    return {"model": fitted, "fit": rep, "footprint": camgeo.footprint(camgeo.Camera.of({**fitted, "width": fw, "height": fh}))}


RING_M = (0, 40, 100)                    # start positions around the pairs' centroid, metres
HEIGHTS = (6.0, 15.0)


def _quick_seed(g, c0, uv, ll, names):
    """camgeo._seed on a coarser grid (30° yaw, 10° pitch, 3 lens widths): only to rank start positions."""
    best, bc = None, math.inf
    for yaw in range(0, 360, 30):
        for pitch in range(0, 75, 10):
            for hfov in ((25, 50, 80) if "hfov" in names else (c0.hfov,)):
                c = g.replace(c0, yaw=float(yaw), pitch=float(pitch), hfov=float(hfov))
                r = g._resid(c, [], __import__("numpy").array([]), uv, ll)
                if (cost := r @ r) < bc:
                    best, bc = c, cost
    return best


def best_start(c0, points: list[dict]):
    """Multi-start for the camera position: the placed position, plus a ring of positions around the pairs (8 bearings
    x RING_M) at a few heights. camgeo.fit's own seed searches yaw/pitch/hfov but starts LM from the placed position, so a
    camera placed far off (e.g. left at the site centre) lands in a wrong minimum. The start with the lowest reprojection
    cost after a short LM (position free) wins; the full fit + leave-one-out then runs from there."""
    g = camgeo
    names = g.free_params(len(points), True)
    uv = __import__("numpy").array([[p["u"], p["v"]] for p in points], float)
    ll = [(p["lat"], p["lon"]) for p in points]
    clat = sum(p["lat"] for p in points) / len(points)
    clon = sum(p["lon"] for p in points) / len(points)
    starts = [(c0.lat, c0.lon, c0.height_m, "placed")]
    for r in RING_M:
        for b in (range(0, 360, 45) if r else (0,)):
            la, lo = g.from_en(r * math.sin(math.radians(b)), r * math.cos(math.radians(b)), clat, clon)
            starts += [(la, lo, hh, f"{r} m {b}° from the pairs") for hh in HEIGHTS]
    best = None
    for la, lo, hh, why in starts:
        c = g.replace(c0, lat=la, lon=lo, height_m=hh)
        s = _quick_seed(g, c, uv, ll, names)
        x = g._lm(s, names, g._x0(s, names), uv, ll, iters=25)
        r = g._resid(s, names, x, uv, ll)
        cost = float(r @ r)
        if best is None or cost < best[0]:
            best = (cost, g._apply(s, names, x), why)
    c = best[1]
    return g.replace(c0, lat=c.lat, lon=c.lon, height_m=c.height_m), {"from": best[2], "rms_px": round(math.sqrt(best[0] / (2 * len(points))), 2)}


@router.post("/fit")
async def fit(req: Request):
    try:
        body = await req.json()
    except ValueError:
        raise HTTPException(400, "body must be JSON")
    if body.get("points") and isinstance(body.get("points"), list):
        _save_draft(getattr(req.state, "user", None) or "unknown", body)
    return await asyncio.to_thread(draft_fit, body)


@router.get("/draft")
async def last_draft(req: Request):
    """This operator's last draft (the body of their newest /fit): pairs + pose, to restore after a reload."""
    return DRAFTS.get(getattr(req.state, "user", None) or "unknown") or {}


# ---------------------------------------------------------------- live people through the saved calibration

def foot(box: list[float]) -> list[float]:
    x1, _, x2, y2 = box
    return [(x1 + x2) / 2, y2]


@router.get("/sites/{sid}/cameras/{cid}/people")
async def people(sid: str, cid: str, req: Request):
    """The person boxes of the newest live frame, foot points projected by netra-ask with the SAVED calibration."""
    row = next((c for c in (await ask_json(req, "GET", f"/sites/{sid}"))["cameras"] if c["id"] == cid), None)
    if row is None:
        raise HTTPException(404, "no such camera")
    cam = (row.get("source") or {}).get("camera_id")
    if not cam:
        return {"camera_id": None, "t_ns": None, "people": [], "why": "this camera has no live feed (uploaded still)"}
    if not row["calibrated"]:
        return {"camera_id": cam, "t_ns": None, "people": [], "why": "not calibrated yet: save a fit first"}
    live = _live()
    live._cam(cam)
    live.kick(cam)
    t = live._current.get(cam)
    if t is None:
        return {"camera_id": cam, "t_ns": None, "people": [], "why": f"no live frame from {cam} right now"}
    boxes = live.OBS.at(cam, t)
    feet = [foot(b["box"]) for b in boxes]
    pts = (await ask_json(req, "POST", f"/sites/{sid}/cameras/{cid}/project",
                          json={"pixels": feet, "space": "source"}))["points"] if feet else []
    return {"camera_id": cam, "t_ns": str(t), "lag_s": round(time.time() - t / NS, 2),
            "frame_url": f"cameras/{cam}/frame.jpg?t={t}",
            "people": [{"track_uuid": b["track_uuid"], "box": b["box"], "foot": f, "conf": b.get("conf"),
                        **({"lat": p["lat"], "lon": p["lon"], "radius_m": p["radius_m"]} if p else {"located": False})}
                       for b, f, p in zip(boxes, feet, pts)]}


_load_state()
