"""Call 2 — Risk Analysis node (Groq).

Gathers the sender's balance and recent history, then asks the risk model to score the
transfer's risk as structured output (RiskAssessment). The LLM call is isolated in
``_run_risk`` so tests can stub it deterministically.
"""

import json
from typing import cast

from langchain_core.messages import HumanMessage, SystemMessage

from .. import data_access
from ..factory import get_llm, trace_config
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
            config=trace_config("risk_analysis", "RiskAnalysis"),
        ),
    )


def risk_analysis(state: State) -> dict:
    """Assess the pending transfer's risk and store it as state['risk']."""
    transfer = require(state.get("transfer"), name="transfer")
    # Precomputed signals (overdraft checks, balances, counts) instead of raw rows.
    payload = data_access.risk_features(transfer=transfer)
    assessment = _run_risk(payload=payload)
    return {"risk": assessment.model_dump()}
