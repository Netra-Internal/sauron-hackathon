"""Manual pan/tilt/zoom for PTZ cameras (the Axis Q6215), for the operator on /hack/.

Each PTZ camera has a ptzd (ptzd/ptzd.py) on the box next to it, reached through an SSH tunnel on a droplet loopback
port (PTZ_CAMS="axis-q6215=http://127.0.0.1:8530"). ptzd only knows a fixed set of commands and stops any continuous move
that is not refreshed within 1.2 s. So the page re-sends /move every 250 ms while a button is held, and a lost release
cannot leave the camera turning.

Calibration: netra-ask maps pixels to the ground for a PTZ camera only at the pose it was calibrated in (site_cameras
frame.ptz). /state compares the live pose with that and says so: moved = the map positions of its people are wrong
until the camera goes back or is recalibrated. With no calibration row, calibrated is false.

  GET  /ptz                         [{camera_id, reachable}]
  GET  /ptz/{cam}/state             pose, zoom x / hfov (measured curve), calibration check, rtt
  POST /ptz/{cam}/move {pan, tilt, zoom}   speeds -1..1 (continuous; repeat while held)
  POST /ptz/{cam}/stop
  POST /ptz/{cam}/center {x, y, zoom?}     x, y in 0..1 of the picture; zoom factor (1 = keep, 2 = 2x in)
  POST /ptz/{cam}/home              go to the "hack-home" server preset
  POST /ptz/{cam}/home/save         save the current pose as "hack-home"
  GET  /ptz/{cam}/snapshot.jpg      the camera's own JPEG (1280x720), for the view the operator clicks on
  GET  /ptz/{cam}/daynight          {mode (last set here), picture colour|mono (IR) measured}   POST {mode}: IR-cut filter
"""
from __future__ import annotations

import asyncio
import bisect
import json
import logging
import os
import time
from pathlib import Path

import httpx
import psycopg
from fastapi import APIRouter, HTTPException, Request, Response
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

log = logging.getLogger("hackdash.ptz")
router = APIRouter()

CAMS = dict(kv.split("=", 1) for kv in os.environ.get("PTZ_CAMS", "axis-q6215=http://127.0.0.1:8530").split(",") if "=" in kv)
def _token() -> str:
    """PTZD_TOKEN, else the file the ptzd installer writes on the droplet (ptzd/install.sh)."""
    if os.environ.get("PTZD_TOKEN"):
        return os.environ["PTZD_TOKEN"]
    try:
        return Path(os.environ.get("PTZD_TOKEN_FILE", "/etc/ptzd-token")).read_text().strip()
    except OSError:
        return ""


TOKEN = _token()
DATABASE_URL = os.environ.get("ASK_DATABASE_URL", "postgresql:///netra_ask")
HOME = "hack-home"
SNAP_W, SNAP_H = 1280, 720
MOVED_DEG = 0.5            # pan/tilt off the calibrated pose by more than this = moved
MOVED_ZOOM = 50            # zoom steps
ZOOMCAL = json.loads((Path(__file__).parent / "ptz_zoomcal.json").read_text())["points"]   # [step, hfov_deg, mag]

_client: httpx.AsyncClient | None = None


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=2.0),
                                    limits=httpx.Limits(max_keepalive_connections=4, keepalive_expiry=30))
    return _client


def zoom_info(step: float) -> dict:
    """Zoom step -> hfov and magnification, interpolated on the measured curve."""
    steps = [p[0] for p in ZOOMCAL]
    i = bisect.bisect_left(steps, step)
    if i <= 0:
        a = b = ZOOMCAL[0]
    elif i >= len(ZOOMCAL):
        a = b = ZOOMCAL[-1]
    else:
        a, b = ZOOMCAL[i - 1], ZOOMCAL[i]
    f = 0.0 if b[0] == a[0] else (step - a[0]) / (b[0] - a[0])
    return {"hfov_deg": round(a[1] + f * (b[1] - a[1]), 2), "x": round(a[2] + f * (b[2] - a[2]), 2)}


def calibrated_pose(cam: str) -> dict | None:
    """netra-ask's calibration of this camera: {pan, tilt, zoom?, site_camera} from site_cameras.frame.ptz, {} when it is
    calibrated without a recorded pose, None when it is not calibrated."""
    with psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=True) as c:
        r = c.execute("""SELECT id, frame->'ptz' AS ptz FROM site_cameras WHERE source->>'camera_id' = %s AND fit IS NOT NULL
                         ORDER BY updated_at DESC LIMIT 1""", (cam,)).fetchone()
    if not r:
        return None
    return {**(r["ptz"] or {}), "site_camera": r["id"]}


def calib_check(pose: dict, cal: dict | None) -> dict:
    if cal is None:
        return {"calibrated": False, "moved": None, "note": "not calibrated: people seen by this camera are not on the map"}
    if "pan" not in cal or "tilt" not in cal:
        return {"calibrated": True, "moved": None, "site_camera": cal["site_camera"],
                "note": "calibrated, but no pose was recorded with it: any move may invalidate the map"}
    dp = abs((pose["pan"] - float(cal["pan"]) + 180) % 360 - 180)
    dt = abs(pose["tilt"] - float(cal["tilt"]))
    dz = abs(pose["zoom"] - float(cal["zoom"])) if cal.get("zoom") is not None else 0.0
    moved = dp > MOVED_DEG or dt > MOVED_DEG or dz > MOVED_ZOOM
    return {"calibrated": True, "moved": moved, "site_camera": cal["site_camera"],
            "calibrated_pose": {k: cal.get(k) for k in ("pan", "tilt", "zoom")},
            "note": "moved off the calibrated view: map positions from this camera are wrong until it goes back or is recalibrated"
            if moved else "at the calibrated view"}


