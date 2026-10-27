#!/usr/bin/env python3
"""nodeguard: the droplet watches a solar camera node (demo-node) and keeps its power/uptime timeline.

The droplet does the watching because a dead Pi cannot report its own death.

  nodeguard.py check      every minute (systemd timer): observe -> step() -> append transitions to the event log,
                          post them to Discord.
  nodeguard.py serve      tiny HTTP receiver, bound to the droplet's Tailscale IP only. The Pi POSTs a report every
                          minute (node/pi/netra-node-report): boot_id, uptime, vcgencmd get_throttled, load, temp.
  nodeguard.py timeline   prints the event log for the last N days, with outage durations.

Observations per check:
  node   : `tailscale ping` to the node, or a Pi report received in the last REPORT_FRESH_S.
           OFFLINE only after OFFLINE_AFTER_S of both failing (DERP-relayed pings drop now and then).
  tunnel : the Pi's report says its push ssh has an established connection to the relay (tunnel_up). Not checked from
           the droplet: UCSD-GUEST changes the public NAT IP under a live session, so matching sessions by IP was wrong.
  video  : feed_health has a row with fps_analysed > 0 for the camera in the last VIDEO_DOWN_AFTER_S.
  boot   : a new boot_id in the Pi's report. booted_at = received_at - uptime (the Pi has no RTC, so its own clock
           is not trusted). prev_uptime_s = the last uptime the previous boot reported (accurate to ~1 report).
  throttle: every change of the get_throttled bits within a boot. Under-voltage (bit 0 now / bit 16 since boot)
           is posted to Discord once per boot.

Event log: append-only JSONL, one object per line: {"t": ISO-8601 UTC, "node", "kind", "state", ...details}.
  kinds: node (online|offline), video (up|down), tunnel (up|down), boot (booted), throttle (bits),
         tailscale (restarted|needs-login|action: the Pi's Tailscale watchdog, with its text),
         schedule (off-window|on-window|not-back: the approved night off, SCHEDULE_OFF; node/video rows inside it
         carry "scheduled": true and are not posted),
         note (state "manual", {"text"}: a hand-added annotation; the log is never edited, corrections are appended).
  Reserved for later, not written yet: kind "power" with {"v": volts, "a": amps} from an INA226 on the Pi's I2C. The
  Pi would add v/a to its report and step() would log a row when it crosses a threshold. The format needs no change.

Config: /etc/netra-nodeguard.env (root 0600, never in git), see nodeguard.env.example.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hmac
import json
import os
import re
import subprocess
import sys
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

NODE = os.environ.get("NODE", "demo-node")
CAMERA = os.environ.get("CAMERA", "demo-linovision")
STATE_DIR = Path(os.environ.get("STATE_DIR", "/var/lib/netra-nodeguard"))
EVENTS = STATE_DIR / "events.jsonl"
STATE = STATE_DIR / "state.json"
OFFLINE_AFTER_S = int(os.environ.get("OFFLINE_AFTER_S", "180"))
VIDEO_DOWN_AFTER_S = int(os.environ.get("VIDEO_DOWN_AFTER_S", "180"))
REPORT_FRESH_S = int(os.environ.get("REPORT_FRESH_S", "180"))
UV_BITS = (1 << 0) | (1 << 16)   # under-voltage now / since boot
# Approved night off (William, Oct 26): "Mon-Fri 01:00-06:00 America/Los_Angeles" (days = the mornings). Inside it, plus
# QUIET_EARLY_MIN before (the staged poweroff runs at 00:58) and until BACK_BY_MIN after, outages are logged as
# scheduled and not posted; whatever is still down when that ends is posted once, with a mention ("NOT back").
SCHEDULE_OFF = os.environ.get("SCHEDULE_OFF", "")
QUIET_EARLY_MIN = int(os.environ.get("QUIET_EARLY_MIN", "5"))
BACK_BY_MIN = int(os.environ.get("BACK_BY_MIN", "15"))
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).isoformat(timespec="seconds")


def parse(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s)


def dur(s: float) -> str:
    s = int(s)
    if s < 3600:
        return f"{s // 60}m{s % 60:02d}s"
    return f"{s // 3600}h{s % 3600 // 60:02d}m"


def throttled_text(bits: int) -> str:
    names = {0: "under-voltage NOW", 1: "freq capped NOW", 2: "throttled NOW", 3: "soft temp limit NOW",
             16: "under-voltage since boot", 17: "freq capped since boot", 18: "throttled since boot",
             19: "soft temp limit since boot"}
    on = [n for b, n in names.items() if bits >> b & 1]
    return f"0x{bits:x}" + (f" ({', '.join(on)})" if on else " (clean)")


def parse_schedule(spec: str):
    """"Mon-Fri 01:00-06:00 America/Los_Angeles" -> (weekdays {0..6}, start, end, tz); "" -> None. Same-day windows only."""
    if not spec.strip():
        return None
    from zoneinfo import ZoneInfo
    days, hours, tz = spec.split()
    d0, _, d1 = days.partition("-")
    i0, i1 = DAYS.index(d0), DAYS.index(d1 or d0)
    wd = {i % 7 for i in range(i0, i1 + 1 + (7 if i1 < i0 else 0))}
    a, b = (dt.time.fromisoformat(x) for x in hours.split("-"))
    if not a < b:
        raise ValueError(f"SCHEDULE_OFF must not cross midnight: {spec}")
    return wd, a, b, ZoneInfo(tz)


def quiet(now: dt.datetime, spec: str | None = None) -> bool:
    """Inside the scheduled-off window, widened by QUIET_EARLY_MIN before and BACK_BY_MIN after."""
    sch = parse_schedule(SCHEDULE_OFF if spec is None else spec)
    if not sch:
        return False
    wd, a, b, tz = sch
    loc = now.astimezone(tz)
    if loc.weekday() not in wd:
        return False
    day = loc.date()
    start = dt.datetime.combine(day, a, tz) - dt.timedelta(minutes=QUIET_EARLY_MIN)
    end = dt.datetime.combine(day, b, tz) + dt.timedelta(minutes=BACK_BY_MIN)
    return start <= loc < end


# ---------------------------------------------------------------- pure state machine (tested in tests/test_nodeguard.py)

def step(state: dict, obs: dict, now: dt.datetime) -> tuple[dict, list[dict], list[tuple[str, bool]]]:
    """state + one minute's observations -> (new state, events to log, Discord posts as (text, mention)).

    obs: ts_ok (tailscale ping answered), report (latest Pi report or None, with "received_at" ISO),
         video_ok (fps_analysed > 0 within VIDEO_DOWN_AFTER_S), video_last_ok (ISO of that newest good row, optional),
         tunnel_ok (bool or None when unknown).
    """
    st = dict(state)
    ev: list[dict] = []
    posts: list[tuple[str, bool]] = []

    def event(kind: str, state_: str, **kw):
        ev.append({"t": iso(now), "node": NODE, "kind": kind, "state": state_, **kw})

    rep = obs.get("report")
    rep_age = (now - parse(rep["received_at"])).total_seconds() if rep else None
    alive = bool(obs.get("ts_ok")) or (rep_age is not None and rep_age <= REPORT_FRESH_S)
    q = quiet(now)
    if q != bool(st.get("quiet")):
        event("schedule", "off-window" if q else "on-window", schedule=SCHEDULE_OFF)
        st["quiet"] = q

    # node online / offline (debounced going down, immediate coming back)
    if alive:
        st["node_last_ok"] = iso(now)
        if st.get("node") != "online":
            if st.get("node") == "offline":
                down_s = (now - parse(st["node_since"])).total_seconds()
                event("node", "online", outage_s=int(down_s), **({"scheduled": True} if st.get("node_sched") else {}))
                if st.get("node_posted", True):   # recoveries only for outages that were posted
                    posts.append((f"🟢 {NODE} back ONLINE after {dur(down_s)} offline", False))
            else:
                event("node", "online", first=True)
            st["node"], st["node_since"] = "online", iso(now)
    else:
        last_ok = parse(st.get("node_last_ok") or iso(now))
        st.setdefault("node_last_ok", iso(last_ok))
        if st.get("node") != "offline" and (now - last_ok).total_seconds() >= OFFLINE_AFTER_S:
            event("node", "offline", last_seen=iso(last_ok), **({"scheduled": True} if q else {}))
            if not q:
                posts.append((f"🔴 {NODE} OFFLINE: no Tailscale reply and no report since {iso(last_ok)} "
                              f"(last report: {_rep_line(st.get('last_report'))})", True))
            st["node"], st["node_since"], st["node_sched"], st["node_posted"] = "offline", iso(last_ok), q, not q

    # video up / down from feed_health
    if obs.get("video_ok"):
        if st.get("video") != "up":
            if st.get("video") == "down":
                down_s = (now - parse(st["video_since"])).total_seconds()
                event("video", "up", outage_s=int(down_s), **({"scheduled": True} if st.get("video_sched") else {}))
                if st.get("video_posted", True):
                    posts.append((f"🟢 {NODE} video recovered ({CAMERA}) after {dur(down_s)}", False))
            else:
                event("video", "up", first=True)
            st["video"], st["video_since"] = "up", iso(now)
    elif st.get("video") != "down":
        # obs video_ok=False already means "no fps>0 row for VIDEO_DOWN_AFTER_S"; the outage starts at the last good row
        since = parse(obs["video_last_ok"]) if obs.get("video_last_ok") else now - dt.timedelta(seconds=VIDEO_DOWN_AFTER_S)
        event("video", "down", camera=CAMERA, **({"scheduled": True} if q else {}))
        node_word = "node online" if alive else "node also unreachable"
        tun = {True: "push tunnel up", False: "push tunnel DOWN", None: "push tunnel unknown"}[obs.get("tunnel_ok")]
        if not q:
            posts.append((f"🔴 {NODE} video DOWN: no {CAMERA} frames analysed since {iso(since)} ({node_word}, {tun})", True))
        st["video"], st["video_since"], st["video_sched"], st["video_posted"] = "down", iso(since), q, not q

    # the scheduled-off window is over (BACK_BY_MIN after its end) and something is still down: say so, once
    if not q:
        late = [w for k, w in (("node", "OFFLINE"), ("video", "DOWN"))
                if st.get(k) in ("offline", "down") and not st.get(f"{k}_posted", True)]
        if late:
            event("schedule", "not-back", down=[w.lower() for w in late])
            posts.append((f"🔴 {NODE} NOT back after the scheduled night off ({SCHEDULE_OFF}): "
                          + ", ".join(f"{k} {w} since {st[k + '_since']}" for k, w in
                                      (("node", "OFFLINE"), ("video", "DOWN")) if w in late), True))
            for k in ("node", "video"):
                if st.get(k) in ("offline", "down"):
                    st[f"{k}_posted"] = True

    # push tunnel (logged only; the video alert covers its effect)
    tun = obs.get("tunnel_ok")
    if tun is not None and st.get("tunnel") != ("up" if tun else "down"):
        st["tunnel"] = "up" if tun else "down"
        event("tunnel", st["tunnel"])

    # Pi reports: boots and throttled bits
    if rep and rep.get("boot_id") and rep["received_at"] != (st.get("last_report") or {}).get("received_at"):
        prev = st.get("last_report") or {}
        recv = parse(rep["received_at"])
        if rep["boot_id"] != prev.get("boot_id"):
            booted = recv - dt.timedelta(seconds=float(rep.get("uptime_s", 0)))
            kw = {"booted_at": iso(booted), "throttled": rep.get("throttled")}
            if prev.get("boot_id"):
                kw["prev_uptime_s"] = int(float(prev.get("uptime_s", 0)))
                kw["prev_last_report"] = prev.get("received_at")
            if "wd_last_reboot" in rep:   # 0 = the watchdog never rebooted this SD card
                # the Wi-Fi watchdog stamps /boot/firmware just before it reboots: a stamp within 5 min before this
                # boot means the watchdog did it; otherwise power loss, brown-out or a manual reboot
                wd = dt.datetime.fromtimestamp(int(rep["wd_last_reboot"]), dt.timezone.utc)
                kw["cause"] = ("wifi-watchdog" if dt.timedelta(0) <= booted - wd <= dt.timedelta(minutes=5)
                               else "not the watchdog (power loss, brown-out or manual)")
            event("boot", "booted", **kw)
            if prev.get("boot_id"):   # a quick reboot never trips OFFLINE, so say it here
                posts.append((f"🔄 {NODE} rebooted at {kw['booted_at']} (previous boot ran ~{dur(kw['prev_uptime_s'])}, "
                              f"cause {kw.get('cause', 'unknown')}, throttled now {throttled_text(int(rep.get('throttled', '0x0'), 16))})", False))
            st["uv_posted_boot"] = None
        bits = int(rep.get("throttled", "0x0"), 16)
        if rep["boot_id"] != prev.get("boot_id") or bits != int(prev.get("throttled", "0x0"), 16):
            if bits or rep["boot_id"] == prev.get("boot_id"):
                event("throttle", throttled_text(bits), bits=f"0x{bits:x}")
        if bits & UV_BITS and st.get("uv_posted_boot") != rep["boot_id"]:
            posts.append((f"⚠️ {NODE} under-voltage seen: get_throttled={throttled_text(bits)}, "
                          f"uptime {dur(float(rep.get('uptime_s', 0)))}", True))
            st["uv_posted_boot"] = rep["boot_id"]
        st["last_report"] = rep

    # the Pi's Tailscale watchdog acted (node/pi/netra-node-tailscale-watchdog): log each action once, by its epoch.
    # Reports can arrive out of order (one retried through a tailscaled restart), so only a NEWER epoch counts.
    at, _, text = (rep or {}).get("ts_wd", "").partition("|")
    if at.isdigit() and int(at) > int(st.get("ts_wd_epoch", 0)):
        kind = "needs-login" if text.startswith("NeedsLogin") else "restarted" if text.startswith("restarted") else "action"
        when = iso(dt.datetime.fromtimestamp(int(at), dt.timezone.utc))
        event("tailscale", kind, at=when, text=text)
        if kind != "action":
            posts.append((f"{'⚠️' if kind == 'needs-login' else '🔧'} {NODE} Tailscale watchdog: {text}", kind == "needs-login"))
        st["ts_wd_epoch"] = int(at)
    return st, ev, posts


def _rep_line(rep: dict | None) -> str:
    if not rep:
        return "none"
    return (f"{rep.get('received_at')}, uptime {dur(float(rep.get('uptime_s', 0)))}, "
            f"throttled {rep.get('throttled')}, load {rep.get('load1')}, {rep.get('temp_c')}°C")


# ---------------------------------------------------------------- observations (droplet side)

def tailscale_ok(host: str) -> bool:
    try:
        r = subprocess.run(["tailscale", "ping", "--c", "2", "--timeout", "10s", host],
                           capture_output=True, text=True, timeout=30)
        return "pong from" in r.stdout
    except Exception:
        return False


def video_last_ok() -> dt.datetime | None:
    """received_at of the newest feed_health row with fps_analysed > 0 (last 7 days), by the droplet's clock."""
    sql = (f"select extract(epoch from max(received_at)) from feed_health where camera_id='{CAMERA}' "
           f"and fps_analysed > 0 and received_at > now() - interval '7 days'")
    r = subprocess.run(["runuser", "-u", "netra", "--", "psql", "netra_ask", "-At", "-c", sql],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"feed_health query failed: {r.stderr.strip()}")
    v = r.stdout.strip()
    return dt.datetime.fromtimestamp(float(v), dt.timezone.utc) if v else None


