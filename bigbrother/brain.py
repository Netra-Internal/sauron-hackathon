"""One question -> one headless Claude Code run (`claude -p`) with only the bigbrother MCP tools.

Claude has no built-in tools (--tools ""), sees only our MCP server (--strict-mcp-config), may call only mcp__bb__*
(--allowedTools), and loads no user/project settings (--setting-sources ""). Auth is the subscription token
CLAUDE_CODE_OAUTH_TOKEN from the service env (/etc/netra-map.env), never printed."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import uuid

CLAUDE = os.environ.get("BB_CLAUDE_BIN", "/home/netra/.local/bin/claude")
MODEL = os.environ.get("BB_MODEL", "sonnet")
TIMEOUT_S = int(os.environ.get("BB_TIMEOUT_S", "300"))
HERE = os.path.dirname(os.path.abspath(__file__))
PROMPT = open(os.path.join(HERE, "prompt.md")).read()


def mcp_config() -> dict:
    return {"mcpServers": {"bb": {"type": "stdio", "command": sys.executable,
                                  "args": ["-m", "bigbrother.mcp_server"], "cwd": os.path.dirname(HERE)}}}


def build_prompt(question: str, context: str = "", history: list | None = None) -> str:
    parts = []
    if history:
        parts.append("Earlier in this channel (most recent last):\n" +
                     "\n".join(f"- William: {h['q']}\n  You: {h['a']}" for h in history))
    if context:
        parts.append("William is replying to this channel message:\n" + context)
    parts.append("William: " + question)
    return "\n\n".join(parts)


def argv(cfg_path: str) -> list[str]:
    return [CLAUDE, "-p", "--output-format", "json", "--model", MODEL, "--tools", "",
            "--mcp-config", cfg_path, "--strict-mcp-config", "--allowedTools", "mcp__bb",
            "--setting-sources", "", "--no-session-persistence", "--system-prompt", PROMPT]


async def ask(question: str, context: str = "", history: list | None = None) -> dict:
    """-> {"answer", "attachments", "cost_usd", "usage", "turns", "duration_s", "req"}"""
    req = uuid.uuid4().hex[:10]
    with tempfile.TemporaryDirectory(prefix="bb-") as d:
        cfg, att = os.path.join(d, "mcp.json"), os.path.join(d, "attach.txt")
        json.dump(mcp_config(), open(cfg, "w"))
        env = {**os.environ, "BB_REQUEST": question, "BB_ATTACH": att, "BB_REQ_ID": req,
               "PYTHONPATH": os.path.dirname(HERE)}
        p = await asyncio.create_subprocess_exec(*argv(cfg), stdin=asyncio.subprocess.PIPE,
                                                 stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                                                 env=env, cwd=d)
        try:
            out, err = await asyncio.wait_for(p.communicate(build_prompt(question, context, history).encode()), TIMEOUT_S)
        except asyncio.TimeoutError:
            p.kill()
            return {"req": req, "answer": f"(no answer: Claude took longer than {TIMEOUT_S} s)", "attachments": []}
        attachments = [ln.strip() for ln in open(att)] if os.path.exists(att) else []
    try:
        r = json.loads(out)
    except ValueError:
        return {"req": req, "answer": f"(Claude failed, exit {p.returncode}: {err.decode()[-300:]})",
                "attachments": attachments}
    return {"req": req, "answer": r.get("result") or f"(no result: {r.get('subtype')})", "attachments": attachments,
            "cost_usd": r.get("total_cost_usd"), "usage": r.get("usage"), "turns": r.get("num_turns"),
            "duration_s": round((r.get("duration_ms") or 0) / 1000, 1), "is_error": r.get("is_error")}
