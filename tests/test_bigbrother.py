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
                                    ("do twenty-one thank yous!", 21), ("do 1 thank you", 1), ("Do a hundred thank yous", 100)])
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


# --- what it may change --------------------------------------------------------------------------------------------

def fake_exec(calls):
    def ex(a):
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
    r = actions.run("restart_pi_push", request_text="is the camera ok?", execute=fake_exec(calls))
    assert not r["ok"] and calls == []
    r = actions.run("restart_pi_push", request_text="restart the push", execute=fake_exec(calls))
    assert r["ok"] and len(calls) == 1


def test_confirm_action_needs_yes():
    calls = []
    r = actions.run("reboot_pi", request_text="fix it, reboot the pi", execute=fake_exec(calls))
    assert not r["ok"] and "yes" in r["refused"] and calls == []
    assert actions.propose("reboot_pi", "push dead after restart")["ok"]
    p = actions.take_pending()
    assert p["action"] == "reboot_pi" and actions.pending() is None
    r = actions.run(p["action"], request_text="yes", confirmed=True, execute=fake_exec(calls))
    assert r["ok"] and calls[0].what.startswith("reboot")


def test_pending_expires():
    actions.propose("reboot_pi", "x", now=1000)
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
        "restart_pi_push", "restart_pi_tailscaled", "restart_pod_jev_watcher", "rerun_r2_archiver",
        "restart_netra_ask", "restart_phonealert"}
    for a in actions.ACTIONS.values():
        assert a.where in ("pi", "pod", "droplet") and a.script.strip()


# --- the MCP gate Claude goes through ------------------------------------------------------------------------------

def call(name, args, request, monkeypatch, calls):
    monkeypatch.setenv("BB_REQUEST", request)
    monkeypatch.setattr(actions.run, "__kwdefaults__", {**actions.run.__kwdefaults__, "execute": fake_exec(calls)})
    out = mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                             "params": {"name": name, "arguments": args}})
    return json.loads(out["result"]["content"][0]["text"])


def test_mcp_run_fix_uses_williams_message(monkeypatch):
    calls = []
    assert not call("run_fix", {"action": "restart_pi_push"}, "how is the pi?", monkeypatch, calls)["ok"]
    assert not call("run_fix", {"action": "reboot_pi"}, "fix it", monkeypatch, calls)["ok"]
    assert not call("run_fix", {"action": "curl_evil"}, "fix it", monkeypatch, calls)["ok"]
    assert calls == []
    assert call("run_fix", {"action": "restart_pi_push"}, "fix it", monkeypatch, calls)["ok"]
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