def last_report() -> dict | None:
    try:
        return json.loads((STATE_DIR / f"report-{NODE}.json").read_text())
    except (OSError, ValueError):
        return None


def discord(text: str, mention: bool) -> None:
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not url:
        print("no DISCORD_WEBHOOK_URL; would post:", text)
        return
    uid = os.environ.get("DISCORD_MENTION_USER_ID")
    body = {"content": (f"<@{uid}> " if mention and uid else "") + text,
            "allowed_mentions": {"users": [uid] if mention and uid else []}}
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json",
                                                                  "User-Agent": "netra-nodeguard"})
    urllib.request.urlopen(req, timeout=20).read()


def append_events(evs: list[dict]) -> None:
    with EVENTS.open("a") as f:
        for e in evs:
            f.write(json.dumps(e, separators=(",", ":")) + "\n")


def cmd_check(_args) -> int:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        state = json.loads(STATE.read_text())
    except (OSError, ValueError):
        state = {}
    rep = last_report()
    obs = {"ts_ok": tailscale_ok(os.environ.get("NODE_TS_HOST", NODE)), "report": rep,
           # the push tunnel as the Pi sees it; unknown without a fresh report (old reporters have no tunnel_up)
           "tunnel_ok": rep.get("tunnel_up") if rep and "tunnel_up" in rep and
           (now_utc() - parse(rep["received_at"])).total_seconds() <= REPORT_FRESH_S else None}
    now = now_utc()
    try:
        last = video_last_ok()
        obs["video_ok"] = last is not None and (now - last).total_seconds() <= VIDEO_DOWN_AFTER_S
        obs["video_last_ok"] = iso(last) if last else None
    except Exception as e:   # a DB hiccup is not a video outage: keep the old video state this minute
        print(e, file=sys.stderr)
        obs["video_ok"] = state.get("video") == "up"
    state, evs, posts = step(state, obs, now)
    append_events(evs)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1))
    tmp.replace(STATE)
    for e in evs:
        print(json.dumps(e))
    failed = 0
    for text, mention in posts:
        try:
            discord(text, mention)
        except Exception as e:
            failed += 1
            print(f"discord post failed: {e}: {text}", file=sys.stderr)
    return 1 if failed else 0


