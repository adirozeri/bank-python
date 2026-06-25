"""Unit tests for the LLM SDK package (app/llm/*).

Covered without network or real LLM calls:
  * data_access      - query/balance/account_exists + execute_transfer (double entry)
  * factory.get_llm  - role -> provider/params resolution; unknown role error
  * prompts          - provider-specific vs generic fallback; persona mapping
  * decision         - the proceed/deny truth table + denial tool message
  * transfer node    - human-confirmation branches (confirm/cancel/unclear)
  * tools_runner     - read dispatch + transfer capture/routing
  * graph._answer_text

Deliberately NOT unit-tested: the live agent/risk/judge model calls (Gemini/Groq) and the
full ask() round-trip. The risk/judge nodes isolate their LLM call in _run_risk/_run_judge,
which tests stub to stay deterministic.

Allure annotations drive the report; they don't change assertions. See docs/allure.md.
"""

import json

import allure
import pytest
from langchain_core.messages import AIMessage, ToolMessage

from langchain_core.language_models import BaseChatModel

from app.llm.config import load_llm_config, provider_for
from app.llm import data_access
from app.llm import factory
from app.llm import prompts
from importlib import import_module

from app.llm.graph import _answer_text, _build_response
from app.llm.nodes import decision, tools_runner
from app.models import Transaction

# nodes/__init__ exports a `transfer` function that shadows the submodule attribute, so
# fetch the actual module from sys.modules to monkeypatch its interrupt/interpret helpers.
transfer_node = import_module("app.llm.nodes.transfer")


# --- data access ----------------------------------------------------------------------


@allure.epic("Unit tests")
@allure.feature("LLM SDK")
@allure.story("Data access")
class TestDataAccess:
    @allure.title("query_transactions filters by account_id")
    def test_query_transactions_filters_by_account(self, seeded):
        sql, rows = data_access.query_transactions(account_id="ACC-0001")
        allure.attach(sql, "SQL", allure.attachment_type.TEXT)
        assert rows and all(r["account_id"] == "ACC-0001" for r in rows)

    @allure.title("query_transactions with no filter spans all accounts")
    def test_query_transactions_all(self, seeded):
        _, rows = data_access.query_transactions(account_id=None)
        assert {r["account_id"] for r in rows} == {"ACC-0001", "ACC-0002"}

    @allure.title("query_balance = completed credits minus completed debits")
    def test_query_balance(self, seeded):
        _, rows = data_access.query_balance(account_id="ACC-0001")
        assert rows == [{"account_id": "ACC-0001", "currency": "USD", "balance": 70.0}]

    @allure.title("account_exists reflects presence in the ledger")
    def test_account_exists(self, session_factory):
        with session_factory() as s:
            s.add(Transaction(account_id="ACC-0001", amount=1.0, type="credit", status="completed"))
            s.commit()
            assert data_access.account_exists(s, account_id="ACC-0001") is True
            assert data_access.account_exists(s, account_id="ACC-NOPE") is False

    @allure.title("execute_transfer books a double entry (debit + credit)")
    def test_execute_transfer_double_entry(self, seeded):
        result = data_access.execute_transfer(from_account="ACC-0001", to_account="ACC-0002", amount=25.0)
        assert "completed" in result.lower()
        with seeded() as s:
            debit = s.query(Transaction).filter_by(account_id="ACC-0001", type="transfer").one()
            credit = s.query(Transaction).filter_by(
                account_id="ACC-0002", type="credit", counterparty="ACC-0001"
            ).one()
            assert debit.amount == 25.0 and credit.amount == 25.0

    @allure.title("execute_transfer rejects an unknown account, writing nothing")
    def test_execute_transfer_unknown_account(self, seeded):
        result = data_access.execute_transfer(from_account="ACC-0001", to_account="ACC-NOPE", amount=25.0)
        assert "not found" in result.lower()
        with seeded() as s:
            assert s.query(Transaction).filter_by(type="transfer").count() == 0


# --- factory & config -----------------------------------------------------------------


_PROVIDER_CLASS = {
    "google": "ChatGoogleGenerativeAI",
    "groq": "ChatGroq",
    "anthropic": "ChatAnthropic",
}


