"""hackdash.calib: the draft fit (netra-ask's camgeo, no DB), frozen frames, the proxy's header pass-through."""
import io
import os
from pathlib import Path

import pytest

pytest.importorskip("numpy")
pytest.importorskip("fastapi")
ASK = Path(os.environ.setdefault("ASK_DIR", str(Path.home() / "netra/netra-ask")))
if not (ASK / "ask/camgeo.py").exists():
    pytest.skip("needs a netra-ask checkout (ASK_DIR) for ask/camgeo.py", allow_module_level=True)
from hackdash import calib  # noqa: E402

TRUE = {"lat": 32.8792343, "lon": -117.2323001, "height_m": 9.0, "yaw": 210.0, "pitch": 22.0, "roll": 0.5, "hfov": 70.0}
FW, FH = 960, 540


def pairs(model, uvs):
    """Exact pairs for a known camera: pixel -> ground with camgeo itself."""
    g = calib.camgeo
    cam = g.Camera.of({**model, "width": FW, "height": FH})
    out = []
    for u, v in uvs:
        lat, lon, _ = g.pixel_to_latlon(cam, u, v)
        out.append({"u": u, "v": v, "lat": lat, "lon": lon})
    return out


UV = [(100, 400), (480, 300), (850, 420), (300, 500), (700, 330), (520, 470)]


def draft(points, **kw):
    start = {**TRUE, "yaw": 0.0, "pitch": 15.0, "hfov": 60.0, "height_m": 9.0, "roll": 0.0}
    return calib.draft_fit({"model": start, "frame": {"width": FW, "height": FH}, "points": points, **kw})


def test_fit_recovers_the_camera_and_reports_loo():
    r = draft(pairs(TRUE, UV))
    f = r["fit"]
    assert f["n"] == 6 and "hfov" in f["free"] and "height_m" in f["free"]
    assert abs(r["model"]["yaw"] - 210) < 0.5 and abs(r["model"]["pitch"] - 22) < 0.5 and abs(r["model"]["hfov"] - 70) < 1
    assert f["rms_px"] < 0.5 and f["loo"]["median_m"] < 0.2 and not f["at_limit"]
    assert len(r["footprint"]) > 10 and r["footprint"][0] == r["footprint"][-1]


def test_mis_click_shows_in_leave_one_out():
    pts = pairs(TRUE, UV + [(200, 350), (650, 520), (900, 300), (400, 380)])
    pts[2] = {**pts[2], "lat": pts[2]["lat"] + 0.0002}           # ~22 m off on the map
    loo = draft(pts)["fit"]["loo"]["per_point_m"]
    assert max(range(len(loo)), key=lambda i: loo[i]) == 2 and loo[2] > 5


def test_under_two_pairs_is_no_fit_and_keeps_the_hand_pose():
    r = draft(pairs(TRUE, UV[:1]))
    assert r["fit"] is None and r["footprint"] is None and r["model"]["yaw"] == 0.0


def test_bad_draft_is_400():
    with pytest.raises(calib.HTTPException) as e:
        calib.draft_fit({"model": {"lat": 1}, "frame": {"width": 1, "height": 1}})
    assert e.value.status_code == 400


def test_frozen_frames_keep_size_and_are_bounded():
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (64, 36)).save(buf, "JPEG")
    calib.FROZEN.clear()
    v = calib.keep_frozen("cam", 1_792_877_297_486_346_183, buf.getvalue())
    assert (v["width"], v["height"]) == (64, 36) and v["t_ns"] == "1792877297486346183" and v["url"].endswith(".jpg")
    for _ in range(calib.KEEP_FROZEN + 3):
        calib.keep_frozen("cam", 1, buf.getvalue())
    assert len(calib.FROZEN) == calib.KEEP_FROZEN and v["token"] not in calib.FROZEN


def test_operator_headers_pass_through_only_auth():
    from types import SimpleNamespace
    req = SimpleNamespace(headers={"cookie": "netra=abc", "authorization": "Basic eA==", "host": "x", "x-forwarded-for": "1.2.3.4"})
    assert calib.auth_headers(req) == {"cookie": "netra=abc", "authorization": "Basic eA=="}


def test_foot_is_bottom_centre():
    assert calib.foot([10, 20, 30, 80]) == [20, 80]
