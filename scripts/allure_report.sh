#!/usr/bin/env bash
# Keep the FULL results of every test run (not just a trend) and view them.
#
# The Allure CLI is stateless, and pytest's --clean-alluredir wipes allure-results/ at the START
# of each run. So run this script immediately AFTER a run you want to keep:
#
#   ASK_EVAL=1 ASK_EVAL_N=50 pytest tests/test_ask_evaluation.py -v
#   scripts/allure_report.sh
#
# It captures this run's fresh allure-results/ three ways, then builds one combined report:
#   1. ARCHIVE    -> allure-archive/<timestamp>/   a full snapshot of THIS run (view any run later)
#   2. ACCUMULATE -> allure-accumulate/            append into the growing union of all runs, so the
#                                                  report shows every test's past executions as
#                                                  "Retries" (see a failure AND its later pass, full
#                                                  detail: message, attachments, the N call payloads)
#   3. TREND      -> carry history/ forward         so the Trend graph compounds across runs
set -euo pipefail

RESULTS="allure-results"
ACCUM="allure-accumulate"
REPORT="allure-report"
TS="$(date +%Y-%m-%d_%H-%M-%S)"
ARCHIVE="allure-archive/$TS"

command -v allure >/dev/null 2>&1 || {
  echo "ERROR: the 'allure' CLI is not installed — see docs/allure.md (install section)." >&2
  exit 1
}
[ -d "$RESULTS" ] || { echo "ERROR: no '$RESULTS/' — run pytest first." >&2; exit 1; }

# 1. Per-run snapshot (full fidelity — browse this single run later with `allure serve`).
mkdir -p "$ARCHIVE"
cp -a "$RESULTS"/. "$ARCHIVE"/
echo "Archived this run    -> $ARCHIVE/"

# 2. Accumulate this run's result + attachment files into the growing union (top-level files only,
#    never the history/ subdir). Unique UUIDs mean no collisions; stable historyIds group a test's
#    executions across runs into Retries.
mkdir -p "$ACCUM"
find "$RESULTS" -maxdepth 1 -type f -exec cp -a {} "$ACCUM"/ \;
echo "Accumulated -> $ACCUM/ ($(find "$ACCUM" -maxdepth 1 -name '*-result.json' | wc -l) executions total)"

# 3. Carry the previous report's trend history into the accumulate dir before regenerating.
[ -d "$REPORT/history" ] && cp -a "$REPORT/history" "$ACCUM/history"

# Build the combined report (Retries + Trend across all runs) and open it.
allure generate "$ACCUM" -o "$REPORT" --clean
echo "Combined report      -> $REPORT/"
allure open "$REPORT"
