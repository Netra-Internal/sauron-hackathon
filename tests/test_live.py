"""hackdash.live: obs store, frame-time choice, 404 fallback and the /live payload (frame and boxes share t)."""
import asyncio

import pytest

from hackdash import live

NS = live.NS
T0 = 1_761_340_000 * NS


def bucket(*tracks):
    return [{"track_uuid": u, "kind": k, "conf": 0.8, "closed": False, "obs": obs} for u, k, obs in tracks]


def test_push_keeps_persons_only_and_groups_by_frame():
    o = live.Obs()
    o.push("cam", bucket(("a", "person", [[T0, 1, 2, 3, 4, 0.9], [T0 + NS // 5, 2, 3, 4, 5, 0.8]]),
                         ("b", "person", [[T0 + NS // 5, 10, 20, 30, 40, 0.7]]),
                         ("car", "car", [[T0 + NS // 5, 0, 0, 9, 9, 0.9]])), now=T0 / NS + 2)
    assert o.times("cam") == [T0 + NS // 5, T0]
    at = o.at("cam", T0 + NS // 5)
    assert {b["track_uuid"] for b in at} == {"a", "b"}
    assert o.arrival_lag["cam"] == pytest.approx(1.8, abs=1e-3)


def test_push_drops_obs_older_than_keep():
    o = live.Obs()
    o.push("cam", bucket(("a", "person", [[T0, 1, 2, 3, 4, 0.9]])))
    o.push("cam", bucket(("a", "person", [[T0 + (live.KEEP_S + 1) * NS, 1, 2, 3, 4, 0.9]])))
    assert o.times("cam") == [T0 + (live.KEEP_S + 1) * NS]


def test_candidates_fallback_is_at_least_200ms_older():
    times = [T0 + 1000, T0 + 900, T0 - live.FALLBACK_NS + 1000, T0 - live.FALLBACK_NS]
    assert live.candidates(times) == T0 + 1000
    assert live.candidates(times, T0 + 1000) == T0 - live.FALLBACK_NS + 1000
    assert live.candidates([T0], T0) is None


def test_top_facts_skips_normal_and_nulls():
    assert live.top_facts({"normal": 0.99, "break_in": 0.4, "theft": None, "trespass": 0.6, "menace": 0.1}) == \
        {"trespass": 0.6, "break_in": 0.4}


def test_advance_falls_back_on_404_and_frame_matches_boxes(monkeypatch):
    cam = "jetson-c920"
    newest, older = T0 + NS, T0 + NS - live.FALLBACK_NS
    live.OBS.by_cam.pop(cam, None)
    live._current.pop(cam, None)
    live.OBS.push(cam, bucket(("p", "person", [[older, 1, 1, 5, 9, 0.6], [newest, 2, 2, 6, 10, 0.7]])))
    asked = []

    async def fake_frame(c, t):
        asked.append(t)
        return None if t == newest else b"jpeg"
    monkeypatch.setattr(live.FRAMES, "edge_frame", fake_frame)
    asyncio.run(live._advance(cam))
    assert asked == [newest, older]
    assert live._current[cam] == older
    assert live.OBS.at(cam, older)[0]["box"] == [1.0, 1.0, 5.0, 9.0]


def test_complete_ns_gives_an_empty_frame_time():
    o = live.Obs()
    o.push("cam", bucket(("a", "person", [[T0, 1, 2, 3, 4, 0.9]])), complete_ns=T0 + 1)
    o.push("cam", [], complete_ns=T0 + NS + 1)
    assert o.times("cam") == [T0 + NS, T0]
    assert o.at("cam", T0 + NS) == []


def test_label_shape_from_an_incident_row():
    row = {"id": "jetson-c920-20261024T213000Z-ab12", "verdict": "deploy", "why": "break_in",
           "record": {"why_label": "forcing a door", "evidence_e": 0.82, "caption_text": "person pries the gate",
                      "facts": {"break_in": 0.9, "tampering": 0.5, "normal": 0.1, "theft": 0.2}}}
    assert live._label(row, "incident") == {"kind": "incident", "verdict": "deploy", "why_label": "forcing a door",
                                            "e": 0.82, "facts": {"break_in": 0.9, "tampering": 0.5},
                                            "caption": "person pries the gate", "incident_id": row["id"]}
