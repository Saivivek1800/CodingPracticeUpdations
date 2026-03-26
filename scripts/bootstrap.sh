#!/usr/bin/env bash
# Install / refresh Python deps and Playwright after clone or git pull.
# Run from anywhere: bash scripts/bootstrap.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Error: python3 not found. Install Python 3.10+ first." >&2
  exit 1
fi

if [ ! -d venv ]; then
  echo "Creating venv..."
  python3 -m venv venv
fi

# shellcheck disable=SC1091
source venv/bin/activate

echo "Upgrading pip and installing requirements..."
pip install --upgrade pip
pip install -r requirements.txt

echo "Installing Chromium for Playwright..."
playwright install chromium

if [ "$(uname -s)" = "Linux" ]; then
  echo "Installing Linux system libraries for Chromium (needs network; use sudo if prompted)..."
  if playwright install-deps chromium 2>/dev/null; then
    echo "playwright install-deps chromium: OK"
  else
    echo "Note: install-deps may need sudo. Run: sudo \$(which playwright) install-deps chromium"
  fi
fi

echo ""
echo "Done. Next:"
echo "  source venv/bin/activate"
echo "  bash scripts/check_setup.sh    # verify before pipeline"
echo "  NON_INTERACTIVE=1 DJANGO_TARGET_ENV=beta bash backend/scripts/run_full_pipeline.sh"
