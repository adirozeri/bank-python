# LangSmith tools

Utilities for pulling observability data out of LangSmith.

## `explore_traces.ipynb`

A notebook to download **runs**, **trace trees**, and **conversation threads** from LangSmith
and save them as JSON under `langsmith/exports/` (git-ignored).

### Prerequisites
- `LANGSMITH_API_KEY` and `LANGSMITH_PROJECT` in the project `.env` (the `langsmith` SDK is
  already a dependency).
- A Jupyter runner: VS Code's notebook UI, or `pip install jupyter && jupyter lab`.

### Usage
1. Run the **Setup** cell (creates the `Client` and the `exports/` dir).
2. Run **Browse recent runs** to list recent runs with their `run_id` / `trace_id`.
3. Run the export cell you need, after pasting an id into the `UPPER_CASE` variable:
   - **Single run** — `client.read_run(run_id)` → `exports/run-<id>.json`
   - **Full trace tree** — `client.list_runs(trace_id=...)` → `exports/trace-<id>.json`
   - **Thread** — runs sharing `metadata.session_id` (set by `ask()` / the probe) →
     `exports/thread-<id>.json`

Each export is written via `save_json(...)`, pretty-printed with `default=str` so UUIDs and
timestamps serialize cleanly.
