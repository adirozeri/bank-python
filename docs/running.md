# Running the app

Two supported ways to run the stack:

- **Workflow 1 — all in Docker:** one command starts everything. Best for a quick
  "just run it" or to test the real container images.
- **Workflow 2 — hybrid (dev loop):** DB + MCP server in Docker; **API and UI on the
  host** (`python run.py`, `streamlit run ui/chat.py`). Best while coding — both host
  processes auto-reload on save, so no Docker rebuild.

Both work off the same `.env` and `docker-compose.yml`; the only value that differs
between them (`DATABASE_URL`) is handled automatically — see "How the two modes
coexist" below.

## What runs

`docker-compose.yml` defines **four** services (it is *not* just Postgres):

| Service          | Container       | What it is                                   | Port (host) |
|------------------|-----------------|----------------------------------------------|-------------|
| `postgres`       | `bank-postgres` | Database (`image: postgres:16`, pulled)      | 5432        |
| `mcp`            | `bank-mcp`      | MCP server — serves LLM config + prompts     | 8000        |
| `app`            | `bank-app`      | FastAPI API (the MCP client)                 | 5002        |
| `ui`             | `bank-ui`       | Streamlit chat UI                            | 8501        |

Dependency order (enforced by healthchecks / `depends_on`):
`postgres` + `mcp` come up healthy → `app` starts → `ui` starts.

## Prerequisites

1. **A `.env` file** in the repo root (copy `.env.example` and fill it in). It must
   contain provider keys (`GOOGLE_API_KEY`, `GROQ_API_KEY`, `ANTHROPIC_API_KEY`) and a
   `DATABASE_URL`. Keep `DATABASE_URL` pointed at **`localhost`** (host value) — Compose
   overrides it to `postgres` automatically for the containerized app.
2. **Docker** running.

## Workflow 1 — all in Docker (one command)

Everything (DB, MCP, API, UI) runs as containers. Nothing to install on the host but
Docker itself.

**1. Start the whole stack:**

```bash
docker-compose up -d
```

