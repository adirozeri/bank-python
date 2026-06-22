"""Conversational banking assistant for /ask.

A tool-calling agent with per-thread message history (the industry-standard chatbot
shape): each turn the LLM either calls a read-only tool to fetch data or replies in
natural language (including asking a clarifying question). There is no rigid yes/no
confirmation step — the user can say anything and the model follows the conversation.

Read-only queries run with no confirmation. The one *write* action — create_transfer
— uses human-in-the-loop: it interrupt()s to ask the user to confirm before any row is
written, which is exactly what interrupts are for.
"""

import json
import os
from typing import Annotated, Literal, TypedDict
from uuid import uuid4

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select

from .database import AnalyticsSession, SessionLocal
from .models import Transaction

llm = ChatAnthropic(
    model=os.getenv("LLM_MODEL", "claude-sonnet-4-6"),
    api_key=os.getenv("ANTHROPIC_API_KEY"),
    temperature=0,
)

# Per-thread conversation memory. In-process only: history doesn't survive a server
# restart (fine for Phase 1).
checkpointer = MemorySaver()

SYSTEM_PROMPT = (
    "You are a helpful banking assistant for the bank-python app. You can answer "
    "questions about transactions and account balances by calling the provided tools. "
    "Only the tools can see the data, so never invent numbers — call a tool. "
    "If a question is ambiguous (for example, which account), ask a brief clarifying "
    "question instead of guessing. If asked about something other than transactions or "
    "balances, briefly say what you can help with. Keep answers concise. "
    "To move/transfer/send money, call create_transfer with from_account, to_account, "
    "and amount (ask the user for any of these that are missing first). Do NOT ask the "
    "user to confirm yourself — calling create_transfer triggers a confirmation step "
    "automatically."
)


# --- Read-only data access (the SELECT-only guardrail is inherent: these only SELECT) ---


def _query_transactions(account_id: str | None) -> tuple[str, list[dict]]:
    stmt = select(Transaction)
    if account_id:
        stmt = stmt.where(Transaction.account_id == account_id)
    stmt = stmt.order_by(Transaction.created_at.desc()).limit(20)
    # Reads go to the analytics engine (Snowflake when configured, else the primary).
    with AnalyticsSession() as session:
        txns = session.scalars(stmt).all()
        rows = [
            {col.name: getattr(t, col.name) for col in Transaction.__table__.columns}
            for t in txns
        ]
    return str(stmt), rows


def _query_balance(account_id: str | None) -> tuple[str, list[dict]]:
    # Balance = completed credits minus completed debits/transfers, per currency.
    balance = func.sum(
        case((Transaction.type == "credit", Transaction.amount), else_=-Transaction.amount)
    ).label("balance")
    stmt = (
        select(Transaction.account_id, Transaction.currency, balance)
        .where(Transaction.status == "completed")
    )
    if account_id:
        stmt = stmt.where(Transaction.account_id == account_id)
    stmt = stmt.group_by(Transaction.account_id, Transaction.currency).order_by(
        Transaction.account_id
    )
    # Reads go to the analytics engine (Snowflake when configured, else the primary).
    with AnalyticsSession() as session:
        rows = [dict(r) for r in session.execute(stmt).mappings().all()]
    return str(stmt), rows


# The @tool objects are bound to the LLM for their schema; the tools node below runs
# the matching helper so it can also capture the SQL + rows for the API response.


@tool
def list_transactions(account_id: str | None = None) -> str:
    """List recent transactions (up to 20, newest first).

    Optionally filter to a single account by account_id, e.g. "ACC-0001".
    """
    _, rows = _query_transactions(account_id)
    return json.dumps(rows, default=str)


@tool
def get_balance(account_id: str | None = None) -> str:
    """Get account balance(s): completed credits minus completed debits/transfers,
    grouped by account and currency. Optionally filter to a single account_id.
    """
    _, rows = _query_balance(account_id)
    return json.dumps(rows, default=str)


# --- Write action: transfer money (human-in-the-loop confirmation) ---


class ConfirmDecision(BaseModel):
    """How to read the user's reply to a transfer-confirmation prompt."""

    decision: Literal["confirm", "cancel", "unclear"] = Field(
        description=(
            "confirm: the user clearly approves the transfer as described. "
            "cancel: the user declines or wants to stop. "
            "unclear: anything else, including approval that also changes the details "
            "(e.g. 'yes but make it 50') or an unrelated message."
        )
    )


confirm_llm = llm.with_structured_output(ConfirmDecision)


def _interpret_confirmation(reply: str) -> str:
    """Let the LLM read a free-text reply; returns 'confirm' | 'cancel' | 'unclear'."""
    verdict: ConfirmDecision = confirm_llm.invoke(
        [
            SystemMessage(
                content=(
                    "The user was asked to confirm a money transfer with the exact "
                    "amount and accounts shown. Classify their reply. Only treat it as "
                    "'confirm' if they approve it as-is; if they approve but change any "
                    "detail, that is 'unclear', not 'confirm'."
                )
            ),
            HumanMessage(content=reply),
        ]
    )
    return verdict.decision


def _account_exists(session, account_id: str) -> bool:
    # No accounts table: an account "exists" if it appears in the transactions ledger.
    return session.scalar(
        select(Transaction.id).where(Transaction.account_id == account_id).limit(1)
    ) is not None


