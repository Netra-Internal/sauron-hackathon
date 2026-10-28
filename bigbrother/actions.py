"""The runbook: the only things Big Brother can change. Each action is a named, fixed script with a target picked from a
fixed list (a node, a camera, or none); nothing is composed from model output.

SAFE    restarts: run when William's own message asks for a fix/restart (policy.fix_intent), after his "yes", or from the
        proactive watcher (auto=True, code not Claude).
CONFIRM bigger blast radius: never from a question; Claude can only propose them, the bot runs one on William's "yes".
REBOOT  reboot_node: a CONFIRM action that the watcher may also run (auto=True) but ONLY after a failed push restart on
        that node in the last REBOOT_AFTER_S, at most once per REBOOT_EVERY_S per node, and only if / is the overlay root.
Anything not listed (config edits, deploys, deleting, spending money, moving the camera) cannot be run at all.
Every action+target runs at most once per COOLDOWN_S."""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from typing import Callable

from . import policy, remote

STATE = os.environ.get("BB_STATE", "/var/lib/netra-bigbrother")
COOLDOWN_S = 300
PENDING_TTL_S = 600
REBOOT_EVERY_S = 1800
REBOOT_AFTER_S = 1200

POD_JEV = """
cd /workspace/edge
if pgrep -f -- 'ask.edge.main --camera {cam} .*--jev on' >/dev/null; then
  echo "{cam}: Jev runs inside the edge (ask.edge.main --jev on, perception): no separate watcher to restart"; exit 5
fi
loop=$(pgrep -f '^bash cloud/pod/dispatch.sh {cam}$')
echo "loop pid: ${loop:-none}"
pkill -f -- '-m ask.dispatch.watch --camera {cam} ' && echo "killed watcher; the loop restarts it in 15 s"
if [ -z "$loop" ]; then setsid nohup bash cloud/pod/dispatch.sh {cam} >/dev/null 2>&1 </dev/null & echo "started a new dispatch.sh loop"; fi
sleep 25
pgrep -af 'dispatch.*{cam}( |$)'
tail -n 4 logs/dispatch-{cam}.log
"""

POD_ARCHIVE = """
cd /workspace/edge
[ -s archive_cams ] || { echo "archive_cams is empty: nothing to archive"; exit 3; }
apid() { pgrep -f -- 'python -u cloud/pod/archive.py$' | head -1; }
pid=$(apid); [ -z "$pid" ] && { sleep 7; pid=$(apid); }     # the loop may be in its 5 s pause
if [ -n "$pid" ]; then
  parent=$(ps -o args= -p "$(ps -o ppid= -p $pid | tr -d ' ')")
  echo "archive.py pid $pid, parent: $parent"
  kill $pid && echo "stopped archive.py"
fi
if [ -n "$pid" ] && [[ "$parent" == bash* ]]; then
  echo "its restart loop starts a fresh pass in 5 s"
else
  setsid nohup bash -c 'while true; do /workspace/edge/venv/bin/python -u cloud/pod/archive.py >> logs/archive.log 2>&1; echo "$(date -u) archive exited $?" >> logs/archive.log; sleep 5; done' >/dev/null 2>&1 </dev/null &
  echo "no restart loop found: started a new archive loop"
fi
sleep 30
pgrep -af 'cloud/pod/archive.py$'
tail -n 4 logs/archive.log
"""

ENGINE = """
pat='-m ask.siteengine --site {site}( |$)'
pid=$(pgrep -f -- "$pat" | head -1); [ -z "$pid" ] && { sleep 10; pid=$(pgrep -f -- "$pat" | head -1); }
[ -n "$pid" ] || { echo "no engine process for {site} and nothing restarted it: launching it is cloudpod's (supervise.py/boot.sh)"; exit 5; }
parent=$(ps -o args= -p "$(ps -o ppid= -p $pid | tr -d ' ')")
echo "engine pid $pid, parent: $parent"
case "$parent" in *supervise.py*|bash*) ;; *) echo "parent is not a restart loop: not killing it"; exit 6;; esac
kill $pid && echo "stopped the engine; its restart loop starts it again"
sleep 25
pgrep -af -- "$pat" || echo "engine NOT back after 25 s"
"""

REBOOT = """
fs=$(findmnt -n -o FSTYPE /)
[ "$fs" = overlay ] || { echo "root filesystem is '$fs', not the overlay root: refusing to reboot"; exit 4; }
echo "overlay root confirmed; rebooting {node}"
sudo systemd-run --on-active=2 --unit=bigbrother-reboot systemctl reboot && echo "reboot scheduled in 2 s"
"""