With no service name this targets **all four** services. The services with a `build:`
block (`mcp`, `app`, `ui`) are built the first time (you'll see `Building mcp` etc.);
`postgres` is pulled. Later `up` runs reuse the cached images — add `--build` to rebuild
after a code change (containers hold a snapshot of the code, so a rebuild is required for
edits to take effect in this mode).

**2. Wait for health and verify:**

```bash
docker-compose ps                                                     # all four Up; postgres + mcp (healthy)
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5002/docs   # expect 200
```

`app` won't start until `postgres` and `mcp` are healthy (`depends_on`), so give it a few
seconds.

**3. (Optional) seed sample data** — run the seeder inside the `app` container:

```bash
docker-compose exec app python -m scripts.seed     # run as a module, not python scripts/seed.py
```

**4. Open it:** **UI** → http://localhost:8501  ·  **API docs** → http://localhost:5002/docs

**Stop it:**

```bash
docker-compose down        # stop + remove containers (data in the pg volume survives)
docker-compose down -v     # also wipe the Postgres volume (fresh DB next time)
```

## Workflow 2 — hybrid: infra in Docker, API + UI on the host (dev loop)

DB + MCP server stay in Docker; the **API and UI run on the host** so edits reload
instantly with no rebuild. Use this while coding. You'll want **three terminals** for the
three foreground host processes.

**1. One-time host setup** — install the Python deps (a virtualenv is recommended):

```bash
python -m venv .venv && source .venv/bin/activate   # optional but recommended
pip install -r requirements.txt
```

**2. Start the infra in Docker:**

```bash
docker-compose up -d postgres mcp     # DB (:5432) + MCP server (:8000)
docker-compose ps                     # both should be Up / (healthy) before continuing
```

**3. Start the API on the host** (terminal 1) — needs the MCP server from step 2 up:

```bash
python run.py                         # FastAPI on :5002, uvicorn reload=True
```

**4. (Optional) seed sample data** (terminal 2, once the DB is up):

```bash
python -m scripts.seed                # run as a module, not python scripts/seed.py
```

**5. Start the UI on the host** (terminal 2 or 3):

```bash
streamlit run ui/chat.py              # Streamlit on :8501
```

**6. Open it:** **UI** → http://localhost:8501  ·  **API docs** → http://localhost:5002/docs

**Why no rebuild here:** the host processes run your working-tree code directly. `run.py`
starts uvicorn with `reload=True` and Streamlit reloads on save, so code changes are
picked up immediately — no `docker-compose build` / `down`.

**How the host reaches the containers:** through Compose's published ports — the API hits
Postgres at `localhost:5432` and the MCP server at `localhost:8000` (its default
`MCP_SERVER_URL`); the UI hits the API at `localhost:5002` (its default `API_URL`). This
is why `.env` keeps `DATABASE_URL` on `localhost` (see below).

**Stop it:** `Ctrl-C` the two host processes, then `docker-compose down` for the infra.

## How the two modes coexist (the `DATABASE_URL` trick)

`localhost` means "the machine I'm running on" — which differs by mode:

| The API runs… | `localhost` means | Postgres address it needs |
|---------------|-------------------|---------------------------|
| on the host (`python run.py`) | your machine | `@localhost:5432` |
| in the `app` container (Docker) | the container itself | `@postgres:5432` (Compose service name) |

Rather than editing `.env` every time you switch, we let both live side by side:

- **`.env`** holds the **host** value: `DATABASE_URL=...@localhost:5432/bankdb`.
- **`docker-compose.yml`** sets an `environment:` **override** on the `app` service:
  `DATABASE_URL=...@postgres:5432/bankdb`. A Compose `environment:` value takes
  precedence over `env_file`, so the container uses `postgres` while the host uses
  `localhost` — no manual switching. (`MCP_SERVER_URL` is overridden the same way:
  `http://mcp:8000/mcp` in-container vs the `localhost:8000` default on the host.)

Symptom of getting this wrong: `bank-app` exits with
`psycopg2.OperationalError: connection to server at "localhost" ... Connection refused`
(a container trying to reach Postgres at `localhost` instead of `postgres`).

## Evaluating the /ask agent (black-box test suite)

`tests/test_ask_evaluation.py` drives the **running** API over HTTP and grades the agent's
answers with an LLM judge (Groq). It is opt-in — a plain `pytest` run skips it — because a
full run fires hundreds of real LLM calls.

With the stack up (either workflow above) and the DB seeded:

```bash
ASK_EVAL=1 ASK_EVAL_N=3 pytest tests/test_ask_evaluation.py -v   # cheap smoke pass (~1 min)
ASK_EVAL=1 pytest tests/test_ask_evaluation.py                   # full run: 4 questions x 100 asks
allure serve allure-results                                      # per-call answers, verdicts, latencies
```

Four question categories (allowed data question, gibberish, forbidden SQL/rows request,
off-domain general question); each category must keep 100% clean functional responses
(schema + no internal leakage) and reach a ≥ 90% judge pass-rate.

**Full guide — behavior, configuration, reading results, known limitations:**
[`docs/ask_evaluation.md`](ask_evaluation.md).

## Common commands

```bash
docker-compose ps                 # status of all services
docker-compose logs -f app        # follow one service's logs (or mcp / ui / postgres)
docker-compose up -d --build      # rebuild images then start (after code changes)
docker-compose up -d postgres     # start ONLY Postgres (e.g. running the API via uvicorn)
docker-compose down               # stop and remove containers
docker-compose down -v            # also delete the Postgres volume (wipes DB data)
```

## Gotcha — legacy `docker-compose` v1 crashes on recreate

If you're on the old **`docker-compose` v1** (e.g. 1.29.2), re-running `up` on
already-existing containers can crash with:

```
KeyError: 'ContainerConfig'
```

This is a v1 bug against modern Docker images, not an app problem. Two options:

- **Workaround (quick):** remove the containers first, then start fresh —
  ```bash
  docker-compose down
  docker-compose up -d
  ```
- **Fix (permanent):** use Compose **v2** and invoke it as `docker compose` (a space,
  not a hyphen). v2 also uses BuildKit by default, which silences the
  "legacy builder is deprecated" warning.
