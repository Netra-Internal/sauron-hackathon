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
