# Plan — Migrate `/ask` to a Multi-Model, Three-Call Agentic Workflow

Implementation plan for the requirements in [`more_llm_calls.md`](./more_llm_calls.md):
move the single-model LangGraph agent to a **config-driven, two-model, three-LLM-call**
workflow that gates transactions behind a Risk Analysis call and a Judge call — and split
the code into small, single-responsibility modules.

> **Scope of this doc: planning only.** No code is written here.

## Locked decisions

| Topic | Decision |
|-------|----------|
| Providers | Config-driven **catalog** of named LLMs (`google`/`groq`/`anthropic`); each role maps to a catalog entry and is swappable with no code change. |
| Abstraction | **LangChain provider wrappers** via a per-provider builder layer (`factory.py`) that translates normalized keys (e.g. `thoughts`) to each SDK. Not LiteLLM. |
| Transfer approval | Risk + Judge gate, **then always** the existing human `interrupt()` yes/no. **Never auto-execute.** |
| Deterministic risk | `data_access.risk_features(transfer)` computes the signals (overdraft checks, balances, counts) **in code**; the LLMs judge those features rather than re-deriving them. |
| Tracing | **LangSmith only** (already stubbed in `.env.example`). No Langfuse. |
| MCP | **Out of scope** for now (later investigation). |
| Phase | Intended **now**. |
| Code style | **Every node/function/module gets an explanatory docstring/comment.** |

---

## 1. Where we are today (`app/llm.py`)

| Piece | Current implementation |
|-------|------------------------|
| Model | Single `ChatAnthropic` (to be **removed**) |
| Config | Plain `os.getenv(...)`; no `BaseSettings` (though `pydantic-settings` is installed) |
| Graph | `agent` ⇄ `tools` loop (`StateGraph`, `MemorySaver` checkpointer) |
| State | `TypedDict` with `messages`, `queries` |
| Tools | `list_transactions`, `get_balance`, `create_transfer` |
| Transfer | `_create_transfer` runs in the `tools` node, uses `interrupt()` for human confirmation, writes a double entry |
| Reusable data helpers | `_query_balance` / `_query_transactions` return `(sql, rows)` — exactly the Risk Analysis inputs |
| Entry point | `main.py` `/ask` → `llm.ask(question, thread_id)` |

**Everything currently lives in one file.** The migration both **adds** the Risk + Judge
calls and **splits** the code into a package by responsibility.

---

## 2. Target module structure (split by responsibility)

`app/llm.py` becomes a package `app/llm/`. `__init__.py` re-exports `ask`, so `main.py`'s
`from . import llm; llm.ask(...)` keeps working unchanged.

The package is **fully self-contained**: code, the routing YAML, and the prompt files all
live under `app/llm/`.

```
app/
  llm/
    __init__.py          # public API: re-export `ask()` only (keeps main.py import stable)
    graph.py             # build/compile the StateGraph (nodes + edges) and expose ask()
    state.py             # State TypedDict (messages, queries, transfer, risk, judge)
    schemas.py           # structured-output models: RiskAssessment, JudgeVerdict, ConfirmDecision
    factory.py           # get_llm(role) -> BaseChatModel via LangChain wrappers (Gemini/Groq)
    prompts.py           # load_prompt(role) [role->llm->prompts/<llm>.yaml] + persona loader
    config.py            # pydantic-settings BaseSettings + YAML loader (package-relative paths)
    data_access.py       # all SQLAlchemy reads/writes (moved out of the old llm.py)
    tools.py             # @tool schemas (list_transactions, get_balance, create_transfer)
    llm_models.yaml      # role -> provider/model/params; persona map
    prompts/                 # one YAML per catalog LLM; keys = roles
      llm1.yaml              # {user_intent, risk_analysis, judge}
      llm2.yaml
      llm3.yaml
      llm4.yaml
      persona/
        formal.md
        casual.md
    nodes/
      __init__.py        # collects node callables for graph.py
      agent.py           # Call 1 — User Intent node (Gemini)
      risk.py            # Call 2 — Risk Analysis node (Groq)
      judge.py           # Call 3 — Judge node (Gemini, different model => less bias)
      decision.py        # decision_gate node — pure logic, no LLM
      transfer.py        # human-confirmation interrupt() + execute double-entry
      tools_runner.py    # runs read-only tools, returns rows to the agent (not to the caller)
```

### Responsibilities at a glance

