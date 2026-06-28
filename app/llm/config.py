"""LLM settings and routing config.

Centralizes the LLM SDK's secrets (provider API keys) and the persona default. The routing
config itself is no longer a local file — it is owned by the MCP server and fetched over the
network via ``mcp_client``; ``load_llm_config`` is now a thin, cached pass-through so existing
callers (``llm_spec_for`` / ``provider_for`` / the prompt layer) are unchanged.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from . import mcp_client


class Settings(BaseSettings):
    """Runtime configuration, populated from environment variables / a local .env file."""

    # extra="ignore" so unrelated env vars (DATABASE_URL, LangSmith, ...) don't error here.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Provider API keys. Field names map to <NAME>_API_KEY env vars (case-insensitive).
    google_api_key: str | None = None
    groq_api_key: str | None = None
    anthropic_api_key: str | None = None

    # MCP server endpoint that serves the routing config + prompts (kept here for visibility;
    # mcp_client reads MCP_SERVER_URL from env directly to avoid an import cycle).
    mcp_server_url: str = "http://localhost:8000/mcp"

    # Default persona key; resolved against the `personas` map served by the MCP server.
    default_persona: str = "default"


@lru_cache
def get_settings() -> Settings:
    """Return the cached Settings singleton (built once per process)."""
    return Settings()


settings = get_settings()


@lru_cache
def load_llm_config() -> dict:
    """Return the LLM routing config (llms catalog + role->llm map + personas).

    Fetched from the MCP server (``llm-config://routing``) and cached for the process.
    """
    return mcp_client.fetch_config()


def llm_spec_for(role: str) -> dict:
    """Resolve a role -> its named catalog LLM -> that LLM's definition dict.

    Two-layer lookup: roles map a role to a catalog name (e.g. judge -> 'llm1'), and `llms`
    holds the actual provider/model/params. Raises ValueError if either lookup fails.
    """
    cfg = load_llm_config()
    roles = cfg.get("roles", {})
    llms = cfg.get("llms", {})
    name = roles.get(role)
    if name is None:
        raise ValueError(f"Unknown LLM role: {role!r} (known: {sorted(roles)})")
    if name not in llms:
        raise ValueError(f"Role {role!r} points at unknown LLM {name!r} (known: {sorted(llms)})")
    return llms[name]


def provider_for(role: str) -> str | None:
    """Return the provider backing a role (via its catalog LLM), or None if unresolved.

    Single source of truth for a role's provider, so callers don't hardcode it.
    """
    try:
        return llm_spec_for(role).get("provider")
    except ValueError:
        return None
