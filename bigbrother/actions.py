"""The runbook: the only things Big Brother can change. Each action is a named, fixed script; nothing is composed from
model output.

SAFE   (restarts from the brief): run when William's own message asks for a fix/restart (policy.fix_intent), or after "yes".
CONFIRM (anything with a bigger blast radius): never run from a question. Claude can only propose them; the bot runs one
        when William answers the proposal with "yes" in the channel, within PENDING_TTL_S.
Anything not listed here (config edits, deploys, deleting, spending money, moving the camera) cannot be run at all:
Claude replies with the exact action for a human to take.
Every action runs at most once per COOLDOWN_S."""
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

CAM = "demo-linovision"

POD_JEV = f"""
cd /workspace/edge
loop=$(pgrep -f '^bash cloud/pod/dispatch.sh {CAM}$')
echo "loop pid: ${{loop:-none}}"
pkill -f -- '-m ask.dispatch.watch --camera {CAM} ' && echo "killed watcher; the loop restarts it in 15 s"
if [ -z "$loop" ]; then setsid nohup bash cloud/pod/dispatch.sh {CAM} >/dev/null 2>&1 </dev/null & echo "started a new dispatch.sh loop"; fi
sleep 25
pgrep -af 'dispatch.*{CAM}'
tail -n 4 logs/dispatch-{CAM}.log
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


def _droplet_restart(unit: str, check: str = "") -> str:
    return f"""systemctl restart {unit}; sleep 4
systemctl is-active {unit}; systemctl show {unit} -p ActiveEnterTimestamp -p NRestarts
{check}
journalctl -u {unit} -n 6 --no-pager -o short-iso"""


@dataclass
class Action:
    kind: str                    # "safe" | "confirm"
    where: str                   # "pi" | "pod" | "droplet"
    what: str
    script: str
    prefer: str = "tailnet"      # Pi route


ACTIONS: dict[str, Action] = {
    "restart_pi_push": Action("safe", "pi", "restart netra-cloud-push on demo-node (camera -> pod video push)",
        "sudo systemctl restart netra-cloud-push; sleep 6; systemctl is-active netra-cloud-push; "
        "journalctl -u netra-cloud-push -n 6 --no-pager -o short-iso"),
    "restart_pi_tailscaled": Action("safe", "pi", "restart tailscaled on demo-node (over the reverse-SSH fallback)",
        "sudo systemctl restart --no-block tailscaled; sleep 10; systemctl is-active tailscaled; "
        "tailscale status --json 2>/dev/null | python3 -c 'import json,sys; print(\"BackendState\", json.load(sys.stdin)[\"BackendState\"])'",
        prefer="rev"),
    "restart_pod_jev_watcher": Action("safe", "pod", f"restart the {CAM} Jev dispatch watcher on the pod "
        "(kill the watcher, its dispatch.sh loop restarts it; start the loop if it is gone)", POD_JEV),
    "rerun_r2_archiver": Action("safe", "pod", "re-run the pod -> R2 footage archiver now (fresh pass; resumes from its done-list)",
        POD_ARCHIVE),
    "restart_netra_ask": Action("safe", "droplet", "restart netra-ask on the droplet",
        _droplet_restart("netra-ask", "sleep 3; curl -s -o /dev/null -w 'GET /ask/ -> %{http_code}\\n' http://127.0.0.1:8400/ask/")),
    "restart_phonealert": Action("safe", "droplet", "restart netra-phonealert on the droplet",
        _droplet_restart("netra-phonealert")),
    # --- need William's "yes" ---
    "reboot_pi": Action("confirm", "pi", "reboot demo-node (camera feed drops for ~1-2 min)",
        "sudo systemctl reboot; echo reboot requested"),
    "restart_pod_tunnels": Action("confirm", "droplet",
        "restart the droplet -> pod SSH tunnels (netra-ask-cloud-tunnel, netra-cloud-hls-tunnel, netra-cloud-presign-tunnel)",
        "systemctl restart netra-ask-cloud-tunnel netra-cloud-hls-tunnel netra-cloud-presign-tunnel; sleep 5; "
        "systemctl is-active netra-ask-cloud-tunnel netra-cloud-hls-tunnel netra-cloud-presign-tunnel; "
        "curl -s -m 5 http://127.0.0.1:8450/health; echo"),
}


def _execute(a: Action) -> dict:
    if a.where == "pi":
        return remote.pi(a.script, timeout=60, prefer=a.prefer)
    if a.where == "pod":
        return remote.pod(a.script, timeout=90)
    return remote.droplet(a.script, timeout=60)


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


def run(name: str, *, request_text: str, confirmed: bool = False,
        execute: Callable[[Action], dict] = _execute, now: float | None = None) -> dict:
    """The single gate every change goes through. Returns {"ok", "action", ...}; refusals say why."""
    now = time.time() if now is None else now
    a = ACTIONS.get(name)
    if a is None:
        return {"ok": False, "action": name, "refused": "not in the runbook allowlist; nothing was run",
                "allowed": sorted(ACTIONS)}
    if a.kind == "confirm" and not confirmed:
        return {"ok": False, "action": name, "refused": "needs William's 'yes': call propose_action instead; nothing was run"}
    if a.kind == "safe" and not confirmed and not policy.fix_intent(request_text):
        return {"ok": False, "action": name,
                "refused": "William's message did not ask for a fix/restart; propose it instead; nothing was run"}
    last = _load("cooldown.json", {})
    if now - last.get(name, 0) < COOLDOWN_S:
        return {"ok": False, "action": name,
                "refused": f"ran {int(now - last[name])} s ago; at most once per {COOLDOWN_S} s; nothing was run"}
    last[name] = now
    _save("cooldown.json", last)
    t0 = time.time()
    res = execute(a)
    return {"ok": res.get("rc") == 0, "action": name, "what": a.what, "seconds": round(time.time() - t0, 1), **res}


def propose(name: str, reason: str, *, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    a = ACTIONS.get(name)
    if a is None:
        return {"ok": False, "refused": "not in the runbook: the bot cannot run it even with a yes. Tell William the "
                "exact command for a human to run.", "allowed": sorted(ACTIONS)}
    p = {"id": uuid.uuid4().hex[:8], "action": name, "what": a.what, "reason": reason, "at": now}
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
