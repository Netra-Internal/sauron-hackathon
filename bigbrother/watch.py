"""Proactive Big Brother: detect an issue, investigate with the read tools, apply the allowlisted fix, verify. Discord gets
ONE message per incident and ONLY when the infra is down and Big Brother could not fix it (with an @mention; William,
Oct 28). Everything else (fixed, checked, recovered, warnings) goes to log.jsonl / incidents.jsonl only.

Runs as netra-bigbrother-watch.service, one pass every INTERVAL_S. Detection is deterministic code, not Claude:
- nodeguard state-<node>.json (nodeguard owns it): node offline, video down (skipped when nodeguard marks it scheduled).
- nodeguard events.jsonl (read from a byte cursor): tailscale watchdog restarts, under-voltage throttle bits.
- feed_health (netra_ask DB) for every camera in remote.CAMERAS: no heartbeat for STALE_S, or mean fps_analysed over the
  last FPS_WINDOW_S below LOW_FPS (the live target is 5).
- the pod: unreachable, a Jev watcher missing for a watched camera, the R2 archiver not running or not progressing.
Fixes go through actions.run(auto=True), so the runbook gates (cooldowns, reboot only after a failed push restart, max
1 reboot / 30 min / node, overlay root) apply here too. Each incident has a key (e.g. cam:demo-linovision-2); while it stays
open it is not posted again; it is retried at most MAX_ATTEMPTS times, RETRY_S apart. Everything goes to log.jsonl and
incidents.jsonl; Big Brother's own node actions are also noted in nodeguard's event log (kind "note", state "bigbrother")."""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from . import actions, log, reads, remote

STATE = os.environ.get("BB_STATE", "/var/lib/netra-bigbrother")
NODEGUARD = reads.NODEGUARD
INTERVAL_S = 60
STALE_S = 180                 # no feed_health heartbeat for 3 min = feed down
FPS_WINDOW_S = 180
LOW_FPS = 2.5                 # "far below 5"
RETRY_S = 3600
MAX_ATTEMPTS = 3
CLOSE_AFTER_CLEAR = 2         # passes without the issue before an incident closes
MAX_POSTS_PER_HOUR = 6
# incident kinds that mean "infra down"; uv (power warning) and engineslow are logged, never posted
POST_KINDS = {"cam", "node", "tailscale", "watcher", "archiver", "pod", "engine", "enginelink", "judged"}
EVENT_MERGE_S = {"tailscale": 3600, "uv": 12 * 3600}
ARCHIVE_STALE_S = 9000        # the archiver passes hourly: a segment still not in R2 after 2.5 h = stalled
PT = ZoneInfo("America/Los_Angeles")


@dataclass
class Issue:
    key: str                  # incident identity, e.g. "cam:demo-linovision-2", "node:demo-node", "tailscale:demo-node"
    kind: str                 # cam | node | tailscale | uv | watcher | archiver | pod
    target: str               # camera or node id ("" for pod/archiver)
    title: str
    evidence: list[str] = field(default_factory=list)
    since: str = ""


def pt(ts: str | float | None) -> str:
    if ts in (None, ""):
        return "?"
    d = datetime.fromtimestamp(ts, timezone.utc) if isinstance(ts, (int, float)) else datetime.fromisoformat(ts)
    return d.astimezone(PT).strftime("%a %H:%M PT")


def ago(ts: str | float, now: float) -> str:
    t = ts if isinstance(ts, (int, float)) else datetime.fromisoformat(ts).timestamp()
    s = int(now - t)
    return f"{s // 3600} h {s % 3600 // 60} min" if s >= 3600 else f"{s // 60} min"


# ----------------------------------------------------------------------------------------------------------- detection

def nodeguard_state(node: str) -> dict:
    try:
        return json.load(open(f"{NODEGUARD}/state-{node}.json"))
    except (OSError, ValueError):
        return {}


