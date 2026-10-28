"""Big Brother's tool surface for `claude -p`: a minimal MCP server over stdio (JSON-RPC, one message per line).
Claude gets these tools and no built-in ones (no shell, no file access). Every call is logged.

Env from the bot: BB_REQUEST (William's message, for the fix-intent gate), BB_ATTACH (file listing images to attach),
BB_REQ_ID (log correlation)."""
from __future__ import annotations

import base64
import json
import os
import sys
import time

from . import actions, log, reads, remote

TOOLS = {
    "node_status": (reads.node_status, "a camera node (Pi): temperature, throttled bits decoded, uptime, "
                    "push/tailscale state, last nodeguard report + state, recent netra-cloud-push journal.",
                    {"node": {"type": "string", "default": "demo-node"}}),
    "node_events": (reads.node_events, "nodeguard events (tailscale/wifi watchdog restarts, throttle, power, tunnel, "
                    "reboots) and the uptime timeline.", {"hours": {"type": "number", "default": 24}}),
    "pi_journal": (reads.pi_journal, "journal of one node unit: " + ", ".join(reads.PI_UNITS),
                   {"unit": {"type": "string"}, "lines": {"type": "integer", "default": 40},
                    "node": {"type": "string", "default": "demo-node"}}),
    "incidents": (reads.bb_incidents, "Big Brother's own proactive incidents (what the watcher detected, did, and the result).",
                  {"n": {"type": "integer", "default": 10}}),
    "camera_health": (reads.camera_health, "production DB view of a camera: feed_health heartbeats (fps, frame age, "
                      "infer ms), Jev watch records, incidents.", {"camera": {"type": "string", "default": "demo-linovision"}}),
    "pod_status": (reads.pod_status, "cloud GPU pod: edge/dispatch/archive processes, GPU, disk, recent log lines.", {}),
    "pod_log": (reads.pod_log, "tail of one pod log: " + ", ".join(reads.POD_LOGS),
                {"name": {"type": "string"}, "lines": {"type": "integer", "default": 40}}),
    "jev_cost": (reads.jev_cost, "Jev (judge VLM) calls and estimated $ for a Pacific-time day, per camera.",
                 {"day": {"type": "string", "enum": ["today", "yesterday"], "default": "today"}}),
    "phone_pushes": (reads.phone_pushes, "last phone alert pushes (Discord @mention) from netra-phonealert.",
                     {"n": {"type": "integer", "default": 10}}),
    "r2_archive": (reads.r2_archive, "pod -> R2 footage archiver progress and log.", {}),
    "droplet_services": (reads.droplet_services, "droplet systemd units active/inactive; optional journal of one unit.",
                         {"unit": {"type": "string", "default": ""}, "lines": {"type": "integer", "default": 20}}),
    "camera_frame": (reads.camera_frame, "latest camera frame; it is attached to the Discord reply.",
                     {"camera": {"type": "string", "default": "demo-linovision"}}),
}


def _actions_doc() -> str:
    return ("; ".join(f"{n} [{a.kind}{', target=' + a.target if a.target else ''}]: {a.what}"
                      for n, a in actions.ACTIONS.items()) +
            f". Nodes: {sorted(remote.NODES)}. Cameras (-> node): {remote.CAMERAS}.")


def tool_list() -> list:
    out = [{"name": n, "description": d, "inputSchema": {"type": "object", "properties": p}}
           for n, (_, d, p) in TOOLS.items()]
    out.append({"name": "run_fix", "description": "Run a SAFE runbook action. Only works when William's message asked "
                "for a fix/restart. Actions: " + _actions_doc(),
                "inputSchema": {"type": "object", "properties": {"action": {"type": "string"}, "target": {"type": "string"}},
                                "required": ["action"]}})
    out.append({"name": "propose_action", "description": "Propose a runbook action for William to approve with 'yes' "
                "(required for [confirm] actions, and for [safe] ones he did not ask for).",
                "inputSchema": {"type": "object", "properties": {"action": {"type": "string"}, "reason": {"type": "string"},
                                                                 "target": {"type": "string"}},
                                "required": ["action", "reason"]}})
    return out


def call(name: str, args: dict) -> list:
    req = os.environ.get("BB_REQUEST", "")
    t0 = time.time()
    if name == "run_fix":
        res = actions.run(str(args.get("action", "")), request_text=req, target=str(args.get("target", "")))
    elif name == "propose_action":
        res = actions.propose(str(args.get("action", "")), str(args.get("reason", "")), str(args.get("target", "")))
    elif name in TOOLS:
        fn = TOOLS[name][0]
        allowed = TOOLS[name][2]
        try:
            res = fn(**{k: v for k, v in args.items() if k in allowed})
        except Exception as e:                                    # a broken read must not kill the session
            res = {"error": f"{type(e).__name__}: {e}"}
    else:
        res = {"error": f"unknown tool {name}"}
    log.write({"kind": "tool", "req": os.environ.get("BB_REQ_ID"), "tool": name, "args": args,
               "s": round(time.time() - t0, 2), "result": res})
    content = [{"type": "text", "text": json.dumps(res, default=str)[:20000]}]
    if name == "camera_frame" and "path" in res:
        att = os.environ.get("BB_ATTACH")
        if att:
            with open(att, "a") as f:
                f.write(res["path"] + "\n")
        with open(res["path"], "rb") as f:
            content.append({"type": "image", "data": base64.b64encode(f.read()).decode(), "mimeType": "image/jpeg"})
    return content


def handle(msg: dict) -> dict | None:
    mid, method = msg.get("id"), msg.get("method")
    if mid is None:                                               # notification
        return None
    if method == "initialize":
        ver = (msg.get("params") or {}).get("protocolVersion", "2025-06-18")
        result = {"protocolVersion": ver, "capabilities": {"tools": {}},
                  "serverInfo": {"name": "bigbrother", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": tool_list()}
    elif method == "tools/call":
        p = msg.get("params") or {}
        result = {"content": call(p.get("name", ""), p.get("arguments") or {})}
    elif method == "ping":
        result = {}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"no method {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def main() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            out = handle(json.loads(line))
        except Exception as e:
            out = {"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": str(e)}}
        if out is not None:
            sys.stdout.write(json.dumps(out) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
