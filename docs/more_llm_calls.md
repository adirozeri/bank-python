# More LLM Calls

Requirements for evolving the `/ask` agent from a single-model workflow into a
multi-model, multi-call agentic workflow. The high-priority goal is the **technical flow**
(LangGraph + multiple LLMs); real-world banking business rules (e.g. actual risk policy)
are explicitly **low priority**.

> **End state:** the agentic workflow uses **two LLMs across three LLM calls**, making the
> workflow more probabilistic and less deterministic.

> **Locked decisions:** **Gemini** (Google) for *User Intent* + *Judge*, **Groq** for *Risk
> Analysis* — **no Anthropic**. Models are selected via **LangChain wrappers** driven by a
> config file. Approved transfers **always** still require the human `interrupt()`
> confirmation (never auto-execute). Tracing via **LangSmith only** (no Langfuse). **MCP is
> out of scope for now.** See [`more_llm_calls_plan.md`](./more_llm_calls_plan.md).

---

## 1. Three LLM Calls in the LangGraph workflow

The graph should make three distinct LLM calls:

### Call 1 — User Intent  ✅ *Done*
Understands what the user wants and drives tool selection (existing agent node).

### Call 2 — Risk Analysis
Runs when the user requests a **transaction**.

- Evaluates the **risk** of the user's status and the requested transaction.
- Receives the data needed to assess risk: current **balance** and **history of previous
  transactions**.
- Returns a JSON verdict:

  ```json
  { "risk_level": "HIGH | MID | LOW", "reason": "..." }
  ```

> **Note:** If a *deterministic* Risk Analysis is already implemented, **keep it** — it will
> be consumed by the Judge later as an additional signal.

### Call 3 — LLM as a Judge
Evaluates the Risk Analysis produced by Call 2.

- **Must use a different LLM model** from Call 2 to reduce bias — here **Gemini** judges the
  **Groq** risk output (see *Configuring LLM Models* below).
- Receives: the data given to the Risk Analysis LLM **and** that LLM's JSON response.
- Returns a JSON verdict:

  ```json
  { "approval": "ACCEPTED | DENIED", "reason": "..." }
  ```

### Decision rule
The transaction is performed **only if both** conditions hold:

| Condition | Requirement |
|-----------|-------------|
| Risk Analysis | risk level is **below HIGH** (i.e. `LOW` or `MID`) |
| Judge | approval is **ACCEPTED** |
| *(optional)* Deterministic Risk | if implemented, may be added as a further condition |

---

## 2. Configuring LLM Models

Add support — via **configuration files and code** (optionally MCP) — for choosing and
configuring the LLMs used by the agentic workflow.

### Configuration files
- A config file declares **which LLM is used per role**: *User Intent* / *Risk Analysis* /
  *Judge*.
- **Chosen mapping:** *Gemini* for User Intent and Judge; *Groq* for Risk Analysis.
- The application **loads the configuration at runtime** to choose the LLM per operation.

### Code abstraction layer
- An **Abstraction Layer** retrieves LLMs at runtime according to the configuration, and
  exposes them in a simple, uniform way.
- **Chosen approach: LangChain wrappers** (`langchain-google-genai`, `langchain-groq`).
- The layer sets **model-specific parameters** (max tokens, creativity/temperature, API
  version, etc.) appropriate to each model and API.

### Prompt files
- **Tailored system-prompt files per model** — e.g. the Judge prompt differs for
  Gemini vs Groq.

### Prompt per user persona
- When an LLM generates **user-facing text**, the tone should follow a **configurable
  persona** — e.g. lighter/casual expressions for a young user, more formal language for an
  older user.

---

## End Result

The agentic workflow should provide:

- **Multi-model support** — replace models without code changes.
- **Prompt customization** — tailored per agent and/or per model.
- **Tracing** — **LangSmith** captures the configuration options chosen at runtime.
- **Cost-aware model routing** — choose between a fast model and a strong model.

> **Parked for later:** using **MCP** for the configuration and prompt requirements above is
> out of scope for now.