def feed(now: float) -> dict:
    """camera -> {"age_s", "fps", "beats"} from feed_health (cameras with no row in 24 h are absent)."""
    cams = ",".join(f"'{c}'" for c in remote.CAMERAS)
    sql = (f"select camera_id, extract(epoch from now()-max(received_at))::int, "
           f"round(avg(fps_analysed) filter (where received_at > now()-interval '{FPS_WINDOW_S} seconds')::numeric, 2), "
           f"count(*) filter (where received_at > now()-interval '{FPS_WINDOW_S} seconds') "
           f"from feed_health where camera_id in ({cams}) and received_at > now()-interval '24 hours' group by 1")
    p = subprocess.run(["sudo", "-u", "postgres", "psql", "-d", "netra_ask", "-X", "-At", "-F", "|", "-c", sql],
                       capture_output=True, text=True, timeout=30, cwd="/tmp")
    out = {}
    for ln in p.stdout.splitlines():
        cam, age, fps, n = ln.split("|")
        out[cam] = {"age_s": int(age), "fps": float(fps) if fps else None, "beats": int(n)}
    return out


def camera_issues(fh: dict, states: dict, now: float) -> list[Issue]:
    out = []
    for cam, node in remote.CAMERAS.items():
        st = states.get(node, {})
        if st.get("node") == "offline":
            continue                                   # the node incident covers it
        if st.get("video") == "down" and st.get("video_sched"):
            continue                                   # nodeguard: scheduled off (night schedule)
        ev, since = [], ""
        if st.get("video") == "down":
            since = st.get("video_since", "")
            ev.append(f"nodeguard: video DOWN since {pt(since)} ({ago(since, now)})"
                      + ("; Pi reports push_active=false" if (st.get("last_report") or {}).get("push_active") is False else ""))
        f = fh.get(cam)
        if f is None:
            ev.append("feed_health: no heartbeat in 24 h")
        elif f["age_s"] > STALE_S:
            ev.append(f"feed_health: last heartbeat {f['age_s'] // 60} min ago")
        elif f["beats"] >= 3 and f["fps"] is not None and f["fps"] < LOW_FPS:
            ev.append(f"feed_health: {f['fps']} fps analysed (mean of {f['beats']} beats, last {FPS_WINDOW_S // 60} min; "
                      f"target 5)")
        if ev:
            out.append(Issue(f"cam:{cam}", "cam", cam, f"{cam} video down / degraded", ev, since))
    return out


def node_issues(states: dict, now: float) -> list[Issue]:
    out = []
    for node, st in states.items():
        if st.get("node") == "offline" and not st.get("node_sched"):
            out.append(Issue(f"node:{node}", "node", node, f"{node} offline",
                             [f"nodeguard: no report since {pt(st.get('node_since'))} ({ago(st['node_since'], now)})"]
                             if st.get("node_since") else ["nodeguard: node offline"], st.get("node_since", "")))
    return out


def new_events(state: dict) -> list[dict]:
    """nodeguard events appended since the last pass (byte cursor in our own state)."""
    path = f"{NODEGUARD}/events.jsonl"
    try:
        size = os.path.getsize(path)
    except OSError:
        return []
    pos = state.get("events_pos")
    if pos is None or pos > size:                      # first run (or rotated): start at the end, don't replay history
        state["events_pos"] = size
        return []
    with open(path, "rb") as f:
        f.seek(pos)
        data = f.read()
    state["events_pos"] = pos + len(data.rsplit(b"\n", 1)[0]) + 1 if b"\n" in data else pos
    out = []
    for ln in data.split(b"\n")[:-1]:
        try:
            out.append(json.loads(ln))
        except ValueError:
            pass
    return out


def event_issues(events: list[dict]) -> list[Issue]:
    out = []
    for e in events:
        node = e.get("node", "")
        if e.get("kind") == "tailscale" and e.get("state") == "restarted":
            out.append(Issue(f"tailscale:{node}", "tailscale", node, f"{node} Tailscale watchdog restarted tailscaled",
                             [f"nodeguard {pt(e.get('at') or e['t'])}: {e.get('text', '')[:300]}"], e.get("at") or e["t"]))
        elif e.get("kind") == "throttle" and int(str(e.get("bits", "0")), 16) & 0x10001:
            out.append(Issue(f"uv:{node}", "uv", node, f"{node} under-voltage",
                             [f"nodeguard {pt(e['t'])}: throttled {e.get('state')}"], e["t"]))
    return out


