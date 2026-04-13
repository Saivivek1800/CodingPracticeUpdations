#!/usr/bin/env bash
# Standalone Jupyter step: builds input_helper.json then drives the helper notebook in a browser.
# Not invoked by backend/scripts/run_full_pipeline.sh or ./run_production.sh — run on a machine with VPN/network to Jupyter.
# Generator-only: SKIP_JUPYTER=1 or JUPYTER_GEN_ONLY=1. NON_INTERACTIVE=1 without creds also runs JSON-only (unless REQUIRE_JUPYTER=1).
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"
# shellcheck source=lib_pipeline_exception.sh
source "$SCRIPT_DIR/lib_pipeline_exception.sh"
# shellcheck source=lib_jupyter_env.sh
source "$SCRIPT_DIR/lib_jupyter_env.sh"

if [ -f "venv/bin/activate" ]; then
  source venv/bin/activate
fi

if [ -f ".secrets.env" ]; then
  set -a
  set +e
  # shellcheck disable=SC1091
  source .secrets.env
  _secrets_env_rc=$?
  set -e
  if [ "$_secrets_env_rc" -ne 0 ]; then
    echo "Warning: sourcing .secrets.env failed (exit $_secrets_env_rc) — fix syntax/quoting; SECRETS_DECRYPTION_KEY may be missing." >&2
  fi
  set +a
fi

if [ -f "secrets.local.env" ]; then
  set -a
  set +e
  # shellcheck disable=SC1091
  source secrets.local.env
  _local_env_rc=$?
  set -e
  if [ "$_local_env_rc" -ne 0 ]; then
    echo "Warning: sourcing secrets.local.env failed (exit $_local_env_rc)." >&2
  fi
  set +a
fi

jupyter_merge_missing_jupyter_from_dotenv
jupyter_inject_secrets_decryption_key
jupyter_export_jupyter_password_vars

if [ "${NON_INTERACTIVE:-0}" = "1" ]; then
  ENV_CHOICE="${DJANGO_TARGET_ENV:-beta}"
  echo "Environment (non-interactive): $ENV_CHOICE"
else
  echo -n "Environment (beta/prod) [default: beta]: "
  read -r ENV_CHOICE
  ENV_CHOICE=${ENV_CHOICE:-beta}
fi

if [ -f ".secrets.enc" ] && [ -z "$BETA_J" ] && [ -z "$PROD_J" ]; then
  if [ -n "${SECRETS_DECRYPTION_KEY:-}" ]; then
    if ! jupyter_decrypt_jupyter_passwords_from_enc "$SECRETS_DECRYPTION_KEY"; then
      echo "Could not load Jupyter passwords from .secrets.enc (see errors above)." >&2
    fi
  elif [ "${NON_INTERACTIVE:-0}" != "1" ]; then
    echo -n "Enter the decryption key (same as setup_secrets.sh; Enter to skip): "
    read -rs DECRYPTION_KEY
    echo ""
    if [ -n "$DECRYPTION_KEY" ]; then
      jupyter_decrypt_jupyter_passwords_from_enc "$DECRYPTION_KEY" || true
    else
      echo "No key entered — cannot decrypt .secrets.enc for Jupyter." >&2
    fi
  fi
fi

jupyter_export_jupyter_password_vars

# URLs and passwords come only from env / .secrets.enc (see .secrets.env.example). No credentials in git.
if [[ "$ENV_CHOICE" == "prod" ]]; then
  export JUPYTER_URL="${PROD_JUPYTER_URL:-https://3.111.135.132:9944/notebooks/LoadHelperCode_to_FunctionBased.ipynb}"
  export JUPYTER_PASSWORD="${PROD_J}"
else
  export JUPYTER_URL="${BETA_JUPYTER_URL:-https://3.111.135.132:2222/notebooks/LoadHelperCode_to_FunctionBased.ipynb}"
  export JUPYTER_PASSWORD="${BETA_J}"
fi

