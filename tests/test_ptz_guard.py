"""PTZ writes are operator-only, and the PTZ lock: a refused write never reaches ptzd (no camera, no network)."""
import pytest

pytest.importorskip("fastapi")
from fastapi import FastAPI, Request          # noqa: E402
from fastapi.testclient import TestClient     # noqa: E402

from hackdash import ptz                      # noqa: E402

WRITES = [("/move", {"pan": 0.1}), ("/stop", None), ("/center", {"x": 0.5, "y": 0.5}), ("/home", None),
          ("/home/save", None), ("/daynight", {"mode": "day"})]


class FakeResp:
    status_code = 200
    content = b""

    def __init__(self, body):
        self.body = body

    def json(self):
        return self.body


@pytest.fixture
def app(monkeypatch, tmp_path):
    calls = []

    async def fake_ptzd(cam, method, path, params=None, base=None):
        calls.append((method, path))
        return FakeResp({"pan": 1.0, "tilt": 2.0, "zoom": 1.0} if path == "/position" else {"ok": True})
    monkeypatch.setattr(ptz, "ptzd", fake_ptzd)
    monkeypatch.setattr(ptz, "TOKEN", "t")
    monkeypatch.setattr(ptz, "calibrated_pose", lambda cam: None)
    monkeypatch.setattr(ptz, "LOCK_FILE", tmp_path / "lock.json")
    monkeypatch.setattr(ptz, "_locks", {})
    a = FastAPI()

    @a.middleware("http")
    async def user(req: Request, call_next):
        req.state.user = req.headers.get("x-user")
        return await call_next(req)
    a.include_router(ptz.router, prefix="/hack/api")
    return TestClient(a), calls


def post(c, user, path, body=None):
    return c.post(f"/hack/api/ptz/axis-q6215{path}", json=body or {}, headers={"x-user": user} if user else {})


@pytest.mark.parametrize("user", ["hack_launch", "landon", "tanay", None])
def test_non_operators_get_403_and_nothing_is_sent(app, user):
    c, calls = app
    for path, body in WRITES + [("/lock", {"locked": True})]:
        r = post(c, user, path, body)
        assert r.status_code == 403 and r.json()["detail"] == "PTZ is operator-only", (user, path)
    assert calls == []


def test_service_account_denied_even_if_listed(app, monkeypatch):
    c, calls = app
    monkeypatch.setattr(ptz, "OPERATORS", {"william", "hack_launch"})
    assert post(c, "hack_launch", "/move", {"pan": 0.1}).status_code == 403 and calls == []


def test_reads_stay_open_for_the_service_account(app):
    c, calls = app
    r = c.get("/hack/api/ptz/axis-q6215/state", headers={"x-user": "hack_launch"})
    assert r.status_code == 200 and r.json()["can_write"] is False and r.json()["locked"] is None
    assert calls == [("GET", "/position")]


def test_operator_writes_and_lock(app):
    c, calls = app
    assert post(c, "william", "/move", {"pan": 0.1}).status_code == 200 and calls == [("POST", "/move")]
    assert post(c, "william", "/lock", {"locked": True}).json()["locked"] is True
    for path, body in WRITES:
        r = post(c, "william", path, body)
        assert r.status_code == 403 and r.json()["detail"].startswith("PTZ is locked"), path
    assert calls == [("POST", "/move")]                                   # nothing sent while locked
    assert c.get("/hack/api/ptz/axis-q6215/state", headers={"x-user": "william"}).json()["locked"]["by"] == "william"
    assert post(c, "william", "/lock", {"locked": False}).status_code == 200
    assert post(c, "william", "/stop").status_code == 200 and calls[-1] == ("POST", "/stop")
    assert ptz.LOCK_FILE.exists()
