"""ptzd: manual pan/tilt/zoom for one Axis PTZ camera, as a tiny HTTP service on the box next to the camera.

It speaks VAPIX (/axis-cgi/com/ptz.cgi, digest auth) to the camera and offers only a fixed set of commands. It never
passes a raw VAPIX query through. It listens on 127.0.0.1 and needs a bearer token (PTZD_TOKEN). The droplet reaches it
through an SSH tunnel.

  GET  /health                          no token: {ok, camera}
  GET  /position                        {pan, tilt, zoom, rtt_ms}
  POST /move?pan=&tilt=&zoom=           continuous speeds, ints -100..100 (0 = that axis stops). DEADMAN: unless another
                                        /move arrives within PTZD_DEADMAN_S (1.2 s), the camera is stopped. So a
                                        hold-to-move button that stops refreshing (lost mouseup, dropped tunnel)
                                        cannot leave the camera turning.
  POST /stop
  POST /center?x=&y=&w=&h=[&zoom=]      areazoom: pixel (x, y) of a w x h image becomes the centre; zoom % (100 = same)
  POST /goto?name=  POST /save?name=    server presets, names from PTZD_PRESETS only (default "hack-home")
  GET  /snapshot.jpg?resolution=&compression=   image.cgi at an allowed resolution, JPEG compression 0-100
  GET  /daynight  POST /daynight?mode=  IR-cut filter: day (filter in, colour) | night (filter out, IR) | auto. On this PTZ
                                        firmware it is ptz.cgi `ircutfilter=on|off|auto`; the IR LEDs follow it (lightcontrol
                                        synchronizeDayNightMode). GET = the mode last set here (the camera can't be asked)

stdlib only. Env: PTZ_CAM_HOST, PTZ_CAM_USER, PTZ_CAM_PASS (the axis-q6215.env names), PTZD_TOKEN, PTZD_LISTEN.
"""
from __future__ import annotations

import argparse
import hmac
import http.client
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

log = logging.getLogger("ptzd")
DEADMAN_S = float(os.environ.get("PTZD_DEADMAN_S", "1.2"))
PRESETS = set(filter(None, os.environ.get("PTZD_PRESETS", "hack-home").split(",")))
RESOLUTIONS = {"640x360", "1280x720", "1920x1080"}
DAYNIGHT = {"day": "on", "night": "off", "auto": "auto"}          # mode -> ptz.cgi ircutfilter


class VapixError(Exception):
    pass


class Vapix:
    def __init__(self, host: str, user: str, password: str, timeout_s: float = 3.0):
        self.host, self.timeout_s = host, timeout_s
        mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        mgr.add_password(None, f"http://{host}/", user, password)
        self.opener = urllib.request.build_opener(urllib.request.HTTPDigestAuthHandler(mgr))

    def get(self, path: str, params: dict) -> bytes:
        url = f"http://{self.host}{path}?{urllib.parse.urlencode(params)}"
        try:
            with self.opener.open(url, timeout=self.timeout_s) as r:
                return r.read()
        except (OSError, http.client.HTTPException) as e:
            raise VapixError(f"{type(e).__name__}: {e}") from e

    def ptz(self, cgi: str = "ptz.cgi", **params) -> str:
        body = self.get(f"/axis-cgi/com/{cgi}", params).decode("iso-8859-1", "replace")
        if body.lstrip().lower().startswith("error"):           # ptz.cgi answers 200 with an "Error:" body
            raise VapixError(body.strip())
        return body

    def position(self) -> dict:
        vals = dict(ln.split("=", 1) for ln in self.ptz(query="position").splitlines() if "=" in ln)
        try:
            return {"pan": float(vals["pan"]), "tilt": float(vals["tilt"]), "zoom": float(vals["zoom"])}
        except (KeyError, ValueError) as e:
            raise VapixError(f"bad position reply: {vals}") from e


def clamp_speed(v: str | None) -> int:
    return max(-100, min(100, int(round(float(v or 0)))))


class Mover:
    """Continuous moves with a deadman: a move not refreshed within DEADMAN_S is stopped."""

    def __init__(self, cam: Vapix, deadman_s: float = DEADMAN_S):
        self.cam, self.deadman_s = cam, deadman_s
        self.lock = threading.Lock()
        self.moving = False
        self.last = 0.0
        threading.Thread(target=self._watch, daemon=True, name="deadman").start()

    def move(self, pan: int, tilt: int, zoom: int) -> None:
        with self.lock:
            self.cam.ptz(continuouspantiltmove=f"{pan},{tilt}")
            self.cam.ptz(continuouszoommove=str(zoom))
            self.moving = bool(pan or tilt or zoom)
            self.last = time.monotonic()

    def stop(self, why: str = "stop") -> None:
        with self.lock:
            self.cam.ptz(continuouspantiltmove="0,0")
            self.cam.ptz(continuouszoommove="0")
            self.moving = False
        log.info("stopped (%s)", why)

    def _watch(self):
        while True:
            time.sleep(0.1)
            if self.moving and time.monotonic() - self.last > self.deadman_s:
                try:
                    self.stop("deadman")
                except VapixError as e:
                    log.warning("deadman stop failed: %s", e)


