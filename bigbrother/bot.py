"""Big Brother Discord bot (gateway). Who it obeys is decided by policy.classify; what it can change by actions.run.

Env (root-only /etc/netra-bigbrother.env): DISCORD_BOT_TOKEN, DISCORD_CHANNEL_ID, DISCORD_MENTION_USER_ID.
Claude's token comes from /etc/netra-map.env (CLAUDE_CODE_OAUTH_TOKEN)."""
from __future__ import annotations

import asyncio
import os
import re

import discord

from . import actions, brain, log, policy

CFG = policy.Cfg(user_id=int(os.environ["DISCORD_MENTION_USER_ID"]), channel_id=int(os.environ["DISCORD_CHANNEL_ID"]))

intents = discord.Intents.none()
intents.guilds = True
intents.guild_messages = True
# Message Content Intent (privileged): without it Discord still sends the text of messages that @mention the bot, so
# everything works with an @mention; a bare "yes"/"no" needs the intent (BB_MESSAGE_CONTENT=1 once enabled in the portal).
intents.message_content = os.environ.get("BB_MESSAGE_CONTENT") == "1"
client = discord.Client(intents=intents, allowed_mentions=discord.AllowedMentions.none())
busy = asyncio.Lock()


def chunks(text: str, n: int = 1900) -> list[str]:
    out = []
    while text:
        cut = text.rfind("\n", 0, n) if len(text) > n else len(text)
        cut = cut if cut > n // 2 else min(n, len(text))
        out.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return out or ["(empty)"]


async def send(msg: discord.Message, text: str, files: list[str] | None = None) -> None:
    parts = chunks(text)
    for i, part in enumerate(parts):
        fs = [discord.File(f) for f in (files or []) if os.path.exists(f)] if i == len(parts) - 1 else []
        await msg.reply(part, files=fs, mention_author=False) if i == 0 else await msg.channel.send(part, files=fs)


def cost_line(r: dict) -> str:
    if r.get("cost_usd") is None:
        return ""
    u = r.get("usage") or {}
    toks = (u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0))
    return (f"\n-# Claude {brain.MODEL}: {r.get('turns')} turns, {r.get('duration_s')} s, {toks:,} in / "
            f"{u.get('output_tokens', 0):,} out tokens, ${r['cost_usd']:.3f} API-equivalent (billed to the subscription)")


@client.event
async def on_ready():
    ch = client.get_channel(CFG.channel_id)
    log.write({"kind": "ready", "user": str(client.user), "guilds": [g.name for g in client.guilds],
               "channel_visible": ch is not None,
               "can_send": bool(ch and ch.permissions_for(ch.guild.me).send_messages)})


@client.event
async def on_message(m: discord.Message):
    me = client.user
    ref = m.reference.resolved if m.reference and isinstance(m.reference.resolved, discord.Message) else None
    text = re.sub(rf"<@!?{me.id}>", "", m.content).strip()
    msg = policy.Msg(author_id=m.author.id, channel_id=m.channel.id, author_is_bot=m.author.bot or m.webhook_id is not None,
                     content=text, mentions_bot=me in m.mentions, replies_to_bot=bool(ref and ref.author.id == me.id))
    kind = policy.classify(msg, CFG, has_pending=actions.pending() is not None)
    if kind == "ignore":
        return
    log.write({"kind": "question", "type": kind, "msg_id": m.id, "text": text})

    if kind == "thanks":
        await send(m, policy.thanks_reply(policy.parse_thanks(text)))
        return
    if kind == "cancel":
        p = actions.take_pending()
        log.write({"kind": "cancel", "pending": p})
        await send(m, f"Cancelled: `{p['action']}` was not run." if p else "Nothing pending.")
        return
    if kind == "confirm":
        p = actions.take_pending()
        if not p:
            await send(m, "Nothing pending (proposals expire after 10 min).")
            return
        async with m.channel.typing():
            res = await asyncio.to_thread(actions.run, p["action"], request_text=text, confirmed=True)
        log.write({"kind": "fix", "confirmed": True, "pending": p, "result": res})
        status = "done" if res.get("ok") else ("REFUSED: " + res["refused"] if "refused" in res else f"FAILED (rc {res.get('rc')})")
        await send(m, f"`{p['action']}` ({p['what']}): {status}\n```\n{(res.get('out', '') + res.get('err', ''))[-1500:]}\n```")
        return

    if busy.locked():
        await m.add_reaction("⏳")
    async with busy:
        context = ""
        if ref and ref.author.id != me.id:
            context = f"[{ref.created_at.isoformat(timespec='seconds')}] {ref.author.display_name}: {ref.content}" + \
                      "".join(f"\n(embed) {e.title or ''} {e.description or ''}" for e in ref.embeds)
        async with m.channel.typing():
            before = actions.pending()
            r = await brain.ask(text, context, log.recent_answers())
            p = actions.pending()
        log.write({"kind": "answer", "req": r["req"], "question": text, "context": context[:2000], "answer": r["answer"],
                   "cost_usd": r.get("cost_usd"), "usage": r.get("usage"), "turns": r.get("turns"),
                   "duration_s": r.get("duration_s")})
        extra = ""
        if p and p != before:
            extra = f"\n**Proposed:** `{p['action']}`: {p['what']}. Reply **yes** within 10 min to run it, or **no**."
        await send(m, r["answer"] + extra + cost_line(r), r.get("attachments"))


def main() -> None:
    client.run(os.environ["DISCORD_BOT_TOKEN"])


if __name__ == "__main__":
    main()
