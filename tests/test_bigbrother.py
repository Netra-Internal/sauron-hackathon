"""Big Brother: who it obeys (policy), what it may change (actions), the MCP tool gate, and the thank-you joke."""
import json

import pytest

from bigbrother import actions, mcp_server, policy, reads, remote

CFG = policy.Cfg(user_id=111, channel_id=222)


def msg(**kw):
    base = dict(author_id=111, channel_id=222, author_is_bot=False, content="status", mentions_bot=True)
    return policy.Msg(**{**base, **kw})


@pytest.fixture(autouse=True)
def state(tmp_path, monkeypatch):
    def no_network(*a, **k):                     # tests must never reach the Pi, pod or droplet
        raise AssertionError("test tried to run a remote command")
    monkeypatch.setattr(remote, "_run", no_network)
    monkeypatch.setattr(actions, "STATE", str(tmp_path))
    monkeypatch.setattr("bigbrother.log.STATE", str(tmp_path))
    monkeypatch.setattr("bigbrother.watch.STATE", str(tmp_path))
    monkeypatch.setattr("bigbrother.watch.NODEGUARD", str(tmp_path))      # nodeguard notes go to the temp dir too
    return tmp_path


# --- who it listens to ---------------------------------------------------------------------------------------------

def test_william_mention_in_channel_is_a_question():
    assert policy.classify(msg(), CFG) == "ask"
    assert policy.classify(msg(mentions_bot=False, replies_to_bot=True), CFG) == "ask"


@pytest.mark.parametrize("kw", [dict(author_id=999), dict(channel_id=333), dict(author_is_bot=True),
                                 dict(mentions_bot=False), dict(content="   ")])
def test_everyone_and_everything_else_is_ignored(kw):
    assert policy.classify(msg(**kw), CFG) == "ignore"


def test_other_user_cannot_confirm_or_get_thanks():
    assert policy.classify(msg(author_id=999, content="yes"), CFG, has_pending=True) == "ignore"
    assert policy.classify(msg(channel_id=333, content="yes"), CFG, has_pending=True) == "ignore"
    assert policy.classify(msg(author_id=999, content="do 5 thank yous"), CFG) == "ignore"
    assert policy.classify(msg(author_is_bot=True, content="yes", author_id=111), CFG, has_pending=True) == "ignore"


def test_yes_only_counts_with_a_pending_proposal():
    assert policy.classify(msg(content="yes", mentions_bot=False), CFG, has_pending=True) == "confirm"
    assert policy.classify(msg(content="yes", mentions_bot=False), CFG, has_pending=False) == "ignore"
    assert policy.classify(msg(content="no", mentions_bot=False), CFG, has_pending=True) == "cancel"
    assert policy.classify(msg(content="yes, but first tell me why", mentions_bot=True), CFG, has_pending=True) == "ask"


# --- thank yous ----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,n", [("Do 5 thank yous", 5), ("do 5 thank you", 5), ("DO FIVE THANK YOUS", 5),
                                    ("do twenty-one thank yous!", 21), ("do 1 thank you", 1), ("Do a hundred thank yous", 100),
                                    ("give me five thank yous", 5), ("five thank yous", 5), ("say 3 thank yous!", 3),
                                    ("send me ten thank-yous please", 10)])
def test_parse_thanks(text, n):
    assert policy.parse_thanks(text) == n
    assert policy.classify(msg(content=text, mentions_bot=False), CFG) == "thanks"


def test_thanks_reply_exact_and_capped():
    assert policy.thanks_reply(5) == "thank you thank you thank you thank you thank you"
    capped = policy.thanks_reply(500)
    first, note = capped.split("\n")
    assert first == " ".join(["thank you"] * 100) and "capped at 100" in note and len(capped) < 2000
    assert policy.parse_thanks("do lots of thank yous") is None
    assert policy.parse_thanks("what did jev cost today") is None
    assert policy.parse_thanks("status") is None and policy.parse_thanks("thank you") is None


# --- what it may change --------------------------------------------------------------------------------------------

def fake_exec(calls):
    def ex(a, node="", cam=""):
        calls.append(a)
        return {"rc": 0, "out": "ok", "err": ""}
    return ex


def test_unknown_action_refused_even_with_yes():
    calls = []
    for confirmed in (False, True):
        r = actions.run("rm_rf_everything", request_text="fix it", confirmed=confirmed, execute=fake_exec(calls))
        assert not r["ok"] and "allowlist" in r["refused"]
    assert calls == []
    assert not actions.propose("edit_config", "because")["ok"]


