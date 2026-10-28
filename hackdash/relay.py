"""Edge relay: an edge whose ask base URL is https://internal.netralabs.net/hack/relay posts here instead of /ask.

netra-ask's bucket ingest takes 2-12 s per POST and the edge poster is sequential, so its boxes back up. Here:
- POST api/edge/bucket: worker token checked, the bucket's positions go to hackdash.live (OBS) at once, the raw request
  (body, content-type, Authorization) is spooled to disk and answered 200; one background worker forwards the spool to
  netra-ask (127.0.0.1:8400, not through nginx, so the /ask mirror never sees it twice) in arrival order, retrying until
  netra-ask answers. Nothing is dropped: a 4xx netra-ask will never accept (bad payload) is moved to rejected/ and
  logged, never deleted. Memory holds file names only; a spool over HACK_RELAY_MAX_MB answers 503, so the edge keeps the
  bucket and retries itself.
- GET api/edge/config, POST api/edge/heartbeat: plain synchronous pass-through (netra-ask checks the token).
- GET api/edge/jev_area, POST api/dispatch/incidents and api/dispatch/watch: the same pass-through, for an edge that runs
  the Jev watcher in-process (ask.edge.main --jev on) and so posts through this base URL too.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import time
from collections import deque
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Request, Response

from hackdash import live

log = logging.getLogger("hackdash.relay")
router = APIRouter()

ASK_URL = os.environ.get("HACK_RELAY_ASK_URL", "http://127.0.0.1:8400/ask")
SPOOL = Path(os.environ.get("HACK_RELAY_DIR", "/var/lib/sauron-hack/relay"))
MAX_BYTES = int(float(os.environ.get("HACK_RELAY_MAX_MB", "2000")) * 1e6)
BACKOFF_S = (1, 2, 5, 10, 30)
KEEP_HEADERS = ("content-type", "authorization", "user-agent")


class Spool:
    def __init__(self, root: Path):
        self.root = root
        self.q: deque[str] = deque()             # spooled file names, oldest first
        self.bytes = 0
        self.seq = 0
        self.stats = {"received": 0, "forwarded": 0, "rejected": 0, "retries": 0, "last_error": None,
                      "last_forward_s": None, "last_forward_at": None}
        self.wake = asyncio.Event()
        self.task: asyncio.Task | None = None
        self.loaded = False

    def load(self):
        """Pick up what a previous run left (in order)."""
        if self.loaded:
            return
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        (self.root / "rejected").mkdir(exist_ok=True)
        for p in sorted(self.root.glob("*.req")):
            self.q.append(p.name)
            self.bytes += p.stat().st_size
        self.seq = int(self.q[-1].split("-")[0]) if self.q else 0
        self.loaded = True
        if self.q:
            log.warning("relay: %d spooled buckets from a previous run", len(self.q))

    def put(self, headers: dict, body: bytes) -> str:
        self.load()
        self.seq += 1
        name = f"{self.seq:012d}-{time.time_ns()}.req"
        head = json.dumps(headers).encode()
        tmp = self.root / (name + ".tmp")
        tmp.write_bytes(len(head).to_bytes(4, "big") + head + body)
        os.replace(tmp, self.root / name)
        self.q.append(name)
        self.bytes += len(head) + len(body) + 4
        self.stats["received"] += 1
        self.wake.set()
        return name

    def read(self, name: str) -> tuple[dict, bytes]:
        raw = (self.root / name).read_bytes()
        n = int.from_bytes(raw[:4], "big")
        return json.loads(raw[4:4 + n]), raw[4 + n:]

    def done(self, name: str, rejected: bool = False):
        p = self.root / name
        size = p.stat().st_size
        if rejected:
            os.replace(p, self.root / "rejected" / name)
        else:
            p.unlink()
        self.q.popleft()
        self.bytes -= size

    def status(self) -> dict:
        oldest = int(self.q[0].split("-")[1].split(".")[0]) if self.q else None
        return {"backlog": len(self.q), "backlog_mb": round(self.bytes / 1e6, 2),
                "oldest_age_s": round(time.time() - oldest / 1e9, 1) if oldest else None, **self.stats}


SPOOL_ = Spool(SPOOL)


async def _forward_loop(sp: Spool):
    client = httpx.AsyncClient(timeout=httpx.Timeout(180, connect=5))
    last_log = 0.0
    while True:
        if not sp.q:
            sp.wake.clear()
            await sp.wake.wait()
            continue
        name = sp.q[0]
        headers, body = sp.read(name)
        for attempt in range(10 ** 9):
            t0 = time.monotonic()
            try:
                r = await client.post(f"{ASK_URL}/api/edge/bucket", content=body, headers=headers)
                code = r.status_code
                err = None if code < 300 else f"{code} {r.text[:200]}"
            except Exception as e:
                code, err = None, f"{type(e).__name__}: {e}"
            if code is not None and code < 300:
                sp.done(name)
                sp.stats["forwarded"] += 1
                sp.stats["last_forward_s"] = round(time.monotonic() - t0, 2)
                sp.stats["last_forward_at"] = time.time()
                break
            sp.stats["last_error"] = err
            if code is not None and 400 <= code < 500 and code not in (401, 403, 408, 409, 429):
                log.error("relay: netra-ask refused %s for good (%s); kept in rejected/", name, err)
                sp.done(name, rejected=True)
                sp.stats["rejected"] += 1
                break
            sp.stats["retries"] += 1
            wait = BACKOFF_S[min(attempt, len(BACKOFF_S) - 1)]
            log.warning("relay: forward %s failed (%s), retry in %ds, backlog %d", name, err, wait, len(sp.q))
            await asyncio.sleep(wait)
        if time.monotonic() - last_log > 30 or len(sp.q) > 20 and time.monotonic() - last_log > 5:
            last_log = time.monotonic()
            log.warning("relay: backlog %d (%.1f MB), forwarded %d, last forward %.2fs", len(sp.q), sp.bytes / 1e6,
                        sp.stats["forwarded"], sp.stats["last_forward_s"] or 0)


def ensure_worker():
    SPOOL_.load()
    if SPOOL_.task is None or SPOOL_.task.done():
        if SPOOL_.task is not None and SPOOL_.task.done() and not SPOOL_.task.cancelled() and SPOOL_.task.exception():
            log.error("relay: forwarder died: %r; restarting", SPOOL_.task.exception())
        SPOOL_.task = asyncio.create_task(_forward_loop(SPOOL_))
        SPOOL_.wake.set()


@router.on_event("startup")
async def _start():
    ensure_worker()


def _token_ok(request: Request) -> bool:
    got = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    return bool(live.WORKER_TOKEN) and hmac.compare_digest(got, live.WORKER_TOKEN)


@router.post("/api/edge/bucket")
async def bucket(request: Request):
    if not _token_ok(request):
        raise HTTPException(401, "bad worker token")
    ensure_worker()
    if SPOOL_.bytes > MAX_BYTES:
        raise HTTPException(503, f"relay spool full ({SPOOL_.bytes // 1_000_000} MB backlog); retry later")
    body = await request.body()
    SPOOL_.put({k: request.headers[k] for k in KEEP_HEADERS if k in request.headers}, body)
    try:
        form = await request.form()
        result = json.loads(form["result"])
        cam = str(result["camera_id"])
        live.OBS.push(cam, result.get("positions") or [], result.get("complete_ns"))
        live.on_bucket(cam)
    except Exception as e:                       # the boxes are best effort; the bucket itself is already spooled
        log.warning("relay: could not read positions: %s", e)
    return {"ok": True, "relayed": True, "backlog": len(SPOOL_.q)}


async def _passthrough(request: Request, path: str) -> Response:
    headers = {k: request.headers[k] for k in KEEP_HEADERS if k in request.headers}
    async with httpx.AsyncClient(timeout=60) as c:
        try:
            r = await c.request(request.method, f"{ASK_URL}/api/{path}", params=request.query_params,
                                content=await request.body(), headers=headers)
        except Exception as e:
            raise HTTPException(502, f"netra-ask unreachable: {type(e).__name__}")
    return Response(r.content, status_code=r.status_code, media_type=r.headers.get("content-type"))


@router.get("/api/edge/config")
async def config(request: Request):
    return await _passthrough(request, "edge/config")


@router.post("/api/edge/heartbeat")
async def heartbeat(request: Request):
    return await _passthrough(request, "edge/heartbeat")


@router.get("/api/edge/jev_area")
async def jev_area(request: Request):
    return await _passthrough(request, "edge/jev_area")


@router.post("/api/dispatch/incidents")
async def dispatch_incident(request: Request):
    return await _passthrough(request, "dispatch/incidents")


@router.post("/api/dispatch/watch")
async def dispatch_watch(request: Request):
    return await _passthrough(request, "dispatch/watch")


@router.get("/status")
async def status():
    """Backlog and counters (behind the internal login: /hack/relay/status is not exempt)."""
    ensure_worker()
    return SPOOL_.status()
