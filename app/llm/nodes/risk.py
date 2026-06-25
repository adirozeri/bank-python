"""Call 2 — Risk Analysis node (Groq).

Gathers the sender's balance and recent history, then asks the risk model to score the
transfer's risk as structured output (RiskAssessment). The LLM call is isolated in
``_run_risk`` so tests can stub it deterministically.
"""

import json
from typing import cast

from langchain_core.messages import HumanMessage, SystemMessage

from .. import data_access
from ..factory import get_llm
from ..prompts import load_prompt
from ..schemas import RiskAssessment
from ..state import State, require


def _run_risk(payload: dict) -> RiskAssessment:
    """Invoke the Groq risk model with the transfer + account data; return its verdict."""
    model = get_llm(role="risk_analysis").with_structured_output(RiskAssessment)
    system = load_prompt(role="risk_analysis")
    return cast(
        RiskAssessment,
        model.invoke(
            [
                SystemMessage(content=system),
                HumanMessage(content=json.dumps(payload, default=str)),
            ],
            config={"run_name": "RiskAnalysis", "tags": ["role:risk_analysis", "provider:groq"]},
        ),
    )


def risk_analysis(state: State) -> dict:
    """Assess the pending transfer's risk and store it as state['risk']."""
    transfer = require(state.get("transfer"), name="transfer")
    _, balance = data_access.query_balance(account_id=transfer["from_account"])
    _, history = data_access.query_transactions(account_id=transfer["from_account"])
    payload = {"transfer": transfer, "balance": balance, "history": history}
    assessment = _run_risk(payload=payload)
    return {"risk": assessment.model_dump()}
