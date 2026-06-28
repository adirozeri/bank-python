"""Prompt + persona loading.

Prompts live per **catalog LLM**: each LLM in llm_models.yaml has a file
``prompts/<llm>.yaml`` mapping the workflow roles (``user_intent``, ``risk_analysis``,
``judge``) to their system prompts. A role's prompt is resolved by following
roles -> llm name -> that LLM's file -> the role's entry. YAML (loaded straight to a dict)
keeps multi-line prompts readable and needs no custom parsing.
"""

from functools import lru_cache

import yaml

from .config import load_llm_config, settings


def _llm_for_role(role: str) -> str:
    """Return the catalog LLM name a role maps to (e.g. 'judge' -> 'llm1')."""
    roles = load_llm_config().get("roles", {})
    name = roles.get(role)
    if name is None:
        raise ValueError(f"Unknown LLM role: {role!r} (known: {sorted(roles)})")
    return name


@lru_cache
def _prompts_for_llm(name: str) -> dict:
    """Load and cache the role->prompt map for a catalog LLM's prompt file."""
    with open(settings.prompts_dir / f"{name}.yaml") as fh:
        return yaml.safe_load(fh) or {}


def load_prompt(role: str) -> str:
    """Return the system prompt for a role, from its catalog LLM's prompt file."""
    name = _llm_for_role(role)
    prompts = _prompts_for_llm(name)
    if role not in prompts:
        raise ValueError(f"Prompt file {name}.yaml has no '{role}' entry")
    return prompts[role].strip()


def load_persona(persona_key: str | None = None) -> str:
    """Return the persona tone snippet for user-facing text.

    The persona key (default from settings) is mapped to a file name via the ``personas``
    section of ``llm_models.yaml``, then read from ``prompts/persona/<name>.md``.
    """
    personas = load_llm_config().get("personas", {})
    key = persona_key or settings.default_persona
    name = personas.get(key) or personas.get("default", "formal")
    return (settings.prompts_dir / "persona" / f"{name}.md").read_text().strip()
