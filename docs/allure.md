# Allure Reporting

Rich, browsable test reports for the pytest suite. `allure-pytest` (pip) **writes** machine-readable
results during a run; the separate **`allure` CLI** (a Java tool) **renders** them into HTML. Two
tools, two jobs — installing one without the other is the usual "where's my report?" cause.

```
pytest ──> allure-results/ ──> allure CLI ──> allure-report/ (HTML)
```

`pytest.ini` sets `--alluredir=allure-results --clean-alluredir`, so **`allure-results/` only ever
holds the latest run** (it's wiped at the start of each run). On its own, Allure keeps no past runs.
This doc sets up a workflow that **keeps the full results of every run** so you can see a test fail
in one run and pass in a later one — with the reason for each.

## Install the Allure CLI (one time)

Needs Java (Java 21 is already installed here). Tarball method (no Node needed):

```bash
VER=2.34.1
curl -fsSL "https://repo.maven.apache.org/maven2/io/qameta/allure/allure-commandline/${VER}/allure-commandline-${VER}.tgz" -o /tmp/allure.tgz
mkdir -p ~/.local/allure && tar -xzf /tmp/allure.tgz -C ~/.local/allure --strip-components=1
ln -sf ~/.local/allure/bin/allure ~/.local/bin/allure   # ensure ~/.local/bin is on PATH
allure --version
```

(Alternatives: `npm install -g allure-commandline`, `brew install allure`, `scoop install allure`.)

## Keep every run: the workflow

Run the tests, then immediately run the report script — **before the next `pytest`**, which wipes
`allure-results/`:

```bash
ASK_EVAL=1 ASK_EVAL_N=50 pytest tests/test_ask_evaluation.py -v   # writes allure-results/ (this run only)
scripts/allure_report.sh                                          # capture it + build the report
```

`scripts/allure_report.sh` captures the fresh `allure-results/` three ways and opens the report:

| Step | Folder | Purpose |
|------|--------|---------|
| **Archive** | `allure-archive/<timestamp>/` | Full snapshot of this single run — replay it in isolation anytime. |
| **Accumulate** | `allure-accumulate/` | Growing union of ALL runs' JSONs. The report groups each test's past executions as **Retries** (failure + later pass, each with full detail). |
| **Trend** | `allure-report/history/` | Carried forward each run so the **Trend** graph compounds. |

The combined report is generated from `allure-accumulate/`, so it always shows the complete history.

### The folders

- `allure-results/` — transient; **latest run only** (pytest rewrites it every run).
- `allure-archive/<ts>/` — one immutable snapshot per run.
- `allure-accumulate/` — every run's results merged; the source of the combined report.
- `allure-report/` — the generated HTML (regenerated each time).

All four are git-ignored — never commit them.

## Viewing

```bash
# The combined "keep everything" report (Retries = each test's fail->pass history, + Trend):
scripts/allure_report.sh          # generate from allure-accumulate/ and open

# Replay ONE past run in full (pick a timestamp folder):
allure serve allure-archive/2026-07-08_10-00-00

# Quick throwaway look at just the latest run:
allure serve allure-results
```

In the combined report, open a test and expand **Retries** to see each past execution — its status,
failure message, and attachments (for `/ask` eval tests: the summary, judge rubric, and all N call
payloads). The **Trend** widget on the overview shows pass/fail across runs.

> The report shows *that* a test failed then passed and the failure/pass detail — but not *why* it
> was fixed. The code change lives in **git**. (The enterprise tool that links runs to commits and
> stores every run natively is **Allure TestOps**; not set up here.)

## What's wired in

| Where | What |
|-------|------|
| `requirements-dev.txt` | `pytest`, `pytest-html`, `allure-pytest` (test-only, not in the prod image). |
| `pytest.ini` | `--alluredir=allure-results --clean-alluredir` — fresh results each run. |
| `tests/conftest.py` | writes `allure-results/environment.properties` (Python, DB URL, model) for the Environment widget. |
| `tests/*.py` | `@allure.epic/feature/story/title` + `allure.attach(...)` annotations (cosmetic; never affect pass/fail). |

CI publishing isn't configured yet. When added, the standard move is a GitHub Actions/Jenkins Allure
step that persists the report (and its `history/`) automatically — no manual archiving.