def test_safe_fix_needs_williams_fix_request():
    calls = []
    r = actions.run("restart_push", request_text="is the camera ok?", execute=fake_exec(calls))
    assert not r["ok"] and calls == []
    r = actions.run("restart_push", request_text="restart the push", execute=fake_exec(calls))
    assert r["ok"] and len(calls) == 1


def test_confirm_action_needs_yes():
    calls = []
    r = actions.run("reboot_node", request_text="fix it, reboot the pi", execute=fake_exec(calls))
    assert not r["ok"] and "yes" in r["refused"] and calls == []
    assert actions.propose("reboot_node", "push dead after restart")["ok"]
    p = actions.take_pending()
    assert p["action"] == "reboot_node" and p["target"] == "demo-node" and actions.pending() is None
    r = actions.run(p["action"], request_text="yes", target=p["target"], confirmed=True, execute=fake_exec(calls))
    assert r["ok"] and calls[0].what.startswith("reboot")


def test_pending_expires():
    actions.propose("reboot_node", "x", now=1000)
    assert actions.pending(now=1000 + actions.PENDING_TTL_S - 1)
    assert actions.pending(now=1000 + actions.PENDING_TTL_S + 1) is None


def test_cooldown():
    calls = []
    assert actions.run("restart_phonealert", request_text="restart it", execute=fake_exec(calls), now=5000)["ok"]
    r = actions.run("restart_phonealert", request_text="restart it", execute=fake_exec(calls), now=5100)
    assert not r["ok"] and "once per" in r["refused"] and len(calls) == 1
    assert actions.run("restart_phonealert", request_text="restart it", execute=fake_exec(calls), now=5400)["ok"]


def test_every_runbook_action_is_a_fixed_script():
    assert {n for n, a in actions.ACTIONS.items() if a.kind == "safe"} == {
        "restart_push", "restart_tailscaled", "restart_pod_jev_watcher", "rerun_r2_archiver",
        "restart_netra_ask", "restart_phonealert", "restart_engine"}
    for a in actions.ACTIONS.values():
        assert a.where in ("node", "pod", "droplet") and a.script.strip()
    assert "{" not in actions.render(actions.ACTIONS["restart_pod_jev_watcher"], "demo-node", "demo-linovision") \
        .replace("${loop:-none}", "")


# --- the MCP gate Claude goes through ------------------------------------------------------------------------------

def call(name, args, request, monkeypatch, calls):
    monkeypatch.setenv("BB_REQUEST", request)
    monkeypatch.setattr(actions.run, "__kwdefaults__", {**actions.run.__kwdefaults__, "execute": fake_exec(calls)})
    out = mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                             "params": {"name": name, "arguments": args}})
    return json.loads(out["result"]["content"][0]["text"])


def test_mcp_run_fix_uses_williams_message(monkeypatch):
    calls = []
    assert not call("run_fix", {"action": "restart_push"}, "how is the pi?", monkeypatch, calls)["ok"]
    assert not call("run_fix", {"action": "reboot_node"}, "fix it", monkeypatch, calls)["ok"]
    assert not call("run_fix", {"action": "curl_evil"}, "fix it", monkeypatch, calls)["ok"]
    assert calls == []
    assert call("run_fix", {"action": "restart_push"}, "fix it", monkeypatch, calls)["ok"]
    assert len(calls) == 1


def test_mcp_lists_only_our_tools():
    out = mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = {t["name"] for t in out["result"]["tools"]}
    assert {"run_fix", "propose_action", "node_status", "jev_cost", "camera_frame"} <= names
    assert mcp_server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_read_tools_refuse_unlisted_targets():
    assert "error" in reads.pi_journal("sshd")
    assert "error" in reads.pod_log("../../etc/shadow")
    assert "error" in reads.camera_health("x'; drop table feed_health;--")


# --- small decoders ------------------------------------------------------------------------------------------------

def test_decode_throttled():
    assert reads.decode_throttled("0x80000") == ["soft temp limit since boot"]
    assert reads.decode_throttled("0x50005") == ["under-voltage now", "throttled now", "under-voltage since boot",
                                                 "throttled since boot"]
    assert reads.decode_throttled("0x0") == ["none (0x0)"]


