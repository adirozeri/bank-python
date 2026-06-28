"""FastMCP server exposing the LLM config + prompts over Streamable HTTP.

Primitives served:
  * Resource ``llm-config://routing`` — the full routing config (llms catalog + roles +
    personas) as JSON; the client needs it to build the actual LLMs (provider/model/params)
    and to derive per-model prompt names.
  * Prompts named per (workflow call, model) — ``intent_gemini``, ``risk_groq``,
    ``judge_gemini`` — plus ``response`` for the persona-styled user-facing reply. Naming
    prompts per model satisfies the "tailored prompt per model" requirement.
  * A few read-only tools for inspection / ops.

Run as its own process:  ``python -m mcp_server.server`` (transport=streamable-http).
"""

import json
import os

from mcp.server.fastmcp import FastMCP

from . import files

# Host/port come from the environment so the same image works locally and in compose.
HOST = os.getenv("MCP_SERVER_HOST", "0.0.0.0")
PORT = int(os.getenv("MCP_SERVER_PORT", "8000"))

mcp = FastMCP("bank-llm-config", host=HOST, port=PORT)


# --- Resource: the routing config the client builds LLMs from -------------------------------
@mcp.resource("llm-config://routing")
def routing() -> str:
    """Return the routing config (llms catalog + role->llm map + personas) as JSON."""
    return json.dumps(files.read_routing())


# --- Prompts: one per (call, model); ``response`` carries persona tone -----------------------
@mcp.prompt()
def intent_gemini() -> str:
    """Call 1 — User Intent system prompt, tailored for Gemini."""
    return files.read_prompt("intent_gemini")


@mcp.prompt()
def risk_groq() -> str:
    """Call 2 — Risk Analysis system prompt, tailored for Groq."""
    return files.read_prompt("risk_groq")


@mcp.prompt()
def judge_gemini() -> str:
    """Call 3 — Judge system prompt, tailored for Gemini (differs from a Groq judge)."""
    return files.read_prompt("judge_gemini")


@mcp.prompt()
def response(persona_key: str | None = None) -> str:
    """User-facing reply guidance, styled by the active persona (young->casual, ...)."""
    base = files.read_prompt("response")
    persona = files.resolve_persona(persona_key)
    return f"{base}\n\n{persona}"


# --- Inspection / ops tools -----------------------------------------------------------------
@mcp.tool()
def list_roles() -> dict:
    """Return the configured roles and the catalog llm each maps to."""
    return files.read_routing().get("roles", {})


@mcp.tool()
def list_personas() -> dict:
    """Return the available persona keys and their backing files."""
    return files.read_routing().get("personas", {})


@mcp.tool()
def reload_config() -> str:
    """Clear the server-side file caches so edited config/prompts are picked up live."""
    files.reload()
    return "reloaded"


def main() -> None:
    """Entry point — serve over Streamable HTTP on MCP_SERVER_HOST:MCP_SERVER_PORT."""
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
