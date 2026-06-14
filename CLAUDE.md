# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project

Backend-only **banking application**. Python + FastAPI, no frontend in the API layer
(driven via Postman). A central `transactions` table is queried both via REST endpoints
and via a **LangGraph-based LLM SDK** that answers natural-language questions.

Build is phased — see `roadmap.md` for the authoritative, detailed plan.

| Phase | Scope |
|-------|-------|
| 1 | FastAPI + `transactions` table (SQLite) + Postman + LangGraph LLM "ask" SDK |
| 2 | Snowflake integration |
| 3 | Streamlit dashboard with KPIs for internal analysts |
| 4 | pytest + Allure tests; Kibana (ELK) logging/observability |
| 5 | Deploy to AWS EC2 + S3 |

**Current phase: 1 (scaffolding).**

Phase 1 is intentionally **minimal/basic** — flat files, SQLite, no Docker/Alembic yet.
Heavier infra (Postgres, Docker, Kibana, etc.) comes in later phases per the roadmap.

## Tech Stack
- **API:** FastAPI, Uvicorn, Pydantic
- **DB (Phase 1):** SQLite via SQLAlchemy (tables created with `create_all`, no migrations)
- **LLM:** LangGraph + `langchain-anthropic` (text-to-SQL over `transactions`)
- **Warehouse (Phase 2+):** Snowflake
- **Analyst UI (Phase 3+):** Streamlit
- **Tests (Phase 4+):** pytest + Allure
- **Observability (Phase 4+):** Elasticsearch + Kibana
- **Containers / Deploy:** Docker (later phases), AWS EC2 + S3 (Phase 5)

## Layout (flat — keep it simple)
```
main.py        # FastAPI app + all endpoints
database.py    # SQLAlchemy engine/session + get_db
models.py      # Transaction model
llm.py         # LangGraph agent: question -> SQL -> answer
seed.py        # sample data
postman/       # Postman collection
roadmap.md
CLAUDE.md
```

## Conventions
- Keep it basic: don't add layers (services/, schemas/, packages) unless really needed.
- Config via environment variables / `.env`; never commit real secrets.
- When adding an endpoint, add a matching request to the Postman collection.

## LLM SDK Rules
- Generated SQL must be **SELECT-only** (guardrail in `llm.py`).
- `/ask` returns the natural-language answer **and** the underlying SQL + rows.

## Common Commands
```bash
pip install -r requirements.txt
python seed.py              # optional sample data
uvicorn main:app --reload   # http://localhost:8000/docs
```

## Working Agreements for Claude
- Stay within the **current phase** unless asked to look ahead; don't pull future-phase
  tech into earlier phases.
- When adding an endpoint, also update the **Postman collection** under `postman/`.
- Keep `roadmap.md` checkboxes and this file in sync as features land.
- Treat banking data as sensitive: validate inputs, least-privilege access, no secrets in code.
