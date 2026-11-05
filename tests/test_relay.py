"""hackdash.relay pass-through: config/heartbeat and the in-edge Jev watcher's routes reach netra-ask unchanged."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hackdash import relay


@pytest.fixture
def ask(monkeypatch):
    """A stand-in netra-ask that records each request and echoes what it saw."""
    seen = []

    class H(BaseHTTPRequestHandler):
        def _answer(self):
            body = self.rfile.read(int(self.headers.get("content-length") or 0))
            seen.append({"method": self.command, "path": self.path, "auth": self.headers.get("authorization"),
                         "ctype": self.headers.get("content-type"), "body": body})
            out = json.dumps({"path": self.path}).encode()
            self.send_response(201 if self.command == "POST" else 200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        do_GET = do_POST = _answer

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(relay, "ASK_URL", f"http://127.0.0.1:{srv.server_port}/ask")
    yield seen
    srv.shutdown()


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(relay.router, prefix="/hack/relay")
    return TestClient(app)


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/edge/config"),
    ("POST", "/api/edge/heartbeat"),
    ("GET", "/api/edge/jev_area?camera=demo-linovision"),
    ("POST", "/api/dispatch/watch"),
    ("POST", "/api/dispatch/incidents"),
])
def test_passthrough_keeps_path_query_token_and_status(ask, client, method, path):
    body = b'{"camera_id": "demo-linovision"}' if method == "POST" else None
    r = client.request(method, "/hack/relay" + path, content=body,
                       headers={"Authorization": "Bearer tok", "Content-Type": "application/json"})
    assert r.status_code == (201 if method == "POST" else 200)
    assert r.json() == {"path": "/ask" + path}
    assert ask[-1]["method"] == method and ask[-1]["path"] == "/ask" + path and ask[-1]["auth"] == "Bearer tok"
    if body:
        assert ask[-1]["body"] == body


def test_incident_multipart_is_forwarded_byte_for_byte(ask, client):
    files = {"result": (None, json.dumps({"id": "i1"})), "strip": ("strip.jpg", b"\xff\xd8jpegbytes", "image/jpeg")}
    r = client.post("/hack/relay/api/dispatch/incidents", files=files, headers={"Authorization": "Bearer tok"})
    assert r.status_code == 201
    got = ask[-1]
    assert got["ctype"].startswith("multipart/form-data; boundary=")
    assert b"\xff\xd8jpegbytes" in got["body"] and b'"id": "i1"' in got["body"]


def test_login_exempts_every_relay_route():
    from hackdash import app as hack_app
    for path in ("edge/bucket", "edge/config", "edge/heartbeat", "edge/jev_area", "dispatch/incidents", "dispatch/watch"):
        assert f"/hack/relay/api/{path}" in hack_app.NO_LOGIN


# ---------------------------------------------------------------- live first: stale buckets parked, never forwarded

import asyncio
import os
import time


def _spool_with(tmp_path, ages_s):
    sp = relay.Spool(tmp_path)
    sp.load()
    for i, age in enumerate(ages_s, 1):
        name = f"{i:012d}-{time.time_ns() - int(age * 1e9)}.req"
        head = json.dumps({"content-type": "application/json"}).encode()
        (tmp_path / name).write_bytes(len(head).to_bytes(4, "big") + head + b'{"n": %d}' % i)
        sp.q.append(name)
        sp.bytes += (tmp_path / name).stat().st_size
    return sp


async def _drain(sp, until):
    task = asyncio.create_task(relay._forward_loop(sp))
    for _ in range(200):
        if until():
            break
        await asyncio.sleep(0.02)
    task.cancel()


def test_stale_buckets_are_parked_and_fresh_ones_forwarded(ask, tmp_path, monkeypatch):
    monkeypatch.setattr(relay, "LIVE_S", 120)
    sp = _spool_with(tmp_path, [3600, 600, 5, 1])          # two from an outage, two live
    asyncio.run(_drain(sp, lambda: not sp.q))
    assert [s["body"] for s in ask] == [b'{"n": 3}', b'{"n": 4}']    # only the live ones reach netra-ask, in order
    assert sorted(p.name.split("-")[0] for p in (tmp_path / "late").glob("*.req")) == ["000000000001", "000000000002"]
    assert sp.stats["parked"] == 2 and sp.stats["forwarded"] == 2 and sp.bytes == 0


def test_bucket_retried_through_an_outage_is_parked_once_stale(tmp_path, monkeypatch):
    monkeypatch.setattr(relay, "ASK_URL", "http://127.0.0.1:9/ask")      # nothing listens: every forward fails
    monkeypatch.setattr(relay, "BACKOFF_S", (0.01,))
    monkeypatch.setattr(relay, "LIVE_S", 0.3)
    sp = _spool_with(tmp_path, [0])
    asyncio.run(_drain(sp, lambda: not sp.q))
    assert not sp.q and sp.stats["parked"] == 1 and len(list((tmp_path / "late").glob("*.req"))) == 1


def test_late_dir_is_capped_oldest_first(tmp_path, monkeypatch):
    monkeypatch.setattr(relay, "LATE_MAX_BYTES", 1)        # keeps nothing but the newest one over the cap check
    sp = _spool_with(tmp_path, [900, 800, 700])
    for _ in range(3):
        sp.park(sp.q[0])
    left = sorted(p.name for p in (tmp_path / "late").glob("*.req"))
    assert sp.stats["late_deleted"] == 3 and left == []
    monkeypatch.setattr(relay, "LATE_MAX_BYTES", 10 ** 9)
    sp2 = _spool_with(tmp_path, [900, 800])
    sp2.late_bytes = 0
    sp2.park(sp2.q[0]); sp2.park(sp2.q[0])
    assert len(list((tmp_path / "late").glob("*.req"))) == 2 and sp2.stats["late_deleted"] == 0
