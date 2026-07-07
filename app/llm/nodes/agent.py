"""Call 1 — User Intent node.

Drives the conversation: the intent model (Gemini) either replies in natural language or
emits tool calls (reads or a transfer request). The system prompt is loaded from a file and
combined with the configured persona so user-facing text matches the desired tone.
"""

import time

from langchain_core.messages import SystemMessage, AIMessage

from ..factory import get_llm, trace_config
from ..prompts import load_prompt, load_response_prompt
from ..state import State
from ..tools import TOOLS


def agent(state: State) -> dict:
    """Invoke the intent model with the tools bound; return its message."""
    model = get_llm(role="user_intent").bind_tools(TOOLS)
    system = f"{load_prompt(role='user_intent')}\n\n{load_response_prompt()}"
    messages = [SystemMessage(content=system), *state["messages"]]
    # Two transient Groq failures are worth retrying: llama-3.3 sometimes emits malformed
    # tool-call syntax (400 `tool_use_failed`) and free-tier bursts hit rate limits (429).
    # Both usually succeed on retry — rate limits after a short pause. Anything else re-raises.
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            response = model.invoke(messages, config=trace_config("user_intent", "UserIntent"))
            return {"messages": [response]}
        except Exception as exc:
            text = str(exc).lower()
            if "tool_use_failed" in text:
                last_exc = exc
            elif "rate limit" in text or "429" in text:
                last_exc = exc
                time.sleep(2 * (attempt + 1))
            else:
                raise
    raise last_exc
