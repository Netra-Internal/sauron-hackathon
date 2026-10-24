"""Shadow droplet for the cloud edge: the pod's netra-edge talks to this instead of production.

GET  /api/edge/config     production's config (fetched with the worker token, read-only), with
                          every camera, renamed to its shadow id and pointed at the pod's own source env.
POST /api/edge/bucket     appended to <out>/buckets.jsonl with the receive time (crops/previews are dropped, the
                          latest preview.jpg is kept for eyeballing). Nothing is forwarded anywhere.
POST /api/edge/heartbeat  appended to <out>/heartbeats.jsonl.

Every production camera is offered as <id>-cloud with source_env CLOUD_<ID>_URL and `stream` = its production id (the
mediamtx path the box pushes to); cloud/pod/supervise.py only runs the ones whose stream is live on the pod."""
from __future__ import annotations

import argparse
import email.parser
import email.policy
import json
import os
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PROD = os.environ.get("PROD_ASK_URL", "https://internal.netralabs.net/ask").rstrip("/")
TOKEN = os.environ["ASK_WORKER_TOKEN"]
LOCK = threading.Lock()


def prod_config() -> dict:
    r = urllib.request.Request(f"{PROD}/api/edge/config", headers={"Authorization": f"Bearer {TOKEN}", "User-Agent": "netra-edge/1"})
    with urllib.request.urlopen(r, timeout=30) as resp:
        cfg = json.loads(resp.read())
    cams = []
    for c in cfg["cameras"]:
        env = "CLOUD_" + c["id"].upper().replace("-", "_") + "_URL"
        cams.append({**c, "id": c["id"] + "-cloud", "edge": {**c["edge"], "source_env": env}, "stream": c["id"]})
    return {**cfg, "cameras": cams}


class H(BaseHTTPRequestHandler):
    out = "."

    def log_message(self, *a):
        pass

    def _send(self, code: int, body: dict):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authed(self) -> bool:
        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            self._send(401, {"detail": "bad token"})
            return False
        return True

    def do_GET(self):
        if not self._authed():
            return
        if self.path.endswith("/api/edge/config"):
            try:
                return self._send(200, prod_config())
            except Exception as e:  # noqa: BLE001
                return self._send(502, {"detail": f"prod config: {type(e).__name__}: {e}"})
        self._send(404, {"detail": "no"})

    def _append(self, name: str, rec: dict):
        with LOCK, open(os.path.join(self.out, name), "a") as f:
            f.write(json.dumps(rec) + "\n")

    def do_POST(self):
        recv_ns = time.time_ns()
        if not self._authed():
            return
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n)
        if self.path.endswith("/api/edge/heartbeat"):
            self._append("heartbeats.jsonl", {"recv_ns": recv_ns, **json.loads(body)})
            return self._send(200, {"ok": True})
        if self.path.endswith("/api/edge/bucket"):
            msg = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
                b"Content-Type: " + self.headers["Content-Type"].encode() + b"\r\n\r\n" + body)
            parts = {p.get_param("name", header="content-disposition"): p.get_payload(decode=True) for p in msg.iter_parts()}
            result = json.loads(parts.pop("result"))
            files = list(parts)
            if "preview.jpg" in parts:
                with open(os.path.join(self.out, "preview.jpg"), "wb") as f:
                    f.write(parts["preview.jpg"])
            for t in result.get("tracks", []):
                t.pop("embedding", None)
            self._append("buckets.jsonl", {"recv_ns": recv_ns, "bytes": n, "files": len(files), "result": result})
            return self._send(200, {"ok": True, "tracks": len(result.get("tracks", [])),
                                    "positions": len(result.get("positions") or [])})
        self._send(404, {"detail": "no"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8470)
    ap.add_argument("--out", default="/workspace/shadow")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    H.out = a.out
    ThreadingHTTPServer(("127.0.0.1", a.port), H).serve_forever()


if __name__ == "__main__":
    main()
