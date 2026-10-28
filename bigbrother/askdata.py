"""Site context from netra-ask itself: runs bigbrother/askhelper.py in netra-ask's venv as user netra with
/etc/netra-ask.env (parsed here, not shell-sourced: values may contain spaces). Read-only."""
from __future__ import annotations

import json
import os
import re
import subprocess

ASK_DIR = os.environ.get("BB_ASK_DIR", "/opt/netra/netra-ask")
ASK_ENV = os.environ.get("BB_ASK_ENV", "/etc/netra-ask.env")
HELPER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "askhelper.py")
SITE = os.environ.get("BB_SITE", "ucsd-design-innovation-building-c1dd")
CAMERA_RE = re.compile(r"^[a-z0-9-]{0,80}$")


def ask_env(path: str = ASK_ENV) -> dict:
    env = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "HOME": "/tmp", "PYTHONPATH": ASK_DIR}
    try:
        for ln in open(path):
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return env


def run(cmd: str, timeout: int = 90, **args) -> dict:
    p = subprocess.run(["/usr/sbin/runuser", "-u", "netra", "--", f"{ASK_DIR}/.venv/bin/python", HELPER, cmd, json.dumps(args)],
                       env=ask_env(), capture_output=True, text=True, timeout=timeout, cwd=ASK_DIR)
    try:
        return json.loads(p.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"error": f"netra-ask helper failed (rc {p.returncode}): {p.stderr.strip()[-600:]}"}


def calibration(camera: str = "") -> dict:
    if not CAMERA_RE.match(camera):
        return {"error": "bad camera id"}
    return run("calibration", sid=SITE, camera=camera)


def site_shapes(camera: str = "") -> dict:
    if not CAMERA_RE.match(camera):
        return {"error": "bad camera id"}
    return run("shapes", sid=SITE, camera=camera)


def bikelog(day: str = "today", hours: float = 48) -> dict:
    if day != "today" and not re.match(r"^\d{4}-\d{2}-\d{2}$", day):
        return {"error": "day = today or YYYY-MM-DD"}
    out = run("bikelog", sid=SITE, day=day, hours=min(float(hours), 24 * 14))
    t = subprocess.run(["systemctl", "show", "netra-bikelog.timer", "-p", "ActiveState", "-p", "LastTriggerUSec"],
                       capture_output=True, text=True).stdout.split()
    j = subprocess.run(["journalctl", "-u", "netra-bikelog", "-n", "6", "--no-pager", "-o", "short-iso"],
                       capture_output=True, text=True).stdout
    out["service"] = {"timer": t, "journal_tail": [ln[:220] for ln in j.splitlines()[-6:]],
                      "note": "netra-bikelog.timer runs the PARK/TAKE tick every minute; 0 parks with the timer active "
                              "= it ran and saw no park"}
    return out


def zone_activity(zone: str = "", hours: float = 2) -> dict:
    """Engine zone entries/stays (agent engine is adding an endpoint). Until it exists, say exactly that and what
    does exist, instead of 'I can't see'."""
    api = open(os.path.join(ASK_DIR, "ask/api.py")).read() if os.path.exists(os.path.join(ASK_DIR, "ask/api.py")) else ""
    routes = re.findall(r'@app\.get\(P \+ "([^"]*zone[^"]*)"\)', api)
    found = [r for r in routes if re.search(r"activity|stays|entries|occupancy", r)]
    return {"available": bool(found), "routes_found": found,
            "status": ("engine zone-activity route exists: " + ", ".join(found)) if found else
                      "not deployed yet: the engine computes zone stays per site track in memory (ask/siteengine core."
                      "zone_stays) but no droplet endpoint/table serves them yet (agent engine is adding it). "
                      "What exists now: decisions (rule hits on zones), site_shapes (which zones each camera sees), "
                      "engine_status (tracks live)."}
