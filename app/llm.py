import os
from typing import Literal, TypedDict
from uuid import uuid4

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select

from .database import SessionLocal
from .models import Transaction

llm = ChatAnthropic(
    model=os.getenv("LLM_MODEL", "claude-sonnet-4-6"),
    api_key=os.getenv("ANTHROPIC_API_KEY"),
    temperature=0,
)

# Holds paused graph state between the first /ask call and the confirmation call.
# In-process only: thread_ids don't survive a server restart (fine for Phase 1).
checkpointer = MemorySaver()

# Intents we know how to answer. Anything else -> "unknown".
Intent = Literal["transactions", "balance", "unknown"]


class Classification(BaseModel):
    """Structured result of the intent-classification step."""

    intent: Intent = Field(
        description=(
            "transactions: the user wants to see/list transaction records. "
            "balance: the user wants an account balance. "
            "unknown: anything else."
        )
    )
    account_id: str | None = Field(
        default=None,
        description="The account id mentioned in the question, if any.",
    )


classifier = llm.with_structured_output(Classification)


class Judgment(BaseModel):
    """LLM-as-judge verdict on the classifier's inferred intent."""

    agrees: bool = Field(
        description="True if the inferred intent matches what the user actually asked for."
    )
    reasoning: str = Field(description="One short sentence explaining the verdict.")


judge_llm = llm.with_structured_output(Judgment)


class State(TypedDict, total=False):
    question: str
    intent: Intent
    account_id: str | None
    judge_agrees: bool
    judge_reasoning: str
    confirmed: bool
    sql: str
    rows: list[dict]
    answer: str


# --- Intent classification (the only place the LLM makes a decision) ---


def classify_intent(state: State) -> State:
    prompt = (
        "You route banking questions to a handler. Classify the question into exactly "
        "one intent: 'transactions' (list/inspect transaction records), 'balance' "
        "(how much money is in an account), or 'unknown' (neither). "
        "If the question names a specific account id, extract it."
    )
    result: Classification = classifier.invoke(
        [SystemMessage(content=prompt), HumanMessage(content=state["question"])]
    )
    state["intent"] = result.intent
    state["account_id"] = result.account_id
    return state


# --- LLM-as-a-judge: does the inferred intent match what the user asked? ---


def judge(state: State) -> State:
    prompt = (
        "You are a judge. Decide whether the inferred intent correctly captures what the "
        "user actually asked. Intents: 'transactions' (list/inspect transaction records), "
        "'balance' (how much money is in an account), 'unknown' (neither). "
        f"Inferred intent: {state['intent']}."
    )
    result: Judgment = judge_llm.invoke(
        [SystemMessage(content=prompt), HumanMessage(content=state["question"])]
    )
    state["judge_agrees"] = result.agrees
    state["judge_reasoning"] = result.reasoning
    return state


def route_after_judge(state: State) -> str:
    # Judge agrees -> ask the user to confirm; disagrees -> ask them to rephrase.
    return "confirm" if state["judge_agrees"] else "clarify"


# --- Human-in-the-loop confirmation (checkpoint / interrupt) ---


def confirm(state: State) -> State:
    decision = interrupt(
        {
            "proposed_intent": state["intent"],
            "question": state["question"],
            "message": f"Did you mean to ask about {state['intent']}?",
        }
    )
    state["confirmed"] = bool(decision)
    return state


def route_after_confirm(state: State) -> str:
    # Confirmed -> run the matching handler; rejected -> ask them to rephrase.
    return state["intent"] if state["confirmed"] else "clarify"


def clarify(state: State) -> State:
    state["rows"] = []
    state["answer"] = (
        "I wasn't sure I understood your question. Could you rephrase it?"
    )
    return state


def handle_transactions(state: State) -> State:
    stmt = select(Transaction)
    if state.get("account_id"):
        stmt = stmt.where(Transaction.account_id == state["account_id"])
    stmt = stmt.order_by(Transaction.created_at.desc()).limit(20)

    state["sql"] = str(stmt)
    with SessionLocal() as session:
        txns = session.scalars(stmt).all()
        state["rows"] = [
            {col.name: getattr(t, col.name) for col in Transaction.__table__.columns}
            for t in txns
        ]
    return state

