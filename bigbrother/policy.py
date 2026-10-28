"""Who Big Brother listens to and what a message asks for. Pure functions, no Discord import, so tests run anywhere.

Rules (brief, Oct 27):
- Only William (DISCORD_MENTION_USER_ID) in the private alert channel (DISCORD_CHANNEL_ID). Everyone and everything else
  (other users, other channels, DMs, bots and webhooks, including our own messages) is ignored.
- Big Brother replies in Discord ONLY when William @mentions it (William, Oct 28, final): questions, "yes"/"no" to a
  pending proposal and "Do N thank yous" (plain code, no Claude call) all need the @mention.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# a safe fix (restart) runs only when William's message asks for one
FIX_INTENT = re.compile(r"\b(fix|restart|re-?start|re-?run|kick|bounce|recover|repair)\b", re.I)
YES = re.compile(r"^\s*(yes|yep|yes please|do it|go ahead)\s*[.!]*\s*$", re.I)
NO = re.compile(r"^\s*(no|nope|cancel|don'?t)\s*[.!]*\s*$", re.I)

WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen "
    "eighteen nineteen twenty".split())}
WORDS.update({"thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
              "hundred": 100, "a": 1, "an": 1})
THANKS = re.compile(r"^\s*(?:(?:please\s+)?(?:do|give(?:\s+me)?|say|send(?:\s+me)?)\s+)?(?P<n>[\w\s-]+?)\s+"
                    r"thank[\s-]*you(?:s)?\s*(?:please)?\s*[.!]*\s*$", re.I)
THANKS_CAP = 100


@dataclass
class Msg:
    author_id: int
    channel_id: int
    author_is_bot: bool          # bots and webhooks (nodeguard, phone alert) are never obeyed
    content: str                 # with the bot mention already stripped
    mentions_bot: bool = False
    replies_to_bot: bool = False


@dataclass
class Cfg:
    user_id: int                 # DISCORD_MENTION_USER_ID (William)
    channel_id: int              # DISCORD_CHANNEL_ID (private alert channel)


def classify(m: Msg, cfg: Cfg, has_pending: bool = False) -> str:
    """'ignore' | 'thanks' | 'confirm' | 'cancel' | 'ask'."""
    if m.author_is_bot or m.author_id != cfg.user_id or m.channel_id != cfg.channel_id or not m.mentions_bot:
        return "ignore"
    if parse_thanks(m.content) is not None:
        return "thanks"
    if has_pending and YES.match(m.content):
        return "confirm"
    if has_pending and NO.match(m.content):
        return "cancel"
    if m.content.strip():
        return "ask"
    return "ignore"


def number(s: str) -> int | None:
    s = s.strip().lower()
    if s.isdigit():
        return int(s)
    total = 0
    for w in re.split(r"[\s-]+", s):
        if w == "and":
            continue
        if w not in WORDS:
            return None
        v = WORDS[w]
        total = total * 100 if v == 100 and total else total + v
    return total


def parse_thanks(text: str) -> int | None:
    m = THANKS.match(text or "")
    return None if not m else number(m.group("n"))


def thanks_reply(n: int) -> str:
    if n > THANKS_CAP:
        return " ".join(["thank you"] * THANKS_CAP) + f"\n(capped at {THANKS_CAP}, Discord's 2000-character limit)"
    return " ".join(["thank you"] * n) if n > 0 else "(zero thank yous)"


def fix_intent(text: str) -> bool:
    return bool(FIX_INTENT.search(text or ""))
