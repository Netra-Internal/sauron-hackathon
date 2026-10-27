"""Read-only tools. Each returns the raw evidence (command output, rows, file lines) plus a few decoded fields, so every
claim Big Brother makes can be traced to something it just ran."""
from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import remote

NODEGUARD = os.environ.get("BB_NODEGUARD_DIR", "/var/lib/netra-nodeguard")
NODEGUARD_PY = os.environ.get("BB_NODEGUARD_PY", "/opt/netra/nodeguard/nodeguard.py")
PUSHES = os.environ.get("BB_PUSHES", "/var/lib/netra-phone/pushes.jsonl")
PREVIEWS = os.environ.get("BB_PREVIEWS", "/var/lib/netra-ask/previews")
PT = ZoneInfo("America/Los_Angeles")
# Jev price basis (stack audit Oct 27): 8,336 input tokens per strip (audit replay of the identical call; the live watcher
# does not log usage) x $0.042 per M input tokens; output is free.
JEV_TOK_PER_STRIP = 8336
JEV_USD_PER_MTOK = 0.042

PI_UNITS = ["netra-cloud-push", "tailscaled", "netra-node-revssh", "netra-node-report", "netra-node-tailscale-watchdog",
            "netra-node-wifi-watchdog"]
DROPLET_UNITS = ["netra-ask", "netra-phonealert", "netra-nodeguard-recv", "netra-ask-cloud-tunnel", "netra-cloud-hls-tunnel",
                 "netra-cloud-presign-tunnel", "netra-r2-presign", "netra-cloud-evidence.timer", "netra-bigbrother"]
POD_LOGS = ["archive", "boot", "dispatch-demo-linovision", "dispatch-axis-q6215", "dispatch-jetson-c920",
            "edge-demo-linovision", "edge-jetson-c920", "mediamtx", "serve", "supervise"]

THROTTLE_BITS = {0: "under-voltage now", 1: "ARM frequency capped now", 2: "throttled now", 3: "soft temp limit now",
                 16: "under-voltage since boot", 17: "frequency capped since boot", 18: "throttled since boot",
                 19: "soft temp limit since boot"}


def decode_throttled(value: str | int) -> list[str]:
    v = int(value, 16) if isinstance(value, str) else int(value)
    return [txt for bit, txt in THROTTLE_BITS.items() if v & (1 << bit)] or ["none (0x0)"]


def _tail_jsonl(path: str, n: int) -> list:
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 400 * n - 4096))
            lines = f.read().decode(errors="replace").splitlines()[-n:]
    except OSError as e:
        return [{"error": str(e)}]
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except ValueError:
            pass
    return out


def node_status() -> dict:
    """Pi health: the last nodeguard report (pushed every minute) + a live query over ssh."""
    rep = {}
    try:
        rep = json.load(open(f"{NODEGUARD}/report-demo-node.json"))
        rep["throttled_decoded"] = decode_throttled(rep.get("throttled", "0x0"))
        rep["age_s"] = round(time.time() - datetime.fromisoformat(rep["received_at"]).timestamp())
    except (OSError, ValueError, KeyError) as e:
        rep = {"error": f"no nodeguard report: {e}"}
    live = remote.pi(
        "echo temp: $(vcgencmd measure_temp); echo $(vcgencmd get_throttled); echo up: $(uptime -p); cat /proc/loadavg; "
        "for u in " + " ".join(PI_UNITS[:3]) + "; do echo \"$u: $(systemctl is-active $u)\"; done; "
        "tailscale status --json 2>/dev/null | python3 -c 'import json,sys; print(\"tailscale BackendState:\", json.load(sys.stdin)[\"BackendState\"])'; "
        "free -m | sed -n 2p; df -h / | tail -1; "
        "echo '--- netra-cloud-push journal'; journalctl -u netra-cloud-push -n 8 --no-pager -o short-iso", timeout=30)
    for ln in live.get("out", "").splitlines():
        if ln.startswith("throttled="):
            live["throttled_decoded"] = decode_throttled(ln.split("=", 1)[1])
    return {"nodeguard_last_report": rep, "live": live}