# ---------------------------------------------------------------- receiver (Pi -> droplet over Tailscale)

FIELDS = {"node": str, "boot_id": str, "uptime_s": (int, float), "throttled": str, "load1": (int, float),
          "load5": (int, float), "temp_c": (int, float), "tunnel_up": bool, "ts_wd": str, "wd_last_reboot": (int, str),
          "clock_synced": bool, "rssi_dbm": (int, float), "push_active": bool}


class Receiver(BaseHTTPRequestHandler):
    token = ""

    def do_POST(self):
        got = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not self.token or not hmac.compare_digest(got, self.token):
            return self._send(401, "bad token")
        if self.path != "/report":
            return self._send(404, "not found")
        n = int(self.headers.get("Content-Length") or 0)
        if not 0 < n <= 4096:
            return self._send(413, "too big")
        try:
            body = json.loads(self.rfile.read(n))
            rep = {k: body[k] for k in FIELDS if k in body and isinstance(body[k], FIELDS[k])}
            if not re.fullmatch(r"[a-z0-9-]{1,40}", rep.get("node", "")) or not re.fullmatch(r"[0-9a-f-]{36}", rep.get("boot_id", "")) \
                    or not re.fullmatch(r"0x[0-9a-fA-F]{1,8}", rep.get("throttled", "")):
                raise ValueError("node, boot_id and throttled are required")
        except (ValueError, TypeError) as e:
            return self._send(400, str(e))
        t = now_utc()
        rep["received_at"] = iso(t)
        line = json.dumps(rep, separators=(",", ":"))
        with (STATE_DIR / f"reports-{rep['node']}-{t:%Y-%m}.jsonl").open("a") as f:   # minute log: load/throttle history
            f.write(line + "\n")
        tmp = STATE_DIR / f".report-{rep['node']}.tmp"
        tmp.write_text(line)
        tmp.replace(STATE_DIR / f"report-{rep['node']}.json")
        self._send(200, "ok")

    def _send(self, code: int, msg: str):
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(msg.encode() + b"\n")

    def log_message(self, fmt, *a):   # journald gets one line per non-200 only
        if a and str(a[1]) != "200":
            sys.stderr.write(f"{self.client_address[0]} {fmt % a}\n")