def _droplet_restart(unit: str, check: str = "") -> str:
    return f"""systemctl restart {unit}; sleep 4
systemctl is-active {unit}; systemctl show {unit} -p ActiveEnterTimestamp -p NRestarts
{check}
journalctl -u {unit} -n 6 --no-pager -o short-iso"""


@dataclass
class Action:
    kind: str                    # "safe" | "confirm"
    where: str                   # "node" | "pod" | "droplet"
    target: str                  # "node" | "camera" | "site" | "" (fills {node} / {cam} / {site} in the script)
    what: str
    script: str
    prefer: str = "tailnet"      # node route


ACTIONS: dict[str, Action] = {
    "restart_push": Action("safe", "node", "node", "restart netra-cloud-push on {node} (camera -> pod video push)",
        "sudo systemctl restart netra-cloud-push; sleep 8; systemctl is-active netra-cloud-push; "
        "journalctl -u netra-cloud-push -n 6 --no-pager -o short-iso"),
    "restart_tailscaled": Action("safe", "node", "node", "restart tailscaled on {node} (over the reverse-SSH fallback)",
        "sudo systemctl restart --no-block tailscaled; sleep 10; systemctl is-active tailscaled; "
        "tailscale status --json 2>/dev/null | python3 -c 'import json,sys; print(\"BackendState\", json.load(sys.stdin)[\"BackendState\"])'",
        prefer="rev"),
    "restart_pod_jev_watcher": Action("safe", "pod", "camera", "restart the {cam} Jev dispatch watcher on the pod "
        "(kill the watcher, its dispatch.sh loop restarts it; start the loop if it is gone)", POD_JEV),
    "rerun_r2_archiver": Action("safe", "pod", "", "re-run the pod -> R2 footage archiver now (fresh pass; resumes from "
        "its done-list)", POD_ARCHIVE),
    "restart_netra_ask": Action("safe", "droplet", "", "restart netra-ask on the droplet",
        _droplet_restart("netra-ask", "sleep 3; curl -s -o /dev/null -w 'GET /ask/ -> %{http_code}\\n' http://127.0.0.1:8400/ask/")),
    "restart_phonealert": Action("safe", "droplet", "", "restart netra-phonealert on the droplet",
        _droplet_restart("netra-phonealert")),
    "restart_engine": Action("safe", "pod", "site", "restart the {site} site engine on the pod (kill it; its restart "
        "loop starts it again and it recovers from snapshots)", ENGINE),
    # --- need William's "yes" (reboot_node: or the watcher, after a failed push restart) ---
    "reboot_node": Action("confirm", "node", "node", "reboot {node} (overlay root; its camera feed drops ~1-2 min)", REBOOT),
    "restart_pod_tunnels": Action("confirm", "droplet", "",
        "restart the droplet -> pod SSH tunnels (netra-ask-cloud-tunnel, netra-cloud-hls-tunnel, netra-cloud-presign-tunnel)",
        "systemctl restart netra-ask-cloud-tunnel netra-cloud-hls-tunnel netra-cloud-presign-tunnel; sleep 5; "
        "systemctl is-active netra-ask-cloud-tunnel netra-cloud-hls-tunnel netra-cloud-presign-tunnel; "
        "curl -s -m 5 http://127.0.0.1:8450/health; echo"),
}


def resolve_target(a: Action, target: str) -> tuple[str, str] | None:
    """-> (node, cam) for the action, or None if the target isn't one we know. Default: demo-node / demo-linovision."""
    if a.target == "node":
        target = target or "demo-node"
        return (target, "") if target in remote.NODES else None
    if a.target == "camera":
        target = target or "demo-linovision"
        return (remote.CAMERAS.get(target, ""), target) if target in remote.CAMERAS else None
    if a.target == "site":
        target = target or remote.ENGINE_SITES[0]
        return ("", target) if target in remote.ENGINE_SITES else None
    return ("", "")


def render(a: Action, node: str, cam: str) -> str:
    """cam carries the site id for site actions."""
    return a.script.replace("{node}", node).replace("{cam}", cam).replace("{site}", cam)


def _execute(a: Action, node: str, cam: str) -> dict:
    script = render(a, node, cam)
    if a.where == "node":
        return remote.pi(script, timeout=90, prefer=a.prefer, node=node)
    if a.where == "pod":
        return remote.pod(script, timeout=120)
    return remote.droplet(script, timeout=60)


