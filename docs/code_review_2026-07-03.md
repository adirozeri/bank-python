# Full Code & Architecture Review — 2026-07-03

Scope: the entire codebase (all commits through `120cc65` plus the uncommitted
working-tree changes), reviewed on three axes:

- **Standards** — does the code follow the repo's documented standards (CLAUDE.md)
  plus a baseline of Fowler code smells?
- **Spec** — does the codebase match what CLAUDE.md and `docs/roadmap.md` ask for?
- **Architecture** — module depth, seams, and interfaces.

The Standards and Spec axes were produced by independent reviewers and are kept
separate on purpose: code can pass one axis and fail the other.

---

## ⚠️ Act on this first

**`.env.bak` holds live credentials and is not gitignored** — a real Anthropic API
key, a Snowflake URL with the password embedded, plus LangSmith, Google, and Groq
keys. `.gitignore` covers `.env` but not `.env.bak`, so a single `git add .` would
publish them.

Remediation:

1. Rotate all five credentials (Anthropic, Snowflake, LangSmith, Google, Groq).
2. Add `.env.*` to `.gitignore`.
3. Delete `.env.bak`.

Relatedly: `bank-key.pem` sits in the repo root — ignored via `*.pem`, but still
worth moving out of the repo directory.

---

## Standards

### Hard violations (documented in CLAUDE.md)

1. **Live secrets in `.env.bak`** — see above. Violates "never commit real secrets."
2. **`GET /s3/image-url` has no Postman request** (`app/main.py:96`) — violates
   "when adding an endpoint, add a matching request to the Postman collection."
3. **CLAUDE.md is badly stale** — it mandates "flat files, SQLite, no Docker,
   phase 1" against a repo with an `app/` package, an MCP microservice, Docker/k8s,
   Postgres, Snowflake, and Streamlit. Also: the LLM flow *writes*
   (`create_transfer` → `data_access.execute_transfer`) — well-gated through
   risk → judge → human confirmation, but CLAUDE.md's "read tools only SELECT"
   framing never acknowledges that a write path exists.
4. **Hardcoded DB credentials** — `bankuser:bankpass` inline in `docker-compose.yml`
   (including the uncommitted change) and `k8s/postgres-deployment.yaml:22`. The k8s
   manifest even uses `secretKeyRef` correctly for the Anthropic key while inlining
   the Postgres password.

### Verified compliant

- **SELECT-only** holds by construction — there is no text-to-SQL at all; reads are
  fixed SQLAlchemy queries in `app/llm/data_access.py`.
- **`/ask` returns exactly `{thread_id, answer}`** — rows travel only as internal
  ToolMessages (`app/llm/graph.py:_build_response`).

### Judgement calls (Fowler smell baseline)

- **Dead code:** `app/my_logging.py` is 100% commented out and imported nowhere —
  delete it.
- **Speculative Generality:** read helpers return `(sql, rows)` but every caller
  discards the SQL (`tools_runner.py:38` — "SQL is intentionally discarded") — drop
  the tuple.
- **Data Clumps:** `from_account / to_account / amount / currency` travel as a loose
  dict through `tools.py`, `tools_runner.py`, `transfer.py`, and `execute_transfer`
  — a small `TransferRequest` type would fit.
- **Duplicated Code:** the row-to-dict comprehension appears in `data_access.py:29`
  and `scripts/sync_to_snowflake.py:36`; `import uvicorn` twice in `run.py`.
- **Lying comment (uncommitted `ui/chat.py`):** the comment still says "Sidebar:"
  after the S3 demo moved to the top of the main page — above the title, which also
  reads oddly.
- **Config-in-code:** `app/s3.py:18-19` hardcodes a personal bucket and a screenshot
  filename (acknowledged as boto3 practice).