POD_PROBE = r"""cd /workspace/edge && python3 - <<'EOF'
import json, os, glob, subprocess, time
ps = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True).stdout.splitlines()
def cams(pat): return sorted({l.split("--camera")[1].split()[0] for l in ps if pat in l and "--camera" in l})
rd = lambda f: open(f).read().split() if os.path.exists(f) else []
arch = {}
for c in rd("archive_cams"):
    df = f"archive/{c}.done"
    done = {l.split()[0] for l in open(df) if l.strip()} if os.path.exists(df) else set()
    seg = sorted(glob.glob(f"ring/{c}/*.mkv"))
    # a segment becomes archivable once two newer ones exist (the archiver never takes the newest two), so its
    # "eligible since" is the time of the segment two places after it, not its own time (matters after an outage)
    elig = [os.path.getmtime(seg[k + 2]) for k in range(len(seg) - 2) if os.path.basename(seg[k]) not in done]
    arch[c] = {"pending": len(elig), "oldest_pending": min(elig) if elig else None}
site = lambda pat: sorted({l.split("--site")[1].split()[0] for l in ps if pat in l and "--site" in l})
print(json.dumps({"now": time.time(), "edge": cams("ask.edge.main"), "watch": cams("ask.dispatch.watch"),
                  "edge_jev": sorted({l.split("--camera")[1].split()[0] for l in ps
                                      if "ask.edge.main" in l and "--camera" in l and "--jev on" in l}),
                  "engine": site("-m ask.siteengine"), "judged": site("-m ask.perception.judged"),
                  "dispatch_cams": rd("dispatch_cams"), "archive_running": any(l.endswith("cloud/pod/archive.py") for l in ps),
                  "archive": arch}))
EOF"""


def pod_issues(now: float) -> tuple[list[Issue], dict]:
    r = remote.pod(POD_PROBE, timeout=40)
    try:
        p = json.loads(r["out"].strip().splitlines()[-1])
    except (ValueError, IndexError, KeyError):
        return [Issue("pod", "pod", "", "cloud pod unreachable",
                      [f"ssh to the pod failed (rc {r.get('rc')}): {r.get('err', '').strip()[-200:]}"])], {}
    out = []
    for cam in remote.CAMERAS:
        # Jev runs either in a dispatch.sh watcher (today) or inside the edge with --jev on (perception, P3)
        if cam in p["dispatch_cams"] and cam not in p["watch"] and cam not in p.get("edge_jev", []):
            out.append(Issue(f"watcher:{cam}", "watcher", cam, f"{cam} Jev dispatch watcher not running",
                             [f"pod: {cam} is in dispatch_cams but no ask.dispatch.watch process and no edge with "
                              f"--jev on (watchers: {p['watch']}, edges: {p['edge']})"]))
    stale = [c for c, a in p["archive"].items()
             if a["oldest_pending"] and p["now"] - a["oldest_pending"] > ARCHIVE_STALE_S]
    if p["archive"] and (not p["archive_running"] or stale):
        ev = [] if p["archive_running"] else ["pod: archive.py is not running"]
        ev += [f"pod: {c} has {p['archive'][c]['pending']} segments not in R2, the oldest "
               f"archivable for {ago(p['archive'][c]['oldest_pending'], p['now'])} (the archiver passes hourly)" for c in stale]
        out.append(Issue("archiver", "archiver", "", "R2 footage archiver stalled", ev))
    return out, p


ENGINE_DOWN_S = 60          # heartbeat every 10 s (ask/siteengine/droplet.py HEALTH_EVERY_S)
ENGINE_LINK_S = 60          # camera fresh in feed_health but nothing reached the engine for this long
STEP_BUDGET_MS = 3000       # camera -> decision budget (CENTRAL-ENGINE-PLAN verification 3)


