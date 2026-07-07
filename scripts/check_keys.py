"""Verify each LLM provider API key is accepted (HTTP 200), without spending tokens.

For every provider that has a key set in the environment / .env, this makes one cheap
authenticated GET (usually the `/models` list, or the key-info endpoint) and prints the status.
Providers with no key are skipped. Ollama is checked locally (no key).

Run:  python scripts/check_keys.py
"""

import os

import requests
from dotenv import load_dotenv

load_dotenv()

TIMEOUT = 15


def _bearer(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


# name, env var, url, headers(key), params(key)
PROVIDERS = [
    ("anthropic", "ANTHROPIC_API_KEY", "https://api.anthropic.com/v1/models",
     lambda k: {"x-api-key": k, "anthropic-version": "2023-06-01"}, lambda k: {}),
    ("google", "GOOGLE_API_KEY", "https://generativelanguage.googleapis.com/v1beta/models",
     lambda k: {}, lambda k: {"key": k}),
    ("groq", "GROQ_API_KEY", "https://api.groq.com/openai/v1/models", _bearer, lambda k: {}),
    ("cerebras", "CEREBRAS_API_KEY", "https://api.cerebras.ai/v1/models", _bearer, lambda k: {}),
    ("openrouter", "OPENROUTER_API_KEY", "https://openrouter.ai/api/v1/key", _bearer, lambda k: {}),
    ("mistral", "MISTRAL_API_KEY", "https://api.mistral.ai/v1/models", _bearer, lambda k: {}),
    ("openai", "OPENAI_API_KEY", "https://api.openai.com/v1/models", _bearer, lambda k: {}),
]


def main() -> None:
    print("Provider key check (authenticated GET — no tokens spent):")
    for name, env, url, headers, params in PROVIDERS:
        key = os.getenv(env)
        if not key:
            print(f"  SKIP {name:11s} (no {env})")
            continue
        try:
            r = requests.get(url, headers=headers(key), params=params(key), timeout=TIMEOUT)
            tag = "OK  " if r.status_code == 200 else "FAIL"
            print(f"  {tag} {name:11s} HTTP {r.status_code}")
        except requests.RequestException as exc:
            print(f"  ERR  {name:11s} {type(exc).__name__}")

    # Ollama: local daemon, no key.
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=5)
        tag = "OK  " if r.status_code == 200 else "FAIL"
        print(f"  {tag} ollama      HTTP {r.status_code}")
    except requests.RequestException:
        print("  DOWN ollama      (ollama serve not running)")


if __name__ == "__main__":
    main()
