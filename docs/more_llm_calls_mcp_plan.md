# Plan — Serve LLM Config & Prompts over MCP (feature branch `mcp`)

## Context

The addendum in [`more_llm_calls.md`](./more_llm_calls.md) asks us to **investigate using MCP
for the configuration and prompt requirements** of the multi-model `/ask` workflow. Today
those two concerns load from local files inside the `app/llm/` package:

- **Routing config** — `app/llm/config.py:load_llm_config()` reads `app/llm/llm_models.yaml`
  (the `llms` catalog + `roles` map + `personas`). Consumed by `llm_spec_for()` /
  `provider_for()` (factory) and by prompts.
- **Prompts/personas** — `app/llm/prompts.py:load_prompt(role)` / `load_persona(key)` read
  `app/llm/prompts/<llm>.yaml` and `prompts/persona/*.md`. Consumed by the `agent`, `risk`,
  and `judge` nodes.

**Goal:** **move all configuration files and prompts out of the LangGraph microservice and
into a separate MCP Server**, exposed via MCP's native **Resources** (config) and **Prompts**
(system prompts + persona) primitives. The Python/LangGraph microservice becomes an **MCP
Client** that fetches them over the network.

### Architecture / topology (explicit requirements)

- **Two separate processes / microservices:**
  1. **MCP Server** — a standalone process that **physically owns** the config + prompt files
     (`llm_models.yaml`, `prompts/*.yaml`, `prompts/persona/*.md`). These files **move here**
     and no longer ship inside the LangGraph service.
  2. **LangGraph microservice** — the existing Python app. It keeps the **entire core
     workflow**: the graph, **nodes, state, flow control, and all LLM calls**. None of that
     moves. It only gains an MCP **client** to retrieve config/prompts.
- **Network connection:** the client talks to the server over a **network transport**
  (**Streamable HTTP**, own host/port), never via local file access or in-process import.
- **MCP is the only source:** `config.py` / `prompts.py` always fetch via the MCP client.
  After the move, the LangGraph service has **no local copy** of the config/prompt files.

