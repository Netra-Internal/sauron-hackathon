import hashlib
import hmac
import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from droplink import droplink

SECRET = "s3cret"


def sig(body: bytes, t: int | None = None, secret: str = SECRET) -> str:
    t = int(time.time()) if t is None else t
    return f"t={t},v1=" + hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()


@pytest.fixture
def srv(tmp_path):
    s = droplink.serve("127.0.0.1:0", str(tmp_path / "m.sqlite"), SECRET)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_address[1]}"
    s.shutdown()


def post(url, body: bytes, header: str | None):
    h = {"Content-Type": "application/json"}
    if header:
        h["X-Netra-Signature"] = header
    try:
        with urllib.request.urlopen(urllib.request.Request(url + "/sauron/v1/messages", data=body, headers=h)) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def messages(url, since=0):
    with urllib.request.urlopen(f"{url}/messages?since={since}") as r:
        return json.loads(r.read())["messages"]


def test_verify():
    b = b'{"a":1}'
    assert droplink.verify(SECRET, sig(b), b) is None
    assert droplink.verify(SECRET, sig(b, int(time.time()) - 301), b) == "stale t"
    assert droplink.verify(SECRET, sig(b, secret="other"), b) == "bad v1"
    assert droplink.verify(SECRET, None, b) == "no X-Netra-Signature"
    assert droplink.verify("", sig(b), b) == "no secret configured"


def test_store_dedupe_and_reject(srv):
    msg = {"type": "netra.dispatch.incident", "delivery_id": "d1", "seq": 1, "incident": {"id": "cam-op-1"}}
    b = json.dumps(msg).encode()
    assert post(srv, b, sig(b)) == (200, {"ok": True, "stored": 1, "duplicate": False})
    code, out = post(srv, b, sig(b))                 # netra-ask retry: same delivery_id
    assert code == 200 and out["duplicate"] is True
    code, out = post(srv, b, sig(b, secret="nope"))
    assert code == 401 and out["error"] == "bad v1"
    cmd = {"type": "netra.dispatch.command", "command": "end", "delivery_id": "d2", "seq": 1, "incident_id": "cam-op-1"}
    b2 = json.dumps(cmd).encode()
    assert post(srv, b2, sig(b2))[0] == 200
    ms = messages(srv)
    assert [(m["type"], m["incident_id"], m["verified"], m["duplicate"]) for m in ms] == [
        ("netra.dispatch.incident", "cam-op-1", True, False),
        ("netra.dispatch.incident", "cam-op-1", True, True),
        ("netra.dispatch.incident", "cam-op-1", False, False),
        ("netra.dispatch.command", "cam-op-1", True, False)]
    assert ms[3]["body"]["command"] == "end"
    assert [m["seq"] for m in messages(srv, since=2)] == [3, 4]