@allure.epic("Unit tests")
@allure.feature("LLM SDK")
@allure.story("Model factory & config")
class TestFactory:
    @allure.title("provider_for resolves each role through the catalog (config-agnostic)")
    def test_provider_for_resolves(self):
        cfg = load_llm_config()
        for role, llm_name in cfg["roles"].items():
            assert provider_for(role) == cfg["llms"][llm_name]["provider"]

    @allure.title("get_llm builds the wrapper matching each role's provider")
    def test_get_llm_builds_matching_wrapper(self):
        for role in load_llm_config()["roles"]:
            model = factory.get_llm(role=role)
            assert isinstance(model, BaseChatModel)
            assert type(model).__name__ == _PROVIDER_CLASS[provider_for(role)]

    @allure.title("Catalog params (e.g. llm3 max_tokens) reach the built model")
    def test_catalog_params_applied(self):
        # Build directly from a known catalog entry, independent of role assignment.
        cfg = load_llm_config()
        if "llm3" in cfg["llms"]:
            assert cfg["llms"]["llm3"].get("max_tokens") == 1024

    @allure.title("get_llm raises on an unknown role")
    def test_get_llm_unknown_role(self):
        with pytest.raises(ValueError):
            factory.get_llm(role="does-not-exist")


# --- prompts --------------------------------------------------------------------------


@allure.epic("Unit tests")
@allure.feature("LLM SDK")
@allure.story("Prompts & persona")
class TestPrompts:
    @allure.title("Each role resolves to its entry in the catalog LLM's prompt file")
    def test_role_prompts(self):
        assert prompts.load_prompt(role="user_intent").startswith("You are a helpful")
        assert prompts.load_prompt(role="risk_analysis").startswith("You are a bank")
        assert prompts.load_prompt(role="judge").startswith("You are an independent")

    @allure.title("A missing role entry raises a clear error")
    def test_missing_entry(self, tmp_path, monkeypatch):
        (tmp_path / "llmX.yaml").write_text("user_intent: hi\n")
        monkeypatch.setattr(prompts.settings, "prompts_dir", tmp_path)
        monkeypatch.setattr(prompts, "_llm_for_role", lambda role: "llmX")
        prompts._prompts_for_llm.cache_clear()
        with pytest.raises(ValueError):
            prompts.load_prompt(role="judge")

    @allure.title("Persona key maps to its tone file")
    def test_persona(self):
        assert prompts.load_persona(persona_key="young").lower().startswith("use a friendly")
        assert prompts.load_persona(persona_key="default").lower().startswith("use a professional")


# --- decision gate (pure) -------------------------------------------------------------


@allure.epic("Unit tests")
@allure.feature("LLM SDK")
@allure.story("Decision gate")
class TestDecisionGate:
    @allure.title("should_proceed truth table (risk x judge)")
    @allure.severity(allure.severity_level.BLOCKER)
    @pytest.mark.parametrize(
        "level,approval,expected",
        [
            ("LOW", "ACCEPTED", True),
            ("MID", "ACCEPTED", True),
            ("HIGH", "ACCEPTED", False),   # HIGH risk always blocks
            ("LOW", "DENIED", False),      # judge denial always blocks
            ("HIGH", "DENIED", False),
        ],
    )
    def test_truth_table(self, level, approval, expected):
        proceed = decision.should_proceed(risk={"risk_level": level}, judge={"approval": approval})
        assert proceed is expected

    @allure.title("Denied decision answers the tool call and clears the transfer")
    def test_denied_emits_tool_message(self):
        state = {
            "transfer": {"tool_call_id": "call-1", "from_account": "A", "to_account": "B",
                         "amount": 10, "currency": "USD"},
            "risk": {"risk_level": "HIGH", "reason": "over balance"},
            "judge": {"approval": "DENIED", "reason": "unsupported"},
        }
        out = decision.decision_gate(state)
        assert out["transfer"] is None
        msg = out["messages"][0]
        assert isinstance(msg, ToolMessage) and msg.tool_call_id == "call-1"
        assert "blocked" in msg.content.lower()
        assert decision.route_after_decision(state) == "agent"

    @allure.title("Approved decision adds nothing and routes to confirmation")
    def test_approved_routes_to_transfer(self):
        state = {"risk": {"risk_level": "LOW"}, "judge": {"approval": "ACCEPTED"}}
        assert decision.decision_gate(state) == {}
        assert decision.route_after_decision(state) == "transfer"


# --- transfer node (human-in-the-loop) ------------------------------------------------


def _stub_confirmation(monkeypatch, verdict):
    """interrupt() suspends a real graph, so stub it; drive the confirmation verdict too."""
    monkeypatch.setattr(transfer_node, "interrupt", lambda payload: "the user's reply")
    monkeypatch.setattr(transfer_node, "interpret_confirmation", lambda reply: verdict)


def _pending(amount=25.0):
    return {"from_account": "ACC-0001", "to_account": "ACC-0002", "amount": amount,
            "currency": "USD", "tool_call_id": "call-xyz"}