def test_pod_target_from_tunnel_unit():
    unit = "ExecStart=/usr/bin/ssh -N -L 127.0.0.1:8450:127.0.0.1:8450 -p 57061 root@203.0.113.7 -i key"
    assert remote.pod_target(unit) == ("203.0.113.7", "57061")
    real = ("ExecStart=/usr/bin/ssh -N -i /root/.ssh/k -o BatchMode=yes -p 57061 -L 127.0.0.1:8450:127.0.0.1:8450 "
            "root@203.0.113.7")
    assert remote.pod_target(real) == ("203.0.113.7", "57061")
    assert remote.pod_target("nothing") is None


# --- targets and the reboot gate -----------------------------------------------------------------------------------

def test_targets_are_from_the_fixed_lists():
    calls = []
    assert not actions.run("restart_push", request_text="fix it", target="evil; rm -rf /", execute=fake_exec(calls))["ok"]
    assert not actions.run("restart_pod_jev_watcher", request_text="fix it", target="axis-q6215",
                           execute=fake_exec(calls))["ok"]
    assert calls == []
    r = actions.run("restart_push", request_text="fix it", target="demo-node2", execute=fake_exec(calls))
    assert r["ok"] and r["target"] == "demo-node2"
    # cooldown is per target
    assert actions.run("restart_push", request_text="fix it", target="demo-node", execute=fake_exec(calls))["ok"]


def test_auto_reboot_only_after_failed_push_restart_and_once_per_30_min():
    calls = []
    r = actions.run("reboot_node", request_text="", target="demo-node2", auto=True, execute=fake_exec(calls), now=10_000)
    assert not r["ok"] and calls == []                                   # no failed push restart yet
    actions.note_push_failed("demo-node2", now=10_000)
    assert not actions.run("reboot_node", request_text="", target="demo-node", auto=True, execute=fake_exec(calls),
                           now=10_010)["ok"]                             # the failure was on the other node
    assert actions.run("reboot_node", request_text="", target="demo-node2", auto=True, execute=fake_exec(calls),
                       now=10_010)["ok"]
    actions.note_push_failed("demo-node2", now=10_600)
    r = actions.run("reboot_node", request_text="", target="demo-node2", auto=True, execute=fake_exec(calls), now=10_610)
    assert not r["ok"] and "once per 1800" in r["refused"]
    r = actions.run("reboot_node", request_text="yes", target="demo-node2", confirmed=True, execute=fake_exec(calls),
                    now=10_620)
    assert not r["ok"]                                                   # even William's yes respects the 30 min
    actions.note_push_failed("demo-node2", now=20_000)
    assert not actions.run("reboot_node", request_text="", target="demo-node2", auto=True, execute=fake_exec(calls),
                           now=20_000 + actions.REBOOT_AFTER_S + 1)["ok"]  # the push failure is too old
    assert len(calls) == 1


def test_reboot_script_refuses_without_overlay_root():
    s = actions.render(actions.ACTIONS["reboot_node"], "demo-node2", "")
    assert 'findmnt -n -o FSTYPE /' in s and 'exit 4' in s and s.index("exit 4") < s.index("reboot &&") \
        if "reboot &&" in s else s.index("exit 4") < s.index("systemctl reboot")


def test_claude_cannot_auto_run():
    import inspect
    src = inspect.getsource(mcp_server.call)
    assert "auto" not in src and "confirmed" not in src


# --- proactive watcher ---------------------------------------------------------------------------------------------

from datetime import datetime  # noqa: E402

from bigbrother import watch  # noqa: E402

NOW = 1_800_000_000.0


def test_camera_issue_detection():
    states = {"demo-node": {"node": "online", "video": "up"},
              "demo-node2": {"node": "online", "video": "down", "video_since": "2026-10-27T23:08:55+00:00",
                             "last_report": {"push_active": False}}}
    fh = {"demo-linovision": {"age_s": 5, "fps": 5.3, "beats": 18}}
    iss = watch.camera_issues(fh, states, NOW)
    assert [i.key for i in iss] == ["cam:demo-linovision-2"]
    assert any("push_active=false" in e for e in iss[0].evidence) and any("no heartbeat" in e for e in iss[0].evidence)
    fh["demo-linovision"] = {"age_s": 5, "fps": 1.2, "beats": 18}
    assert "cam:demo-linovision" in [i.key for i in watch.camera_issues(fh, states, NOW)]
    fh["demo-linovision"] = {"age_s": 400, "fps": None, "beats": 0}
    assert "cam:demo-linovision" in [i.key for i in watch.camera_issues(fh, states, NOW)]
    # scheduled off / node offline -> no camera incident
    states["demo-node2"]["video_sched"] = True
    states["demo-node"]["node"] = "offline"
    assert watch.camera_issues(fh, states, NOW) == []


