"""MCP **client** for the LangGraph microservice.

The LangGraph service no longer owns the config/prompt files — it fetches them from the MCP
server over the network (Streamable HTTP). This module is the only place that talks MCP; the
rest of the package keeps calling the same ``config``/``prompts`` helpers.

Two problems it solves:
  * **sync over async** — the MCP client is async, but the graph nodes are sync and may run
    inside a live event loop (FastAPI / ``langgraph dev``), so ``asyncio.run`` would explode.
    We keep a dedicated background event loop in its own thread and submit coroutines to it.
  * **chattiness** — every public fetch is ``lru_cache``d, so each resource/role/persona hits
    the network at most once per process (mirrors the old in-process file caches).
"""

import asyncio
import json
import os
import threading
from functools import lru_cache

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


def _server_url() -> str:
    """MCP server endpoint. Read from env directly (not config.settings) to avoid an import
    cycle, since config.py depends on this module."""
    return os.getenv("MCP_SERVER_URL", "http://localhost:8000/mcp")


# --- background event loop (one per process) ------------------------------------------------
_loop: asyncio.AbstractEventLoop | None = None
_loop_lock = threading.Lock()


def _get_loop() -> asyncio.AbstractEventLoop:
    """Lazily start a daemon thread running a private event loop for all MCP I/O."""
    global _loop
    if _loop is None:
        with _loop_lock:
            if _loop is None:
                loop = asyncio.new_event_loop()
                threading.Thread(target=loop.run_forever, daemon=True, name="mcp-client-loop").start()
                _loop = loop
    return _loop


def _run(coro):
    """Run an MCP coroutine on the background loop and block for its result."""
    return asyncio.run_coroutine_threadsafe(coro, _get_loop()).result()


async def _with_session(fn):
    """Open a Streamable-HTTP session, initialize it, run ``fn(session)``, then tear down."""
    async with streamable_http_client(_server_url()) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await fn(session)


def _text(messages) -> str:
    """Flatten a prompt's messages into a single system-prompt string."""
    parts = [getattr(m.content, "text", str(m.content)) for m in messages]
    return "\n\n".join(parts).strip()


# --- config (routing) -----------------------------------------------------------------------
@lru_cache
def fetch_config() -> dict:
    """Fetch the ``llm-config://routing`` resource (llms catalog + roles + personas)."""

    async def go(s):
        res = await s.read_resource("llm-config://routing")
        return json.loads(res.contents[0].text)

    return _run(_with_session(go))


# --- prompts --------------------------------------------------------------------------------
# Per-model prompt naming: the server hosts one prompt per (call, model family), e.g.
# `judge_gemini`. The client derives the name from the role's provider in the routing config,
# so repointing a role in llm_models.yaml selects that model's prompt with no code change.
_ROLE_SHORT = {"user_intent": "intent", "risk_analysis": "risk", "judge": "judge"}
_PROVIDER_FAMILY = {"google": "gemini", "groq": "groq", "anthropic": "claude"}


def _prompt_name_for(role: str) -> str:
    """Resolve role -> per-model prompt name (e.g. judge + google -> 'judge_gemini')."""
    cfg = fetch_config()
    llm_name = cfg.get("roles", {}).get(role)
    provider = cfg.get("llms", {}).get(llm_name, {}).get("provider")
    short = _ROLE_SHORT.get(role, role)
    family = _PROVIDER_FAMILY.get(provider, provider)
    return f"{short}_{family}"


@lru_cache
def fetch_prompt(role: str) -> str:
    """Fetch a role's system prompt by its per-model name (Call 1/2/3 system prompts)."""
    name = _prompt_name_for(role)

    async def go(s):
        gp = await s.get_prompt(name, {})
        return _text(gp.messages)

    return _run(_with_session(go))


@lru_cache
def fetch_response_prompt(persona_key: str | None = None) -> str:
    """Fetch the persona-styled `response` prompt for user-facing text."""
    args = {"persona_key": persona_key} if persona_key else {}

    async def go(s):
        gp = await s.get_prompt("response", args)
        return _text(gp.messages)

    return _run(_with_session(go))
