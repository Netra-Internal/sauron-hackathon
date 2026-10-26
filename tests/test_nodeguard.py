"""node/droplet/nodeguard.py: the state machine and the timeline (no network, no DB, no Discord)."""
import datetime as dt
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("nodeguard", Path(__file__).parent.parent / "node/droplet/nodeguard.py")
ng = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ng)

T0 = dt.datetime(2026, 10, 26, 22, 0, tzinfo=dt.timezone.utc)
BOOT_A = "a" * 8 + "-aaaa-aaaa-aaaa-" + "a" * 12
BOOT_B = "b" * 8 + "-bbbb-bbbb-bbbb-" + "b" * 12


def rep(t, boot=BOOT_A, uptime=600, throttled="0x0", **kw):
    return {"node": "demo-node", "boot_id": boot, "uptime_s": uptime, "throttled": throttled,
            "received_at": ng.iso(t), **kw}


def run(steps):
    """steps: list of (minute, obs) -> all events and posts in order."""
    st, evs, posts = {}, [], []
    for m, obs in steps:
        st, e, p = ng.step(st, obs, T0 + dt.timedelta(minutes=m))
        evs += e
        posts += p
    return st, evs, posts


def test_offline_after_3_min_once_then_online_without_mention():
    up = {"ts_ok": True, "video_ok": True}
    down = {"ts_ok": False, "video_ok": True}
    st, evs, posts = run([(0, up), (1, down), (2, down), (3, down), (4, down), (5, down), (6, up)])
    kinds = [(e["kind"], e["state"]) for e in evs]
    assert kinds == [("node", "online"), ("video", "up"), ("node", "offline"), ("node", "online")]
    assert evs[3]["outage_s"] == 360          # counted from the last good minute (0) to back (6)
    offline = [p for p in posts if "OFFLINE" in p[0]]
    online = [p for p in posts if "back ONLINE" in p[0]]
    assert len(offline) == 1 and offline[0][1] is True
    assert len(online) == 1 and online[0][1] is False


def test_fresh_report_keeps_node_online_when_tailscale_ping_drops():
    st, evs, posts = run([(m, {"ts_ok": False, "video_ok": True, "report": rep(T0 + dt.timedelta(minutes=m))})
                          for m in range(6)])
    assert not [e for e in evs if e["state"] == "offline"] and not posts


def test_video_down_once_per_outage_and_recovered_unmentioned():
    st, evs, posts = run([(0, {"ts_ok": True, "video_ok": True})] +
                         [(m, {"ts_ok": True, "video_ok": False, "tunnel_ok": False}) for m in range(1, 6)] +
                         [(6, {"ts_ok": True, "video_ok": True})])
    downs = [p for p in posts if "video DOWN" in p[0]]
    assert len(downs) == 1 and downs[0][1] is True and "push tunnel DOWN" in downs[0][0]
    rec = [p for p in posts if "video recovered" in p[0]]
    assert len(rec) == 1 and rec[0][1] is False


def test_boot_event_prev_uptime_cause_and_under_voltage_once_per_boot():
    wd = int((T0 + dt.timedelta(minutes=1, seconds=50)).timestamp())
    steps = [(0, {"ts_ok": True, "video_ok": True, "report": rep(T0, uptime=7200)}),
             # new boot: received at minute 3 with uptime 60 s -> booted at 2:00; watchdog stamped 1:50 -> its reboot
             (3, {"ts_ok": True, "video_ok": True, "report": rep(T0 + dt.timedelta(minutes=3), BOOT_B, 60, "0x50005",
                                                                  wd_last_reboot=wd)}),
             (4, {"ts_ok": True, "video_ok": True, "report": rep(T0 + dt.timedelta(minutes=4), BOOT_B, 120, "0x50005")}),
             (5, {"ts_ok": True, "video_ok": True, "report": rep(T0 + dt.timedelta(minutes=5), BOOT_B, 180, "0x50000")})]
    st, evs, posts = run(steps)
    boots = [e for e in evs if e["kind"] == "boot"]
    assert len(boots) == 2
    assert boots[1]["booted_at"] == "2026-10-26T22:02:00+00:00"
    assert boots[1]["prev_uptime_s"] == 7200 and boots[1]["cause"] == "wifi-watchdog"
    uv = [p for p in posts if "under-voltage seen" in p[0]]
    assert len(uv) == 1 and uv[0][1] is True
    assert [p for p in posts if "rebooted" in p[0]]
    throttles = [e["bits"] for e in evs if e["kind"] == "throttle"]
    assert throttles == ["0x50005", "0x50000"]   # logged at boot (non-zero) and on each change, not every minute


def test_timeline_reports_outage_durations_and_open_outage():
    evs = [{"t": "2026-10-26T10:00:00+00:00", "node": "demo-node", "kind": "node", "state": "online", "first": True},
           {"t": "2026-10-26T11:03:00+00:00", "node": "demo-node", "kind": "node", "state": "offline",
            "last_seen": "2026-10-26T11:00:00+00:00"},
           {"t": "2026-10-26T12:00:00+00:00", "node": "demo-node", "kind": "node", "state": "online", "outage_s": 3600},
           {"t": "2026-10-26T13:00:00+00:00", "node": "demo-node", "kind": "video", "state": "down"}]
    out = ng.timeline(evs, T0 - dt.timedelta(days=7), T0)
    text = "\n".join(out)
    assert "was down 1h00m" in text
    assert "now: video DOWN for 9h00m" in text
    assert "closed outages in window: node 1h00m" in text