def test_event_issues():
    ev = [{"t": "2026-10-27T17:28:14+00:00", "node": "demo-node", "kind": "tailscale", "state": "restarted",
           "at": "2026-10-27T17:28:00+00:00", "text": "restarted tailscaled"},
          {"t": "2026-10-27T17:14:16+00:00", "node": "demo-node", "kind": "throttle", "bits": "0x80008"},
          {"t": "2026-10-27T17:14:16+00:00", "node": "demo-node", "kind": "throttle", "bits": "0x50005"}]
    assert [i.key for i in watch.event_issues(ev)] == ["tailscale:demo-node", "uv:demo-node"]


def test_events_cursor_starts_at_end_and_reads_only_new(tmp_path, monkeypatch):
    monkeypatch.setattr(watch, "NODEGUARD", str(tmp_path))
    f = tmp_path / "events.jsonl"
    f.write_text('{"t":"x","kind":"old"}\n')
    st = {}
    assert watch.new_events(st) == []
    with open(f, "a") as fh:
        fh.write('{"t":"y","kind":"new"}\n{"t":"z","kind":"part')
    assert [e["kind"] for e in watch.new_events(st)] == ["new"]
    with open(f, "a") as fh:
        fh.write('ial"}\n')
    assert [e["kind"] for e in watch.new_events(st)] == ["partial"]


def test_message_mentions_only_when_not_fixed():
    i = watch.Issue("cam:x", "cam", "x", "x down", ["e1"])
    t, m = watch.message(i, ["restarted push"], True, "42")
    assert not m and "<@42>" not in t and "FIXED" in t
    t, m = watch.message(i, ["nothing"], False, "42")
    assert m and "<@42>" in t and "could not fix" in t
    assert len(watch.message(i, ["x" * 3000], False, "42")[0]) <= 1901


def run(monkeypatch, issues_seq, results, now0=NOW):
    """Drive run_pass with canned detections; returns (posts, state)."""
    posts, state = [], {"open": {}, "posts": []}
    for n, issues in enumerate(issues_seq):
        monkeypatch.setattr(watch, "detect", lambda s, now, iss=issues: ([watch.Issue(**i) for i in iss], {}))
        watch.run_pass(state, now0 + n * 60, handle=lambda i, did: results[i.key],
                       poster=lambda text, mention: posts.append((text, mention)) or {"status": 200})
    return posts, state


CAM = dict(key="cam:demo-linovision-2", kind="cam", target="demo-linovision-2", title="down", evidence=["e"])


def test_fixed_is_silent_and_closes(monkeypatch):
    posts, state = run(monkeypatch, [[CAM]] * 5 + [[], [], []], {CAM["key"]: True})
    assert posts == []                                               # fixed -> log only (William, Oct 28)
    assert state["open"] == {}                                       # closed after 2 clear passes


@pytest.mark.parametrize("fixed", [True, None])
def test_only_unfixed_infra_down_posts(monkeypatch, fixed):
    uv = dict(key="uv:demo-node", kind="uv", target="demo-node", title="uv", evidence=[])
    slow = dict(key="engineslow:s", kind="engineslow", target="s", title="slow", evidence=[])
    posts, _ = run(monkeypatch, [[uv, slow]], {uv["key"]: False, slow["key"]: False})
    assert posts == []                                               # warnings never post, even unfixed
    posts, _ = run(monkeypatch, [[CAM]], {CAM["key"]: fixed})
    assert posts == []


def test_unfixed_camera_posts_once_and_is_never_retried(monkeypatch):
    results = {CAM["key"]: False}
    posts, state = run(monkeypatch, [[CAM]] * 150, results)         # 2.5 h still broken
    assert len(posts) == 1 and posts[0][1]                          # one mention
    assert state["open"][CAM["key"]]["attempts"] == 1               # one push restart + one reboot, no loop
    posts, state = run(monkeypatch, [[CAM]] * 3 + [[], []], results)  # recovers on its own -> no post
    assert len(posts) == 1 and state["open"] == {}


