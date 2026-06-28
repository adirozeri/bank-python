"""Call 1 — User Intent node.

Drives the conversation: the intent model (Gemini) either replies in natural language or
emits tool calls (reads or a transfer request). The system prompt is loaded from a file and
combined with the configured persona so user-facing text matches the desired tone.
"""

from langchain_core.messages import SystemMessage, AIMessage

from ..factory import get_llm, trace_config
from ..prompts import load_persona, load_prompt
from ..state import State
from ..tools import TOOLS


def agent(state: State) -> dict:
    """Invoke the intent model with the tools bound; return its message."""
    model = get_llm(role="user_intent").bind_tools(TOOLS)
    system = f"{load_prompt(role='user_intent')}\n\n{load_persona()}"
    response = model.invoke(
        [SystemMessage(content=system), *state["messages"]],
        config=trace_config("user_intent", "UserIntent"),
    )
    return {"messages": [response]}
