"""Assemble and run the agentic workflow.

Wires the nodes into a LangGraph state machine and exposes ``ask()`` — the single entry
point used by the API. Graph shape:

    agent ──(tool calls)──▶ tools ──(transfer?)──▶ risk_analysis ▶ judge ▶ decision
      ▲                       │                                                │
      └───────────────────────┴──────────(no transfer / denied / executed)────┘

Read tools loop straight back to the agent; a transfer is gated through risk -> judge ->
decision, and (if approved) confirmed + executed before returning to the agent for the
final natural-language answer.
"""

from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from .nodes import (
    agent,
    decision_gate,
    judge,
    risk_analysis,
    route_after_decision,
    route_after_tools,
    run_tools,
    transfer,
)
from .state import State

# Per-thread conversation memory. In-process only: history doesn't survive a server
# restart (fine for Phase 1).
def should_continue(state: State) -> str:
    """After the agent: run tools if it requested any, otherwise end the turn."""
    return "tools" if getattr(state["messages"][-1], "tool_calls", None) else END


def _build_graph() -> StateGraph:
    """Construct the StateGraph (nodes + edges), left uncompiled so callers choose how to
    compile it (with or without a checkpointer)."""
    graph = StateGraph(State)
    graph.add_node("agent", agent)
    graph.add_node("tools", run_tools)
    graph.add_node("risk_analysis", risk_analysis)
    graph.add_node("judge", judge)
    graph.add_node("decision", decision_gate)
    graph.add_node("transfer", transfer)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    graph.add_conditional_edges(
        "tools", route_after_tools, {"risk_analysis": "risk_analysis", "agent": "agent"}
    )
    graph.add_edge("risk_analysis", "judge")
    graph.add_edge("judge", "decision")
    graph.add_conditional_edges(
        "decision", route_after_decision, {"transfer": "transfer", "agent": "agent"}
    )
    graph.add_edge("transfer", "agent")
    return graph


# In-process graph used by ask(): MemorySaver gives per-thread conversation memory within
# this process (fine for Phase 1). Not used when served via the LangGraph platform.
checkpointer = MemorySaver()
app_graph = _build_graph().compile(checkpointer=checkpointer)


def make_graph():
    """Graph factory for the LangGraph CLI/platform (referenced by langgraph.json).

    Compiled WITHOUT a custom checkpointer: the platform provides persistence itself, and
    passing one raises a GraphLoadError when the graph is loaded by the API.
    """
    return _build_graph().compile()


def _answer_text(message: AIMessage) -> str:
    """LLM content can be a string or a list of blocks; return plain text."""
    content = message.content
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content if isinstance(b, dict))


def _run_turn(question: str, config: RunnableConfig, snapshot) -> dict:
    """Resume a paused confirmation interrupt, or start a fresh turn."""
    if snapshot.next:
        # The graph is paused at a confirmation interrupt; treat this message as the reply.
        return app_graph.invoke(Command(resume=question), config=config)
    return app_graph.invoke({"messages": [HumanMessage(content=question)]}, config=config)


def _build_response(thread_id: str, result: dict) -> dict:
    """Shape a graph result into the /ask payload (pure; no graph/LLM needed).

    - pending interrupt -> the confirmation prompt
    - otherwise         -> the natural-language answer

    The reply intentionally never includes SQL or rows; tool data stays internal (it reaches
    the agent via ToolMessage content) and is not exposed to the caller.
    """
    # A pending interrupt means we're now awaiting confirmation: surface its prompt.
    if result.get("__interrupt__"):
        return {"thread_id": thread_id, "answer": result["__interrupt__"][0].value["message"]}

    return {"thread_id": thread_id, "answer": _answer_text(message=result["messages"][-1])}


def ask(question: str, thread_id: str | None = None) -> dict:
    """Send one user turn. Pass the returned thread_id back to continue the conversation.

    Thin orchestrator: set up the per-thread config, run the turn (new or resumed), and
    shape the reply. See _build_response for the possible output shapes.
    """
    thread_id = thread_id or str(uuid4())
    config: RunnableConfig = {
        "configurable": {"thread_id": thread_id},
        # session_id groups all turns of this thread into one conversation in LangSmith.
        "metadata": {"session_id": thread_id},
    }

    snapshot = app_graph.get_state(config)
    result = _run_turn(question=question, config=config, snapshot=snapshot)
    return _build_response(thread_id=thread_id, result=result)