def engine_rows(site: str) -> list | None:
    """Newest engine_health rows (epoch, health) for the site in the last 24 h, newest first; None if no table yet."""
    sql = (f"select extract(epoch from received_at), health::text from engine_health where site_id='{site}' "
           f"and received_at > now()-interval '24 hours' order by received_at desc limit 12")
    p = subprocess.run(["sudo", "-u", "postgres", "psql", "-d", "netra_ask", "-X", "-At", "-F", "\t", "-c", sql],
                       capture_output=True, text=True, timeout=30, cwd="/tmp")
    if "does not exist" in p.stderr:
        return None
    out = []
    for ln in p.stdout.splitlines():
        t, h = ln.split("\t", 1)
        out.append((float(t), json.loads(h)))
    return out


def engine_issues(site: str, rows: list | None, fh: dict, pod: dict, state: dict, now: float) -> list[Issue]:
    """Only once the engine has run in the last 24 h (no rows = not deployed / switched off on purpose: silent)."""
    out = []
    seen = state.setdefault("seen", {})
    if pod and site in pod.get("judged", []):
        seen[f"judged:{site}"] = True
    if not rows:
        return out
    t0, h = rows[0]
    proc = (" (pod: engine process " + ("running" if site in pod.get("engine", []) else "NOT running") + ")") if pod else ""
    if now - t0 > ENGINE_DOWN_S:
        return [Issue(f"engine:{site}", "engine", site, f"site engine {site} down",
                      [f"engine_health: last heartbeat {ago(t0, now)} ago ({pt(t0)}), every 10 s when up{proc}"])]
    older = next(((t, oh) for t, oh in rows if t <= t0 - 60), None)
    if older and h.get("steps") is not None and h.get("steps") == older[1].get("steps"):
        out.append(Issue(f"engine:{site}", "engine", site, f"site engine {site} stuck",
                         [f"engine_health: steps {h.get('steps')} unchanged since {pt(older[0])}; heartbeats still "
                          f"arriving{proc}"]))
    for cam, c in (h.get("cameras") or {}).items():
        f = fh.get(cam)
        rx = c.get("last_rx_age_s")
        if f and f["age_s"] < ENGINE_LINK_S and (rx is None or rx > ENGINE_LINK_S):
            out.append(Issue(f"enginelink:{cam}", "enginelink", cam, f"{cam} -> engine link broken",
                             [f"feed_health: {cam} heartbeat {f['age_s']} s old (edge is up)",
                              f"engine_health {pt(t0)}: last bucket from {cam} "
                              + (f"{rx} s before" if rx is not None else "never received")]))
    if (h.get("step_ms_last") or 0) > STEP_BUDGET_MS:
        out.append(Issue(f"engineslow:{site}", "engineslow", site, f"site engine {site} slow",
                         [f"engine_health: step_ms_last {h['step_ms_last']}, max {h.get('step_ms_max')} "
                          f"(budget {STEP_BUDGET_MS} ms camera -> decision)"]))
    if pod and site in pod.get("engine", []) and site not in pod.get("judged", []) and seen.get(f"judged:{site}"):
        out.append(Issue(f"judged:{site}", "judged", site, f"on-demand Jev (judged) for {site} not running",
                         [f"pod: ask.perception.judged --site {site} was running before and is gone; the engine's "
                          f"needs_judgment rules get no Jev answers"]))
    return out


def detect(state: dict, now: float) -> tuple[list[Issue], dict]:
    states = {n: nodeguard_state(n) for n in remote.NODES}
    fh = feed(now)
    pod, probe = pod_issues(now)
    eng = []
    for site in remote.ENGINE_SITES:
        eng += engine_issues(site, engine_rows(site), fh, probe, state, now)
    issues = node_issues(states, now) + camera_issues(fh, states, now) + event_issues(new_events(state)) + pod + eng
    return issues, {"feed": fh, "pod": probe, "nodes": {n: {k: s.get(k) for k in ("node", "video", "video_since")}
                                                        for n, s in states.items()}}