- **Drift:** `Dockerfile` EXPOSEs/serves 8000 while compose/docs use 5002 (8000 is
  the MCP server's port).

---

## Spec

1. **CLAUDE.md and `docs/roadmap.md` contradict each other and reality.**
   Roadmap 1.4 says /ask should "return both the natural-language answer and the
   underlying query/rows for transparency"; CLAUDE.md forbids exactly that; the code
   follows CLAUDE.md. CLAUDE.md names `langchain-anthropic` while roadmap 1.4a says
   "no Anthropic" and the live config (`mcp_server/config/llm_models.yaml`) uses
   Gemini/Groq. CLAUDE.md points to `roadmap.md` at the repo root (it lives at
   `docs/roadmap.md`), and `.gitignore` says not to commit CLAUDE.md even though it
   *is* the committed spec.
2. **Roadmap 1.3 partial:** `GET /transactions` has no date-range filter and no
   pagination; no Pydantic response schemas (raw ORM objects are returned); no
   centralized error handling. **1.2 partial:** no Alembic migrations
   (`create_all`), no `updated_at` column, and `amount` is `Float` — a poor type
   for money (use `Numeric`).
3. **Checkbox drift in both directions:** almost all Phase 1 boxes are unchecked yet
   done (endpoints, seed, Docker, compose, Postman); meanwhile the repo contains
   Phase 2 (Snowflake), 3 (Streamlit), 4 (pytest + Allure), and 5 (S3, EC2 docs)
   work, plus **k8s manifests that appear in no phase at all** (Phase 5 says
   Compose-on-EC2).
4. **"Read-only DB role" (roadmap 1.4) doesn't exist** — LLM reads and the transfer
   write share the same full-privilege connection. The transfer gate itself matches
   spec 1.4a exactly (`risk != HIGH AND judge == ACCEPTED`, plus an unconditional
   `interrupt()` before any write).

Residual notes: the agent can freely paraphrase row contents into `answer`
(inherent to the design), and unhandled LLM errors surface as raw 500s.

---

## Architecture

The core is genuinely well-shaped. `app.llm` is a **deep module**: the entire
interface is `ask(question, thread_id) → {thread_id, answer}`, hiding a six-node
LangGraph, three LLM providers, a risk/judge/confirm gate, and dual DB engines.
Three seams are real (two or more adapters each) and cleanly placed:

- `AnalyticsSession` (`app/database.py`) — primary engine vs. Snowflake, with a
  transparent fallback when `ANALYTICS_URL` is unset.
- `factory._BUILDERS` (`app/llm/factory.py`) — per-provider model construction
  behind one normalized spec.
- `mcp_client` (`app/llm/mcp_client.py`) — all MCP/async complexity in one file.

### Weak spots

- **The MCP config service made the config interface shallower, not deeper.**
  Reading a prompt used to cost "open a file"; now the interface a caller must know
  includes service availability, startup ordering ("start MCP first"), port
  allocation, and two layers of `lru_cache`. The server's `reload_config` tool
  clears *server* caches, but the client's `lru_cache`s stay stale until process
  restart — the reload feature can't actually work end-to-end. Fine as an MCP
  learning exercise; know that it's paying complexity rent.
- **`tools.py` has two dispatch paths, one dead.** The `@tool` bodies call
  `transactions_json`, but `tools_runner` dispatches `READ_HELPERS` by name and
  never invokes the bodies. A maintainer editing a tool body would change nothing.
  Pick one path.
- **`prompts.py` and `config.load_llm_config` are Middle Men** — pure delegation to
  `mcp_client`, kept for call-site stability. Defensible, but three names for one
  fetch.
- **API endpoints return raw ORM objects** — the response interface is "whatever
  columns the table has," so any schema change silently changes the public API.
  Pydantic response models would pin it.
- **Conversation state is a locality risk:** `MemorySaver` is in-process, so a
  paused transfer confirmation dies on restart, and anyone who guesses a
  `thread_id` can resume any conversation (no auth anywhere on the API). Fine at
  `replicas: 1`; breaks the moment you scale.
- **Repo hygiene:** ~3,370 `.bank-venv/` files and `allure-report/` are git-tracked
  (the ignore rules landed after they were added — `git rm -r --cached` them);
  `mcp` is unpinned in `requirements.txt` while the uncommitted diff uses the newer
  `streamable_http_client` symbol (works on installed mcp 1.28.1, breaks on older
  versions that only export `streamablehttp_client`); stray `downloaded_example.txt`,
  `boto3_tutorial/`, and `runs/` clutter the root.

---

## Summary

| Axis | Findings | Worst issue |
|------|----------|-------------|
| Standards | 4 hard violations + 8 judgement calls | Live secrets in un-ignored `.env.bak` |
| Spec | 4 findings | The two spec docs contradict each other and neither describes the actual system |
| Architecture | 6 weak spots (deep core, real seams) | MCP config service adds operational complexity without end-to-end reload working |
