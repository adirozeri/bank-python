"""LLM abstraction layer: turn a workflow *role* into a configured chat model.

Two layers:
  * `get_llm(role)` resolves role -> catalog LLM -> a NORMALIZED spec (see llm_models.yaml),
    then dispatches to a per-provider **builder**.
  * the builders translate the normalized, provider-agnostic keys into each SDK's actual
    constructor kwargs.

Normalized keys understood here: provider, model, temperature, max_tokens. Anything else is
passed through unchanged. NOTE: `thoughts` / `thoughts_budget` may still appear in the YAML but
are intentionally ignored — extended thinking/reasoning is disabled for all API calls (it spends
extra output-priced tokens for little gain here), so those keys are dropped, never sent.

Supported providers: google (Gemini), groq (Llama), anthropic (Claude), openai (OpenAI-compatible
endpoints incl. OpenRouter via base_url), cerebras, mistralai, ollama (local).
"""

from functools import lru_cache

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableConfig

from .config import llm_spec_for, provider_for, settings


def trace_config(role: str, run_name: str) -> RunnableConfig:
    """Build the LangSmith run config for a node call.

    Tags are derived from the live config (`provider_for(role)`) — never hardcoded — so they
    always reflect the model a role actually uses, even after the YAML is repointed.
    """
    return {"run_name": run_name, "tags": [f"role:{role}", f"provider:{provider_for(role)}"]}


def _build_google(spec: dict) -> BaseChatModel:
    """Gemini."""
    from langchain_google_genai import ChatGoogleGenerativeAI

    kwargs = dict(spec)
    if settings.google_api_key:
        kwargs["google_api_key"] = settings.google_api_key
    return ChatGoogleGenerativeAI(**kwargs)


def _build_groq(spec: dict) -> BaseChatModel:
    """Groq."""
    from langchain_groq import ChatGroq

    kwargs = dict(spec)
    if settings.groq_api_key:
        kwargs["api_key"] = settings.groq_api_key
    return ChatGroq(**kwargs)


def _build_anthropic(spec: dict) -> BaseChatModel:
    """Claude."""
    from langchain_anthropic import ChatAnthropic

    kwargs = dict(spec)
    if settings.anthropic_api_key:
        kwargs["api_key"] = settings.anthropic_api_key
    return ChatAnthropic(**kwargs)


def _build_openai(spec: dict) -> BaseChatModel:
    """OpenAI-compatible endpoints. Used here for OpenRouter via the spec's `base_url`."""
    from langchain_openai import ChatOpenAI

    kwargs = dict(spec)
    key = settings.openrouter_api_key or settings.openai_api_key
    if key:
        kwargs["api_key"] = key
    return ChatOpenAI(**kwargs)


def _build_cerebras(spec: dict) -> BaseChatModel:
    """Cerebras."""
    from langchain_cerebras import ChatCerebras

    kwargs = dict(spec)
    if settings.cerebras_api_key:
        kwargs["api_key"] = settings.cerebras_api_key
    return ChatCerebras(**kwargs)


def _build_mistral(spec: dict) -> BaseChatModel:
    """Mistral La Plateforme."""
    from langchain_mistralai import ChatMistralAI

    kwargs = dict(spec)
    if settings.mistral_api_key:
        kwargs["api_key"] = settings.mistral_api_key
    return ChatMistralAI(**kwargs)


def _build_ollama(spec: dict) -> BaseChatModel:
    """Local Ollama server (no API key; reaches the daemon at the spec's `base_url`)."""
    from langchain_ollama import ChatOllama

    return ChatOllama(**dict(spec))


# The translation layer: provider -> builder.
_BUILDERS = {
    "google": _build_google,
    "groq": _build_groq,
    "anthropic": _build_anthropic,
    "openai": _build_openai,
    "cerebras": _build_cerebras,
    "mistralai": _build_mistral,
    "ollama": _build_ollama,
}


@lru_cache
def get_llm(role: str) -> BaseChatModel:
    """Resolve a role to its configured chat model via the catalog + provider builder."""
    spec = dict(llm_spec_for(role))  # raises ValueError on an unknown role/llm
    provider = spec.pop("provider", None)
    # Accepted in the YAML for compatibility but no longer used: thinking is disabled, so drop
    # these keys here rather than pass them on to the SDK constructors.
    spec.pop("thoughts", None)
    spec.pop("thoughts_budget", None)

    builder = _BUILDERS.get(provider)
    if builder is None:
        raise ValueError(f"Unsupported provider {provider!r} for role {role!r}")
    return builder(spec)