def _load(name: str, default):
    try:
        with open(os.path.join(STATE, name)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save(name: str, obj) -> None:
    os.makedirs(STATE, exist_ok=True)
    tmp = os.path.join(STATE, name + ".tmp")
    with open(tmp, "w") as f:
        json.dump(obj, f)
    os.replace(tmp, os.path.join(STATE, name))


def note_push_failed(node: str, now: float | None = None) -> None:
    """The watcher calls this when a push restart did not bring the feed back; it unlocks reboot_node for that node."""
    s = _load("pushfail.json", {})
    s[node] = time.time() if now is None else now
    _save("pushfail.json", s)


def run(name: str, *, request_text: str, target: str = "", confirmed: bool = False, auto: bool = False,
        execute: Callable[..., dict] = _execute, now: float | None = None) -> dict:
    """The single gate every change goes through. Returns {"ok", "action", ...}; refusals say why and run nothing."""
    now = time.time() if now is None else now
    a = ACTIONS.get(name)
    if a is None:
        return {"ok": False, "action": name, "refused": "not in the runbook allowlist; nothing was run",
                "allowed": sorted(ACTIONS)}
    t = resolve_target(a, target)
    if t is None:
        return {"ok": False, "action": name, "refused": f"unknown target {target!r}; nodes {sorted(remote.NODES)}, "
                f"cameras {sorted(remote.CAMERAS)}, sites {remote.ENGINE_SITES}; nothing was run"}
    node, cam = t
    key = f"{name}:{cam or node}" if a.target else name
    what = a.what.replace("{node}", node).replace("{cam}", cam).replace("{site}", cam)
    cooldown = _load("cooldown.json", {})
    if name == "reboot_node":
        if not confirmed:
            failed = _load("pushfail.json", {}).get(node, 0)
            if not (auto and now - failed < REBOOT_AFTER_S):
                return {"ok": False, "action": name, "refused": "a reboot needs William's 'yes' (propose_action), or "
                        "the watcher after a failed push restart on this node; nothing was run"}
        if now - cooldown.get(key, 0) < REBOOT_EVERY_S:
            return {"ok": False, "action": name, "refused": f"{node} was rebooted by Big Brother "
                    f"{int(now - cooldown[key])} s ago; at most once per {REBOOT_EVERY_S} s; nothing was run"}
    elif a.kind == "confirm" and not confirmed:
        return {"ok": False, "action": name, "refused": "needs William's 'yes': call propose_action instead; nothing was run"}
    elif a.kind == "safe" and not (confirmed or auto or policy.fix_intent(request_text)):
        return {"ok": False, "action": name,
                "refused": "William's message did not ask for a fix/restart; propose it instead; nothing was run"}
    elif now - cooldown.get(key, 0) < COOLDOWN_S:
        return {"ok": False, "action": name,
                "refused": f"ran {int(now - cooldown[key])} s ago; at most once per {COOLDOWN_S} s; nothing was run"}
    cooldown[key] = now
    _save("cooldown.json", cooldown)
    t0 = time.time()
    res = execute(a, node, cam)
    return {"ok": res.get("rc") == 0, "action": name, "target": cam or node, "what": what,
            "seconds": round(time.time() - t0, 1), **res}


def propose(name: str, reason: str, target: str = "", *, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    a = ACTIONS.get(name)
    if a is None:
        return {"ok": False, "refused": "not in the runbook: the bot cannot run it even with a yes. Tell William the "
                "exact command for a human to run.", "allowed": sorted(ACTIONS)}
    t = resolve_target(a, target)
    if t is None:
        return {"ok": False, "refused": f"unknown target {target!r}"}
    node, cam = t
    p = {"id": uuid.uuid4().hex[:8], "action": name, "target": cam or node,
         "what": a.what.replace("{node}", node).replace("{cam}", cam).replace("{site}", cam), "reason": reason, "at": now}
    _save("pending.json", p)
    return {"ok": True, "pending": p, "note": "The bot will ask William to reply 'yes' within 10 min."}


def pending(now: float | None = None) -> dict | None:
    now = time.time() if now is None else now
    p = _load("pending.json", None)
    return p if p and now - p.get("at", 0) < PENDING_TTL_S else None


def take_pending(now: float | None = None) -> dict | None:
    p = pending(now)
    try:
        os.remove(os.path.join(STATE, "pending.json"))
    except OSError:
        pass
    return p