def test_degrades_again_within_2h_needs_root_cause(monkeypatch):
    calls = []
    def handle(i, did):
        calls.append(i.key)
        return True
    posts, state = [], {"open": {}, "posts": []}
    seq = [[CAM], [], [], [CAM]] + [[CAM], [], []] * 20               # fixed, clears, back 3 min later, flaps for 1 h
    for n, issues in enumerate(seq):
        monkeypatch.setattr(watch, "detect", lambda s, now, iss=issues: ([watch.Issue(**i) for i in iss], {}))
        watch.run_pass(state, NOW + n * 60, handle=handle, poster=lambda t, m: posts.append((t, m)))
    assert calls == [CAM["key"]]                                     # fixed once, then never touched again
    assert len(posts) == 1 and "NEEDS ROOT CAUSE" in posts[0][0] and posts[0][1]
    assert "demo-linovision-2" in state["rootcause"]
    # nodeguard marks demo-node2 fixed -> cleared, and a later outage is handled normally again
    assert watch.clear_rootcause(state, [{"node": "demo-node2", "kind": "note", "state": "fixed"}]) == ["demo-linovision-2"]
    assert "demo-linovision-2" not in state["rootcause"]


def test_hold_file_stops_actions_and_posts(monkeypatch, tmp_path):
    monkeypatch.setattr(watch, "HOLD_DIRS", [str(tmp_path)])
    (tmp_path / "hold-demo-node2").write_text(json.dumps({"by": "nodeguard", "reason": "root-causing"}))
    calls = []
    posts, state = [], {"open": {}, "posts": []}
    monkeypatch.setattr(watch, "detect", lambda s, now: ([watch.Issue(**CAM)], {}))
    for n in range(5):
        watch.run_pass(state, NOW + n * 60, handle=lambda i, d: calls.append(1) or False,
                       poster=lambda t, m: posts.append(t))
    assert calls == [] and posts == []
    (tmp_path / "hold-demo-node2").write_text(json.dumps({"until": NOW + 120}))   # expiring hold
    assert watch.hold("demo-node2", NOW + 60) and watch.hold("demo-node2", NOW + 121) is None
    (tmp_path / "hold-demo-node2").write_text("")                                  # empty file = until removed
    assert watch.hold("demo-node2", NOW + 10**6)


def test_defers_to_the_nodes_own_push_health():
    st = {"recent_events": [{"t": "2026-10-28T19:50:15+00:00", "at": "2026-10-28T19:49:51+00:00", "node": "demo-node2",
                             "kind": "push", "state": "fallback"}]}
    t = datetime.fromisoformat("2026-10-28T19:55:00+00:00").timestamp()
    i = watch.Issue(**CAM)
    assert "push-health" in watch.blocked(i, st, t)
    assert watch.blocked(i, st, t + watch.PUSH_HEALTH_DEFER_S) is None


def test_burst_fps_is_not_proof_of_health(monkeypatch):
    seq = iter([{"demo-linovision-2": {"age_s": 5, "fps": 295.5, "beats": 3}},
                {"demo-linovision-2": {"age_s": 5, "fps": 5.1, "beats": 9}}])
    monkeypatch.setattr(watch, "feed", lambda now: next(seq))
    assert watch.wait_feed("demo-linovision-2", 100, sleep=lambda s: None)["fps"] == 5.1


def test_tailscale_events_merge_within_an_hour(monkeypatch):
    ts = dict(key="tailscale:demo-node", kind="tailscale", target="demo-node", title="ts", evidence=[])
    posts, _ = run(monkeypatch, [[ts], [], [ts], [], [ts]], {ts["key"]: False})
    assert len(posts) == 1


def test_post_rate_limit(monkeypatch):
    many = [dict(key=f"watcher:c{n}", kind="watcher", target=f"c{n}", title="w", evidence=[]) for n in range(10)]
    posts, _ = run(monkeypatch, [many], {m["key"]: False for m in many})
    assert len(posts) == watch.MAX_POSTS_PER_HOUR