def _create_transfer(from_account: str, to_account: str, amount: float, currency: str = "USD") -> str:
    # Pause and ask the user to confirm BEFORE writing anything. interrupt() suspends the
    # graph; ask() resumes it with the user's next message, which arrives here as `decision`.
    reply = interrupt(
        {
            "action": "create_transfer",
            "message": (
                f"Please confirm: transfer {amount} {currency} from {from_account} "
                f"to {to_account}? (yes/no)"
            ),
        }
    )
    decision = _interpret_confirmation(str(reply))
    if decision == "cancel":
        return "Transfer cancelled — no transaction was created."
    if decision == "unclear":
        return (
            "I didn't take that as a clear yes. No transfer was made. If you still want "
            "it, say so (and restate the amount/accounts if you'd like to change them)."
        )

    with SessionLocal() as session:
        missing = [a for a in (from_account, to_account) if not _account_exists(session, a)]
        if missing:
            return f"Account(s) not found: {', '.join(missing)}. No transfer created."

        # Double-entry: debit the sender (a 'transfer' out), credit the receiver.
        debit = Transaction(
            account_id=from_account, amount=amount, currency=currency, type="transfer",
            status="completed", counterparty=to_account,
            description=f"Transfer to {to_account}",
        )
        credit = Transaction(
            account_id=to_account, amount=amount, currency=currency, type="credit",
            status="completed", counterparty=from_account,
            description=f"Transfer from {from_account}",
        )
        session.add_all([debit, credit])
        session.commit()
        return (
            f"Transfer completed: {amount} {currency} from {from_account} to "
            f"{to_account} (transaction id {debit.id})."
        )


@tool
def create_transfer(from_account: str, to_account: str, amount: float, currency: str = "USD") -> str:
    """Transfer money from one account to another. Use this whenever the user asks to
    move, send, or transfer money. The user will be asked to confirm before it is created.
    """
    return _create_transfer(from_account, to_account, amount, currency)


TOOLS = [list_transactions, get_balance, create_transfer]
HELPERS = {"list_transactions": _query_transactions, "get_balance": _query_balance}
WRITE_TOOLS = {"create_transfer": _create_transfer}  # run in-node; may interrupt()
llm_with_tools = llm.bind_tools(TOOLS)


# --- Agent graph: agent <-> tools loop ---


class State(TypedDict):
    messages: Annotated[list, add_messages]
    # SQL + rows from the tool calls of the most recent tools step (overwritten each
    # time tools run); surfaced in the API response per the "/ask returns SQL+rows" rule.
    queries: list[dict]


def agent(state: State) -> dict:
    response = llm_with_tools.invoke([SystemMessage(content=SYSTEM_PROMPT), *state["messages"]])
    return {"messages": [response]}


def run_tools(state: State) -> dict:
    last = state["messages"][-1]
    tool_messages = []
    queries = []
    for call in last.tool_calls:
        name = call["name"]
        if name in WRITE_TOOLS:
            # Write tool (e.g. create_transfer): runs here and may interrupt() to confirm.
            content = WRITE_TOOLS[name](**call["args"])
        else:
            sql, rows = HELPERS[name](call["args"].get("account_id"))
            queries.append({"tool": name, "sql": sql, "rows": rows})
            content = json.dumps(rows, default=str)
        tool_messages.append(ToolMessage(content=content, tool_call_id=call["id"]))
    return {"messages": tool_messages, "queries": queries}


def should_continue(state: State) -> str:
    return "tools" if getattr(state["messages"][-1], "tool_calls", None) else END


graph = StateGraph(State)
graph.add_node("agent", agent)
graph.add_node("tools", run_tools)
graph.add_edge(START, "agent")
graph.add_conditional_edges("agent", 
                            should_continue, 
                            {
                                "tools": "tools",
                                END: END
                            }
                            )
graph.add_edge("tools", "agent")

app_graph = graph.compile(checkpointer=checkpointer)


def _answer_text(message: AIMessage) -> str:
    """Anthropic content can be a string or a list of blocks; return plain text."""
    content = message.content
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content if isinstance(b, dict))


def ask(question: str, thread_id: str | None = None) -> dict:
    """Send one user turn. Pass the returned thread_id back to continue the conversation.

    Returns the natural-language answer plus, when tools were used this turn, the
    underlying SQL + rows (one entry per tool call).
    """
    thread_id = thread_id or str(uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    snapshot = app_graph.get_state(config)
    prev_count = len(snapshot.values.get("messages", [])) if snapshot.values else 0

    if snapshot.next:
        # The graph is paused at a confirmation interrupt; treat this message as the reply.
        result = app_graph.invoke(Command(resume=question), config=config)
    else:
        result = app_graph.invoke({"messages": [HumanMessage(content=question)]}, config=config)

    # A pending interrupt means we're now awaiting confirmation: surface its prompt.
    if result.get("__interrupt__"):
        return {"thread_id": thread_id, "answer": result["__interrupt__"][0].value["message"]}

    new_messages = result["messages"][prev_count:]
    used_tools = any(isinstance(m, ToolMessage) for m in new_messages)

    payload = {"thread_id": thread_id, "answer": _answer_text(result["messages"][-1])}
    if used_tools:
        payload["queries"] = result.get("queries", [])
    return payload
