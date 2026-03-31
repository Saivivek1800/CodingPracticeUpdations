#!/usr/bin/env bash
# One-shot setup on a new machine (Debian/Ubuntu): OS packages + venv + pip + Chromium + Playwright deps.
#
# Usage (from project root or any path):
#   bash scripts/install_everything.sh
#
# Skips apt if INSTALL_SYSTEM_DEPS=0 (only Python/Playwright via bootstrap):
#   INSTALL_SYSTEM_DEPS=0 bash scripts/install_everything.sh
#
# Requires: sudo access once for apt (unless packages already installed).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

INSTALL_SYSTEM_DEPS="${INSTALL_SYSTEM_DEPS:-1}"

if [ "$INSTALL_SYSTEM_DEPS" = "1" ] && [ "$(uname -s)" = "Linux" ] && command -v apt-get >/dev/null 2>&1; then
  echo ">>> Installing system packages (git, python3, venv, pip, curl, openssl) — needs sudo once..."
  sudo apt-get update
  sudo apt-get install -y git python3 python3-venv python3-pip curl openssl
else
  if [ "$INSTALL_SYSTEM_DEPS" = "1" ] && [ "$(uname -s)" != "Linux" ]; then
    echo "Note: Skipping apt (not Linux). On macOS install Python 3.10+ from python.org or Homebrew, then this script runs bootstrap only."
  fi
fi

echo ""
echo ">>> Project bootstrap (venv, requirements.txt, Chromium, install-deps)..."
bash "$ROOT/scripts/bootstrap.sh"

echo ""
echo "All project dependencies installed. Next:"
echo "  source venv/bin/activate"
echo "  bash scripts/check_setup.sh"