@allure.epic("Unit tests")
@allure.feature("LLM SDK")
@allure.story("Transfer (human-in-the-loop)")
class TestTransferNode:
    @allure.title("Confirmed transfer executes a double entry")
    @allure.severity(allure.severity_level.BLOCKER)
    def test_confirmed_executes(self, monkeypatch, seeded):
        _stub_confirmation(monkeypatch, "confirm")
        out = transfer_node.transfer(state={"transfer": _pending()})
        assert out["transfer"] is None
        assert "completed" in out["messages"][0].content.lower()
        with seeded() as s:
            assert s.query(Transaction).filter_by(type="transfer").count() == 1

    @allure.title("Declined confirmation writes nothing")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_cancelled_writes_nothing(self, monkeypatch, seeded):
        _stub_confirmation(monkeypatch, "cancel")
        out = transfer_node.transfer(state={"transfer": _pending()})
        assert "cancelled" in out["messages"][0].content.lower()
        with seeded() as s:
            assert s.query(Transaction).filter_by(type="transfer").count() == 0

    @allure.title("Ambiguous reply writes nothing")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_unclear_writes_nothing(self, monkeypatch, seeded):
        _stub_confirmation(monkeypatch, "unclear")
        out = transfer_node.transfer(state={"transfer": _pending()})
        assert "clear yes" in out["messages"][0].content.lower()
        with seeded() as s:
            assert s.query(Transaction).filter_by(type="transfer").count() == 0


# --- tools_runner ---------------------------------------------------------------------


@allure.epic("Unit tests")
@allure.feature("LLM SDK")
@allure.story("Tool dispatch & routing")
class TestToolsRunner:
    @allure.title("Read tool runs and is answered; routes back to agent")
    def test_read_tool(self, seeded):
        ai = AIMessage(content="", tool_calls=[
            {"name": "get_balance", "args": {"account_id": "ACC-0001"}, "id": "c1"},
        ])
        out = tools_runner.run_tools(state={"messages": [ai]})
        assert isinstance(out["messages"][0], ToolMessage)  # rows feed the agent
        assert "queries" not in out  # never surfaced
        assert "transfer" not in out
        assert tools_runner.route_after_tools(out) == "agent"

    @allure.title("create_transfer call is captured and routes to risk analysis")
    def test_transfer_capture(self):
        ai = AIMessage(content="", tool_calls=[
            {"name": "create_transfer",
             "args": {"from_account": "A", "to_account": "B", "amount": 5}, "id": "c2"},
        ])
        out = tools_runner.run_tools(state={"messages": [ai]})
        assert out["transfer"]["tool_call_id"] == "c2"
        assert out["transfer"]["currency"] == "USD"  # default applied
        assert out["messages"] == []  # not answered here; subflow answers later
        assert tools_runner.route_after_tools(out) == "risk_analysis"


# --- misc -----------------------------------------------------------------------------


@allure.epic("Unit tests")
@allure.feature("LLM SDK")
@allure.story("Answer formatting")
class TestAnswerText:
    @allure.title("Plain string content is returned as-is")
    def test_plain(self):
        assert _answer_text(message=AIMessage(content="hello")) == "hello"

    @allure.title("A list of text blocks is concatenated")
    def test_blocks(self):
        msg = AIMessage(content=[{"type": "text", "text": "a"}, {"type": "text", "text": "b"}])
        assert _answer_text(message=msg) == "ab"


# --- response shaping (_build_response, pure) ------------------------------------------


class _Interrupt:
    """Minimal stand-in for LangGraph's interrupt object: only .value is accessed."""

    def __init__(self, message):
        self.value = {"message": message}


@allure.epic("Unit tests")
@allure.feature("LLM SDK")
@allure.story("Response shaping")
class TestBuildResponse:
    @allure.title("Pending interrupt returns the confirmation prompt")
    def test_interrupt(self):
        result = {"__interrupt__": [_Interrupt("confirm? (yes/no)")]}
        out = _build_response(thread_id="t1", result=result)
        assert out == {"thread_id": "t1", "answer": "confirm? (yes/no)"}

    @allure.title("A normal turn returns only thread_id + answer (no SQL/rows)")
    def test_answer_only(self):
        # Even when read tools ran (ToolMessage present), the reply exposes neither SQL nor
        # rows — only the natural-language answer.
        result = {
            "messages": [ToolMessage(content="[]", tool_call_id="c1"), AIMessage(content="done")],
        }
        out = _build_response(thread_id="t1", result=result)
        assert out == {"thread_id": "t1", "answer": "done"}
        assert "queries" not in out