def handle_balance(state: State) -> State:
    # Balance = completed credits minus completed debits/transfers, per currency.
    balance = func.sum(
        case((Transaction.type == "credit", Transaction.amount), else_=-Transaction.amount)
    ).label("balance")
    stmt = (
        select(Transaction.account_id, Transaction.currency, balance)
        .where(Transaction.status == "completed")
    )
    if state.get("account_id"):
        stmt = stmt.where(Transaction.account_id == state["account_id"])
    stmt = stmt.group_by(Transaction.account_id, Transaction.currency).order_by(
        Transaction.account_id
    )

    state["sql"] = str(stmt)
    with SessionLocal() as session:
        rows = session.execute(stmt).mappings().all()
        state["rows"] = [dict(r) for r in rows]
    return state


def handle_unknown(state: State) -> State:
    state["rows"] = []
    state["answer"] = (
        "I can only answer questions about transactions or account balances. "
        "Try asking to list transactions or for an account balance."
    )
    return state

def summarize(state: State) -> State:
    context = f"Question: {state['question']}\nRows: {state['rows']}"
    state["answer"] = llm.invoke(
        [
            SystemMessage(content="Answer the question from the rows, concisely."),
            HumanMessage(content=context),
        ]
    ).content
    return state


graph = StateGraph(State)
graph.add_node("classify_intent", classify_intent)
graph.add_node("judge", judge)
graph.add_node("confirm", confirm)
graph.add_node("clarify", clarify)
graph.add_node("handle_transactions", handle_transactions)
graph.add_node("handle_balance", handle_balance)
graph.add_node("handle_unknown", handle_unknown)
graph.add_node("summarize", summarize)

graph.add_edge(START, "classify_intent")
graph.add_edge("classify_intent", "judge")
graph.add_conditional_edges(
    "judge",
    route_after_judge,
    {"confirm": "confirm", "clarify": "clarify"},
)
graph.add_conditional_edges(
    "confirm",
    route_after_confirm,
    {
        "transactions": "handle_transactions",
        "balance": "handle_balance",
        "unknown": "handle_unknown",
        "clarify": "clarify",
    },
)
graph.add_edge("handle_transactions", "summarize")
graph.add_edge("handle_balance", "summarize")
graph.add_edge("handle_unknown", END)
graph.add_edge("clarify", END)
graph.add_edge("summarize", END)

# Checkpointer is required for interrupt()/Command(resume=...) to work.
app_graph = graph.compile(checkpointer=checkpointer)


class ResumeError(Exception):
    """A thread_id can't be resumed: unknown/expired, or not awaiting confirmation."""


def _shape(result: dict, thread_id: str) -> dict:
    """Turn raw graph output into the API response (pending confirmation vs. done)."""
    interrupts = result.get("__interrupt__")
    if interrupts:
        return {"status": "needs_confirmation", "thread_id": thread_id, **interrupts[0].value}
    return {
        "status": "done",
        "answer": result.get("answer"),
        "intent": result.get("intent"),
        "sql": result.get("sql"),
        "rows": result.get("rows"),
    }


def ask(question: str) -> dict:
    """Start a new question; pauses at the confirmation step and returns a thread_id."""
    thread_id = str(uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    return _shape(app_graph.invoke({"question": question}, config=config), thread_id)


def resume(thread_id: str, confirm: bool) -> dict:
    """Resume a paused question with the user's confirmation decision.

    Raises ResumeError if the thread is unknown/expired (no saved state) or is not
    currently waiting on a confirmation (e.g. already completed). Without this guard,
    resuming an unknown thread restarts the graph with no question and crashes.
    """
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = app_graph.get_state(config)
    if snapshot.created_at is None:
        raise ResumeError(
            f"Unknown or expired thread_id '{thread_id}'. Start a new question via /ask."
        )
    if not snapshot.next:
        raise ResumeError(
            f"Thread '{thread_id}' is not awaiting confirmation (already completed)."
        )
    return _shape(app_graph.invoke(Command(resume=confirm), config=config), thread_id)