Out of scope: changing the workflow graph, risk/judge logic, model routing semantics, or
secrets handling (provider API keys stay in the LangGraph service's env, never served by MCP).

---

## Design overview

Two independent processes, talking only over HTTP:

```
  ╔════════════ PROCESS 2: MCP Server (separate service / container, port 8000) ═════╗
  ║  mcp_server/server.py  (FastMCP, transport=streamable-http)                      ║
  ║  OWNS the config + prompt files (moved here):                                    ║
  ║    mcp_server/config/llm_models.yaml                                             ║
  ║    mcp_server/config/prompts/llm*.yaml, prompts/persona/*.md                     ║
  ║  Exposes:                                                                        ║
  ║    • Resource  llm-config://routing   → llms+roles+personas (JSON)               ║
  ║    • @mcp.prompt  intent_gemini   → User Intent system prompt (Gemini-tailored)  ║
  ║    • @mcp.prompt  risk_groq       → Risk Analysis system prompt (Groq-tailored)  ║
  ║    • @mcp.prompt  judge_gemini    → Judge system prompt (Gemini-tailored)        ║
  ║    • @mcp.prompt  response        → user-facing reply prompt (persona-styled)    ║
  ╚═════════════════════════════════════════════════════════════════════════════════╝
                         ▲
                         │  NETWORK — Streamable HTTP  (MCP_SERVER_URL=http://mcp:8000/mcp)
                         │  prompts/get   +   resources/read
                         ▼
  ╔════════════ PROCESS 1: LangGraph microservice (FastAPI, port 5002) ═════════════╗
  ║  PURE ORCHESTRATION — graph, nodes, state, flow control, all LLM calls.          ║
  ║                                                                                  ║
  ║  app/llm/mcp_client.py  (sync wrapper, MCP CLIENT only)                          ║
  ║    streamablehttp_client + ClientSession                                         ║
  ║    fetch_config() / fetch_prompt(role) / fetch_response_prompt(persona)          ║
  ║    cached (lru_cache); async→sync via a worker thread+loop                       ║
  ║        ▲                                   ▲                                     ║
  ║  config.py:load_llm_config()        prompts.py:load_prompt()/load_persona()      ║
  ║  (factory.get_llm, provider_for)    intent_node / risk_node / judge_node         ║
  ╚═════════════════════════════════════════════════════════════════════════════════╝
```

The LangGraph service keeps **no local config/prompt files** — it holds only the MCP client
and the unchanged graph. The MCP Server is the sole owner of those files and runs in its own
process.

Key ideas:
- **Prompts are named per role *and* model** — `intent_gemini`, `risk_groq`, `judge_gemini`,
  plus a dedicated `response` prompt for the user-facing reply. This directly satisfies the
  "tailored system prompt **per model**" requirement (a Gemini judge prompt differs from a
  Groq one).
- **The client derives the prompt name from config, not hardcode.** `fetch_prompt(role)` reads
  the role→model mapping from the routing resource and asks for `f"{intent|risk|judge}_{model
  family}"`. So repointing a role to another model in `llm_models.yaml` automatically selects
  that model's prompt — still **no code change** to swap models.
- **Prompt resolution lives server-side.** The server owns the files and returns final prompt
  text; the client only names what it wants.

---

## MCP surface (sources, tools, templates)

The server exposes all three MCP primitives. The **app only consumes** the items marked
*"used by app"*; the rest exist for inspection, debugging, and MCP completeness (e.g. via the
MCP Inspector or another agent).

### Resources (sources) — `@mcp.resource`
Read-only data, addressed by URI.

| URI | Returns | Used by app |
|-----|---------|:-----------:|
| `llm-config://routing` | Full routing config: `llms` catalog + `roles` map + `personas` (JSON). | ✅ `config.load_llm_config()` |
| `llm-config://roles` | Convenience list of `role → catalog llm name`. | inspection |
| `llm-config://personas` | The persona key → file-name map. | inspection |

### Resource templates (parameterized sources) — `@mcp.resource("…/{param}")`
URI templates the client expands with arguments.

| URI template | Returns | Used by app |
|--------------|---------|:-----------:|
| `llm-config://role/{role}` | The resolved spec (`provider`/`model`/`temperature`/…) for one role. | inspection |
| `llm-config://prompt-file/{llm}` | The raw prompt YAML for a catalog llm (`llm1`…`llm4`) for debugging. | inspection |

### Tools — `@mcp.tool`
Callable actions (for agents / operators).

| Tool | Args | Does | Used by app |
|------|------|------|:-----------:|
| `get_llm_spec` | `role` | Return the resolved provider/model/params for a role (same data as the `role/{role}` template, as a tool call). | inspection |
| `list_roles` | — | List the configured roles and the catalog llm each maps to. | inspection |
| `list_personas` | — | List the available persona keys. | inspection |
| `reload_config` | — | Clear the server-side file cache so edited YAML/MD is picked up **without a restart**. | ops |

### Prompt templates — `@mcp.prompt`
Named **per role + model** and fetched via `prompts/get`. One prompt per (workflow call,
model family) so each model gets tailored wording; the client selects the right name from the
role→model mapping in the routing resource.

| Prompt | Args | Returns | Used by app |
|--------|------|---------|:-----------:|
| `intent_gemini` | `persona_key?` | Call 1 — **User Intent** system prompt, Gemini-tailored. | ✅ `intent_node` |
| `risk_groq` | — | Call 2 — **Risk Analysis** system prompt, Groq-tailored. | ✅ `risk_node` |
| `judge_gemini` | — | Call 3 — **Judge** system prompt, Gemini-tailored (differs from a Groq judge). | ✅ `judge_node` |
| `response` | `persona_key?` | User-facing **reply** prompt, styled by the active persona (young→casual, older→formal). | ✅ user-facing text |

- Prompt name convention: `f"{intent|risk|judge}_{model_family}"`, e.g. swapping the judge to
  Groq makes the client request `judge_groq` — add that prompt on the server, change no code.
- `persona_key` is an argument only on the prompts that emit user-facing text (`intent_gemini`,
  `response`); risk/judge prompts are internal and persona-free.

> **Minimum viable surface** (what the workflow strictly needs): the `llm-config://routing`
> resource plus the four prompts above (`intent_gemini`, `risk_groq`, `judge_gemini`,
> `response`). The extra resources/templates/tools are additive and can be implemented
> incrementally.

---

## Service 2 (NEW, separate process): `mcp_server/`

A standalone microservice that **owns the relocated files** and runs in its own process /
container. It has **no dependency on `app/`** — it can be deployed independently.

```
mcp_server/
  __init__.py
  server.py            # FastMCP app, transport=streamable-http (port 8000)
  files.py             # file access + resolution (no MCP imports)
  config/              # ← the files MOVED out of app/llm/
    llm_models.yaml
    prompts/
      intent_gemini.md     # Call 1 — User Intent (Gemini)
      risk_groq.md         # Call 2 — Risk Analysis (Groq)
      judge_gemini.md      # Call 3 — Judge (Gemini)
      response.md          # user-facing reply template
      persona/ formal.md, casual.md
  Dockerfile           # (or reuse root image with a different command)
  requirements.txt     # mcp, pyyaml, uvicorn — server-only deps
```

### `mcp_server/files.py` — file access (no MCP imports)
The single source of truth for reading the relocated files (logic lifted from the old
`config.py` / `prompts.py`):
- path constants for `config/llm_models.yaml` and `config/prompts/`.
- `read_routing() -> dict` — `yaml.safe_load(llm_models.yaml)`.
- `read_prompt(name) -> str` — read `config/prompts/<name>.md` (e.g. `intent_gemini`).
- `resolve_persona(key|None) -> str` — old `prompts.load_persona` body.

### `mcp_server/server.py` — FastMCP streamable-HTTP server
- `from mcp.server.fastmcp import FastMCP`; `mcp = FastMCP("bank-llm-config")`.
- `@mcp.resource("llm-config://routing")` → returns `json.dumps(files.read_routing())`.
- One `@mcp.prompt()` per (call, model), matching the diagram:
  - `intent_gemini(persona_key: str | None = None)` → intent prompt (+ persona injected).
  - `risk_groq()` → risk-analysis prompt.
  - `judge_gemini()` → judge prompt.
  - `response(persona_key: str | None = None)` → user-facing reply prompt (+ persona).
- (Plus the inspection resources/templates/tools from the *MCP surface* section.)
- `__main__`: read host/port from env (`MCP_SERVER_HOST` default `0.0.0.0`,
  `MCP_SERVER_PORT` default `8000`) and `mcp.run(transport="streamable-http")`.
- Runnable as `python -m mcp_server.server`.

## Service 1 (existing LangGraph microservice): client only

### `app/llm/mcp_client.py` — sync MCP **client** (the only new file in `app/`)
The hard part: the loaders are **sync** and run inside graph nodes that may execute under a
live asyncio loop (FastAPI / `langgraph dev`), so `asyncio.run()` would fail. Use a dedicated
background thread that owns its own event loop, and submit coroutines with
`run_coroutine_threadsafe(...).result()`. Wrap that in a `_run(coro)` helper. Because every
public function is `@lru_cache`d, the **network** call is made **once per process** per
resource/role/persona.

- `fetch_config() -> dict` → open `streamablehttp_client(MCP_SERVER_URL)` →
  `ClientSession` → `read_resource("llm-config://routing")` → parse JSON.
- `fetch_prompt(role) -> str` → derive the prompt name from the routing config
  (`f"{intent|risk|judge}_{model_family}"`, e.g. role `judge` + Gemini → `judge_gemini`), then
  `session.get_prompt(name, {...})` → extract the message text. A small `role → short` map
  (`user_intent→intent`, `risk_analysis→risk`, `judge→judge`) plus `provider→family` keeps
  this swap-safe.
- `fetch_response_prompt(persona_key) -> str` → `session.get_prompt("response", {...})` for
  the user-facing reply.
- `MCP_SERVER_URL` from env (default `http://localhost:8000/mcp`). Read it directly via
  `os.getenv` (not via `config.settings`) to avoid a `config ↔ client` import cycle.

---

## Modified files (LangGraph service)

### `app/llm/config.py`
- `load_llm_config()` → `return mcp_client.fetch_config()` (drop the `open()/yaml` read).
- Keep `Settings` (API keys, `default_persona`); **add** `mcp_server_url` field for
  visibility/.env documentation (client still reads env directly to avoid the cycle).
- `llm_spec_for()` / `provider_for()` unchanged — they operate on the dict returned above.
- **Delete** the `PACKAGE_DIR` / `llm_models_path` / `prompts_dir` path constants — those
  files are gone from this service (moved to `mcp_server/config/`).

### `app/llm/prompts.py`
- `load_prompt(role)` → `return mcp_client.fetch_prompt(role)` (client picks the per-model
  prompt name, e.g. `risk_groq`).
- `load_persona(key=None)` is **folded into** the `response` / `intent_gemini` prompts, which
  take `persona_key` server-side. Keep a thin `load_response_prompt(persona=None)` helper that
  calls `mcp_client.fetch_response_prompt(...)` for user-facing text.
- Remove `_llm_for_role` / `_prompts_for_llm` / direct file reads (now server-side). The node
  call sites stay **unchanged** apart from the agent's persona now coming via the prompt arg.

### Relocate (git move) — out of the LangGraph service
- `app/llm/llm_models.yaml` → `mcp_server/config/llm_models.yaml`
- `app/llm/prompts/llm*.yaml` → split/rename into per-(call,model) files
  `mcp_server/config/prompts/{intent_gemini,risk_groq,judge_gemini,response}.md`
- `app/llm/prompts/persona/**` → `mcp_server/config/prompts/persona/**`
  After this, `app/llm/` contains **no** config/prompt files.

### `mcp_server/Dockerfile` (the MCP service ships as its own image)
A dedicated, minimal image — independent of the LangGraph app image, so the server can be
built, versioned, and deployed on its own:

```dockerfile
FROM python:3.12-slim
WORKDIR /srv
COPY mcp_server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY mcp_server/ ./mcp_server/          # code + config/ + prompts/ all bundled in the image
EXPOSE 8000
ENV MCP_SERVER_HOST=0.0.0.0 MCP_SERVER_PORT=8000
CMD ["python", "-m", "mcp_server.server"]
```
The config/prompt files are **baked into this image** (they live only here now). Build:
`docker build -f mcp_server/Dockerfile -t bank-mcp .`.

### `docker-compose.yml` (three independent containers)
```yaml
services:
  mcp:
    build:
      context: .
      dockerfile: mcp_server/Dockerfile
    container_name: bank-mcp
    env_file: .env
    ports:
      - "8000:8000"
    healthcheck:                         # gate `app` startup on the server being ready
      test: ["CMD-SHELL", "python -c \"import urllib.request,sys; urllib.request.urlopen('http://localhost:8000/mcp'); \" || exit 1"]
      interval: 5s
      timeout: 5s
      retries: 5

  app:                                   # LangGraph / FastAPI, port 5002
    build: .
    container_name: bank-app
    env_file: .env
    environment:
      MCP_SERVER_URL: http://mcp:8000/mcp   # reaches the server by compose service name
    ports:
      - "5002:5002"
    depends_on:
      mcp:
        condition: service_healthy
  # ui: unchanged except it still depends_on: [app]
```
- `mcp` is a **separate container/process**; `app` cannot start until its healthcheck passes
  (proves the network-only dependency). Tune the healthcheck command if FastMCP's
  unauthenticated GET on `/mcp` returns a non-200 — fall back to a TCP-port check.

### `.env.example`
- Add `MCP_SERVER_HOST=0.0.0.0`, `MCP_SERVER_PORT=8000`,
  `MCP_SERVER_URL=http://localhost:8000/mcp` with a one-line comment.

### `requirements.txt`
- `mcp` is already present. Confirm the installed extra provides the streamable-http
  server/client (`mcp.server.fastmcp`, `mcp.client.streamable_http`); add `uvicorn`/`httpx`
  only if an import check shows they're missing (both are typically transitive deps).

### Docs
- Update the `more_llm_calls.md` addendum (or add a short `docs/mcp.md`) noting MCP is now the
  live source, how to run the server, and the resource/prompt names.
- Tick the relevant roadmap checkbox if one exists.

---

## Tests (`tests/`)
- Existing tests mock the LLM boundary but now also hit config/prompts over the network →
  **mock the MCP client**: monkeypatch
  `app.llm.mcp_client.fetch_config / fetch_prompt / fetch_response_prompt` to return canned
  data (catalog dict, prompt strings). Add a shared fixture so unit tests for `decision_gate`,
  risk, and judge stay offline and deterministic (no server required).
- Add `tests/test_mcp_server.py` (tests the server service in-process):
  - **Round-trip** using FastMCP's in-memory client session (no socket): assert
    `risk_groq`, `judge_gemini`, `intent_gemini`, `response`, and the `llm-config://routing`
    resource match what the relocated `mcp_server/config/` files contain.
  - `mcp_client._run` bridge returns correctly when called from inside a running event loop.
- Keep Allure annotations per `docs/allure.md`.

---

## Verification
Two processes — start the **MCP Server** first, then the LangGraph service.
1. `pip install -r requirements.txt`; sanity-check imports:
   `python -c "from mcp.server.fastmcp import FastMCP; import mcp.client.streamable_http"`.
2. **Process 2** — start the MCP Server: `python -m mcp_server.server` (listens on `:8000`).
3. Inspect it from another machine/process over the network: `npx
   @modelcontextprotocol/inspector` (or a small script) against `http://localhost:8000/mcp` →
   confirm the `llm-config://routing` resource and the `intent_gemini` / `risk_groq` /
   `judge_gemini` / `response` prompts are listed and return the expected content.
4. **Process 1** — with the server up, run the API on **:5002** (`uvicorn app.main:app
   --port 5002` / `run.py`) and POST to `/ask`:
   - a read question → answers (config + intent prompt fetched from MCP over HTTP);
   - a transfer → risk + judge run, gate + human `interrupt()` behave as before.
   Confirm via logs/LangSmith that the run still shows **3 calls across 2 models**; optionally
   add a `config_source:mcp` trace tag in `factory.trace_config`.
5. Stop the MCP Server and confirm the LangGraph service fails fast with a clear error (proves
   it is the single, network-only source) — then restart.
6. `pytest -q` green; `docker-compose up` brings up `mcp` (`:8000`) + `app` (`:5002`) + `ui`
   as **separate containers** and the same `/ask` flows work container-to-container via
   `http://mcp:8000/mcp`.

## Risks / notes
- **Single source of truth**: with MCP-only, the graph hard-depends on the server being up
  (intended). The dev workflow gains one step: start the MCP Server process before the API /
  `langgraph dev`. Document this prominently.
- **Sync/async bridge** is the main implementation subtlety — the worker-thread+loop pattern
  in `mcp_client.py` must be correct under both sync (pytest) and async (FastAPI/langgraph)
  callers.
- **Caching**: `lru_cache` means config/prompt edits require a server restart (same as today's
  in-process caches) — acceptable and worth a note.
