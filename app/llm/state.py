"""Graph state definition for the agentic workflow."""

from typing import Annotated, NotRequired, TypedDict, TypeVar

from langgraph.graph.message import add_messages

T = TypeVar("T")


def require(value: T | None, name: str) -> T:
    """Assert a NotRequired state value is present and narrow its type for the checker.

    Some nodes are only reached once an upstream node has populated a field (e.g. the
    transfer subflow always has state['transfer']). This documents that graph invariant and
    turns a silent KeyError into a clear error if the invariant is ever violated.
    """
    if value is None:
        raise RuntimeError(f"expected state key {name!r} to be set at this node")
    return value


class State(TypedDict):
    """Shared state threaded through the LangGraph nodes.

    Only ``messages`` is required as graph input; the rest are populated by nodes during a
    run, so they are NotRequired (absent on the initial ``{"messages": [...]}``).
    """

    # Conversation history; the add_messages reducer appends new messages each step.
    # Tool results travel here as ToolMessage content (this is how rows reach the agent);
    # they are never exposed in the /ask response.
    messages: Annotated[list, add_messages]

    # Pending transfer captured from a create_transfer tool call: from/to/amount/currency
    # plus the originating tool_call_id (so the subflow can answer that exact call).
    transfer: NotRequired[dict]

    # Call 2 output (RiskAssessment.model_dump()): {risk_level, reason}.
    risk: NotRequired[dict]

    # Call 3 output (JudgeVerdict.model_dump()): {approval, reason}.
    judge: NotRequired[dict]
