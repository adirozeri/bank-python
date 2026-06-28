"""Tests for the standalone MCP server service (mcp_server/*).

Two layers, both offline (no socket / no real LLM):
  * files.py        - routing + per-model prompt + persona resolution from disk
  * server.py       - the MCP surface, exercised in-process via an in-memory client session
                      (no network), asserting the resource + prompts round-trip correctly.

Also covers the app-side client's prompt-name derivation (role+provider -> prompt name), which
is what keeps model swaps code-free.

Allure annotations drive the report; see docs/allure.md.
"""

import asyncio
import json

import allure
import pytest
from mcp.shared.memory import create_connected_server_and_client_session as connect

from mcp_server import files as mcp_files
from mcp_server import server as mcp_server
from app.llm import mcp_client


# --- server file access ---------------------------------------------------------------


@allure.epic("Unit tests")
@allure.feature("MCP server")
@allure.story("File access")
class TestServerFiles:
    @allure.title("Routing exposes the llms catalog, role map, and personas")
    def test_routing_shape(self):
        cfg = mcp_files.read_routing()
        assert set(cfg["roles"]) == {"user_intent", "risk_analysis", "judge"}
        assert cfg["llms"][cfg["roles"]["risk_analysis"]]["provider"] == "groq"

    @allure.title("Per-model prompt files load by name")
    def test_read_prompt(self):
        assert mcp_files.read_prompt("judge_gemini").startswith("You are an independent")
        with pytest.raises(ValueError):
            mcp_files.read_prompt("nope_model")

    @allure.title("Persona key maps to its tone snippet, with a default fallback")
    def test_resolve_persona(self):
        assert mcp_files.resolve_persona("young").lower().startswith("use a friendly")
        assert mcp_files.resolve_persona(None).lower().startswith("use a professional")


# --- app client prompt-name derivation ------------------------------------------------


@allure.epic("Unit tests")
@allure.feature("MCP server")
@allure.story("Per-model prompt naming")
class TestPromptNaming:
    @allure.title("role + provider resolves to the per-model prompt name")
    def test_names(self):
        # mock_mcp (autouse) points fetch_config at the real routing file.
        assert mcp_client._prompt_name_for("user_intent") == "intent_gemini"
        assert mcp_client._prompt_name_for("risk_analysis") == "risk_groq"
        assert mcp_client._prompt_name_for("judge") == "judge_gemini"


# --- server MCP surface (in-memory, no socket) ----------------------------------------


def _run(coro):
    return asyncio.run(coro)


@allure.epic("Unit tests")
@allure.feature("MCP server")
@allure.story("MCP surface round-trip")
class TestServerSurface:
    @allure.title("routing resource round-trips over an in-memory MCP session")
    def test_resource_roundtrip(self):
        async def go():
            async with connect(mcp_server.mcp._mcp_server) as client:
                res = await client.read_resource("llm-config://routing")
                return json.loads(res.contents[0].text)

        routing = _run(go())
        assert routing["roles"]["judge"] in routing["llms"]

    @allure.title("all four prompts are served and non-empty; response carries persona")
    def test_prompts_roundtrip(self):
        async def go():
            async with connect(mcp_server.mcp._mcp_server) as client:
                names = [p.name for p in (await client.list_prompts()).prompts]
                texts = {}
                for name in ("intent_gemini", "risk_groq", "judge_gemini"):
                    gp = await client.get_prompt(name, {})
                    texts[name] = gp.messages[0].content.text
                resp = await client.get_prompt("response", {"persona_key": "young"})
                texts["response"] = resp.messages[0].content.text
                return names, texts

        names, texts = _run(go())
        assert {"intent_gemini", "risk_groq", "judge_gemini", "response"} <= set(names)
        assert all(t.strip() for t in texts.values())
        assert "friendly" in texts["response"].lower()
