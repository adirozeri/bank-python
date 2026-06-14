# Bank App — Build Roadmap

A backend-only banking application built with **Python + FastAPI**. No frontend in
the API layer (testing/driving via **Postman**); analyst-facing UI arrives later via
**Streamlit**. A core `transactions` table is the heart of the system, and an
**LLM SDK built on LangGraph** lets users ask natural-language questions against that
table.

---

## Tech Stack Overview

| Concern              | Technology                                  | Introduced In |
|----------------------|---------------------------------------------|---------------|
| API framework        | FastAPI + Uvicorn                           | Phase 1       |
| Data validation      | Pydantic v2                                 | Phase 1       |
| Local database       | PostgreSQL + SQLAlchemy + Alembic           | Phase 1       |
| API client / testing | Postman                                     | Phase 1       |
| LLM orchestration    | LangGraph + Anthropic Claude SDK            | Phase 1       |
| Containerization     | Docker + Docker Compose                     | Phase 1       |
| Cloud data warehouse | Snowflake                                   | Phase 2       |
| Analyst UI / KPIs    | Streamlit                                   | Phase 3       |
| Testing + reporting  | pytest + Allure                             | Phase 4       |
| Logging / dashboards | Elasticsearch + Kibana (ELK)                | Phase 4       |
| Deployment           | AWS EC2 + S3                                 | Phase 5       |

---

## Phase 1 — Core API + LangGraph LLM SDK

**Goal:** A running, containerized FastAPI service backed by a `transactions` table,
fully exercisable in Postman, with a LangGraph agent that answers questions about
transactions.

### 1.1 Project scaffolding
- [ ] Initialize repo, `pyproject.toml` (or `requirements.txt`), virtualenv
- [ ] Folder structure (`app/`, `app/api/`, `app/models/`, `app/services/`, `app/llm/`)
- [ ] Config via environment variables (`pydantic-settings`, `.env` + `.env.example`)
- [ ] Pre-commit hooks (ruff/black) — optional but recommended

### 1.2 Database & models
- [ ] PostgreSQL running locally (via Docker, see 1.6)
- [ ] SQLAlchemy engine/session setup
- [ ] `transactions` table schema:
  - `id` (PK, UUID)
  - `account_id`
  - `amount` (numeric)
  - `currency`
  - `type` (debit / credit / transfer)
  - `status` (pending / completed / failed)
  - `counterparty`
  - `description` / `category`
  - `created_at`, `updated_at`
- [ ] Alembic migrations
- [ ] Seed script with sample transactions

### 1.3 FastAPI endpoints
- [ ] `GET /health`
- [ ] `POST /transactions` — create
- [ ] `GET /transactions` — list with filters (account, date range, type, status) + pagination
- [ ] `GET /transactions/{id}` — fetch one
- [ ] `PATCH /transactions/{id}` — update status (optional)
- [ ] Pydantic request/response schemas
- [ ] Centralized error handling

### 1.4 LangGraph LLM SDK ("ask questions on the transactions table")
- [ ] Reusable internal SDK module (`app/llm/`)
- [ ] LangGraph graph: parse question → generate query → execute → summarize answer
- [ ] **Text-to-SQL** (or tool-calling) against the `transactions` table
- [ ] Guardrails: read-only DB role, statement allow-list, row limits
- [ ] `POST /ask` endpoint that takes a natural-language question and returns an answer
- [ ] Return both the natural-language answer and the underlying query/rows for transparency

### 1.5 Postman
- [ ] Postman collection covering every endpoint
- [ ] Environment file (base URL, sample IDs)
- [ ] Example requests/responses saved for `/ask`
- [ ] Export collection into repo (`/postman`)

### 1.6 Docker (introduced here)
- [ ] `Dockerfile` for the FastAPI app
- [ ] `docker-compose.yml`: `api` + `postgres` services
- [ ] Volume for Postgres data; healthchecks; `.dockerignore`
- [ ] One-command local startup (`docker compose up`)

**Exit criteria:** `docker compose up` brings up API + DB; Postman collection runs green;
`/ask` answers a real question about seeded transactions.

---

## Phase 2 — Snowflake Integration

**Goal:** Move analytical/warehouse data into Snowflake; let the LLM query it there.

- [ ] Snowflake account, warehouse, database, schema, role setup
- [ ] Snowflake connector / SQLAlchemy dialect (`snowflake-sqlalchemy`)
- [ ] Define source of truth: OLTP in Postgres, analytics in Snowflake
- [ ] ELT pipeline: load/sync `transactions` from Postgres → Snowflake
  - [ ] Batch load script (and a path to incremental/CDC later)
