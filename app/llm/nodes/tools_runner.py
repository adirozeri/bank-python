"""Tool-dispatch node.

Runs the read-only tools the intent model requested and returns their rows as ToolMessage
content (this is how data reaches the agent — it is never exposed to the API caller). A
create_transfer call is NOT executed here — it is captured as a pending transfer so the graph
can route it through the risk -> judge -> confirm subflow, which answers that tool call later.
"""

import json

from langchain_core.messages import ToolMessage

from ..state import State
from ..tools import READ_HELPERS


def run_tools(state: State) -> dict:
    """Execute read tools; stash any create_transfer call as state['transfer']."""
    last = state["messages"][-1]
    tool_messages: list = []
    transfer: dict | None = None

    for call in last.tool_calls:
        name = call["name"]
        if name == "create_transfer":
            # Defer to the gated subflow; remember which call to answer.
            args = call["args"]
            transfer = {
                "from_account": args["from_account"],
                "to_account": args["to_account"],
                "amount": args["amount"],
                "currency": args.get("currency", "USD"),
                "tool_call_id": call["id"],
            }
            continue

        # Only rows are needed (to feed the agent); the SQL is intentionally discarded.
        _, rows = READ_HELPERS[name](account_id=call["args"].get("account_id"))
        tool_messages.append(
            ToolMessage(content=json.dumps(rows, default=str), tool_call_id=call["id"])
        )

    out: dict = {"messages": tool_messages}
    if transfer:
        out["transfer"] = transfer
    return out


def route_after_tools(state: State) -> str:
    """Go to the risk/judge subflow if a transfer is pending, otherwise back to the agent."""
    return "risk_analysis" if state.get("transfer") else "agent"
