# MCP — config & prompts service

The LLM **routing config** and **prompts** are owned by a separate microservice and served
over **MCP (Streamable HTTP)**. The FastAPI/LangGraph app is an **MCP client** that fetches
them over the network — it keeps no local copy. See the design in
[`more_llm_calls_mcp_plan.md`](./more_llm_calls_mcp_plan.md).

```
 LangGraph app (MCP client, :5002)  ──HTTP──▶  MCP server (:8000)
   app/llm/mcp_client.py                         mcp_server/  (owns config/ + prompts/)
```

## What the server exposes

| Kind | Name | Purpose |
|------|------|---------|
| Resource | `llm-config://routing` | `llms` catalog + role→llm map + personas (JSON) |
| Prompt | `intent_gemini` | Call 1 — User Intent system prompt |
| Prompt | `risk_groq` | Call 2 — Risk Analysis system prompt |
| Prompt | `judge_gemini` | Call 3 — Judge system prompt |
| Prompt | `response` *(arg: `persona_key`)* | persona-styled user-facing reply |
| Tool | `list_roles` / `list_personas` / `reload_config` | inspection / ops |

Prompt names are **per role + model**. The client derives the name from the role's provider in
the routing config (`judge` + `google` → `judge_gemini`), so repointing a role in
`mcp_server/config/llm_models.yaml` selects that model's prompt with **no code change**.

## Run locally (two processes)

Start the MCP server **first** (the app fails fast if it's unreachable):

```bash
# 1) MCP server  (owns mcp_server/config/)
python -m mcp_server.server                 # listens on :8000  (MCP_SERVER_HOST/PORT)

# 2) LangGraph API  (MCP client)
python run.py                               # FastAPI on :5002
#   reads MCP_SERVER_URL (default http://localhost:8000/mcp)
```

Env (see `.env.example`): `MCP_SERVER_HOST`, `MCP_SERVER_PORT`, `MCP_SERVER_URL`, plus the
provider keys your roles use (`GOOGLE_API_KEY`, `GROQ_API_KEY`).

## Run with Docker Compose (three containers)

```bash
docker-compose up --build
#   mcp  -> :8000   (built from mcp_server/Dockerfile, config/prompts baked in)
#   app  -> :5002   (depends_on mcp healthcheck; MCP_SERVER_URL=http://mcp:8000/mcp)
#   ui   -> :8501
```

## Restart after changing MCP code (Docker)

The MCP server's **code and its `config/` + `prompts/` are baked into the image** at build time
(`mcp_server/Dockerfile` runs `COPY mcp_server/ ...`; there is **no** volume mount). So any edit
under `mcp_server/` — code, `config/`, or `prompts/` — needs a **rebuild**; `docker-compose
restart mcp` and the `reload_config` tool both keep serving the OLD baked-in files.

On this host `docker-compose` is **v1 (1.29.2)**, whose automatic recreate crashes on a modern
Docker Engine (`KeyError: 'ContainerConfig'` — see below). So do the rebuild + recreate
**manually** in three steps:

```bash
# 1. Rebuild the mcp image with your new code (postgres/app/ui untouched)
docker-compose build mcp

# 2. Stop + remove the old container (this is the step compose v1 can't do itself)
docker-compose rm -sf mcp        # -s stop, -f no prompt

# 3. Start a fresh container from the image you just built
docker-compose up -d mcp
```

One-liner for the same thing:

```bash
docker-compose build mcp && docker-compose rm -sf mcp && docker-compose up -d mcp
```

If your change also affects what the **app** consumes (routing config or a prompt it fetches),
refresh the app too — it caches fetched values per process:

```bash
docker-compose restart app
```

Verify it came back healthy:

```bash
docker-compose ps            # bank-mcp should be Up (healthy)
docker-compose logs -f mcp   # watch startup; Ctrl-C to stop tailing
```

### Why not just `docker-compose up -d --build mcp`?

That single command *should* rebuild and recreate in one go, and it does on **Docker Compose v2**
(`docker compose`, with a space). But **compose v1 (1.29.2, EOL 2021)** crashes when it tries to
*recreate* an existing container on a modern engine (26+): it reads a legacy `ContainerConfig`
image field the engine no longer emits, and dies with `KeyError: 'ContainerConfig'`. The image
still builds fine — only the recreate fails, which is why the manual `rm -sf` above (removing the
old container so compose only has to *create*) sidesteps it.

Better long-term fix: install **Docker Compose v2** and use `docker compose` (space, not hyphen):

```bash
sudo apt-get install docker-compose-plugin
docker compose up -d --build mcp     # v2 recreates correctly — no manual rm needed
```

## Inspect / debug

```bash
npx @modelcontextprotocol/inspector        # point it at http://localhost:8000/mcp
```

## Editing config or prompts

Edit files under `mcp_server/config/` (routing) and `mcp_server/config/prompts/` (per-model
prompts + `persona/`). The server caches them; pick up changes with either a restart or the
`reload_config` tool. The app caches fetched values per process, so restart the app to refresh.

**Docker note:** the above applies to the local two-process run. In Docker the files are baked
into the image, so edits require a **rebuild** — see
[Restart after changing MCP code (Docker)](#restart-after-changing-mcp-code-docker).

## Tests

`pytest -q` runs offline — `tests/conftest.py`'s autouse `mock_mcp` fixture serves the real
`mcp_server/config/` files to the client without a socket; `tests/test_mcp_server.py` round-trips
the server in-memory.
