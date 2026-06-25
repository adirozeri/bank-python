"""Call 3 — Judge node (Gemini).

An independent model (different vendor than Risk Analysis, to reduce bias) reviews the risk
verdict against the same underlying data and returns ACCEPTED/DENIED as structured output.
The LLM call is isolated in ``_run_judge`` so tests can stub it deterministically.
"""

import json
from typing import cast

from langchain_core.messages import HumanMessage, SystemMessage

from .. import data_access
from ..factory import get_llm
from ..prompts import load_prompt
from ..schemas import JudgeVerdict
from ..state import State, require


def _run_judge(payload: dict) -> JudgeVerdict:
    """Invoke the Gemini judge model with the data + prior risk verdict; return its verdict."""
    model = get_llm(role="judge").with_structured_output(JudgeVerdict)
    system = load_prompt(role="judge")
    return cast(
        JudgeVerdict,
        model.invoke(
            [
                SystemMessage(content=system),
                HumanMessage(content=json.dumps(payload, default=str)),
            ],
            config={"run_name": "Judge", "tags": ["role:judge", "provider:google"]},
        ),
    )


def judge(state: State) -> dict:
    """Evaluate the risk assessment and store the verdict as state['judge']."""
    transfer = require(state.get("transfer"), name="transfer")
    risk = require(state.get("risk"), name="risk")
    _, balance = data_access.query_balance(account_id=transfer["from_account"])
    _, history = data_access.query_transactions(account_id=transfer["from_account"])
    payload = {
        "transfer": transfer,
        "balance": balance,
        "history": history,
        "risk_assessment": risk,
    }
    verdict = _run_judge(payload=payload)
    return {"judge": verdict.model_dump()}