def test_video_outage_starts_at_last_good_frame():
    last = ng.iso(T0 + dt.timedelta(seconds=10))
    st, evs, posts = run([(0, {"ts_ok": True, "video_ok": True}),
                          (5, {"ts_ok": True, "video_ok": False, "video_last_ok": last}),
                          (8, {"ts_ok": True, "video_ok": True})])
    assert [e for e in evs if e["kind"] == "video"][-1]["outage_s"] == 470
    assert last in [p for p in posts if "video DOWN" in p[0]][0][0]


def test_boot_without_watchdog_stamp_is_not_the_watchdog():
    st, evs, posts = run([(0, {"ts_ok": True, "video_ok": True, "report": rep(T0, uptime=7200, wd_last_reboot=0)}),
                          (3, {"ts_ok": True, "video_ok": True,
                               "report": rep(T0 + dt.timedelta(minutes=3), BOOT_B, 60, wd_last_reboot=0)})])
    assert [e for e in evs if e["kind"] == "boot"][1]["cause"].startswith("not the watchdog")


# ---- approved night off: Mon-Fri 01:00-06:00 San Diego time (PDT = UTC-7 in these dates)
SCHED = "Mon-Fri 01:00-06:00 America/Los_Angeles"


def night(day_utc, video_back_utc=None, node_off=None, node_back_utc=None):
    """Minute checks 07:30-14:00 UTC on day_utc. Video stops at 08:00 UTC (01:00 PDT, push stopped) or at node_off;
    it comes back at video_back_utc. node_off/node_back_utc: the Pi itself is off (staged poweroff)."""
    ng.SCHEDULE_OFF = SCHED
    try:
        st, evs, posts = {}, [], []
        t = dt.datetime.combine(day_utc, dt.time(7, 30), dt.timezone.utc)
        stop = node_off or dt.datetime.combine(day_utc, dt.time(8, 0), dt.timezone.utc)
        last_frame = None
        while t <= dt.datetime.combine(day_utc, dt.time(14, 0), dt.timezone.utc):
            video = t < stop or (video_back_utc is not None and t >= video_back_utc)
            last_frame = t if video else last_frame
            alive = not (node_off and node_off <= t and (node_back_utc is None or t < node_back_utc))
            obs = {"ts_ok": alive, "video_ok": video, "video_last_ok": ng.iso(last_frame)}
            st, e, p = ng.step(st, obs, t)
            evs += e
            posts += p
            t += dt.timedelta(minutes=1)
        return st, evs, posts
    finally:
        ng.SCHEDULE_OFF = ""


def at(day, hh, mm):
    return dt.datetime.combine(day, dt.time(hh, mm), dt.timezone.utc)


TUE = dt.date(2026, 10, 27)
SAT = dt.date(2026, 10, 31)


def test_quiet_window_edges_in_local_time():
    for t, want in [(at(TUE, 7, 54), False), (at(TUE, 7, 55), True), (at(TUE, 13, 14), True), (at(TUE, 13, 15), False),
                    (at(SAT, 9, 0), False), (at(dt.date(2026, 11, 2), 9, 0), True),   # Mon after DST ends: 01:00 PST
                    (at(dt.date(2026, 11, 2), 8, 30), False)]:
        assert ng.quiet(t, SCHED) is want, t


def test_scheduled_night_back_on_time_posts_nothing_and_logs_scheduled():
    st, evs, posts = night(TUE, video_back_utc=at(TUE, 13, 2))
    assert posts == []
    v = [e for e in evs if e["kind"] == "video"]
    assert [x["state"] for x in v][-2:] == ["down", "up"] and v[-1]["scheduled"] and v[-2]["scheduled"]
    assert [e["state"] for e in evs if e["kind"] == "schedule"] == ["off-window", "on-window"]


def test_not_back_by_0615_alerts_once_with_mention_then_recovery_without():
    st, evs, posts = night(TUE, video_back_utc=at(TUE, 13, 40))
    late = [p for p in posts if "NOT back" in p[0]]
    assert len(late) == 1 and late[0][1] is True and "video DOWN" in late[0][0]
    rec = [p for p in posts if "video recovered" in p[0]]
    assert len(rec) == 1 and rec[0][1] is False
    assert len(posts) == 2


def test_weekend_night_alerts_as_usual():
    st, evs, posts = night(SAT, video_back_utc=at(SAT, 13, 2))
    assert [p[1] for p in posts if "video DOWN" in p[0]] == [True]
    assert not [e for e in evs if e.get("scheduled")]


def test_staged_poweroff_night_node_off_and_back_is_quiet():
    st, evs, posts = night(TUE, video_back_utc=at(TUE, 13, 3), node_off=at(TUE, 7, 58), node_back_utc=at(TUE, 13, 1))
    assert posts == []
    off = [e for e in evs if e["kind"] == "node" and e["state"] == "offline"]
    assert off and off[0]["scheduled"]
