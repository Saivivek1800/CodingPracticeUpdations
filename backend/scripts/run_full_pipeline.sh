#!/bin/bash
# One-shot: generate all inputs from input.json, then push everything to beta admin.
# Continues past individual step failures so later updaters still run.
# Non-interactive: printf 'beta\n\n' | bash run_full_pipeline.sh

# Do not use set -e — we record failures and continue.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

export PYTHONUNBUFFERED=1

FAIL_COUNT=0
FAILED_STEPS=()

note_fail() {
    local step="$1"
    local ec="${2:-1}"
    echo ""
    echo ">>> PIPELINE_SKIP: step failed (exit $ec) — continuing with remaining steps."
    echo ">>>   failed_at: $step"
    FAIL_COUNT=$((FAIL_COUNT + 1))
    FAILED_STEPS+=("$step")
}

FORMATTERS=(
    "generate_input_code_data.py"
    "generate_input_desc.py"
    "generate_input_metadata.py"
    "generate_input_evaluation_metrics.py"
    "generate_input_weightages.py"
    "generate_input.py"
    "generate_input_data.py"
)

UPDATERS=(
    "run_code_updater.sh"
    "run_hints_updater.sh"
    "run_description_updater.sh"
    "run_metadata_updater.sh"
    "run_evaluation_metrics_updater.sh"
    "run_weightage_updater.sh"
    "run_loader.sh"
)

if [ "${SKIP_TESTCASES:-0}" = "1" ]; then
    echo ""
    echo ">>> SKIP_TESTCASES=1 — skipping testcase weightage updater (run_weightage_updater.sh)."
    UPDATERS=(
        "run_code_updater.sh"
        "run_hints_updater.sh"
        "run_description_updater.sh"
        "run_metadata_updater.sh"
        "run_evaluation_metrics_updater.sh"
        "run_loader.sh"
    )
fi

echo ""
echo "========== PHASE 1: FORMAT INPUTS (generate files from input.json) =========="
for f in "${FORMATTERS[@]}"; do
    echo ">>> RUNNING: $f"
    python3 "$f"
    _fmt_ec=$?
    if [ "$_fmt_ec" -ne 0 ]; then
        note_fail "PHASE_1: $f" "$_fmt_ec"
    fi
done

echo ""
echo "========== PHASE 2: PERFORM ACTIONS (push to Django admin) =========="
for s in "${UPDATERS[@]}"; do
    echo ">>> RUNNING: $s"
    printf 'beta\n\n' | bash "$s"
    _up_ec=$?
    if [ "$_up_ec" -ne 0 ]; then
        note_fail "PHASE_2: $s" "$_up_ec"
    fi
done

echo ""
echo "================================================================================"
echo ">>> FULL PIPELINE FINISHED"
if [ "$FAIL_COUNT" -eq 0 ]; then
    echo ">>> PIPELINE_SUMMARY: all steps succeeded."
    exit 0
fi

echo ">>> PIPELINE_SUMMARY: $FAIL_COUNT step(s) failed (others were still executed):"
for s in "${FAILED_STEPS[@]}"; do
    echo ">>>   - $s"
done
echo "================================================================================"
exit 1
