# Allure Reporting

Rich, browsable test reports for the pytest suite (roadmap Phase 4 §4.1). `allure-pytest`
writes machine-readable **results** during a test run; the separate **`allure` CLI** (a JVM
tool) renders them into an interactive HTML report.

```
pytest ──> allure-results/ (JSON + attachments) ──> allure CLI ──> allure-report/ (HTML)
```

## What's wired up

| Where | What it does |
|-------|--------------|
| `requirements-dev.txt` | `pytest`, `pytest-html`, `allure-pytest` (test-only; not in the prod image). |
| `pytest.ini` | `addopts = ... --alluredir=allure-results --clean-alluredir` — every run writes fresh Allure results. |
| `tests/conftest.py` | `_allure_environment` fixture writes `allure-results/environment.properties` (Python, DB URL, model) for the report's Environment widget. (Also keeps the existing `pytest-html` per-run report under `tests/reports/`.) |
| `tests/test_llm.py` | `@allure.epic/feature/story/title/step` annotations + `allure.attach(...)` for generated SQL/rows and assistant replies. |
| `.gitignore` | `allure-results/` and `allure-report/` are ignored — never commit them. |

## One-time setup

### 1. Python deps
```bash
pip install -r requirements-dev.txt
```

### 2. The Allure CLI (needs Java — Java 21 is already installed here)
The CLI is a Java app distributed separately from the pip plugin. Pick one:

**Tarball (no Node required) — how this repo was set up:**
```bash
VER=2.34.1
curl -fsSL "https://repo.maven.apache.org/maven2/io/qameta/allure/allure-commandline/${VER}/allure-commandline-${VER}.tgz" -o /tmp/allure.tgz
mkdir -p ~/.local/allure && tar -xzf /tmp/allure.tgz -C ~/.local/allure --strip-components=1
ln -sf ~/.local/allure/bin/allure ~/.local/bin/allure   # ensure ~/.local/bin is on PATH
allure --version
```

**Alternatives:**
```bash
npm install -g allure-commandline      # if you have Node
brew install allure                    # macOS
scoop install allure                   # Windows
```

> If `allure: command not found`, add the CLI to your PATH, e.g.
> `export PATH="$HOME/.local/bin:$PATH"` (put it in your shell profile to persist).

## Daily workflow

```bash
# 1. Run the tests — results land in allure-results/ automatically (via pytest.ini)
pytest

# 2a. Quick look: build a temp report and open it in the browser
allure serve allure-results

# 2b. Or produce a persistent static report
allure generate allure-results -o allure-report --clean
allure open allure-report
```

`serve` is best for local iteration (ephemeral); `generate` + `open` produces a saved
`allure-report/` you can archive or hand off.

## Reading the report

- **Behaviors** — tests grouped by the `@allure.epic → @feature → @story` hierarchy. Here:
  `Unit tests → LLM SDK → {Answer formatting, Read helpers, Money transfer (HITL)}`.
- **Suites** — grouping by file/class/module.
- A test's detail pane shows its `@allure.title`, the `with allure.step(...)` timeline, and
  **Attachments** — e.g. the SQL + rows from `_query_transactions`/`_query_balance`, or the
  assistant's reply from a `_create_transfer` branch.
- **Severity** — transfer tests are tagged `CRITICAL`/`BLOCKER` via `@allure.severity`.
- **Environment** — Python version, `DATABASE_URL`, `LLM_MODEL` (from the conftest fixture).

## Adding annotations to new tests

```python
import allure

@allure.epic("Unit tests")
@allure.feature("LLM SDK")
@allure.story("My area")
class TestThing:
    @allure.title("Human-readable test name")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_x(self):
        with allure.step("Arrange / act phase"):
            sql, rows = do_thing()
        allure.attach(sql, "SQL", allure.attachment_type.TEXT)
        allure.attach(json.dumps(rows, default=str), "rows", allure.attachment_type.JSON)
        assert ...
```

All annotations are cosmetic — they shape the report only and never affect pass/fail.

## Notes & gotchas

- **Two tools, two responsibilities:** `allure-pytest` (pip) only *writes* results; rendering
  *always* needs the `allure` CLI (Java). Installing one without the other is the usual
  "where's my report?" cause.
- `--clean-alluredir` clears `allure-results/` at the start of each run, so the report always
  reflects the latest run. Trend/history across runs would require copying
  `allure-report/history/` back into `allure-results/` before regenerating (not set up here).
- CI publishing is intentionally **not** configured yet (roadmap §4.1 last box). When added,
  a job would `pip install -r requirements-dev.txt`, run `pytest`, then upload/publish
  `allure-report/`.
