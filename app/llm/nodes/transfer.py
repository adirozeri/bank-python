"""Transfer execution node — human-in-the-loop confirmation, then the write.

Reached only after the risk/judge gate approves. It ALWAYS asks the user to confirm via
interrupt() before any row is written (never auto-executes), interprets the free-text reply
with the intent model, and on a clear yes performs the double-entry write. The outcome is
returned as the transfer tool call's result so the agent can summarise it.
"""

from typing import cast

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.types import interrupt

from .. import data_access
from ..factory import get_llm, trace_config
from ..schemas import ConfirmDecision
from ..state import State, require

_CONFIRM_SYSTEM = (
    "The user was asked to confirm a money transfer with the exact amount and accounts "
    "shown. Classify their reply. Only treat it as 'confirm' if they approve it as-is; if "
    "they approve but change any detail, that is 'unclear', not 'confirm'."
)


def interpret_confirmation(reply: str) -> str:
    """Classify a free-text confirmation reply as 'confirm' | 'cancel' | 'unclear'."""
    model = get_llm(role="user_intent").with_structured_output(ConfirmDecision)
    verdict = cast(
        ConfirmDecision,
        model.invoke(
            [SystemMessage(content=_CONFIRM_SYSTEM), HumanMessage(content=reply)],
            config=trace_config("user_intent", "ConfirmParse"),
        ),
    )
    return verdict.decision


def transfer(state: State) -> dict:
    """Confirm with the user, then execute (or cancel) the approved transfer."""
    t = require(state.get("transfer"), name="transfer")
    # Pause and ask the user to confirm BEFORE writing anything. interrupt() suspends the
    # graph; ask() resumes it with the user's next message, delivered here as `reply`.
    reply = interrupt(
        {
            "action": "create_transfer",
            "message": (
                f"Please confirm: transfer {t['amount']} {t['currency']} from "
                f"{t['from_account']} to {t['to_account']}? (yes/no)"
            ),
        }
    )

    decision = interpret_confirmation(reply=str(reply))
    if decision == "cancel":
        result = "Transfer cancelled — no transaction was created."
    elif decision == "unclear":
        result = (
            "I didn't take that as a clear yes. No transfer was made. If you still want it, "
            "say so (and restate the amount/accounts if you'd like to change them)."
        )
    else:
        result = data_access.execute_transfer(
            from_account=t["from_account"],
            to_account=t["to_account"],
            amount=t["amount"],
            currency=t["currency"],
        )

    return {
        "messages": [ToolMessage(content=result, tool_call_id=t["tool_call_id"])],
        "transfer": None,
    }
