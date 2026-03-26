# Print a machine-readable failure block, then exit with the given code.
# Usage: pipeline_exception "PHASE_NAME" "step_name" exit_code "optional detail line"
pipeline_exception() {
    local phase="$1"
    local step="$2"
    local code="${3:-1}"
    local detail="${4:-}"
    echo ""
    echo ">>> PIPELINE_EXCEPTION"
    echo ">>>   phase:   $phase"
    echo ">>>   step:    $step"
    echo ">>>   code:    $code"
    if [ -n "$detail" ]; then
        echo ">>>   detail:  $detail"
    fi
    echo ">>>   (See traceback or messages above this block for the root cause.)"
    exit "$code"
}
