"""Run one netra-edge (ask.edge.main, unmodified) per camera whose stream is live on this pod's mediamtx, and the site
engine (ask.siteengine) + its on-demand Jev endpoint (ask.perception.judged) per site in /workspace/edge/engine_sites.

A camera joins the cloud edge by config + stream only: it is in the droplet's edge config (sites.yaml) and a box pushes
it to the pod as mediamtx path <stream> (= the production camera id). Every 15 s this reads the config and mediamtx's
ready paths; a configured camera with a ready path gets an edge process with its source_env set to
rtsp://127.0.0.1:8554/<stream>. A process that exits is restarted (as systemd's Restart=always does on the Jetson) once
its stream is ready, so stopping the edge of a camera that no longer streams here retires it. Once started, an edge keeps
running when its stream drops: it reports the growing frame age, which is what pages. Edges outlive the supervisor; a new
supervisor adopts the ones already running instead of starting a second edge per camera.

Files in /workspace/edge (read every pass; a change applies to processes started after it, so restart an edge to apply):
  engine_sites   site ids, one engine per site: the n-th site's engine on 127.0.0.1:8610+2n, its judged on 8611+2n.
                 A camera in that site's site file (cameras[].source.camera_id) gets EDGE_ENGINE_URL and --judge on.
                 Engines post to the droplet's /ask directly (the edge relay only carries the edge routes).
  engine.env     KEY=VALUE lines added to every engine's env (e.g. ENGINE_WORLD=1, ENGINE_WORLD_PRIORS=<json>).
  edge_jev       "on": cameras in dispatch_cams run the Jev watcher inside their edge (--jev on, DISPATCH_* from
                 dispatch.env, Jev key from /root/dispatch.secret) and boot.sh starts no dispatch.sh loops.
                 Anything else / missing: the standalone dispatch.sh watchers (the rollback).
Engine recordings (--record) older than 7 days are deleted hourly."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request

ASK = os.environ["ASK_URL"].rstrip("/")
ASK_DIRECT = os.environ.get("ASK_DIRECT_URL", "https://internal.netralabs.net/ask")
TOKEN = os.environ["ASK_WORKER_TOKEN"]
MTX = os.environ.get("MTX_API", "http://127.0.0.1:9997")
W = os.environ.get("EDGE_HOME", "/workspace/edge")
LOGS = os.environ.get("EDGE_LOGS", f"{W}/logs")
REC = os.environ.get("ENGINE_REC", "/workspace/engine/rec")
LEDGER = os.environ.get("ENGINE_LEDGER", "/workspace/engine/jev-ledger")
JUDGE_DIR = os.environ.get("EDGE_JUDGE_DIR", "/run/netra-edge/judge")
SECRET = "/root/dispatch.secret"
REC_KEEP_S = 7 * 86400


def get(url: str, auth: bool) -> dict:
    h = {"Authorization": f"Bearer {TOKEN}", "User-Agent": "netra-edge/1"} if auth else {}
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=20) as r:
        return json.loads(r.read())


def words(name: str) -> list[str]:
    try:
        return open(os.path.join(W, name)).read().split()
    except OSError:
        return []


def env_file(path: str) -> dict:
    """KEY=VALUE lines (dispatch.env, the decrypted Jev key); comments and blanks skipped, no shell expansion."""
    out = {}
    try:
        for ln in open(path):
            k, sep, v = ln.strip().partition("=")
            if sep and k and not k.startswith("#"):
                out[k.strip()] = v.strip().strip("'\"")
    except OSError:
        pass
    return out


class Adopted:
    """A process started by an earlier supervisor (not our child): alive while its pid is."""

    def __init__(self, pid: int):
        self.pid, self.returncode = pid, None

    def poll(self):
        try:
            os.kill(self.pid, 0)
        except ProcessLookupError:
            self.returncode = -1
        return self.returncode


KINDS = {b"ask.edge.main": ("edge", b"--camera"), b"ask.siteengine": ("engine", b"--site"),
         b"ask.perception.judged": ("judged", b"--site")}


def running() -> dict[str, Adopted]:
    """Edges, engines and judged processes already running, keyed "edge:<camera>", "engine:<site>", "judged:<site>"."""
    out = {}
    for d in filter(str.isdigit, os.listdir("/proc")):
        try:
            argv = open(f"/proc/{d}/cmdline", "rb").read().split(b"\0")
        except OSError:
            continue
        for mod, (kind, flag) in KINDS.items():
            if mod in argv and flag in argv[:-1]:
                out[f"{kind}:{argv[argv.index(flag) + 1].decode()}"] = Adopted(int(d))
    return out


def start(procs: dict, key: str, args: list[str], env: dict, log: str, why: str):
    p = procs.get(key)
    if p is not None:
        print(f"{time.strftime('%T')} {key} exited {p.returncode}; restarting", flush=True)
    procs[key] = subprocess.Popen([sys.executable, "-u", "-m", *args], env=env, stdout=open(os.path.join(LOGS, log), "a"),
                                  stderr=subprocess.STDOUT)
    print(f"{time.strftime('%T')} {key} started {why}(pid {procs[key].pid}): {' '.join(args)}", flush=True)


def jev_env() -> dict:
    return {**env_file(f"{W}/dispatch.env"), **env_file(SECRET)}


SITEFILE_EVERY_S = 60
_sitefile_at: dict[str, float] = {}


def sites_pass(procs: dict, site_cams: dict[str, tuple[str, int]]):
    """Engine + judged per listed site (always restarted); the camera -> (site, engine port) map from the site files
    (re-read every minute)."""
    sites = words("engine_sites")
    for n, sid in enumerate(sites):
        port = 8610 + 2 * n
        if time.time() - _sitefile_at.get(sid, 0) >= SITEFILE_EVERY_S:
            try:
                sf = get(f"{ASK_DIRECT}/api/sites/{sid}/sitefile", True)
                for c in sf.get("cameras") or []:
                    cid = (c.get("source") or {}).get("camera_id")
                    if cid:
                        site_cams[cid] = (sid, port)
                _sitefile_at[sid] = time.time()
            except Exception as e:  # noqa: BLE001 - keep the last map; the engine itself still starts
                print(f"{time.strftime('%T')} site file {sid}: {type(e).__name__}: {e}", flush=True)
        env = {**os.environ, "ASK_URL": ASK_DIRECT}
        for key, args, extra in (
                (f"engine:{sid}", ["ask.siteengine", "--site", sid, "--port", str(port), "--record", REC],
                 {"ENGINE_JUDGE_URL": f"http://127.0.0.1:{port + 1}", "PERCEPTION_JUDGE_URL": f"http://127.0.0.1:{port + 1}",
                 **env_file(f"{W}/engine.env")}),
                (f"judged:{sid}", ["ask.perception.judged", "--site", sid, "--port", str(port + 1), "--ledger-dir", LEDGER],
                 {**jev_env(), "EDGE_JUDGE_DIR": JUDGE_DIR})):
            p = procs.get(key)
            if p is None or p.poll() is not None:
                start(procs, key, args, {**env, **extra}, f"{key.replace(':', '-')}.log", "")
    for key, p in list(procs.items()):           # a site taken out of engine_sites: stop its engine and judged
        kind, _, sid = key.partition(":")
        if kind in ("engine", "judged") and sid not in sites and p.poll() is None:
            os.kill(p.pid, 15)
            print(f"{time.strftime('%T')} {key} stopped (not in engine_sites)", flush=True)
            del procs[key]


def edge_pass(procs: dict, site_cams: dict[str, tuple[str, int]]):
    cams = get(f"{ASK}/api/edge/config", True)["cameras"]
    ready = {p["name"] for p in get(f"{MTX}/v3/paths/list", False)["items"] if p.get("ready")}
    jev_cams = set(words("dispatch_cams")) if words("edge_jev") == ["on"] else set()
    for c in cams:
        stream, cid = c.get("stream", c["id"]), c["id"]
        p = procs.get(f"edge:{cid}")
        if p is not None and p.poll() is None:
            continue
        if stream not in ready:
            continue
        env = {**os.environ, c["edge"]["source_env"]: f"rtsp://127.0.0.1:8554/{stream}"}
        args = ["ask.edge.main", "--camera", cid]
        if cid in site_cams:
            # the judge server in the edge makes the Jev call itself, so it needs the key too
            env.update(env_file(SECRET), EDGE_ENGINE_URL=f"http://127.0.0.1:{site_cams[cid][1]}", EDGE_JUDGE_DIR=JUDGE_DIR)
            args += ["--judge", "on"]
        if cid in jev_cams:
            env.update(jev_env(), DISPATCH_LOG_DIR=f"{W}/dispatch/{cid}")
            os.makedirs(env["DISPATCH_LOG_DIR"], exist_ok=True)
            args += ["--jev", "on"]
        start(procs, f"edge:{cid}", args, env, f"edge-{cid}.log", f"on stream {stream} ")


def prune_recordings():
    now = time.time()
    for root, _, files in os.walk(REC):
        for f in files:
            path = os.path.join(root, f)
            try:
                if now - os.path.getmtime(path) > REC_KEEP_S:
                    os.remove(path)
                    print(f"{time.strftime('%T')} pruned {path}", flush=True)
            except OSError:
                pass


def main():
    for d in (JUDGE_DIR, REC, LEDGER):
        os.makedirs(d, exist_ok=True)
    procs: dict[str, subprocess.Popen | Adopted] = running()
    for key, p in procs.items():
        print(f"{time.strftime('%T')} {key} adopted (pid {p.pid})", flush=True)
    site_cams: dict[str, tuple[str, int]] = {}
    last_prune = 0.0
    while True:
        # each part on its own: a droplet blip in one must not stop the other (or the engines' restarts)
        for step in (lambda: sites_pass(procs, site_cams), lambda: edge_pass(procs, site_cams)):
            try:
                step()
            except Exception as e:  # noqa: BLE001 — the supervisor must outlive a droplet or mediamtx blip
                print(f"{time.strftime('%T')} supervise: {type(e).__name__}: {e}", flush=True)
        if time.time() - last_prune > 3600:
            prune_recordings()
            last_prune = time.time()
        time.sleep(15)


if __name__ == "__main__":
    main()