| Module | Single responsibility |
|--------|-----------------------|
| `llm/__init__.py` | Public surface — only re-exports `ask`. |
| `llm/graph.py` | Wire nodes + conditional edges, compile with `MemorySaver`, implement `ask()`. |
| `llm/state.py` | Typed graph state + the pending-transfer payload. |
| `llm/schemas.py` | Pydantic models for the three structured outputs. |
| `llm/factory.py` | Turn a role into a configured LangChain chat model (per-provider params). |
| `llm/prompts.py` | Load role/provider system prompts and persona snippets. |
| `llm/config.py` | LLM settings + YAML loader; centralizes secrets/paths (replaces scattered `os.getenv`). |
| `llm/data_access.py` | DB queries (balance, history, account-exists) and the transfer write. |
| `llm/tools.py` | Tool schemas bound to the intent model. |
| `llm/llm_models.yaml` | Declarative model routing (swap models with no code change). |
| `llm/prompts/*` | Editable, per-model/persona prompt text. |
| `llm/nodes/*` | One file per node; one clear step of the workflow each. |

---

## 3. New graph shape

Keep the `agent` ⇄ `tools` loop for reads. When the agent calls `create_transfer`, route
through the gated transfer subflow:

```
agent ──(read tools)──▶ tools_runner ──▶ agent ...
  │
  └──(create_transfer requested)──▶ risk_analysis ──▶ judge ──▶ decision_gate
                                                                   │
                         ┌──────────────────────────────────────────┤
                         ▼ (risk != HIGH AND ACCEPTED)               ▼ (HIGH or DENIED)
                   transfer: confirm() + execute                 deny (return reason)
                         │
                         ▼
                       agent (final natural-language answer, persona-styled)
```

- `risk_analysis`, `judge` = **LLM nodes** (traced as graph steps in LangSmith).
- `decision_gate` = **pure function** (no LLM): combines risk + judge into proceed/deny.
- `transfer` keeps today's `interrupt()` human yes/no **after** an approved gate — never
  auto-executes.

### State additions (`state.py`)
Use `NotRequired` so read flows still validate without them:
`risk: NotRequired[dict]`, `judge: NotRequired[dict]`,
`transfer: NotRequired[TransferRequest]` (from/to/amount/currency captured from the tool
call).

### Structured outputs (`schemas.py`)
```python
class RiskAssessment(BaseModel):   # Call 2 output
    risk_level: Literal["HIGH", "MID", "LOW"]
    reason: str

class JudgeVerdict(BaseModel):     # Call 3 output
    approval: Literal["ACCEPTED", "DENIED"]
    reason: str

class ConfirmDecision(BaseModel):  # existing human-confirmation parse
    decision: Literal["confirm", "cancel", "unclear"]
```
Each obtained via `get_llm(role).with_structured_output(...)`.

---

## 4. Model selection & configuration (LangChain wrappers)

### `app/llm/llm_models.yaml`
Two layers — a named `llms` **catalog** using NORMALIZED keys, plus a `roles` map that points
each role at a catalog entry by name. Per-provider builders in `factory.py` translate the
normalized keys (notably `thoughts`) into each SDK's kwargs (Gemini `include_thoughts`,
Claude `thinking{}`+`temperature=1`, Groq `reasoning_format`):
```yaml
llms:
  llm1: { provider: google,    model: gemini-2.5-flash, temperature: 0, thoughts: true }
  llm2: { provider: google,    model: gemini-2.5-pro,   temperature: 0, thoughts: true }
  llm3: { provider: groq,      model: llama-3.3-70b-versatile, temperature: 0.2, max_tokens: 1024, thoughts: true }
  llm4: { provider: anthropic, model: claude-sonnet-4-6, thoughts: true }
roles:
  user_intent: llm1
  risk_analysis: llm3
  judge: llm1            # e.g. set to llm2/llm4 to use a stronger/different-vendor judge
personas:
  default: formal        # maps to prompts/persona/formal.md
  young:   casual        # maps to prompts/persona/casual.md
```

### `app/llm/config.py` (pydantic-settings)
Centralizes: `GOOGLE_API_KEY`, `GROQ_API_KEY`, `ANTHROPIC_API_KEY`, package-relative paths to
the YAML and prompts dir, and the default persona. `llm_spec_for(role)` resolves role -> llm
name -> definition; `provider_for(role)` returns the backing provider. Replaces scattered
`os.getenv`.

### `app/llm/factory.py`
```python
def get_llm(role: str) -> BaseChatModel:
    """Resolve a role (user_intent|risk_analysis|judge) to a configured LangChain
    chat model, reading provider/model/params from llm_models.yaml and applying
    per-model params (temperature, max_tokens, etc.)."""
```
- `provider: google` → `ChatGoogleGenerativeAI` (`langchain-google-genai`).
- `provider: groq`   → `ChatGroq` (`langchain-groq`).
- Uniform `BaseChatModel` return so node code stays simple and provider-agnostic.

### `app/llm/prompts.py`
`load_prompt(role)` follows role -> catalog llm name -> `app/llm/prompts/<llm>.yaml` and
returns that file's entry for the role (keys: `user_intent`/`risk_analysis`/`judge`). One
YAML per LLM keeps multi-line prompts readable with no custom parsing. Persona text is
injected **only** into user-facing generations.

