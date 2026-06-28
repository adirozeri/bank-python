"""Structured-output models for the LLM calls.

Each model is the schema the corresponding LLM call must return (via
``llm.with_structured_output(...)``), keeping the three calls' outputs typed and validated.
"""

from typing import Literal

from pydantic import BaseModel, Field


class RiskAssessment(BaseModel):
    """Call 2 (Risk Analysis) output: how risky the requested transfer is."""

    risk_level: Literal["HIGH", "MID", "LOW"] = Field(
        description="Overall risk of performing the transfer."
    )
    reason: str = Field(description="Brief, factual justification for the risk level.")


class JudgeVerdict(BaseModel):
    """Call 3 (Judge) output: whether the risk analysis is trustworthy."""

    approval: Literal["ACCEPTED", "DENIED"] = Field(
        description="ACCEPTED if the risk analysis is well supported, else DENIED."
    )
    reason: str = Field(description="Brief justification for accepting or denying.")


class ConfirmDecision(BaseModel):
    """How to read the user's free-text reply to a transfer-confirmation prompt."""

    decision: Literal["confirm", "cancel", "unclear"] = Field(
        description=(
            "confirm: the user clearly approves the transfer as described. "
            "cancel: the user declines or wants to stop. "
            "unclear: anything else, including approval that also changes the details "
            "(e.g. 'yes but make it 50') or an unrelated message."
        )
    )