- [ ] Parameterize LLM SDK to target Snowflake for analytical questions
- [ ] Secrets handling for Snowflake creds (env vars / secrets manager)
- [ ] Update Postman with any new warehouse-backed endpoints

**Exit criteria:** Transactions are queryable in Snowflake; `/ask` can answer analytical
questions using the warehouse.

---

## Phase 3 — Streamlit Analyst Dashboard

**Goal:** Internal-only UI for company analysts showing information and KPIs.

- [ ] Separate Streamlit app (own container/service)
- [ ] Connect to Snowflake (and/or API) as the data source
- [ ] KPI tiles: total volume, transaction count, avg ticket, failure rate,
      debit/credit split, top categories/counterparties
- [ ] Charts: transactions over time, volume by type/status, trends
- [ ] Filters: date range, account, type, status
- [ ] Embed the LangGraph "ask a question" box in the UI
- [ ] Basic auth/access control (internal users only)
- [ ] Add Streamlit service to `docker-compose.yml`

**Exit criteria:** Analysts can open the dashboard, filter data, view KPIs, and ask
NL questions.

---

## Phase 4 — Testing (pytest + Allure) & Observability (Kibana)

**Goal:** Confidence via automated tests with rich reporting, plus centralized logging
and dashboards.

### 4.1 pytest + Allure
- [ ] `pytest` setup with fixtures (test DB, FastAPI `TestClient`)
- [ ] Unit tests: models, services, LLM SDK helpers
- [ ] API/integration tests: every endpoint, happy + error paths
- [ ] LLM SDK tests: deterministic checks + mocked LLM where needed
- [ ] `allure-pytest` for results; generate Allure HTML report
- [ ] Test data isolation (transactional rollbacks / ephemeral DB)
- [ ] CI step to run tests and publish the Allure report

### 4.2 Logging + Kibana (introduced here)
- [ ] Structured JSON logging across API + LLM SDK (request IDs, latencies)
- [ ] Ship logs to Elasticsearch (Filebeat/Logstash or direct)
- [ ] Add `elasticsearch` + `kibana` services to Docker Compose
- [ ] Kibana dashboards: request volume, error rates, `/ask` latency, slow queries
- [ ] Index lifecycle / retention policy

**Exit criteria:** `pytest` runs produce an Allure report; logs flow into Kibana with
working dashboards.

---

## Phase 5 — Deployment (AWS EC2 + S3)

**Goal:** Run the system in AWS.

- [ ] Containerize for production (multi-stage builds, non-root user)
- [ ] EC2 instance(s): security groups, IAM roles, SSH/SSM access
- [ ] Run stack via Docker Compose on EC2 (or split services as needed)
- [ ] Reverse proxy + TLS (Nginx/Caddy) in front of FastAPI
- [ ] S3 usage:
  - [ ] Store exports/reports, Allure report artifacts, backups
  - [ ] Optional: static assets / data file landing zone for ELT
- [ ] Secrets via AWS Secrets Manager / SSM Parameter Store
- [ ] Snowflake + Anthropic credentials wired securely in cloud
- [ ] Logging/monitoring in cloud (ship to Elasticsearch/Kibana or managed equivalent)
- [ ] CI/CD: build image → push to ECR → deploy to EC2
- [ ] Backups & basic runbook

**Exit criteria:** Public/internal endpoints reachable on EC2; artifacts in S3;
secrets managed; deploy is repeatable.

---

## Cross-Cutting Concerns (apply every phase)
- **Security:** read-only DB role for the LLM, input validation, secrets never in code,
  least-privilege IAM.
- **Config:** 12-factor; everything via env vars; `.env.example` kept current.
- **Docs:** keep `CLAUDE.md`, this roadmap, and Postman collection in sync.
- **Cost control:** mind Snowflake warehouse auto-suspend, EC2 sizing, LLM token usage.

---

## Suggested Build Order (quick view)
1. Scaffold → DB + `transactions` → CRUD endpoints → Dockerize (Phase 1)
2. LangGraph `/ask` over Postgres (Phase 1)
3. Snowflake load + analytical `/ask` (Phase 2)
4. Streamlit KPIs for analysts (Phase 3)
5. pytest + Allure, then Kibana logging (Phase 4)
6. Ship to EC2 + S3 (Phase 5)
