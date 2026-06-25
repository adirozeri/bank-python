# Running LangGraph Studio (`langgraph dev`) from scratch

This guide explains how to set up and run **LangGraph Studio** for this project's
`/ask` graph. Studio is a local visual UI that draws the graph as nodes/edges, lets
you run it step-by-step, inspect state at each node, and approve/reject the
human-in-the-loop (HITL) **confirm** interrupt.

> **Studio vs. LangSmith — don't confuse them.**
> - **LangSmith** (smith.langchain.com) records *traces* of real runs from your
>   FastAPI app. It needs only the `LANGSMITH_*` env vars — **not** `langgraph dev`.
> - **LangGraph Studio** (`langgraph dev`) is a *local* interactive graph editor/runner.
>   Use it to explore and debug the graph by hand.
> They are independent. You can use either, both, or neither.

---

## 1. Prerequisites

- Python 3.12 and the project virtualenv (`.bank-venv`) already created.
- The graph defined as a module-level object in `app/llm.py`:
  - `graph` — the `StateGraph` **builder** (what Studio should load).
  - `app_graph` — the **compiled** graph with a `MemorySaver`, used by the FastAPI app.
- An Anthropic API key (the graph calls Claude in `classify_intent`, `judge`, `summarize`).

---

## 2. Install the CLI

The LangGraph CLI and the in-memory runtime are what power `langgraph dev`:

```bash
pip install -U "langgraph-cli[inmem]"
```

This installs `langgraph-cli`, `langgraph-api`, and `langgraph-runtime-inmem`.
Verify:

```bash
langgraph --version          # e.g. "LangGraph CLI, version 0.4.29"
```

Add it to `requirements.txt` so the setup is reproducible (dev-only dependency):

```
langgraph-cli[inmem]
```

---

## 3. Configure `langgraph.json`

`langgraph.json` lives at the repo root and tells the dev server which graph(s) to
serve, which dependencies to install, and where to find env vars.

```json
{
    "dependencies": ["."],
    "graphs": {
        "bank_graph": "app.llm:graph"
    },
    "env": ".env"
}
```

Field by field:

| Field          | Meaning |
|----------------|---------|
| `dependencies` | Where to install project code from. `["."]` = this repo. |
| `graphs`       | Map of `name -> "<module-or-path>:object"`. `bank_graph` is the name shown in Studio. |
| `env`          | Path to the env file to load (`.env`). Studio reads keys from here. |

> **Important #1 — use dotted-module syntax, not a file path.**
> Use `app.llm:graph`, **not** `./app/llm.py:graph`. The runtime decides how to
> import based on whether the string contains a `/`:
> - a value with `/` (e.g. `./app/llm.py:graph`) is loaded **by file path**, *outside*
>   the `app` package — so `app/llm.py`'s relative imports (`from .database import ...`)
>   fail with `ImportError: attempted relative import with no known parent package`.
> - a value with `.` and no `/` (e.g. `app.llm:graph`) is loaded via
>   `importlib.import_module`, *as part of* the `app` package — relative imports resolve.
>
> This works because `app/__init__.py` exists (so `app` is a package) and the repo
> root is on the import path when you run `langgraph dev` from there.

> **Important #2 — point at the builder, not the compiled graph.**
> Use `app.llm:graph` (the `StateGraph` builder), **not** `app.llm:app_graph`.
> The dev server provides its **own** persistence/checkpointer. If you hand it a
> graph that was already compiled with our `MemorySaver`, it conflicts. Letting
> Studio compile the builder itself means the `confirm` **interrupt** works natively
> in the UI. The FastAPI app keeps using `app_graph` (with `MemorySaver`) separately.

---

## 4. Set environment variables (`.env`)

`langgraph dev` loads the file named in `langgraph.json`'s `env` field. Required:

```bash
# Anthropic (the graph's LLM calls)
ANTHROPIC_API_KEY=sk-ant-...
LLM_MODEL=claude-sonnet-4-6

# Database (Phase 1: local SQLite)
DATABASE_URL=sqlite:///./bank.db
```

Optional — also stream Studio runs into LangSmith:

