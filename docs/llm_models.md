# LLM routing config — `mcp_server/config/llm_models.yaml`

This file is the single source of truth for **which models run the `/ask` workflow**. It's owned by
the MCP server and served as the `llm-config://routing` resource; the LangGraph app fetches it at
runtime (it keeps no local copy). See [`mcp.md`](./mcp.md) for the server/deploy side.

## The three workflow roles

Every `/ask` turn uses up to three LLM calls, one per **role**:

| Role | What it does |
|------|--------------|
| `user_intent` | Call 1 — drives the conversation and picks tools (list/count transactions, transfer). |
| `risk_analysis` | Call 2 — scores a transfer's risk from precomputed features (only on transfers). |
| `judge` | Call 3 — an independent review of the risk verdict (only on transfers). |

## File structure

1. **`llms`** — a catalog of named model definitions (provider + model + params).
2. **`role_configs`** — named bundles that map each role to a catalog model.
3. **`selected_roles_configuration`** — which bundle is live (env `SELECTED_ROLES_CONFIGURATION`
   overrides it at runtime, no rebuild needed).
4. **`personas`** — user-facing tone presets (separate concern).

Resolution happens in `mcp_server/files.py::read_routing()`, which sets the active `roles` map from
the selected config, so every consumer just reads `roles`. `thoughts` is accepted but **ignored** —
extended thinking is disabled everywhere (see `app/llm/factory.py`).

## Catalog (`llms`)

| Name | Provider | Model | Temp | max_tokens | Cost | Notes |
|------|----------|-------|:----:|:----------:|------|-------|
| `gemini_flash` | google | gemini-2.5-flash | 0 | — | Free\* | Default workhorse; free tier has daily caps |
| `gemini_pro` | google | gemini-2.5-pro | 0 | — | Free\* | Stronger reasoning; tighter free quota (low RPM/RPD) |
| `groq_llama33_70b` | groq | llama-3.3-70b-versatile | 0.2 | 1024 | Free | Fast 70B; solid general workhorse |
| `claude_sonnet` | anthropic | claude-sonnet-4-6 | 0 | — | **Paid** | Best tool-use, reasoning, consistency |
| `gemini_flash_lite` | google | gemini-2.5-flash-lite | 0 | — | Free | Highest Gemini free RPM; 1M-token context |
| `groq_llama31_8b` | groq | llama-3.1-8b-instant | 0.2 | 1024 | Free | Fastest (~840 tok/s); very high daily limit |
| `cerebras_llama33_70b` | cerebras | llama-3.3-70b | 0 | — | Free | Best free daily volume (~1M tok/day, ~2000 tok/s) |
| `openrouter_deepseek_r1` | openai\*\* | deepseek/deepseek-r1:free | 0 | — | Free | Reasoning model; slower + verbose (emits reasoning) |
| `mistral_small` | mistralai | mistral-small-latest | 0 | — | Free\* | EU-hosted/GDPR; **trains on your prompts** |
| `ollama_llama31_8b` | ollama | llama3.1:8b | 0 | — | Free/local | Unlimited, offline, private; needs `ollama serve` |

\* Free but rate/quota-limited (Gemini daily caps; Mistral requires opting into training).
\*\* `openai` provider = OpenAI-compatible endpoint; here it's OpenRouter via `base_url`.

## Role configurations (the matrix)

Cost is **Free** unless noted. "Cross-vendor" = risk and judge run on *different* providers (reduces
correlated errors / self-agreement bias).

| Config | `user_intent` | `risk_analysis` | `judge` | Cost | Cross-vendor | Best for / trade-off |
|--------|---------------|-----------------|---------|------|:------------:|----------------------|
| **`max_quality`** *(default)* | claude_sonnet | claude_sonnet | claude_sonnet | Paid | no | Top quality & tool-use; single-vendor; costs on all 3 calls |
| `balanced_free` | gemini_flash | groq_llama33_70b | gemini_flash | Free\* | yes | Solid free all-rounder, cross-vendor debias; Gemini daily caps |
| `fastest_free` | groq_llama31_8b | groq_llama33_70b | gemini_flash_lite | Free | yes | Max throughput/daily limits; small intent model is weaker |
| `reasoning_free` | cerebras_llama33_70b | openrouter_deepseek_r1 | cerebras_llama33_70b | Free | yes | R1 reasoning on **risk**; R1 slow/verbose |
| `local_offline` | ollama_llama31_8b | ollama_llama31_8b | ollama_llama31_8b | Free/local | no | Unlimited, offline, private; quality bounded by your HW/8B |
| `quality_judge` | gemini_flash | groq_llama33_70b | claude_sonnet | Paid (1/3) | yes | Cheap-but-sharp: free grunt work, Claude only on the final verdict |
| `gemini_pro_judge` | gemini_flash | gemini_flash | gemini_pro | Free\* | no | Pro reasoning on the judge; Pro's tight free quota is the bottleneck |
| `groq_only` | groq_llama31_8b | groq_llama33_70b | groq_llama33_70b | Free | no | Blazing fast, all-Groq; no risk/judge vendor separation |
| `max_diversity_free` | gemini_flash_lite | openrouter_deepseek_r1 | groq_llama33_70b | Free | yes | 3 different vendors — strongest debias story of the free configs |
| `volume_free` | groq_llama31_8b | cerebras_llama33_70b | cerebras_llama33_70b | Free | no | Best free tokens/day for batch runs; same-vendor risk/judge |
| `reasoning_judge_free` | gemini_flash | groq_llama33_70b | openrouter_deepseek_r1 | Free | yes | R1 reasoning on the **judge** (complements `reasoning_free`) |
| `local_hybrid` | ollama_llama31_8b | groq_llama33_70b | gemini_flash | Free | yes | Local intent + free cloud risk/judge; not fully offline |
| `eu_hosted` | mistral_small | ollama_llama31_8b | mistral_small | Free\* | yes | EU/GDPR-leaning (Mistral) + local risk; Mistral trains on prompts |

\* Gemini/Mistral free tiers carry the caveats noted in the catalog.

## Switching configuration

- **Edit the file:** set `selected_roles_configuration:` to any config name above. Baked into the
  MCP image → needs the MCP rebuild + app restart.
- **Env override (no rebuild):** set `SELECTED_ROLES_CONFIGURATION=<name>` in `.env` and restart the
  container. It wins over the file's selector.

Whichever role you point at a given provider, make sure its **API key** is set (see `.env`) and, for
`ollama_*`, that `ollama serve` is running with the model pulled. Use `python scripts/check_keys.py`
to confirm every configured key returns 200.
