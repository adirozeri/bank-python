"""File access for the MCP server (no MCP imports).

Single source of truth for reading the relocated config + prompt files that this service now
owns. Kept separate from ``server.py`` so the file/parse logic can be unit-tested directly and
the MCP layer stays a thin wrapper.
"""

from functools import lru_cache
from pathlib import Path

import yaml

# Files live under mcp_server/config/. They moved here out of app/llm/ — this service is now
# their sole owner.
CONFIG_DIR = Path(__file__).resolve().parent / "config"
ROUTING_PATH = CONFIG_DIR / "llm_models.yaml"
PROMPTS_DIR = CONFIG_DIR / "prompts"


@lru_cache
def read_routing() -> dict:
    """Load and cache the routing file (llms catalog + role->llm map + personas)."""
    with open(ROUTING_PATH) as fh:
        return yaml.safe_load(fh)


@lru_cache
def read_prompt(name: str) -> str:
    """Return a named prompt's text from ``prompts/<name>.md`` (e.g. 'risk_groq')."""
    path = PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise ValueError(f"Unknown prompt {name!r} (no file {path.name})")
    return path.read_text().strip()


def resolve_persona(persona_key: str | None = None) -> str:
    """Return the persona tone snippet for user-facing text.

    The persona key is mapped to a file name via the ``personas`` section of the routing file,
    then read from ``prompts/persona/<name>.md``. Falls back to the configured default.
    """
    personas = read_routing().get("personas", {})
    key = persona_key or "default"
    name = personas.get(key) or personas.get("default", "formal")
    return (PROMPTS_DIR / "persona" / f"{name}.md").read_text().strip()


def reload() -> None:
    """Clear the file caches so edited config/prompt files are picked up without a restart."""
    read_routing.cache_clear()
    read_prompt.cache_clear()
