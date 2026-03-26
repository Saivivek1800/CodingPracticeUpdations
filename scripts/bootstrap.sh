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
pip install playwright

echo "Installing Chromium for Playwright..."
playwright install chromium

echo ""
echo "Done. Activate with: source venv/bin/activate"
echo "On Linux, recommended once: playwright install-deps chromium  (may need sudo)"
