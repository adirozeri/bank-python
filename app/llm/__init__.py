"""Public API for the LLM SDK.

Keeps the import path stable: ``from app import llm; llm.ask(...)`` still works after the
split from a single module into this package. Only ``ask`` is part of the public surface.
"""

from .graph import ask

__all__ = ["ask"]
