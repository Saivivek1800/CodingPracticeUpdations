#!/usr/bin/env bash
# Remove everything this project installs locally (venv + Playwright browsers cache).
# Safe to run before a clean reinstall: bash scripts/uninstall_dependencies.sh
#
# Does NOT remove OS packages (python3, git, openssl, etc.) — other apps may need them.
#
# Options:
#   REMOVE_PLAYWRIGHT_CACHE=0  — keep ~/.cache/ms-playwright (other Playwright projects may use it)
#   REMOVE_PIP_CACHE=1         — also run pip cache purge (global pip cache, not only this project)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# shellcheck disable=SC1091
deactivate 2>/dev/null || true

echo ">>> Removing project virtual environment: $ROOT/venv"
if [ -d "$ROOT/venv" ]; then
  rm -rf "$ROOT/venv"
  echo "    Removed."
else
  echo "    (already absent)"
fi

if [ "${REMOVE_PLAYWRIGHT_CACHE:-1}" = "1" ]; then
  _PW_CACHE="${HOME}/.cache/ms-playwright"
  echo ">>> Removing Playwright browser downloads: $_PW_CACHE"
  if [ -d "$_PW_CACHE" ]; then
    rm -rf "$_PW_CACHE"
    echo "    Removed."
  else
    echo "    (already absent)"
  fi
else
  echo ">>> Skipping Playwright cache (REMOVE_PLAYWRIGHT_CACHE=0)."
fi

if [ "${REMOVE_PIP_CACHE:-0}" = "1" ]; then
  echo ">>> Purging pip download cache (all projects, if pip available)..."
  if command -v pip3 >/dev/null 2>&1; then
    pip3 cache purge 2>/dev/null || true
    echo "    Done (or pip had nothing to purge)."
  else
    echo "    pip3 not on PATH; skip."
  fi
fi

echo ""
echo "Done. System packages installed with apt (git, python3, python3-venv, curl, openssl, …) were NOT removed."
echo "Reinstall this project only:  bash scripts/bootstrap.sh"
echo "Full Ubuntu path (apt + bootstrap):  bash scripts/install_everything.sh"