# ----------------------------------------------------------------------------------------------------------- playbooks

def nodeguard_note(node: str, text: str) -> None:
    """Tell nodeguard's timeline what we did (same shape as its hand-written notes)."""
    rec = {"t": datetime.now(timezone.utc).isoformat(timespec="seconds"), "node": node, "kind": "note",
           "state": "bigbrother", "text": text}
    try:
        with open(f"{NODEGUARD}/events.jsonl", "a") as f:
            f.write(json.dumps(rec) + "\n")
    except OSError:
        pass


def wait_feed(cam: str, timeout_s: int, sleep=time.sleep) -> dict | None:
    """Poll feed_health until a fresh heartbeat (< 30 s old) with fps >= 3 over the last 60 s; None on timeout."""
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        sleep(15)
        f = feed(time.time()).get(cam)
        if f and f["age_s"] < 30 and (f["fps"] or 0) >= 3:
            return f
    return None


def probe_node(node: str) -> dict:
    """Which routes reach the node, plus the push state and journal."""
    script = ("echo up: $(uptime -p); echo push: $(systemctl is-active netra-cloud-push); "
              "echo tailscaled: $(systemctl is-active tailscaled); echo root: $(findmnt -n -o FSTYPE /); "
              "journalctl -u netra-cloud-push -n 6 --no-pager -o short-iso | cut -c1-200")
    tn = remote.pi(script, timeout=25, node=node)
    rev = None if tn["via"].endswith(":tailnet") else remote.pi(script, timeout=25, prefer="rev", node=node)
    best = tn if tn["rc"] != 255 else (rev or tn)
    return {"tailnet": tn["via"].endswith(":tailnet"), "rev": bool(rev and rev["via"].endswith(":rev")),
            "reachable": best["rc"] != 255, "out": best.get("out", ""), "err": best.get("err", "")}


def _short(res: dict) -> str:
    if "refused" in res:
        return "refused: " + res["refused"]
    tail = [ln for ln in (res.get("out", "") + res.get("err", "")).strip().splitlines() if ln.strip()][-2:]
    return ("ok" if res.get("ok") else f"FAILED rc {res.get('rc')}") + (": " + " / ".join(t[:160] for t in tail) if tail else "")


def fix_camera(i: Issue, did: list[str]) -> bool | None:
    cam, node = i.target, remote.CAMERAS[i.target]
    pr = probe_node(node)
    push_line = next((ln for ln in pr["out"].splitlines() if ln.startswith("push:")), "push: ?")
    i.evidence.append(f"{node}: " + (f"reachable ({'tailnet' if pr['tailnet'] else 'reverse tunnel only'}), {push_line}"
                                     if pr["reachable"] else "UNREACHABLE over tailnet and reverse tunnel"))
    if not pr["reachable"]:
        did.append("nothing: cannot reach the node (power / Wi-Fi?); its Wi-Fi watchdog reboots it after 10 min offline")
        return False
    r = actions.run("restart_push", request_text="", target=node, auto=True)
    did.append(f"restart netra-cloud-push on {node}: {_short(r)}")
    if r.get("ok"):
        nodeguard_note(node, f"Big Brother restarted netra-cloud-push ({i.title})")
    f = wait_feed(cam, 150)
    if f:
        did.append(f"verified: feed_health {f['fps']} fps, heartbeat {f['age_s']} s old")
        return True
    did.append("feed still down 150 s after the push restart")
    actions.note_push_failed(node)
    r = actions.run("reboot_node", request_text="", target=node, auto=True)
    did.append(f"reboot {node}: {_short(r)}")
    if not r.get("ok"):
        return False
    nodeguard_note(node, f"Big Brother rebooted {node}: push restart did not bring {cam} back ({i.title})")
    t0 = time.time()
    while time.time() - t0 < 240 and not probe_node(node)["reachable"]:
        time.sleep(20)
    f = wait_feed(cam, 240)
    if f:
        did.append(f"verified after reboot: feed_health {f['fps']} fps, heartbeat {f['age_s']} s old")
        return True
    did.append("feed still down 4 min after the reboot")
    return False