```bash
LANGSMITH_TRACING=true            # NOT "LANGSMITH_TRACING_V2"
LANGSMITH_API_KEY=lsv2_...
LANGSMITH_PROJECT=bank-python
```

> The tracing toggle must be exactly `LANGSMITH_TRACING=true` (or the legacy
> `LANGCHAIN_TRACING_V2=true`). `LANGSMITH_TRACING_V2` is **not** a real variable
> and silently disables tracing.

`.env` is gitignored — keep real secrets there. `.env.example` documents the keys
with placeholders.

---

## 5. Run the dev server

From the repo root:

```bash
langgraph dev
```

What happens:
- A local server starts on **http://localhost:2024**.
- Your browser opens **LangGraph Studio** at a URL like
  `https://smith.langchain.com/studio/?baseUrl=http://localhost:2024`
  (the Studio front-end runs in the cloud but talks to your **local** server).
- The API docs are at **http://localhost:2024/docs**.

Useful flags:

```bash
langgraph dev --no-browser        # don't auto-open the browser
langgraph dev --port 2025         # use a different port
langgraph dev --debug-port 5678   # attach a debugger
```

Stop it with `Ctrl-C`.

---

## 6. Use Studio with this graph

1. In the left panel pick the graph: **`bank_graph`**.
2. You'll see the flow:
   `classify_intent → judge → confirm → [handle_transactions | handle_balance | handle_unknown] → summarize`,
   with the `clarify` branch off `judge`/`confirm`.
3. Provide an input matching the graph `State`, e.g.:
   ```json
   { "question": "show me transactions for account ACC-0001" }
   ```
4. Run it. Execution pauses at **`confirm`** (the `interrupt`). Studio shows the
   interrupt payload (`proposed_intent`, `message`, ...).
5. **Resume** from the UI by providing the resume value:
   - `true` to confirm → routes to the matching handler → `summarize`.
   - `false` to reject → routes to `clarify`.
6. Inspect state before/after each node, edit state and re-run from a node, and
   replay previous runs from the thread history.

---

## 7. How this relates to the FastAPI `/ask` flow

The graph logic is identical; only the *host* differs:

| | FastAPI (`python run.py`) | Studio (`langgraph dev`) |
|--|--|--|
| Port | `:8000` | `:2024` |
| Persistence / checkpointer | our `MemorySaver` on `app_graph` | provided by the dev server |
| Resume the `confirm` interrupt | 2nd `POST /ask` with `{thread_id, confirm}` | click **Resume** in the UI |
| Graph object used | `app_graph` (compiled) | `graph` (builder, compiled by Studio) |

---

## 8. Troubleshooting

- **`ImportError: attempted relative import with no known parent package`** — you used
  the file-path form (`./app/llm.py:graph`). Switch to dotted-module form
  (`app.llm:graph`) so the graph is imported as part of the `app` package. See
  "Important #1" above.
- **Graph not found** — the `graphs` value is wrong, or the object doesn't exist at
  module top level. It must be `app.llm:graph`.
- **Checkpointer/persistence conflict** — you pointed at `app_graph` (already has
  `MemorySaver`). Point at the `graph` builder instead.
- **LLM auth errors (401/403)** — `ANTHROPIC_API_KEY` missing/invalid in `.env`, or
  `langgraph.json` `env` doesn't point at the right file.
- **Port already in use** — something is on `:2024`; use `langgraph dev --port 2025`.
- **`langgraph: command not found`** — CLI not installed in the active venv:
  `pip install -U "langgraph-cli[inmem]"` (and make sure the venv is activated).
- **No traces in LangSmith** — check `LANGSMITH_TRACING=true` (exact name) and a
  valid `LANGSMITH_API_KEY`.

---

## Quick reference

```bash
# one-time install (dev dependency)
pip install -U "langgraph-cli[inmem]"

# run Studio (from repo root, with langgraph.json + .env present)
langgraph dev

# local endpoints
#   Studio  -> https://smith.langchain.com/studio/?baseUrl=http://localhost:2024
#   API     -> http://localhost:2024
#   Docs    -> http://localhost:2024/docs
```