def _base(cam: str) -> str:
    if cam not in CAMS:
        raise HTTPException(404, "not a PTZ camera")
    if not TOKEN:
        raise HTTPException(503, "PTZD_TOKEN is not set")
    return CAMS[cam]


async def ptzd(cam: str, method: str, path: str, params: dict | None = None) -> httpx.Response:
    base = _base(cam)
    try:
        r = await client().request(method, base + path, params=params, headers={"Authorization": f"Bearer {TOKEN}"})
    except httpx.HTTPError as e:
        raise HTTPException(503, f"camera link down ({type(e).__name__})")
    if r.status_code != 200:
        try:
            msg = r.json().get("error", r.text)
        except ValueError:
            msg = r.text[:200]
        raise HTTPException(502 if r.status_code >= 500 else 400, msg)
    return r


def _user(req: Request) -> str:
    return getattr(req.state, "user", None) or "unknown"


async def _cmd(cam: str, req: Request, path: str, params: dict | None = None) -> dict:
    t0 = time.monotonic()
    out = (await ptzd(cam, "POST", path, params)).json()
    out["ms"] = round((time.monotonic() - t0) * 1000, 1)          # page -> camera answered, as seen from the droplet
    if path != "/move":
        log.info("ptz %s %s %s by %s -> %s", cam, path, params, _user(req), out)
    return out


class Move(BaseModel):
    pan: float = Field(0, ge=-1, le=1)
    tilt: float = Field(0, ge=-1, le=1)
    zoom: float = Field(0, ge=-1, le=1)


class Center(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    zoom: float = Field(1, ge=0.05, le=20)


@router.get("/ptz")
async def cams():
    out = []
    for cam in CAMS:
        try:
            await ptzd(cam, "GET", "/position")
            out.append({"camera_id": cam, "reachable": True})
        except HTTPException as e:
            out.append({"camera_id": cam, "reachable": False, "why": e.detail})
    return out


@router.get("/ptz/{cam}/state")
async def state(cam: str):
    t0 = time.monotonic()
    pose = (await ptzd(cam, "GET", "/position")).json()
    ms = round((time.monotonic() - t0) * 1000, 1)
    cal = await asyncio.to_thread(calibrated_pose, cam)
    p = {k: pose[k] for k in ("pan", "tilt", "zoom")}
    return {"camera_id": cam, **p, "zoom_info": zoom_info(p["zoom"]), "calibration": calib_check(p, cal),
            "ms": ms, "camera_rtt_ms": pose.get("rtt_ms"), "home": HOME}


@router.post("/ptz/{cam}/move")
async def move(cam: str, body: Move, req: Request):
    s = lambda v: int(round(v * 100))                  # noqa: E731
    return await _cmd(cam, req, "/move", {"pan": s(body.pan), "tilt": s(body.tilt), "zoom": s(body.zoom)})


@router.post("/ptz/{cam}/stop")
async def stop(cam: str, req: Request):
    return await _cmd(cam, req, "/stop")


@router.post("/ptz/{cam}/center")
async def center(cam: str, body: Center, req: Request):
    return await _cmd(cam, req, "/center", {"x": round(body.x * SNAP_W), "y": round(body.y * SNAP_H), "w": SNAP_W,
                                            "h": SNAP_H, "zoom": round(body.zoom * 100)})


@router.post("/ptz/{cam}/home")
async def home(cam: str, req: Request):
    return await _cmd(cam, req, "/goto", {"name": HOME})


@router.post("/ptz/{cam}/home/save")
async def home_save(cam: str, req: Request):
    return await _cmd(cam, req, "/save", {"name": HOME})


class DayNight(BaseModel):
    mode: str = Field(pattern="^(day|night|auto)$")


def picture_kind(jpeg: bytes) -> dict:
    """Colour or IR, from the picture itself: an IR picture (filter out) is grey, mean HSV saturation ~0."""
    import io
    from PIL import Image, ImageStat
    im = Image.open(io.BytesIO(jpeg)).convert("RGB").resize((160, 90))
    sat = ImageStat.Stat(im.convert("HSV")).mean[1]
    return {"picture": "colour" if sat > 8 else "mono (IR)", "saturation": round(sat, 1)}


@router.get("/ptz/{cam}/daynight")
async def daynight(cam: str):
    """mode: last set through ptzd (null if not since it started); picture: measured on a snapshot now."""
    out = (await ptzd(cam, "GET", "/daynight")).json()
    snap = await ptzd(cam, "GET", "/snapshot.jpg", {"resolution": "640x360"})
    return {**out, **await asyncio.to_thread(picture_kind, snap.content)}


@router.post("/ptz/{cam}/daynight")
async def daynight_set(cam: str, body: DayNight, req: Request):
    return await _cmd(cam, req, "/daynight", {"mode": body.mode})


@router.get("/ptz/{cam}/snapshot.jpg")
async def snapshot(cam: str):
    r = await ptzd(cam, "GET", "/snapshot.jpg", {"resolution": f"{SNAP_W}x{SNAP_H}"})
    return Response(r.content, media_type="image/jpeg", headers={"Cache-Control": "no-store"})
