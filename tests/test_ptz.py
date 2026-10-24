"""ptzd against a recording stand-in for the camera's ptz.cgi (test fixture only), and hackdash.ptz's pure parts."""
import json
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from ptzd import ptzd


class CamRecorder(BaseHTTPRequestHandler):
    calls: list = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        CamRecorder.calls.append((u.path, q))
        body = b"pan=10.5\ntilt=-3.25\nzoom=2000\n" if q.get("query") == "position" else \
            b"root.PTZ.Various.V1.IrCutFilter=on\n" if q.get("group") == "PTZ.Various.V1.IrCutFilter" else b""
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def srv():
    CamRecorder.calls = []
    cam_srv = ThreadingHTTPServer(("127.0.0.1", 0), CamRecorder)
    threading.Thread(target=cam_srv.serve_forever, daemon=True).start()
    cam = ptzd.Vapix(f"127.0.0.1:{cam_srv.server_address[1]}", "u", "p")
    s = ptzd.serve("127.0.0.1:0", cam, "tok", deadman_s=0.3)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_address[1]}"
    s.shutdown(); cam_srv.shutdown()


def call(base, method, path, token="tok"):
    req = urllib.request.Request(base + path, method=method, data=b"" if method == "POST" else None,
                                 headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def ptzcalls():
    return [q for p, q in CamRecorder.calls if p.startswith("/axis-cgi/com/ptz") and "query" not in q]


def test_auth_and_position(srv):
    assert call(srv, "GET", "/position", token="bad")[0] == 401
    code, out = call(srv, "GET", "/position")
    assert code == 200 and (out["pan"], out["tilt"], out["zoom"]) == (10.5, -3.25, 2000.0)


def test_move_clamps_and_deadman_stops(srv):
    assert call(srv, "POST", "/move?pan=250&tilt=-40&zoom=0")[1]["moving"] is True
    assert ptzcalls()[:2] == [{"continuouspantiltmove": "100,-40"}, {"continuouszoommove": "0"}]
    time.sleep(0.6)                                   # no refresh -> the deadman stops it
    assert ptzcalls()[2:4] == [{"continuouspantiltmove": "0,0"}, {"continuouszoommove": "0"}]


def test_refresh_keeps_moving(srv):
    for _ in range(4):
        call(srv, "POST", "/move?pan=20")
        time.sleep(0.15)
    assert {"continuouspantiltmove": "0,0"} not in ptzcalls()
    call(srv, "POST", "/stop")
    assert ptzcalls()[-2:] == [{"continuouspantiltmove": "0,0"}, {"continuouszoommove": "0"}]


def test_allowlist(srv):
    assert call(srv, "POST", "/goto?name=other")[0] == 400
    assert call(srv, "POST", "/save?name=hack-home")[0] == 200
    assert CamRecorder.calls[-1] == ("/axis-cgi/com/ptzconfig.cgi", {"setserverpresetname": "hack-home"})
    assert call(srv, "POST", "/center?x=640&y=360&w=1280&h=720")[0] == 200
    assert ptzcalls()[-1] == {"areazoom": "640,360,100", "imagewidth": "1280", "imageheight": "720"}
    assert call(srv, "POST", "/center?x=2000&y=1&w=1280&h=720")[0] == 400
    assert call(srv, "GET", "/snapshot.jpg?resolution=99x99")[0] == 400
    assert call(srv, "POST", "/raw?query=anything")[0] == 404


def test_zoom_info_and_calib_check():
    pytest.importorskip("fastapi")
    from hackdash import ptz
    assert ptz.zoom_info(1) == {"hfov_deg": 56.44, "x": 1.0}
    assert ptz.zoom_info(9999)["x"] == 21.37
    assert 1.0 < ptz.zoom_info(1000)["x"] < ptz.zoom_info(2000)["x"]
    pose = {"pan": 10.0, "tilt": 5.0, "zoom": 1.0}
    assert ptz.calib_check(pose, None)["calibrated"] is False
    assert ptz.calib_check(pose, {"site_camera": "c", "pan": 10.2, "tilt": 5.1, "zoom": 1})["moved"] is False
    assert ptz.calib_check(pose, {"site_camera": "c", "pan": 12, "tilt": 5, "zoom": 1})["moved"] is True
    assert ptz.calib_check({**pose, "pan": 179.9}, {"site_camera": "c", "pan": -179.9, "tilt": 5})["moved"] is False
    assert ptz.calib_check(pose, {"site_camera": "c"})["moved"] is None


def test_daynight(srv):
    assert call(srv, "POST", "/daynight?mode=sepia")[0] == 400
    code, out = call(srv, "POST", "/daynight?mode=day")
    assert code == 200 and out["mode"] == "day" and ptzcalls()[-1] == {"ircutfilter": "on"}
    assert call(srv, "GET", "/daynight")[1]["mode"] == "day"
    call(srv, "POST", "/daynight?mode=night")
    assert ptzcalls()[-1] == {"ircutfilter": "off"}


def test_picture_kind():
    pytest.importorskip("fastapi")
    import io
    from PIL import Image
    from hackdash import ptz
    for rgb, want in (((120, 120, 120), "mono (IR)"), ((160, 110, 60), "colour")):
        b = io.BytesIO(); Image.new("RGB", (64, 36), rgb).save(b, "JPEG")
        assert ptz.picture_kind(b.getvalue())["picture"] == want
