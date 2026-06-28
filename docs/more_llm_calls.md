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

---

## Addendum — Update (feature branch: `mcp`)

> The following restates and extends the requirements above. It is **additive** — nothing
> in the sections above changes. The new emphasis is the **MCP** investigation (now an
> active feature branch rather than parked) and the explicit per-persona / per-model prompt
> tailoring.

### More LLM calls

The LangGraph should have **3 calls to the LLM**:

1. **First call — User Intent** — *Done.*
2. **Second call — Risk Analysis**
   - In the case of performing a **Transaction**, there should be a **Risk Evaluation** of
     the user status and the transaction he requests.
   - **NOTE:** if you already implemented **Deterministic Risk Analysis**, keep it. It will
     be used by the Judge later.
   - The LLM should receive data to perform Risk Analysis (**balance**, **history of previous
     transactions**), and return a JSON with **risk level** (`HIGH`, `MID`, `LOW`) and
     **reason**.
3. **Third call — LLM as a Judge** to evaluate the Risk Analysis performed by the previous
   LLM call.
   - The Judge LLM should be a **different LLM model** to ensure there is no bias (see the
     configuration instructions below).
   - The Judge LLM receives data to perform evaluation (the data given to the previous LLM,
     and the JSON response answer from the LLM). The Judge should return a JSON with
     **approval** `ACCEPTED` or `DENIED`, and **reason**.
4. The Transaction will perform **only if** Risk Analysis is **below HIGH** *and* the Judge
   returned **APPROVED**. If Deterministic Risk Analysis is also implemented, it can be added
   as another condition.

> **NOTE:** the high priority in this task is the **technical flow** using LangGraph + LLM.
> The business rules that would exist in a real-world bank application (e.g. bank policy for
> deciding risk level) are **low priority**.

The end result is the agentic workflow uses **two LLMs for three LLM calls**, and the
workflow is **more probabilistic and less deterministic**.

### Configuring LLM models

Add support — by **configuration files and code** (**optional: MCP**) — for choosing and
configuring the LLMs used by the agentic workflow.

- **Configuration files:** create a configuration file indicating which LLMs will be used per
  **User Intent / Risk Analysis / Judge**. For example, Gemini will be used for User Intent
  and Judge, Groq used for Risk Analysis. The application will **load the configuration at
  runtime** for choosing LLMs per operation.
- **Code abstraction:** create an **Abstraction Layer** for retrieving LLMs at runtime
  according to the configuration. The Abstraction Layer should allow working with the
  different models in a simple way. Can use different optional APIs, e.g. LLM Provider SDK,
  LangChain wrappers, LiteLLM. The Abstraction Layer implementation should set **model-specific
  parameters**, e.g. max tokens, creativity level, temperature, API version, according to the
  specific model and API implementation.
- **Prompt files:** create **tailored system prompt files per model**, e.g. the Judge prompt
  will be different for Gemini vs Groq.
- **Prompt per user persona:** in the case where a textual response to the user is generated
  by an LLM, the text should have a **configurable persona**. For example, for a young user
  use a more light tone with casual expressions; for an older user use more formal language.

The end result is the agentic workflow has:

- **Multi-model support** enabling model replacement without code changes.
- **Prompt customization** tailored per agent or model.
- **Langfuse / LangSmith** traces of the configuration options chosen at runtime.
- **Cost-aware model routing** — choosing between a fast model and a strong model.

> **NOTE:** optionally, investigate how to use **MCP** for the above configuration and prompt
> requirements.

> **Feature branch:** `mcp`.