def cmd_serve(args) -> int:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    Receiver.token = os.environ.get("NODEGUARD_TOKEN", "")
    if not Receiver.token:
        sys.exit("NODEGUARD_TOKEN is not set")
    host, port = args.bind.rsplit(":", 1)
    ThreadingHTTPServer((host, int(port)), Receiver).serve_forever()
    return 0


# ---------------------------------------------------------------- timeline

def timeline(events: list[dict], since: dt.datetime, now: dt.datetime) -> list[str]:
    """Human timeline: every event since `since`, outages with their duration (still-open ones up to now)."""
    out = []
    for e in events:
        t = parse(e["t"])
        if t < since:
            continue
        k, s = e["kind"], e["state"]
        sched = "  [scheduled off]" if e.get("scheduled") else ""
        if k in ("node", "video") and s in ("online", "up"):
            line = f"{k} {s}" + (f"   (was down {dur(e['outage_s'])})" if "outage_s" in e else "   (first observation)") + sched
        elif k == "node" and s == "offline":
            line = f"node OFFLINE   (last seen {e['last_seen'][11:19]}Z)" + sched
        elif k == "video" and s == "down":
            line = "video DOWN" + sched
        elif k == "schedule":
            line = {"off-window": "-- scheduled night off begins (alerts muted)",
                    "on-window": "-- scheduled night off over (alerts on)",
                    "not-back": f"!! NOT back after scheduled off: {', '.join(e.get('down', []))}"}.get(s, f"schedule {s}")
        elif k == "boot":
            prev = f", previous boot ran {dur(e['prev_uptime_s'])}" if "prev_uptime_s" in e else ""
            line = f"BOOT at {e['booted_at'][:19]}Z{prev}, cause {e.get('cause', 'unknown')}, throttled {e.get('throttled')}"
        elif k == "throttle":
            line = f"throttle bits {s}"
        elif k == "tailscale":
            line = f"tailscale {s}: {e.get('text')}"
        elif k == "note":   # hand-written annotation (corrections, maintenance), never generated by step()
            line = f"note: {e.get('text')}"
        else:
            line = f"{k} {s}"
        out.append(f"{t:%a %Y-%m-%d %H:%M:%S}Z  {line}")
    for k, down, up in (("node", "offline", "online"), ("video", "down", "up")):
        last = [e for e in events if e["kind"] == k]
        if last and last[-1]["state"] == down:
            out.append(f"   now: {k} {down.upper()} for {dur((now - parse(last[-1]['t'])).total_seconds())}")
    total = {}
    for e in events:
        if e["kind"] in ("node", "video") and "outage_s" in e and parse(e["t"]) >= since:
            key = e["kind"] + (" (scheduled)" if e.get("scheduled") else "")
            total[key] = total.get(key, 0) + e["outage_s"]
    out.append("   closed outages in window: " + (", ".join(f"{k} {dur(v)}" for k, v in total.items()) or "none"))
    return out


def cmd_timeline(args) -> int:
    evs = []
    if EVENTS.exists():
        evs = [json.loads(l) for l in EVENTS.read_text().splitlines() if l.strip()]
    evs = [e for e in evs if e.get("node") == args.node]
    now = now_utc()
    print(f"{args.node} timeline, last {args.days} days (UTC; event log {EVENTS})")
    for line in timeline(evs, now - dt.timedelta(days=args.days), now):
        print(line)
    rep = last_report()
    if rep:
        print("   last Pi report:", _rep_line(rep))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    s = sub.add_parser("serve")
    s.add_argument("--bind", default=os.environ.get("BIND", "127.0.0.1:8790"))
    t = sub.add_parser("timeline")
    t.add_argument("--days", type=float, default=7)
    t.add_argument("--node", default=NODE)
    a = ap.parse_args()
    return {"check": cmd_check, "serve": cmd_serve, "timeline": cmd_timeline}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
