import os
from typing import TypedDict

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from sqlalchemy import text

from database import engine

SCHEMA = """
Table: transactions
  id, account_id, amount (float), currency, type (debit/credit/transfer),
  status (pending/completed/failed), counterparty, category, description, created_at
"""

llm = ChatAnthropic(
    model=os.getenv("LLM_MODEL", "claude-sonnet-4-6"),
    api_key=os.getenv("ANTHROPIC_API_KEY"),
    temperature=0,
)


class State(TypedDict, total=False):
    question: str
    sql: str
    rows: list[dict]
    answer: str


def generate_sql(state: State) -> State:
    prompt = (
        "Write a SINGLE read-only SQL SELECT for the question below. "
        "Return only raw SQL, no markdown, no semicolon.\n" + SCHEMA
    )
    sql = llm.invoke(
        [SystemMessage(content=prompt), HumanMessage(content=state["question"])]
    ).content.strip().strip("`").removeprefix("sql").strip()

    # Simple guardrail: SELECT-only.
    if not sql.lower().startswith(("select", "with")):
        raise ValueError("Only SELECT queries are allowed.")
    state["sql"] = sql
    return state


def run_sql(state: State) -> State:
    with engine.connect() as conn:
        result = conn.execute(text(state["sql"]))
        state["rows"] = [dict(r) for r in result.mappings().all()]
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
graph.add_node("generate_sql", generate_sql)
graph.add_node("run_sql", run_sql)
graph.add_node("summarize", summarize)
graph.add_edge(START, "generate_sql")
graph.add_edge("generate_sql", "run_sql")
graph.add_edge("run_sql", "summarize")
graph.add_edge("summarize", END)

app_graph = graph.compile()


def ask(question: str) -> State:
    return app_graph.invoke({"question": question})
