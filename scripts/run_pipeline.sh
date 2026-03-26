#!/usr/bin/env bash
# Install deps (venv + pip + Playwright) and run the full pipeline in one go.
# Usage (from anywhere):
#   bash scripts/run_pipeline.sh
# With encrypted secrets only:
#   SECRETS_DECRYPTION_KEY='your-key' bash scripts/run_pipeline.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo ">>> Step 1/2: bootstrap (venv, requirements, Chromium)..."
bash "$ROOT/scripts/bootstrap.sh"

# shellcheck disable=SC1091
source "$ROOT/venv/bin/activate"

export NON_INTERACTIVE="${NON_INTERACTIVE:-1}"
export DJANGO_TARGET_ENV="${DJANGO_TARGET_ENV:-beta}"

echo ""
echo ">>> Step 2/2: full pipeline (beta)..."
bash "$ROOT/backend/scripts/run_full_pipeline.sh"
