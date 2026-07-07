"""File access for the MCP server (no MCP imports).

Single source of truth for reading the relocated config + prompt files that this service now
owns. Kept separate from ``server.py`` so the file/parse logic can be unit-tested directly and
the MCP layer stays a thin wrapper.
"""

import os
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
        cfg = yaml.safe_load(fh)
    _apply_selected_roles(cfg)
    return cfg


def _apply_selected_roles(cfg: dict) -> None:
    """Resolve the active ``roles`` map from the named role configurations.

    New schema: ``role_configs: {name: {role: llm}}`` plus ``selected_roles_configuration: name``.
    This sets ``cfg['roles']`` to the selected configuration so every downstream consumer (which
    reads ``cfg['roles']``) is unchanged. The env var ``SELECTED_ROLES_CONFIGURATION`` overrides
    the YAML's selector, so a config can be switched without editing (or rebuilding) the file. A
    legacy top-level ``roles:`` with no ``role_configs`` is left as-is.
    """
    configs = cfg.get("role_configs")
    if not configs:
        return  # legacy single-map form: cfg already has `roles`
    selected = os.getenv("SELECTED_ROLES_CONFIGURATION") or cfg.get("selected_roles_configuration")
    if selected not in configs:
        raise ValueError(
            f"selected_roles_configuration {selected!r} is not defined in role_configs "
            f"(available: {sorted(configs)})"
        )
    cfg["roles"] = configs[selected]


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
