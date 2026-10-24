"""droplink: our stand-in for the drone's receiver of netra-ask's dispatch webhook.

netra-ask POSTs every dispatch message (netra.dispatch.incident / .position / .command / .watch) to DISPATCH_WEBHOOK,
signed `X-Netra-Signature: t=<unix>,v1=<hex HMAC-SHA256(secret, "<t>.<raw body>")>`. droplink checks the signature
(DISPATCH_WEBHOOK_SECRET, |now - t| <= 300 s), drops repeats of a delivery_id, stores every message in sqlite and answers
2xx, so it shows exactly what a drone would get. A bad signature is stored too (verified=0) and answered 401.

  POST /sauron/v1/messages          the webhook
  GET  /messages?since=<seq>&limit= what was received, oldest first (the hackdash reads this; bound to 127.0.0.1 only)
  GET  /health

stdlib only: python3 droplink.py --listen 127.0.0.1:8510 --db /var/lib/droplink/messages.sqlite
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

log = logging.getLogger("droplink")
SKEW_S = 300
MAX_BODY = 2 * 1024 * 1024
SCHEMA = """CREATE TABLE IF NOT EXISTS messages (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at TEXT NOT NULL,
    type TEXT,
    incident_id TEXT,
    delivery_id TEXT,
    msg_seq INTEGER,
    verified INTEGER NOT NULL,
    why TEXT,
    duplicate INTEGER NOT NULL DEFAULT 0,
    body TEXT NOT NULL)"""


def verify(secret: str, header: str | None, body: bytes, now: float | None = None) -> str | None:
    """None when the signature is good, else why not."""
    if not secret:
        return "no secret configured"
    if not header:
        return "no X-Netra-Signature"
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    try:
        t = int(parts["t"])
    except (KeyError, ValueError):
        return "bad t"
    if abs((now if now is not None else time.time()) - t) > SKEW_S:
        return "stale t"
    want = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(want, parts.get("v1", "")):
        return "bad v1"
    return None


class Store:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute(SCHEMA)
        self.db.execute("CREATE INDEX IF NOT EXISTS messages_delivery ON messages(delivery_id)")
        self.db.commit()
        self.lock = threading.Lock()

    def add(self, msg: dict | None, raw: bytes, why: str | None) -> tuple[int, bool]:
        """Store one received message. Returns (seq, duplicate). A verified repeat of a delivery_id is stored as
        duplicate=1 (so the log shows the retry) and the caller answers 2xx without acting on it."""
        m = msg if isinstance(msg, dict) else {}
        inc = m.get("incident") if isinstance(m.get("incident"), dict) else {}
        iid = inc.get("id") or m.get("incident_id")
        did = m.get("delivery_id")
        with self.lock:
            dup = bool(why is None and did and self.db.execute(
                "SELECT 1 FROM messages WHERE delivery_id=? AND verified=1 AND duplicate=0", (did,)).fetchone())
            cur = self.db.execute(
                "INSERT INTO messages (received_at, type, incident_id, delivery_id, msg_seq, verified, why, duplicate, body)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (datetime.now(timezone.utc).isoformat(), m.get("type"), iid, did,
                 m.get("seq") if isinstance(m.get("seq"), int) else None, int(why is None), why, int(dup),
                 raw.decode("utf-8", "replace")))
            self.db.commit()
            return cur.lastrowid, dup

    def since(self, seq: int, limit: int) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT * FROM messages WHERE seq > ? ORDER BY seq LIMIT ?", (seq, limit)).fetchall()
        out = []
        for r in rows:
            try:
                body = json.loads(r["body"])
            except ValueError:
                body = r["body"]
            out.append({"seq": r["seq"], "received_at": r["received_at"], "type": r["type"],
                        "incident_id": r["incident_id"], "delivery_id": r["delivery_id"], "msg_seq": r["msg_seq"],
                        "verified": bool(r["verified"]), "why": r["why"], "duplicate": bool(r["duplicate"]),
                        "body": body})
        return out


class Handler(BaseHTTPRequestHandler):
    server_version = "droplink/1"

    def log_message(self, fmt, *a):
        log.info("%s " + fmt, self.address_string(), *a)

    def _send(self, code: int, obj) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if urlparse(self.path).path != "/sauron/v1/messages":
            return self._send(404, {"error": "not found"})
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            return self._send(413, {"error": "too large"})
        raw = self.rfile.read(n)
        why = verify(self.server.secret, self.headers.get("X-Netra-Signature"), raw)
        try:
            msg = json.loads(raw)
        except ValueError:
            msg = None
            why = why or "body is not JSON"
        seq, dup = self.server.store.add(msg, raw, why)
        log.info("message %s type=%s verified=%s dup=%s", seq, (msg or {}).get("type"), why is None, dup)
        if why:
            return self._send(401, {"ok": False, "error": why, "stored": seq})
        return self._send(200, {"ok": True, "stored": seq, "duplicate": dup})

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/health":
            return self._send(200, {"ok": True, "secret": bool(self.server.secret), "t": time.time()})
        if u.path == "/messages":
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                since, limit = int(q.get("since", 0)), min(int(q.get("limit", 500)), 5000)
            except ValueError:
                return self._send(400, {"error": "since and limit are integers"})
            return self._send(200, {"messages": self.server.store.since(since, limit)})
        return self._send(404, {"error": "not found"})


def serve(listen: str, db: str, secret: str) -> ThreadingHTTPServer:
    host, port = listen.rsplit(":", 1)
    srv = ThreadingHTTPServer((host, int(port)), Handler)
    srv.store, srv.secret = Store(db), secret
    return srv


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen", default=os.environ.get("DROPLINK_LISTEN", "127.0.0.1:8510"))
    ap.add_argument("--db", default=os.environ.get("DROPLINK_DB", "/var/lib/droplink/messages.sqlite"))
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    secret = os.environ.get("DISPATCH_WEBHOOK_SECRET", "")
    if not secret:
        log.warning("DISPATCH_WEBHOOK_SECRET is unset: every message will be stored unverified and answered 401")
    srv = serve(a.listen, a.db, secret)
    log.info("droplink on %s, db %s", a.listen, a.db)
    srv.serve_forever()


if __name__ == "__main__":
    main()