def node_events(hours: float = 24) -> dict:
    """nodeguard events (watchdog restarts, throttle, power, tunnel) and its uptime timeline."""
    since = time.time() - hours * 3600
    ev = [e for e in _tail_jsonl(f"{NODEGUARD}/events.jsonl", 400)
          if "t" not in e or datetime.fromisoformat(e["t"]).timestamp() >= since]
    tl = subprocess.run(["python3", NODEGUARD_PY, "timeline", "--days", str(max(1, round(hours / 24)))],
                        capture_output=True, text=True, timeout=30)
    return {"events": ev[-60:], "timeline": tl.stdout[-4000:], "timeline_err": tl.stderr[-500:]}


def pi_journal(unit: str, lines: int = 40) -> dict:
    if unit not in PI_UNITS:
        return {"error": f"unit not allowed; choose from {PI_UNITS}"}
    return remote.pi(f"systemctl status {unit} --no-pager -n 0 | head -5; "
                     f"journalctl -u {unit} -n {min(int(lines), 200)} --no-pager -o short-iso", timeout=30)


def _psql(sql: str) -> str:
    p = subprocess.run(["sudo", "-u", "postgres", "psql", "-d", "netra_ask", "-X", "-A", "-F", " | ", "-P", "footer=off",
                        "-c", sql], capture_output=True, text=True, timeout=30, cwd="/tmp")
    return (p.stdout + p.stderr)[-5000:]


def camera_health(camera: str = "demo-linovision") -> dict:
    """Production view of one camera: feed_health heartbeats, Jev watch records, incidents (netra_ask DB, read-only)."""
    if not camera.replace("-", "").isalnum():
        return {"error": "bad camera id"}
    c = camera
    return {
        "feed_health_last_5": _psql(f"select received_at, frame_age_s, fps_in, fps_analysed, infer_ms, restarts, "
                                    f"open_tracks, worker from feed_health where camera_id='{c}' order by id desc limit 5"),
        "feed_health_last_hour": _psql(f"select count(*) beats, round(avg(fps_analysed)::numeric,1) fps_avg, "
                                       f"round(max(frame_age_s)::numeric,1) max_frame_age_s, max(received_at) last "
                                       f"from feed_health where camera_id='{c}' and received_at > now()-interval '1 hour'"),
        "dispatch_watch_24h": _psql(f"select count(*) n, max(opened_at) last from dispatch_watch where camera_id='{c}' "
                                    f"and opened_at > now()-interval '24 hours'"),
        "dispatch_incidents_7d": _psql(f"select id, mode, status, verdict, why, opened_at, closed_at from dispatch_incidents "
                                       f"where camera_id='{c}' and opened_at > now()-interval '7 days' "
                                       f"order by opened_at desc limit 10"),
    }


def pod_status() -> dict:
    return remote.pod("""
echo "host $(hostname), up $(cut -d. -f1 /proc/uptime) s"
ps -eo pid,etime,args | grep -E 'supervise|edge.main|dispatch|archive|mediamtx|edge.serve' | grep -v grep | cut -c1-160
nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu --format=csv,noheader
df -h /workspace | tail -1; uptime
cd /workspace/edge/logs && for f in supervise dispatch-demo-linovision edge-demo-linovision; do echo "--- $f"; tail -n 3 $f.log; done
""", timeout=40)


def pod_log(name: str, lines: int = 40) -> dict:
    if name not in POD_LOGS:
        return {"error": f"log not allowed; choose from {POD_LOGS}"}
    return remote.pod(f"tail -n {min(int(lines), 300)} /workspace/edge/logs/{name}.log | cut -c1-400", timeout=30)


