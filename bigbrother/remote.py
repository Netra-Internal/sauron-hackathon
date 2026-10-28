"""Run a fixed script on the droplet, the Pi (demo-node) or the cloud pod. Scripts go over stdin (`bash -s`), so their
text never appears on a remote command line (a pkill -f on the pod can't match its own ssh session).

- Pi: over the tailnet (ssh netra@demo-node); when that fails, the noderev reverse tunnel on the droplet
  (127.0.0.1:2201, HostKeyAlias demo-node-rev), which works with Tailscale down.
- Pod: host and port are read from the droplet's netra-ask-cloud-tunnel unit, so a pod restart (new ports) is picked up as
  soon as cloudpod updates that unit.
Key and known_hosts: BB_SSH_DIR (/var/lib/netra-bigbrother/ssh), the dedicated bigbrother key."""
from __future__ import annotations

import os
import re
import subprocess

SSH_DIR = os.environ.get("BB_SSH_DIR", "/var/lib/netra-bigbrother/ssh")
PI_USER = os.environ.get("BB_PI_USER", "netra")
# node -> its noderev reverse-tunnel port on the droplet; camera -> the node that pushes it
NODES = dict(kv.split(":") for kv in os.environ.get("BB_NODES", "demo-node:2201 demo-node2:2202").split())
CAMERAS = dict(kv.split(":") for kv in os.environ.get(
    "BB_CAMERAS", "demo-linovision:demo-node demo-linovision-2:demo-node2").split())
POD_UNIT = os.environ.get("BB_POD_UNIT", "/etc/systemd/system/netra-ask-cloud-tunnel.service")


def _ssh_base(port: str | None = None, alias: str | None = None) -> list[str]:
    a = ["ssh", "-i", f"{SSH_DIR}/id_ed25519", "-o", f"UserKnownHostsFile={SSH_DIR}/known_hosts",
         "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=accept-new",
         "-o", "ServerAliveInterval=10", "-o", "ServerAliveCountMax=3"]
    if port:
        a += ["-p", port]
    if alias:
        a += ["-o", f"HostKeyAlias={alias}"]
    return a


def _run(argv: list[str], script: str, timeout: int) -> dict:
    try:
        p = subprocess.run(argv, input=script, capture_output=True, text=True, timeout=timeout)
        return {"rc": p.returncode, "out": p.stdout[-6000:], "err": p.stderr[-1500:]}
    except subprocess.TimeoutExpired as e:
        return {"rc": 124, "out": (e.stdout or "")[-6000:] if isinstance(e.stdout, str) else "",
                "err": f"timed out after {timeout}s"}


def droplet(script: str, timeout: int = 60) -> dict:
    return {"via": "droplet", **_run(["bash", "-s"], script, timeout)}


def pi(script: str, timeout: int = 45, prefer: str = "tailnet", node: str = "demo-node") -> dict:
    """prefer='rev' goes through the reverse tunnel first (use it to restart tailscaled)."""
    if node not in NODES:
        return {"via": "pi:none", "rc": 255, "out": "", "err": f"unknown node {node}; known: {sorted(NODES)}"}
    routes = {
        "tailnet": _ssh_base() + [f"{PI_USER}@{node}", "bash -s"],
        "rev": _ssh_base(NODES[node], f"{node}-rev") + [f"{PI_USER}@127.0.0.1", "bash -s"],
    }
    order = ["rev", "tailnet"] if prefer == "rev" else ["tailnet", "rev"]
    tried = []
    for r in order:
        res = _run(routes[r], script, timeout)
        if res["rc"] != 255:            # 255 = ssh itself failed (no route / auth); anything else is the script's rc
            return {"via": f"{node}:{r}", "tried": tried, **res}
        tried.append({"route": r, "err": res["err"].strip()[-300:]})
    return {"via": f"{node}:none", "rc": 255, "out": "", "err": f"{node} unreachable on both routes", "tried": tried}


def pod_target(unit_text: str | None = None) -> tuple[str, str] | None:
    if unit_text is None:
        try:
            unit_text = open(POD_UNIT).read()
        except OSError:
            return None
    port, host = re.search(r"\s-p\s+(\d+)\b", unit_text), re.search(r"\sroot@([\w.-]+)", unit_text)
    return (host.group(1), port.group(1)) if port and host else None


def pod(script: str, timeout: int = 60) -> dict:
    t = pod_target()
    if not t:
        return {"via": "pod", "rc": 255, "out": "", "err": f"pod host/port not found in {POD_UNIT}"}
    host, port = t
    return {"via": "pod", **_run(_ssh_base(port) + [f"root@{host}", "bash -s"], script, timeout)}