class Handler(BaseHTTPRequestHandler):
    server_version = "ptzd/1"
    protocol_version = "HTTP/1.1"                  # keep-alive: the droplet's client reuses one tunnel channel

    def log_message(self, fmt, *a):
        log.debug(fmt, *a)

    def _send(self, code: int, body: bytes, ctype: str = "application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj):
        self._send(code, json.dumps(obj).encode())

    def _authed(self) -> bool:
        got = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        return bool(self.server.token) and hmac.compare_digest(got, self.server.token)

    def _handle(self, method: str):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if int(self.headers.get("Content-Length") or 0):
            self.rfile.read(int(self.headers["Content-Length"]))
        cam, mover = self.server.cam, self.server.mover
        if u.path == "/health":
            return self._json(200, {"ok": True, "camera": cam.host})
        if not self._authed():
            return self._json(401, {"error": "bad token"})
        t0 = time.monotonic()
        try:
            if method == "GET" and u.path == "/position":
                out = cam.position()
            elif method == "GET" and u.path == "/snapshot.jpg":
                res = q.get("resolution", "1280x720")
                if res not in RESOLUTIONS:
                    return self._json(400, {"error": f"resolution one of {sorted(RESOLUTIONS)}"})
                comp = max(0, min(100, int(q.get("compression", 30))))
                return self._send(200, cam.get("/axis-cgi/jpg/image.cgi", {"resolution": res, "compression": comp}), "image/jpeg")
            elif method == "POST" and u.path == "/move":
                mover.move(clamp_speed(q.get("pan")), clamp_speed(q.get("tilt")), clamp_speed(q.get("zoom")))
                out = {"moving": mover.moving}
            elif method == "POST" and u.path == "/stop":
                mover.stop()
                out = {"moving": False}
            elif method == "POST" and u.path == "/center":
                x, y, w, h = (int(float(q[k])) for k in ("x", "y", "w", "h"))
                z = max(1, min(9999, int(float(q.get("zoom", 100)))))
                if not (0 < w <= 10000 and 0 < h <= 10000 and 0 <= x <= w and 0 <= y <= h):
                    return self._json(400, {"error": "x, y inside a w x h image"})
                cam.ptz(areazoom=f"{x},{y},{z}", imagewidth=w, imageheight=h)
                out = {"ok": True}
            elif u.path == "/daynight":
                if method == "POST":
                    mode = q.get("mode", "")
                    if mode not in DAYNIGHT:
                        return self._json(400, {"error": f"mode one of {sorted(DAYNIGHT)}"})
                    cam.ptz(ircutfilter=DAYNIGHT[mode])
                    self.server.daynight = mode
                # the camera does not report the live filter state (PTZ.Various.V1.IrCutFilter stays at its config
                # value), so this is the mode set through ptzd since it started, or null
                out = {"mode": self.server.daynight}
            elif method == "POST" and u.path in ("/goto", "/save"):
                name = q.get("name", "")
                if name not in PRESETS:
                    return self._json(400, {"error": f"preset one of {sorted(PRESETS)}"})
                if u.path == "/goto":
                    cam.ptz(gotoserverpresetname=name)
                else:                                   # presets are created by ptzconfig.cgi; ptz.cgi ignores this
                    cam.ptz("ptzconfig.cgi", setserverpresetname=name)
                out = {"ok": True, "preset": name}
            else:
                return self._json(404, {"error": "not found"})
        except (KeyError, ValueError):
            return self._json(400, {"error": "bad parameters"})
        except VapixError as e:
            log.warning("%s %s -> camera error: %s", u.path, q, e)
            return self._json(502, {"error": f"camera: {e}"})
        out["rtt_ms"] = round((time.monotonic() - t0) * 1000, 1)
        if u.path != "/position":
            log.info("%s %s -> %s", u.path, q, out)
        return self._json(200, out)

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")


def serve(listen: str, cam: Vapix, token: str, deadman_s: float = DEADMAN_S) -> ThreadingHTTPServer:
    host, port = listen.rsplit(":", 1)
    srv = ThreadingHTTPServer((host, int(port)), Handler)
    srv.cam, srv.token, srv.mover, srv.daynight = cam, token, Mover(cam, deadman_s), None
    return srv


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen", default=os.environ.get("PTZD_LISTEN", "127.0.0.1:8530"))
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    token = os.environ.get("PTZD_TOKEN", "")
    if not token:
        raise SystemExit("PTZD_TOKEN is not set")
    cam = Vapix(os.environ["PTZ_CAM_HOST"], os.environ["PTZ_CAM_USER"], os.environ["PTZ_CAM_PASS"])
    srv = serve(a.listen, cam, token)
    log.info("ptzd on %s for camera %s (deadman %.1f s, presets %s)", a.listen, cam.host, DEADMAN_S, sorted(PRESETS))
    srv.serve_forever()


if __name__ == "__main__":
    main()