def test_camera_playbook_push_then_reboot(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(actions.run, "__kwdefaults__", {**actions.run.__kwdefaults__, "execute": fake_exec(calls)})
    monkeypatch.setattr(watch, "probe_node", lambda node: {"tailnet": True, "rev": False, "reachable": True,
                                                           "out": "push: inactive", "err": ""})
    monkeypatch.setattr(watch.time, "sleep", lambda s: None)
    feeds = iter([None, {"fps": 5.1, "age_s": 4}])                  # down after the push restart, back after reboot
    monkeypatch.setattr(watch, "wait_feed", lambda cam, t: next(feeds))
    i = watch.Issue("cam:demo-linovision-2", "cam", "demo-linovision-2", "down", [])
    did = []
    assert watch.fix_camera(i, did) is True
    assert [c.script == actions.ACTIONS["reboot_node"].script for c in calls] == [False, True]
    assert any("verified after reboot" in d for d in did)
    notes = (tmp_path / "events.jsonl").read_text().splitlines()
    assert len(notes) == 2 and all('"state": "bigbrother"' in n for n in notes)
    # same thing again 10 min later: push restart is in cooldown and the reboot is refused (once per 30 min)
    feeds = iter([None])
    monkeypatch.setattr(watch, "wait_feed", lambda cam, t: next(feeds))
    did = []
    assert watch.fix_camera(i, did) is False and len(calls) == 2
    assert any("refused" in d for d in did)


def test_unreachable_node_is_not_fixed():
    i = watch.Issue("node:demo-node2", "node", "demo-node2", "offline", [])
    did = []
    watch_probe = watch.probe_node
    try:
        watch.probe_node = lambda node: {"tailnet": False, "rev": False, "reachable": False, "out": "", "err": ""}
        assert watch.fix_node(i, did) is False and "unreachable" in did[0]
    finally:
        watch.probe_node = watch_probe


# --- engine / perception health (site/BIGBROTHER-ENGINE-HEALTH.md) -------------------------------------------------

SITE = "ucsd-design-innovation-building-c1dd"


def hrow(t, steps=100, cams=None, step_ms=40):
    return (t, {"steps": steps, "step_ms_last": step_ms, "step_ms_max": step_ms,
                "cameras": cams if cams is not None else {"demo-linovision": {"last_rx_age_s": 0.4, "buckets": 9}}})


def test_engine_silent_until_deployed():
    assert watch.engine_issues(SITE, None, {}, {}, {}, NOW) == []       # no table
    assert watch.engine_issues(SITE, [], {}, {}, {}, NOW) == []         # no heartbeat in 24 h


def test_engine_down_stuck_link_slow():
    fh = {"demo-linovision": {"age_s": 5, "fps": 5, "beats": 18}}
    pod = {"engine": [SITE], "judged": []}
    down = watch.engine_issues(SITE, [hrow(NOW - 300)], fh, pod, {}, NOW)
    assert [i.key for i in down] == [f"engine:{SITE}"] and "down" in down[0].title
    stuck = watch.engine_issues(SITE, [hrow(NOW - 5, 100), hrow(NOW - 40, 100), hrow(NOW - 70, 100)], fh, pod, {}, NOW)
    assert [i.title for i in stuck] == [f"site engine {SITE} stuck"]
    moving = watch.engine_issues(SITE, [hrow(NOW - 5, 160), hrow(NOW - 70, 100)], fh, pod, {}, NOW)
    assert moving == []
    st = {}
    link = watch.engine_issues(SITE, [hrow(NOW - 5, 160, {"demo-linovision": {"last_rx_age_s": 300}})], fh, pod, st, NOW)
    assert link == []                                                   # never seen working (rollout): silent
    watch.engine_issues(SITE, [hrow(NOW - 5, 160)], fh, pod, st, NOW)   # link works once
    link = watch.engine_issues(SITE, [hrow(NOW - 5, 160, {"demo-linovision": {"last_rx_age_s": 300}})], fh, pod, st, NOW)
    assert [i.key for i in link] == ["enginelink:demo-linovision"]
    # camera itself down -> that's the camera incident, not a link incident
    assert watch.engine_issues(SITE, [hrow(NOW - 5, 160, {"demo-linovision": {"last_rx_age_s": 300}})],
                               {"demo-linovision": {"age_s": 900, "fps": None, "beats": 0}}, pod, {}, NOW) == []
    slow = watch.engine_issues(SITE, [hrow(NOW - 5, 160, step_ms=5000)], fh, pod, {}, NOW)
    assert [i.kind for i in slow] == ["engineslow"]


def test_judged_alert_only_after_it_was_seen():
    st = {}
    rows = [hrow(NOW - 5, 160)]
    assert watch.engine_issues(SITE, rows, {}, {"engine": [SITE], "judged": []}, st, NOW) == []
    assert watch.engine_issues(SITE, rows, {}, {"engine": [SITE], "judged": [SITE]}, st, NOW) == []
    gone = watch.engine_issues(SITE, rows, {}, {"engine": [SITE], "judged": []}, st, NOW)
    assert [i.key for i in gone] == [f"judged:{SITE}"]


def test_merged_perception_is_not_a_missing_watcher(monkeypatch):
    probe = {"now": NOW, "edge": ["demo-linovision"], "watch": [], "edge_jev": ["demo-linovision"],
             "dispatch_cams": ["demo-linovision"], "archive_running": True, "archive": {}, "engine": [], "judged": []}
    monkeypatch.setattr(watch.remote, "pod", lambda script, timeout=0: {"rc": 0, "out": json.dumps(probe), "err": ""})
    issues, _ = watch.pod_issues(NOW)
    assert issues == []
    probe["edge_jev"] = []
    issues, _ = watch.pod_issues(NOW)
    assert [i.key for i in issues] == ["watcher:demo-linovision"]
    s = actions.render(actions.ACTIONS["restart_pod_jev_watcher"], "demo-node", "demo-linovision")
    assert "--jev on" in s and s.index("exit 5") < s.index("pkill")      # never starts a 2nd Jev next to a merged edge


def test_restart_engine_gate_and_script():
    calls = []
    assert not actions.run("restart_engine", request_text="how is the engine?", execute=fake_exec(calls))["ok"]
    assert not actions.run("restart_engine", request_text="restart it", target="other-site", execute=fake_exec(calls))["ok"]
    assert calls == []
    r = actions.run("restart_engine", request_text="restart the engine", execute=fake_exec(calls))
    assert r["ok"] and r["target"] == SITE
    s = actions.render(actions.ACTIONS["restart_engine"], "", SITE)
    assert f"--site {SITE}" in s and "exit 6" in s and s.index("exit 6") < s.index("kill $pid")


def test_engine_reads_refuse_bad_input():
    assert "error" in reads.engine_status("x'; drop table engine_health;--")
    assert "error" in reads.decisions("nope")
    assert "error" in reads.explain_decision("1' or '1'='1")


# --- site context tools (bike log, shapes, calibration, zone activity) ---------------------------------------------

from bigbrother import askdata  # noqa: E402


def test_ask_env_parses_values_with_spaces(tmp_path):
    f = tmp_path / "ask.env"
    f.write_text('# c\nA=1\nDISPATCH_WEBHOOK=http://a:1 http://b:2\nQ="x y"\n\nBAD LINE\n')
    env = askdata.ask_env(str(f))
    assert env["DISPATCH_WEBHOOK"] == "http://a:1 http://b:2" and env["Q"] == "x y" and env["A"] == "1"
    assert "/usr/sbin" in env["PATH"]


def test_site_tools_validate_input(monkeypatch):
    monkeypatch.setattr(askdata, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run")))
    assert "error" in askdata.calibration("x'; drop")
    assert "error" in askdata.site_shapes("../../etc")
    assert "error" in askdata.bikelog(day="yesterday; rm -rf /")


def test_zone_activity_finds_the_engine_route_when_it_exists(tmp_path, monkeypatch):
    (tmp_path / "ask").mkdir()
    api = tmp_path / "ask" / "api.py"
    api.write_text('@app.get(P + "/api/sites/{sid}/cameras/{cid}/zones")\n')
    monkeypatch.setattr(askdata, "ASK_DIR", str(tmp_path))
    r = askdata.zone_activity()
    assert not r["available"] and "not deployed yet" in r["status"]
    api.write_text(api.read_text() + '@app.get(P + "/api/sites/{sid}/zones/activity")\n')
    r = askdata.zone_activity()
    assert r["available"] and r["routes_found"] == ["/api/sites/{sid}/zones/activity"]


def test_new_tools_are_listed():
    names = {t["name"] for t in mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]}
    assert {"bike_log", "site_shapes", "calibration", "zone_activity"} <= names
    desc = next(t for t in mcp_server.tool_list() if t["name"] == "bike_log")["description"]
    assert "login" in desc and "PARK" in desc and "TAKE" in desc
