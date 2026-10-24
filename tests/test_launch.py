"""Pure parts of hackdash.launch (no DB, no netra-ask): following a person, evidence, the multipart post."""
import io
import json
from collections import deque
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("psycopg")
from hackdash import launch  # noqa: E402

NS = launch.NS
T0 = 1_792_877_000 * NS


def fake_live(obs, links=None):
    return SimpleNamespace(OBS=SimpleNamespace(by_cam={"cam": deque(obs)}),
                           labels_for=lambda cam, uuids: ({u: s for u, s in (links or {}).items() if u in uuids}, {}))


def row(rec):
    return {"id": rec["id"], "record": rec}


BASE = {"id": "cam-op-20261024T210000Z-abcd", "camera_id": "cam", "mode": "live", "status": "open", "edge_track": "u1",
        "op_site_track": None, "track": [{"at": launch.iso(T0), "box": [1, 2, 3, 4], "lat": 1.0}],
        "lat": 32.0, "located": True, "loc_source": "sitefuse", "site_track_id": None}


def test_follow_appends_newest_obs_and_strips_derived():
    live = fake_live([(T0, "u1", [1, 2, 3, 4], 0.9, "person"), (T0 + NS, "u1", [5, 6, 7, 8], 0.9, "person"),
                      (T0 + 2 * NS, "u9", [0, 0, 1, 1], 0.9, "person")])
    rec = launch.follow(live, row(BASE), "2026-10-24T21:00:05+00:00")
    assert rec["track"][-1] == {"at": launch.iso(T0 + NS), "box": [5, 6, 7, 8]}
    assert rec["track"][0] == {"at": launch.iso(T0), "box": [1, 2, 3, 4]}       # per-point lat/lon dropped
    assert rec["updated_at"] == "2026-10-24T21:00:05+00:00"
    assert not set(launch.DERIVED) & set(rec)


def test_follow_person_gone_adds_no_point():
    live = fake_live([(T0, "u1", [1, 2, 3, 4], 0.9, "person")])
    rec = launch.follow(live, row(BASE), "2026-10-24T21:00:40+00:00")
    assert len(rec["track"]) == 1 and rec["updated_at"] == "2026-10-24T21:00:40+00:00"


def test_follow_relinked_edge_track_same_site_track():
    base = {**BASE, "site_track_id": "st1"}
    live = fake_live([(T0 + 3 * NS, "u2", [9, 9, 10, 10], 0.8, "person")], links={"u2": "st1"})
    rec = launch.follow(live, row(base), "x")
    assert rec["edge_track"] == "u2" and rec["op_site_track"] == "st1" and rec["track"][-1]["box"] == [9, 9, 10, 10]


def test_follow_keeps_last_points():
    base = {**BASE, "track": [{"at": launch.iso(T0 - i * NS), "box": [1, 2, 3, 4]} for i in range(40, 0, -1)]}
    live = fake_live([(T0, "u1", [1, 2, 3, 4], 0.9, "person")])
    assert len(launch.follow(live, row(base), "x")["track"]) == launch.KEEP_POINTS


def test_evidence_draws_and_crops():
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (1280, 720), (0, 0, 0)).save(buf, "JPEG")
    out = launch.evidence(buf.getvalue(), [960, 540, 1056, 810], 1920, 1080)
    assert set(out) == {"frame.jpg", "crop.jpg"}
    im = Image.open(io.BytesIO(out["frame.jpg"]))
    assert im.size == (1280, 720) and im.getpixel((640, 450))[0] > 200        # red box edge at the scaled x1
    assert launch.evidence(None, [0, 0, 1, 1], 1, 1) == {}


def test_post_incident_multipart(monkeypatch):
    seen = {}

    def fake(method, url, body, headers, timeout=15):
        seen.update(url=url, body=body, headers=headers)
        return 200, {"ok": True}
    monkeypatch.setattr(launch, "_http", fake)
    monkeypatch.setattr(launch, "WORKER_TOKEN", "tok")
    launch.post_incident({"id": "x"}, {"frame.jpg": b"\xff\xd8jpeg"})
    assert seen["url"].endswith("/api/dispatch/incidents") and seen["headers"]["Authorization"] == "Bearer tok"
    assert b'name="result"\r\n\r\n{"id": "x"}' in seen["body"] and b'name="frame.jpg"; filename="frame.jpg"' in seen["body"]
    monkeypatch.setattr(launch, "_http", lambda *a, **k: (400, {"detail": "bad incident id"}))
    with pytest.raises(RuntimeError, match="400: bad incident id"):
        launch.post_incident({"id": "x"})
