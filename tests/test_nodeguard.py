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
