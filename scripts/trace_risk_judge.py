"""Manual probe: run Risk Analysis + Judge against the REAL LLMs so their reasoning shows up
in LangSmith as one grouped thread.

This is a script, not a pytest test, on purpose: the unit suite stays offline and conftest
stubs the provider keys with placeholders — both would fight a real-LLM call. Run it when you
want to inspect what the models actually do:

    python scripts/trace_risk_judge.py

Requires real GOOGLE_API_KEY + GROQ_API_KEY and LANGSMITH_TRACING=true + LANGSMITH_API_KEY in
.env. After it runs, open the `bank-python` project in LangSmith and find the "RiskJudgeProbe"
trace: it nests the RiskAnalysis and Judge model calls, and — when the assigned LLMs have
`thoughts: true` (translated per provider in factory.py) — shows the model's reasoning.
"""

import os
import uuid

from dotenv import load_dotenv

load_dotenv()  # load provider + LangSmith keys before importing app.database / the graph

from langsmith import traceable  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.llm.nodes import judge, risk_analysis  # noqa: E402  (functions re-exported by nodes)
from app.models import Transaction  # noqa: E402

ACCOUNT = "ACC-0001"


def ensure_seed() -> None:
    """Make sure the probe account has some history for the risk/judge data to chew on."""
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        if db.query(Transaction).filter_by(account_id=ACCOUNT).first():
            return
        db.add_all(
            [
                Transaction(account_id=ACCOUNT, amount=5116.93, currency="USD", type="credit",
                            status="completed", category="salary", counterparty="Sample Co"),
                Transaction(account_id=ACCOUNT, amount=1557.73, currency="USD", type="transfer",
                            status="completed", category="utilities", counterparty="Sample Co"),
                Transaction(account_id=ACCOUNT, amount=4997.28, currency="GBP", type="transfer",
                            status="failed", category="dining", counterparty="Sample Co"),
                Transaction(account_id=ACCOUNT, amount=1283.47, currency="USD", type="transfer",
                            status="failed", category="utilities", counterparty="Sample Co"),
                Transaction(account_id="ACC-0002", amount=10.0, currency="USD", type="credit",
                            status="completed", category="salary", counterparty="Sample Co"),
            ]
        )
        db.commit()


@traceable(name="RiskJudgeProbe")
def run_probe() -> dict:
    """Run the two gated calls in sequence (real LLMs): risk_analysis -> judge."""
    state: dict = {
        "transfer": {
            "from_account": ACCOUNT,
            "to_account": "ACC-0002",
            "amount": 100,
            "currency": "USD",
            "tool_call_id": str(uuid.uuid4()),
        }
    }
    state.update(risk_analysis(state))
    state.update(judge(state))
    return {"risk": state["risk"], "judge": state["judge"]}


if __name__ == "__main__":

    ensure_seed()
    thread_id = str(uuid.uuid4())
    print(f"thread_id (session) = {thread_id}")
    # langsmith_extra.metadata.session_id groups this run as a thread in LangSmith.
    result = run_probe(langsmith_extra={"metadata": {"session_id": thread_id}})
    print("risk  :", result["risk"])
    print("judge :", result["judge"])
