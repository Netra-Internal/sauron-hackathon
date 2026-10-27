"""Run one netra-edge (ask.edge.main, unmodified) per camera whose stream is live on this pod's mediamtx.

A camera joins the cloud edge by config + stream only: it is in the droplet's edge config (sites.yaml) and a box pushes
it to the pod as mediamtx path <stream> (= the production camera id). Every 15 s this reads the config and mediamtx's
ready paths; a configured camera with a ready path gets an edge process with its source_env set to
rtsp://127.0.0.1:8554/<stream>. A process that exits is restarted (as systemd's Restart=always does on the Jetson) once
its stream is ready, so stopping the edge of a camera that no longer streams here retires it. Once started, an edge keeps
running when its stream drops: it reports the growing frame age, which is what pages. Edges outlive the supervisor; a new
supervisor adopts the ones already running instead of starting a second edge per camera."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request

ASK = os.environ["ASK_URL"].rstrip("/")
TOKEN = os.environ["ASK_WORKER_TOKEN"]
MTX = os.environ.get("MTX_API", "http://127.0.0.1:9997")
LOGS = os.environ.get("EDGE_LOGS", "/workspace/edge/logs")


def get(url: str, auth: bool) -> dict:
    h = {"Authorization": f"Bearer {TOKEN}", "User-Agent": "netra-edge/1"} if auth else {}
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=20) as r:
        return json.loads(r.read())


class Adopted:
    """An edge started by an earlier supervisor (not our child): alive while its pid is."""

    def __init__(self, pid: int):
        self.pid, self.returncode = pid, None

    def poll(self):
        try:
            os.kill(self.pid, 0)
        except ProcessLookupError:
            self.returncode = -1
        return self.returncode


def running_edges() -> dict[str, Adopted]:
    out = {}
    for d in filter(str.isdigit, os.listdir("/proc")):
        try:
            argv = open(f"/proc/{d}/cmdline", "rb").read().split(b"\0")
        except OSError:
            continue
        if b"ask.edge.main" in argv and b"--camera" in argv[:-1]:
            out[argv[argv.index(b"--camera") + 1].decode()] = Adopted(int(d))
    return out


def main():
    procs: dict[str, subprocess.Popen | Adopted] = running_edges()
    for cid, p in procs.items():
        print(f"{time.strftime('%T')} edge {cid} adopted (pid {p.pid})", flush=True)
    while True:
        try:
            cams = get(f"{ASK}/api/edge/config", True)["cameras"]
            ready = {p["name"] for p in get(f"{MTX}/v3/paths/list", False)["items"] if p.get("ready")}
            for c in cams:
                stream, cid = c.get("stream", c["id"]), c["id"]
                p = procs.get(cid)
                if p is not None and p.poll() is None:
                    continue
                if stream not in ready:
                    continue
                if p is not None:
                    print(f"{time.strftime('%T')} edge {cid} exited {p.returncode}; restarting", flush=True)
                env = {**os.environ, c["edge"]["source_env"]: f"rtsp://127.0.0.1:8554/{stream}"}
                log = open(os.path.join(LOGS, f"edge-{cid}.log"), "a")
                procs[cid] = subprocess.Popen([sys.executable, "-u", "-m", "ask.edge.main", "--camera", cid], env=env,
                                              stdout=log, stderr=subprocess.STDOUT)
                print(f"{time.strftime('%T')} edge {cid} started on stream {stream} (pid {procs[cid].pid})", flush=True)
        except Exception as e:  # noqa: BLE001 — the supervisor must outlive a droplet or mediamtx blip
            print(f"{time.strftime('%T')} supervise: {type(e).__name__}: {e}", flush=True)
        time.sleep(15)


if __name__ == "__main__":
    main()