### Tracing
Enable **LangSmith** via existing env vars; attach the runtime config (model per role +
persona) as run metadata/tags so each `/ask` shows which models ran. **No Langfuse.**

---

## 5. Risk + Judge data flow (deterministic features, computed in code)

To cut tokens and make the math reliable, the agent computes the risk signals **in code** and
passes the LLMs a compact feature summary instead of the raw rows — the model does
*judgement*, not arithmetic (LLMs are unreliable at the arithmetic and were missing overdrafts).

1. `data_access.risk_features(transfer)` pulls balances + recent history (via the existing
   `query_balance` / `query_transactions`) and reduces them to a small dict:
   `available_balance`, `balances_by_currency`, `negative_currencies`, `amount_pct_of_balance`,
   `pending_outflows_same_currency`, `projected_balance_after_pending`,
   `would_overdraft_now` / `would_overdraft_after_pending`, `status_counts`,
   `largest_recent_outflow`, `history_size`. (`@traceable`, so the features show in LangSmith.)
2. `risk.py`: `get_llm("risk_analysis").with_structured_output(RiskAssessment)` over the
   features → `RiskAssessment`.
3. `judge.py`: `get_llm("judge").with_structured_output(JudgeVerdict)` over the **same**
   features + the RiskAssessment → `JudgeVerdict` (**different model** from risk).
4. `decision.py`: proceed **iff** `risk_level != HIGH` **and** `approval == "ACCEPTED"`;
   else return a denial carrying both reasons.
5. `transfer.py`: on proceed, run the existing `interrupt()` confirmation, then the
   double-entry write.

The per-LLM prompt files describe these features ("the arithmetic is already done; do not
recompute") and cap `reason` to one short sentence to keep output tokens low.

> **Known limitation:** Anthropic's *thinking* is incompatible with structured output via
> forced tool calls, so on Claude the structured call can intermittently raise (best-effort
> via langchain's fallback). Gemini's structured output coexists with thinking. Current
> decision: **leave as-is**; prefer Gemini for roles where visible reasoning matters.

---

## 6. Files to create / modify

**New:** the whole self-contained `app/llm/` package (§2) — including `app/llm/config.py`,
`app/llm/llm_models.yaml`, and `app/llm/prompts/*`.

**Modified:**
- `app/llm.py` → deleted, replaced by the `app/llm/` package (import path unchanged).
- `requirements.txt` — add `langchain-google-genai`, `langchain-groq`, `pyyaml`; **remove
  reliance on** `langchain-anthropic` (may stay installed but is unused).
- `.env.example` — add `GOOGLE_API_KEY`, `GROQ_API_KEY`, persona default; drop the
  Anthropic key from the active path; keep LangSmith.
- `docs/roadmap.md` — note the multi-LLM workflow.

---

## 7. Suggested sequencing

1. **Scaffolding & split (no behavior change):** create `app/llm/` package, move existing
   logic into `data_access.py`, `tools.py`, `schemas.py`, `graph.py`, `state.py`; keep the
   agent working — but swap the model to `get_llm("user_intent")` (Gemini) and delete
   Anthropic. Tests stay green.
2. **factory + config + prompts:** `app/llm/config.py`, `app/llm/llm_models.yaml`,
   `factory.py`, `prompts.py`; move prompts into per-LLM YAML files
   (`app/llm/prompts/<llm>.yaml`).
3. **Risk Analysis node** (`nodes/risk.py`, Groq) — reuse data helpers.
4. **Judge node** (`nodes/judge.py`, Gemini) — different model, consumes risk output.
5. **Decision gate** (`nodes/decision.py`) + rewire `create_transfer` through the subflow,
   keeping the human `interrupt()` last.
6. **LangSmith metadata** for chosen models/persona.
7. **Persona** applied to user-facing text.

---

## 8. Testing impact

- Existing `tests/test_llm.py` mocks the LLM boundary and tests `_query_*` /
  `_create_transfer`; update import paths to the new modules — logic unaffected.
- Add unit tests: `get_llm(role)` resolves the right provider/params from YAML; prompt loader
  fallback; `decision_gate` truth table (HIGH→deny, DENIED→deny, LOW/MID+ACCEPTED→proceed).
- Mock `get_llm` to return canned `RiskAssessment` / `JudgeVerdict` so risk/judge nodes are
  deterministic (same pattern as today's `_interpret_confirmation` stub).
- Keep Allure annotations (`docs/allure.md`) on new tests.

**Verification:** `pytest -q` green, then drive the Postman transfer scenarios
(`Acceptance → money transfer must be confirmed`): LOW/MID + ACCEPTED → asks for
confirmation → executes; HIGH or DENIED → refused with reason. Confirm the LangSmith trace
shows **three calls across two distinct models** (Gemini + Groq).
