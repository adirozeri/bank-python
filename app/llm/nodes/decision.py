"""Decision gate node — pure logic, no LLM.

Combines the Risk Analysis and Judge verdicts into a single proceed/deny decision:
proceed only when risk is below HIGH AND the judge ACCEPTED. (A deterministic rule-based
check could later be added here as an extra AND condition.) On denial it answers the
transfer's tool call with the reasons; on proceed it lets the edge route to confirmation.
"""

from langchain_core.messages import ToolMessage
from langsmith import traceable

from ..state import State, require


@traceable(run_type="tool")
def should_proceed(risk: dict, judge: dict) -> bool:
    """Proceed iff risk level is not HIGH and the judge approved.

    @traceable so the gate's inputs (risk/judge) and proceed/deny output show up in the
    LangSmith trace — making it clear *why* a transfer was allowed or blocked.
    """
    return risk.get("risk_level") != "HIGH" and judge.get("approval") == "ACCEPTED"


def decision_gate(state: State) -> dict:
    """If denied, emit the explanation as the transfer's tool result and clear it."""
    risk = state.get("risk", {})
    judge = state.get("judge", {})
    if should_proceed(risk=risk, judge=judge):
        # Approved: nothing to add; the edge routes to the transfer (confirmation) node.
        return {}

    transfer = require(state.get("transfer"), name="transfer")
    message = (
        f"Transfer blocked before confirmation. "
        f"Risk={risk.get('risk_level')} ({risk.get('reason')}); "
        f"Judge={judge.get('approval')} ({judge.get('reason')})."
    )
    return {
        "messages": [ToolMessage(content=message, tool_call_id=transfer["tool_call_id"])],
        "transfer": None,
    }


def route_after_decision(state: State) -> str:
    """Route to confirmation when approved, otherwise back to the agent (with the denial)."""
    proceed = should_proceed(risk=state.get("risk", {}), judge=state.get("judge", {}))
    return "transfer" if proceed else "agent"