if [ -z "$JUPYTER_PASSWORD" ]; then
  if [ "${SKIP_JUPYTER:-0}" = "1" ] || [ "${JUPYTER_GEN_ONLY:-0}" = "1" ]; then
    if [ "${JUPYTER_GEN_ONLY:-0}" = "1" ] && [ "${SKIP_JUPYTER:-0}" != "1" ]; then
      echo ">>>   [run_helper_updater] JUPYTER_GEN_ONLY=1 — notebook/Playwright skipped on purpose; JSON only." >&2
      echo ">>>   For full notebook run: unset JUPYTER_GEN_ONLY and set BETA_JUPYTER_PASSWORD or SECRETS_DECRYPTION_KEY / .secrets.key." >&2
    else
      echo ">>>   [run_helper_updater] SKIP_JUPYTER=1 — skipping Jupyter; running generator only." >&2
    fi
    python3 generate_helper_input.py || pipeline_exception "PHASE_2_PERFORM_ACTIONS" "run_helper_updater.sh → generate_helper_input.py" "$?" "see Python output above"
    exit 0
  fi
  if [ "${NON_INTERACTIVE:-0}" = "1" ] && [ "${REQUIRE_JUPYTER:-0}" != "1" ]; then
    echo ">>> =============================================================================" >&2
    echo ">>> [run_helper_updater] NON_INTERACTIVE=1: no Jupyter password — JSON ONLY (Playwright NOT run)." >&2
    echo ">>> Add BETA_JUPYTER_PASSWORD=, JUPYTER_PASSWORD=, or SECRETS_DECRYPTION_KEY / .secrets.key for the notebook step." >&2
    echo ">>> Use REQUIRE_JUPYTER=1 to fail here instead of generating JSON only." >&2
    echo ">>> =============================================================================" >&2
    python3 generate_helper_input.py || pipeline_exception "PHASE_2_PERFORM_ACTIONS" "run_helper_updater.sh → generate_helper_input.py" "$?" "see Python output above"
    exit 0
  fi
  echo "Error: BETA_JUPYTER_PASSWORD / PROD_JUPYTER_PASSWORD not set."
  echo "  This script is separate from the dashboard full pipeline and from production Gunicorn — Jupyter creds are optional there." >&2
  if [ -f ".secrets.enc" ] && [ -z "${SECRETS_DECRYPTION_KEY:-}" ]; then
    echo "  Note: .secrets.enc exists but SECRETS_DECRYPTION_KEY is still empty — add an uncommented line to .secrets.env, or create .secrets.key (one line, same passphrase as setup_secrets.sh)." >&2
  fi
  echo "  To run the notebook step: use .secrets.key, SECRETS_DECRYPTION_KEY= in .secrets.env, SECRETS_DECRYPTION_KEY_FILE, or plaintext BETA_JUPYTER_PASSWORD in .secrets.env."
  echo "  Or include Jupyter lines inside .secrets.enc (plain or export KEY=value) and ensure decrypt works (bash scripts/verify_secrets_enc.sh)."
  echo "  Interactive: run without NON_INTERACTIVE to be prompted. Generator-only: SKIP_JUPYTER=1 or JUPYTER_GEN_ONLY=1."
  jupyter_diagnose_missing_jupyter_password
  pipeline_exception "PHASE_2_PERFORM_ACTIONS" "run_helper_updater.sh (credentials)" 1 "JUPYTER_PASSWORD empty — set BETA_JUPYTER_PASSWORD in .secrets.env or .secrets.enc"
fi

echo ">>>   [run_helper_updater] generate_helper_input.py"
python3 generate_helper_input.py || pipeline_exception "PHASE_2_PERFORM_ACTIONS" "run_helper_updater.sh → generate_helper_input.py" "$?" "see Python output above"
echo ">>>   [run_helper_updater] run_jupyter_helper.py"
python3 run_jupyter_helper.py || pipeline_exception "PHASE_2_PERFORM_ACTIONS" "run_helper_updater.sh → run_jupyter_helper.py" "$?" "Jupyter automation failed — network, login, or notebook UI"