def fix_node(i: Issue, did: list[str]) -> bool | None:
    node = i.target
    pr = probe_node(node)
    i.evidence.append(f"ssh: tailnet {'OK' if pr['tailnet'] else 'FAIL'}, reverse tunnel "
                      f"{'OK' if pr['rev'] else ('not tried' if pr['tailnet'] else 'FAIL')}")
    if pr["tailnet"]:
        did.append("nothing to fix: the node answers over the tailnet (nodeguard's reports are not arriving; "
                   "netra-node-report on the node is nodeguard's)")
        return None
    if pr["rev"]:
        r = actions.run("restart_tailscaled", request_text="", target=node, auto=True)
        did.append(f"restart tailscaled on {node} (via reverse tunnel): {_short(r)}")
        if r.get("ok"):
            nodeguard_note(node, "Big Brother restarted tailscaled (node unreachable over the tailnet)")
        time.sleep(20)
        ok = probe_node(node)["tailnet"]
        did.append("verified: tailnet ssh works again" if ok else "tailnet ssh still fails")
        return ok
    did.append("nothing: unreachable on both routes (power / Wi-Fi?); its Wi-Fi watchdog reboots it after 10 min offline")
    return False


def check_tailscale(i: Issue, did: list[str]) -> bool | None:
    pr = probe_node(i.target)
    if pr["tailnet"]:
        did.append("checked: the watchdog's restart worked, the node answers over the tailnet now")
        return True
    i.evidence.append("ssh over the tailnet fails now")
    return fix_node(i, did)


def report_uv(i: Issue, did: list[str]) -> bool | None:
    st = reads.node_status(i.target)
    rep = st.get("nodeguard_last_report", {})
    i.evidence.append(f"now: {rep.get('temp_c')} °C, throttled {rep.get('throttled')} = "
                      f"{', '.join(rep.get('throttled_decoded', []))}")
    did.append("nothing: under-voltage is power (solar / battery / cable), no remote fix")
    return False


def fix_watcher(i: Issue, did: list[str]) -> bool | None:
    r = actions.run("restart_pod_jev_watcher", request_text="", target=i.target, auto=True)
    did.append(f"restart the {i.target} Jev watcher: {_short(r)}")
    ok = bool(r.get("ok")) and f"--camera {i.target}" in r.get("out", "")
    did.append("verified: watcher process running" if ok else "watcher process not seen after the restart")
    return ok


def fix_archiver(i: Issue, did: list[str]) -> bool | None:
    r = actions.run("rerun_r2_archiver", request_text="", auto=True)
    did.append(f"re-run the R2 archiver: {_short(r)}")
    ok = bool(r.get("ok")) and "cloud/pod/archive.py" in r.get("out", "").split("stopped archive.py")[-1]
    did.append("verified: archive.py running a fresh pass" if ok else "archive.py not seen running after the re-run")
    return ok


def report_pod(i: Issue, did: list[str]) -> bool | None:
    did.append("nothing: the pod is not reachable over SSH; a pod restart is cloudpod's / William's call (costs money, "
               "changes ports)")
    return False


def wait_engine(site: str, timeout_s: int, sleep=time.sleep) -> tuple | None:
    """A fresh heartbeat (< 20 s) whose step counter moved since the previous one."""
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        sleep(15)
        rows = engine_rows(site) or []
        if len(rows) >= 2 and time.time() - rows[0][0] < 20 and rows[0][1].get("steps") != rows[1][1].get("steps"):
            return rows[0]
    return None


