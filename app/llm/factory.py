"""LLM abstraction layer: turn a workflow *role* into a configured chat model.

Two layers:
  * `get_llm(role)` resolves role -> catalog LLM -> a NORMALIZED spec (see llm_models.yaml),
    then dispatches to a per-provider **builder**.
  * the builders translate the normalized, provider-agnostic keys into each SDK's actual
    constructor kwargs. This keeps the YAML uniform (e.g. one `thoughts: true` flag) while
    each provider exposes "reasoning" differently.

Normalized keys understood here: provider, model, temperature, max_tokens, thoughts (bool),
thoughts_budget (int, optional). Anything else is passed through unchanged.

Supported providers: google (Gemini), groq (Llama/reasoning models), anthropic (Claude).
"""

from functools import lru_cache

from langchain_core.language_models import BaseChatModel

from .config import llm_spec_for, settings

# Default token budget for "thinking" when a spec enables thoughts without its own budget.
_DEFAULT_THOUGHTS_BUDGET = 1024


def _build_google(spec: dict, *, thoughts: bool, budget: int | None) -> BaseChatModel:
    """Gemini: `thoughts` -> include_thoughts (+ optional thinking_budget)."""
    from langchain_google_genai import ChatGoogleGenerativeAI

    kwargs = dict(spec)
    if settings.google_api_key:
        kwargs["google_api_key"] = settings.google_api_key
    if thoughts:
        kwargs["include_thoughts"] = True
        if budget is not None:
            kwargs["thinking_budget"] = budget
    return ChatGoogleGenerativeAI(**kwargs)


def _build_groq(spec: dict, *, thoughts: bool, budget: int | None) -> BaseChatModel:
    """Groq: `thoughts` -> reasoning_format='parsed' (only effective on reasoning models)."""
    from langchain_groq import ChatGroq

    kwargs = dict(spec)
    if settings.groq_api_key:
        kwargs["api_key"] = settings.groq_api_key
    if thoughts:
        # Groq surfaces reasoning only on reasoning-capable models (e.g. gpt-oss / qwen3);
        # on a plain chat model like llama-3.3 this has no effect / may be rejected.
        kwargs["reasoning_format"] = "parsed"
    return ChatGroq(**kwargs)


def _build_anthropic(spec: dict, *, thoughts: bool, budget: int | None) -> BaseChatModel:
    """Claude: `thoughts` -> thinking={enabled, budget}; requires temperature=1 and
    max_tokens > budget."""
    from langchain_anthropic import ChatAnthropic

    kwargs = dict(spec)
    if settings.anthropic_api_key:
        kwargs["api_key"] = settings.anthropic_api_key
    if thoughts:
        b = budget or _DEFAULT_THOUGHTS_BUDGET
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": b}
        kwargs["temperature"] = 1  # Anthropic requires temperature=1 when thinking is on
        # max_tokens must exceed the thinking budget; bump it if needed.
        kwargs["max_tokens"] = max(kwargs.get("max_tokens") or 0, b + _DEFAULT_THOUGHTS_BUDGET)
    return ChatAnthropic(**kwargs)


# The translation layer: provider -> builder.
_BUILDERS = {
    "google": _build_google,
    "groq": _build_groq,
    "anthropic": _build_anthropic,
}


@lru_cache
def get_llm(role: str) -> BaseChatModel:
    """Resolve a role to its configured chat model via the catalog + provider builder."""
    spec = dict(llm_spec_for(role))  # raises ValueError on an unknown role/llm
    provider = spec.pop("provider", None)
    thoughts = bool(spec.pop("thoughts", False))
    budget = spec.pop("thoughts_budget", None)

    builder = _BUILDERS.get(provider)
    if builder is None:
        raise ValueError(f"Unsupported provider {provider!r} for role {role!r}")
    return builder(spec, thoughts=thoughts, budget=budget)
