# Postgres (Local Development)

How `bank-python` uses Postgres locally, how it differs from SQLite, and how to
run and inspect it. The production/k8s setup is documented separately in
`k8s/k8s deployments.md`.

## How the app chooses a database

The code never hardcodes a database. It reads one environment variable with a
SQLite fallback:

```python
# app/database.py
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./bank.db")
```

| Environment | `DATABASE_URL` source | Result |
|-------------|-----------------------|--------|
| Local       | `.env` → Postgres URL | Postgres (via Docker) |
| Kubernetes  | Deployment YAML env   | Postgres (postgres-service pod) |
| (fallback)  | nothing set           | SQLite file `bank.db` |

The same code tolerates both backends because of two details in `app/database.py`:

- **`connect_args`** is conditional — `check_same_thread=False` is SQLite-only and
  Postgres rejects it, so it is stripped for non-SQLite URLs.
- **`pool_pre_ping=True`** validates a connection before use, preventing stale
  connection errors when Postgres drops idle connections.

### `.env` loading caveat

`.env` is only read when the app is started via **`python run.py`** (it calls
`load_dotenv()`). Running `uvicorn app.main:app` directly does **not** load `.env`,
so it would silently fall back to SQLite.

## SQLite vs Postgres — why Postgres needs extra setup

- **SQLite is a library, not a server.** It is just a file (`bank.db`) plus code
  linked into the Python process. No separate process, no port, no network.
  Opening `sqlite:///./bank.db` literally reads/writes a file on disk.
- **Postgres is a client/server database.** A separate program must be *running*
  and listening on a port (5432) before the app can connect. Something has to host
  that process — that is what Docker Compose does here.

```
Postgres:  app ──TCP:5432──► postgres server process ──► data files
SQLite:    app ──function call──► bank.db file
```

This is also why there is no "compose file for SQLite": there is no server process
to run or keep alive.

## Local setup

### `docker-compose.yml`

Runs Postgres with the **same credentials as the k8s deployment**
(`bankuser` / `bankpass` / `bankdb`) so local and cluster behavior match:

```yaml
services:
  postgres:
    image: postgres:16
    container_name: bank-postgres
    environment:
      POSTGRES_USER: bankuser
      POSTGRES_PASSWORD: bankpass
      POSTGRES_DB: bankdb
    ports:
      - "5432:5432"
    volumes:
      - bank_pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U bankuser -d bankdb"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  bank_pgdata:
```

### `.env`

```
DATABASE_URL=postgresql://bankuser:bankpass@localhost:5432/bankdb
```

### Driver

`psycopg2-binary` (in `requirements.txt`) must be installed in the venv:

```bash
pip install -r requirements.txt   # or: pip install psycopg2-binary
```

## Starting the app

```bash
docker-compose up -d        # 1. start Postgres
python run.py               # 2. start the app (loads .env -> Postgres)
```

Then open http://127.0.0.1:8000/docs

The `transactions` table is created automatically on startup (`create_all`), but
the Postgres database starts **empty**. Run `python seed.py` for sample data.

Stop:

```bash
# Ctrl+C to stop the app
docker-compose down         # stop Postgres (data kept in the volume)
```

## Inspecting the running server

```bash
docker ps --filter name=bank-postgres   # is it running?
docker-compose ps                        # compose's view
docker logs -f bank-postgres             # live logs
docker stats bank-postgres               # live CPU/memory
docker inspect bank-postgres             # full JSON (env, mounts, health)
```

### Open a SQL prompt (most common)

```bash
docker exec -it bank-postgres psql -U bankuser -d bankdb
```

At the `bankdb=#` prompt:

```sql
\dt                       -- list tables (shows "transactions")
\d transactions           -- describe the table
SELECT * FROM transactions LIMIT 5;
\q                        -- quit
```

### GUI clients

Port 5432 is mapped to the host, so any desktop client (DBeaver, TablePlus,
pgAdmin, VS Code PostgreSQL extension) can connect with:

```
host: localhost   port: 5432
user: bankuser    password: bankpass    database: bankdb
```

## Where the data lives

Postgres has **no single `.db` file** (that is a SQLite thing). It stores data as a
directory tree of many files under `/var/lib/postgresql/data` inside the container:

```
/var/lib/postgresql/data/
├── base/        ← actual table/row data (one subdir per database)
├── global/      ← cluster-wide catalogs
├── pg_wal/      ← write-ahead log
├── pg_hba.conf  ← config
└── ...          ← many more
```

That directory is backed by the Docker **named volume** `bank_pgdata`, which on the
host disk lives at:

```
/var/lib/docker/volumes/bank-python_bank_pgdata/_data
```

Naming: `bank-python` (compose project, from the folder name) + `bank_pgdata`
(volume name) = `bank-python_bank_pgdata`.

**Do not read or edit these files directly** — unlike `bank.db` they are not
human-readable and editing them outside `psql`/SQL corrupts the database. Always go
through `psql` or a client.

## Persistence & gotchas

- Data **survives** `docker-compose down`, container restarts, and reboots, because
  it is in a named volume.
- Data is **deleted** only by `docker-compose down -v` or
  `docker volume rm bank-python_bank_pgdata`.
- The host volume path is root-owned (`/var/lib/docker/...`); listing it needs
  `sudo` — but you rarely should need to.
- **No migration from SQLite.** The old `bank.db` still exists in the project root,
  untouched and separate. The Postgres database starts empty; there are no
  migrations in Phase 1 (`Base.metadata.create_all` only creates missing tables).
- If another Postgres is already using host port 5432, this container will fail to
  start — stop the other one or change the port mapping.