def fix_engine(i: Issue, did: list[str]) -> bool | None:
    r = actions.run("restart_engine", request_text="", target=i.target, auto=True)
    did.append(f"restart the {i.target} engine: {_short(r)}")
    if not r.get("ok"):
        return False
    h = wait_engine(i.target, 120)
    if h:
        did.append(f"verified: fresh heartbeat at {pt(h[0])}, steps {h[1].get('steps')} and moving")
        return True
    did.append("no moving heartbeat 2 min after the restart")
    return False


def report_engine_link(i: Issue, did: list[str]) -> bool | None:
    r = remote.pod(f"""for p in $(pgrep -f -- 'ask.edge.main --camera {i.target}( |$)'); do
  echo "edge pid $p: EDGE_ENGINE_URL=$(tr '\\0' '\\n' < /proc/$p/environ | sed -n 's/^EDGE_ENGINE_URL=//p')"; done
tail -n 3 /workspace/edge/logs/edge-{i.target}.log | cut -c1-200""", timeout=25)
    i.evidence += [ln for ln in r.get("out", "").splitlines() if ln.strip()][:5]
    did.append("nothing: the edge -> engine post (EDGE_ENGINE_URL) is perception's/engine's; no allowlisted fix")
    return False


def report_info(i: Issue, did: list[str]) -> bool | None:
    did.append("nothing to run: reported for the owners (engine / perception)")
    return None if i.kind == "engineslow" else False


PLAYBOOKS = {"cam": fix_camera, "node": fix_node, "tailscale": check_tailscale, "uv": report_uv,
             "watcher": fix_watcher, "archiver": fix_archiver, "pod": report_pod,
             "engine": fix_engine, "enginelink": report_engine_link, "engineslow": report_info, "judged": report_info}


# ---------------------------------------------------------------------------------------------------------- reporting

def message(i: Issue, did: list[str], fixed: bool | None, user_id: str, attempt: int = 1) -> tuple[str, bool]:
    mention = fixed is False
    head = {True: "✅ FIXED", None: "ℹ️ checked", False: "🚨 DOWN, could not fix"}[fixed]
    lines = [f"🤖 **Big Brother** · {head}: **{i.title}**" + (f" (attempt {attempt})" if attempt > 1 else "")
             + (f" <@{user_id}>" if mention and user_id else "")]
    lines += ["**Evidence**"] + [f"• {e}" for e in i.evidence]
    lines += ["**Did**"] + [f"• {d}" for d in did]
    text = "\n".join(lines)
    return (text[:1900] + "…") if len(text) > 1900 else text, mention