def day_window(day: str = "today", now: datetime | None = None) -> tuple[float, float, str]:
    """A Pacific-time calendar day as epoch seconds (William is in PT)."""
    now = now or datetime.now(PT)
    d = now.date() - timedelta(days=1) if day == "yesterday" else now.date()
    start = datetime(d.year, d.month, d.day, tzinfo=PT)
    end = start + timedelta(days=1)
    return start.timestamp(), min(end.timestamp(), now.timestamp()), d.isoformat() + " PT"


def jev_cost(day: str = "today") -> dict:
    """Jev calls = rows in the pod's dispatch/<cam>/strips.jsonl without "gated" (gated rows skipped Jev)."""
    t0, t1, label = day_window(day)
    res = remote.pod(f"""/workspace/edge/venv/bin/python - <<'EOF'
import json, glob, os
for f in sorted(glob.glob('/workspace/edge/dispatch/*/strips.jsonl')):
    cam = f.split('/')[-2]; jev = gated = 0
    with open(f) as fh:
        for ln in fh:
            try: r = json.loads(ln)
            except ValueError: continue
            if not ({t0} <= r.get('t', 0) < {t1}): continue
            if r.get('gated'): gated += 1
            else: jev += 1
    print(json.dumps({{"camera": cam, "jev_calls": jev, "gated_skipped": gated}}))
EOF""", timeout=60)
    cams = []
    for ln in res.get("out", "").splitlines():
        try:
            c = json.loads(ln)
        except ValueError:
            continue
        c["usd_est"] = round(c["jev_calls"] * JEV_TOK_PER_STRIP * JEV_USD_PER_MTOK / 1e6, 2)
        cams.append(c)
    return {"day": label, "window_epoch": [t0, t1], "cameras": cams,
            "total_usd_est": round(sum(c["usd_est"] for c in cams), 2),
            "basis": f"counted strips (measured) x {JEV_TOK_PER_STRIP} input tokens/strip (assumed: audit replay, live usage "
                     f"is not logged) x ${JEV_USD_PER_MTOK}/M tokens; output free",
            "ssh": {k: res.get(k) for k in ("rc", "err")}}


def phone_pushes(n: int = 10) -> dict:
    return {"file": PUSHES, "last": _tail_jsonl(PUSHES, min(int(n), 50))}


def r2_archive() -> dict:
    return remote.pod("""cd /workspace/edge
echo "cameras: $(cat archive_cams)"
for c in $(cat archive_cams); do echo "$c done: $(wc -l < archive/$c.done 2>/dev/null || echo 0) segments, ring now: $(ls ring/$c 2>/dev/null | wc -l) files"; done
pgrep -af 'cloud/pod/archive.py$' || echo 'archive.py NOT running'
echo '--- archive.log'; tail -n 8 logs/archive.log
""", timeout=30)


def droplet_services(unit: str = "", lines: int = 20) -> dict:
    out = {"active": subprocess.run(["systemctl", "is-active", *DROPLET_UNITS], capture_output=True, text=True).stdout.split()}
    out["active"] = dict(zip(DROPLET_UNITS, out["active"]))
    if unit:
        if unit not in DROPLET_UNITS:
            return {**out, "error": f"unit not allowed; choose from {DROPLET_UNITS}"}
        out["journal"] = subprocess.run(["journalctl", "-u", unit, "-n", str(min(int(lines), 200)), "--no-pager",
                                         "-o", "short-iso"], capture_output=True, text=True).stdout[-5000:]
    return out


def camera_frame(camera: str = "demo-linovision") -> dict:
    """The droplet's latest preview frame for the camera (written by netra-ask from the edge)."""
    if not camera.replace("-", "").isalnum():
        return {"error": "bad camera id"}
    p = f"{PREVIEWS}/{camera}.jpg"
    try:
        st = os.stat(p)
    except OSError:
        return {"error": f"no preview frame at {p}"}
    return {"path": p, "bytes": st.st_size, "age_s": round(time.time() - st.st_mtime),
            "mtime_utc": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(timespec="seconds")}
