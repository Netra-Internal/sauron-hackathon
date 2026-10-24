"""Run one netra-edge (ask.edge.main, unmodified) per camera whose stream is live on this pod's mediamtx.

A camera joins the cloud edge by config + stream only: it is in the droplet's edge config (sites.yaml) and a box pushes
it to the pod as mediamtx path <stream> (= the production camera id). Every 15 s this reads the config and mediamtx's
ready paths; a configured camera with a ready path gets an edge process with its source_env set to
rtsp://127.0.0.1:8554/<stream>. A process that exits is restarted (as systemd's Restart=always does on the Jetson). Once
started, an edge keeps running when its stream drops: it reports the growing frame age, which is what pages."""
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


def main():
    procs: dict[str, subprocess.Popen] = {}
    while True:
        try:
            cams = get(f"{ASK}/api/edge/config", True)["cameras"]
            ready = {p["name"] for p in get(f"{MTX}/v3/paths/list", False)["items"] if p.get("ready")}
            for c in cams:
                stream, cid = c.get("stream", c["id"]), c["id"]
                p = procs.get(cid)
                if p is not None and p.poll() is None:
                    continue
                if p is None and stream not in ready:
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
