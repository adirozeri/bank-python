"""Prompt + persona loading — thin wrappers over the MCP client.

Prompts are owned by the MCP server, named per (workflow call, model): ``intent_gemini``,
``risk_groq``, ``judge_gemini`` for the three system prompts, and ``response`` for the
persona-styled user-facing reply. This module keeps the old call sites (``load_prompt``) stable
while the actual text now comes over the network; ``mcp_client`` derives the per-model prompt
name from the routing config so swapping a model needs no code change.
"""

from . import mcp_client
from .config import settings


def load_prompt(role: str) -> str:
    """Return the system prompt for a role (user_intent / risk_analysis / judge)."""
    return mcp_client.fetch_prompt(role)


def load_response_prompt(persona_key: str | None = None) -> str:
    """Return the persona-styled `response` prompt for user-facing text.

    Defaults to the configured persona; the MCP server maps the key to a tone snippet.
    """
    return mcp_client.fetch_response_prompt(persona_key or settings.default_persona)