def post(text: str, mention: bool) -> dict:
    token, ch, uid = (os.environ.get(k, "") for k in ("DISCORD_BOT_TOKEN", "DISCORD_CHANNEL_ID", "DISCORD_MENTION_USER_ID"))
    body = {"content": text, "allowed_mentions": {"parse": [], "users": [uid] if mention and uid else []}}
    req = urllib.request.Request(f"https://discord.com/api/v10/channels/{ch}/messages", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bot {token}", "Content-Type": "application/json",
                                          "User-Agent": "DiscordBot (https://netralabs.net, 1) bigbrother"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return {"status": r.status, "id": json.loads(r.read()).get("id")}
    except Exception as e:                                         # a failed post must not stop the watcher
        return {"status": getattr(e, "code", None), "error": str(e)[:300]}


# ------------------------------------------------------------------------------------------------------------- driver

def _load() -> dict:
    try:
        return json.load(open(os.path.join(STATE, "watch.json")))
    except (OSError, ValueError):
        return {"open": {}, "posts": []}


def _save(s: dict) -> None:
    os.makedirs(STATE, exist_ok=True)
    tmp = os.path.join(STATE, "watch.json.tmp")
    json.dump(s, open(tmp, "w"))
    os.replace(tmp, os.path.join(STATE, "watch.json"))


def decide(inc: dict | None, now: float, kind: str) -> str:
    """'new' (handle + post), 'retry' (handle again; post only if the result changed), or 'skip'."""
    if inc is None:
        return "new"
    if kind in EVENT_MERGE_S:                                      # event-born: merge repeats within the window
        return "skip" if now - inc["opened"] < EVENT_MERGE_S[kind] else "new"
    if inc["fixed"] is not False and now - inc["last_attempt"] < 600:
        return "skip"                                              # just fixed / checked: give it time to clear
    if inc["attempts"] >= MAX_ATTEMPTS:
        return "skip"
    return "retry" if now - inc["last_attempt"] >= (RETRY_S if inc["fixed"] is False else 600) else "skip"


def run_pass(state: dict, now: float, handle=None, poster=post) -> list[dict]:
    issues, snapshot = detect(state, now)
    seen = {i.key for i in issues}
    done = []
    state["posts"] = [t for t in state.get("posts", []) if now - t < 3600]
    for i in issues:
        inc = state["open"].get(i.key)
        d = decide(inc, now, i.kind)
        if d == "skip":
            continue
        did: list[str] = []
        t0 = time.time()
        try:
            fixed = (handle or PLAYBOOKS[i.kind])(i, did)
        except Exception as e:                                     # a broken playbook must not stop the watcher
            did.append(f"playbook error: {type(e).__name__}: {e}")
            fixed = False
        attempt = 1 if d == "new" else inc["attempts"] + 1
        prev = None if d == "new" else inc["fixed"]
        state["open"][i.key] = {"opened": now if d == "new" else inc["opened"], "attempts": attempt,
                                "last_attempt": now, "fixed": fixed, "clear": 0, "kind": i.kind,
                                "posted_unfixed": (fixed is False) or bool(inc and inc.get("posted_unfixed"))}
        text, mention = message(i, did, fixed, os.environ.get("DISCORD_MENTION_USER_ID", ""), attempt)
        # William, Oct 28 (strict): Discord only for "infra DOWN and Big Brother could not fix it". Fixed, checked,
        # recovered, slow, under-voltage: log only. One post per incident: the first failed attempt (or a fixed
        # incident that breaks again and can't be fixed).
        should_post = fixed is False and prev is not False and i.kind in POST_KINDS
        posted = None
        if should_post and len(state["posts"]) < MAX_POSTS_PER_HOUR:
            posted = poster(text, mention)
            state["posts"].append(now)
        rec = {"key": i.key, "kind": i.kind, "decision": d, "attempt": attempt, "fixed": fixed, "evidence": i.evidence,
               "did": did, "seconds": round(time.time() - t0, 1), "posted": posted,
               "post_skipped": should_post and posted is None}
        done.append(rec)
        log.write({"kind": "auto", **rec})
        with open(os.path.join(STATE, "incidents.jsonl"), "a") as f:
            f.write(json.dumps({"t": datetime.now(timezone.utc).isoformat(timespec="seconds"), **rec}) + "\n")
    for key in list(state["open"]):                                # close incidents that cleared
        inc = state["open"][key]
        if key in seen:
            inc["clear"] = 0
            continue
        if inc["kind"] in EVENT_MERGE_S:
            if now - inc["opened"] >= EVENT_MERGE_S[inc["kind"]]:
                del state["open"][key]
            continue
        inc["clear"] = inc.get("clear", 0) + 1
        if inc["clear"] >= CLOSE_AFTER_CLEAR:
            log.write({"kind": "auto_close", "key": key, "incident": inc})
            del state["open"][key]
    state["last_pass"] = {"t": now, "issues": sorted(seen), "snapshot": snapshot}
    return done


def main() -> None:
    import fcntl
    os.makedirs(STATE, exist_ok=True)
    lock = open(os.path.join(STATE, "watch.lock"), "w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)               # one watcher at a time
    log.write({"kind": "watch_start", "cameras": remote.CAMERAS, "nodes": remote.NODES})
    while True:
        t0 = time.time()
        state = _load()
        try:
            run_pass(state, t0)
        except Exception as e:
            log.write({"kind": "watch_error", "error": f"{type(e).__name__}: {e}"})
        _save(state)
        time.sleep(max(5, INTERVAL_S - (time.time() - t0)))


if __name__ == "__main__":
    main()
