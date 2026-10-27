"""Append-only log of every question, tool call, fix and answer: /var/lib/netra-bigbrother/log.jsonl."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

STATE = os.environ.get("BB_STATE", "/var/lib/netra-bigbrother")


def write(rec: dict) -> None:
    os.makedirs(STATE, exist_ok=True)
    rec = {"t": datetime.now(timezone.utc).isoformat(timespec="seconds"), **rec}
    with open(os.path.join(STATE, "log.jsonl"), "a") as f:
        f.write(json.dumps(rec, default=str)[:60000] + "\n")


def recent_answers(n: int = 3, max_age_s: float = 1800) -> list[dict]:
    """The last few question/answer pairs, so "fix it" can follow "status"."""
    try:
        with open(os.path.join(STATE, "log.jsonl")) as f:
            lines = f.readlines()[-400:]
    except OSError:
        return []
    now = datetime.now(timezone.utc).timestamp()
    out = []
    for ln in lines:
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if r.get("kind") == "answer" and now - datetime.fromisoformat(r["t"]).timestamp() < max_age_s:
            out.append({"q": r.get("question", "")[:500], "a": r.get("answer", "")[:1500]})
    return out[-n:]
