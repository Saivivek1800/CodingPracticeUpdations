#!/usr/bin/env bash
# One-time / deploy build on Replit: Python deps + Playwright browser.
# Replit usually runs `pip install -r requirements.txt` from the packager; this script
# adds the Playwright Chromium download (required for admin automation).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ ! -d venv ]; then
  python3 -m venv venv
fi
# shellcheck disable=SC1091
source venv/bin/activate

python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt

echo "Installing Playwright Chromium (needed for updaters / pipeline)..."
python3 -m playwright install chromium

if [ "$(uname -s)" = "Linux" ]; then
  python3 -m playwright install-deps chromium 2>/dev/null || \
    echo "Note: install-deps may need extra Nix packages on Replit; if Chromium fails to start, add libs via replit.nix."
fi

echo "replit_bootstrap: OK"
