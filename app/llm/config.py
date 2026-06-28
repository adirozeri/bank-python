"""LLM settings and routing config.

Centralizes the LLM SDK's secrets and file locations (previously scattered ``os.getenv``
calls), plus loading of the declarative routing file ``config/llm_models.yaml``. Lives in
the llm package because every value here is LLM-specific; import the module-level
``settings`` singleton and the ``load_llm_config`` helper where needed.
"""

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

# The llm package directory (app/llm). Prompts and the routing YAML live alongside the
# code so the package is self-contained.
PACKAGE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    """Runtime configuration, populated from environment variables / a local .env file."""

    # extra="ignore" so unrelated env vars (DATABASE_URL, LangSmith, ...) don't error here.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Provider API keys. Field names map to <NAME>_API_KEY env vars (case-insensitive).
    google_api_key: str | None = None
    groq_api_key: str | None = None
    anthropic_api_key: str | None = None

    # Locations of the LLM routing file and the prompt templates (inside the package).
    llm_models_path: Path = PACKAGE_DIR / "llm_models.yaml"
    prompts_dir: Path = PACKAGE_DIR / "prompts"

    # Default persona key; resolved against the `personas` map in llm_models.yaml.
    default_persona: str = "default"


@lru_cache
def get_settings() -> Settings:
    """Return the cached Settings singleton (built once per process)."""
    return Settings()


settings = get_settings()


@lru_cache
def load_llm_config() -> dict:
    """Load and cache the LLM routing file (llms catalog + role->llm map + personas)."""
    with open(settings.llm_models_path) as fh:
        return yaml.safe_load(fh)


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
