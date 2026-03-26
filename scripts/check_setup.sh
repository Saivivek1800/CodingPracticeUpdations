#!/usr/bin/env bash
# Run after bootstrap. Prints what is OK vs broken — paste output if pipeline still fails.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "=== check_setup (project: $ROOT) ==="
echo ""

if [ ! -f "venv/bin/activate" ]; then
  echo "[FAIL] venv missing — run: bash scripts/bootstrap.sh"
  exit 1
fi
echo "[OK] venv exists"

# shellcheck disable=SC1091
source venv/bin/activate

if python3 -c "import playwright" 2>/dev/null; then
  echo "[OK] python can import playwright"
else
  echo "[FAIL] playwright not in venv — run: bash scripts/bootstrap.sh"
  exit 1
fi

if [ -d "$HOME/.cache/ms-playwright" ] || [ -d "$ROOT/node_modules/.cache/ms-playwright" ]; then
  echo "[OK] Playwright browser cache dir likely present"
else
  echo "[WARN] No obvious Playwright cache — run: playwright install chromium"
fi

echo ""
echo "--- credentials (Phase 2) ---"
if [ -f ".secrets.env" ]; then
  if grep -q "^BETA_DJANGO_ADMIN_USERNAME=.\+" .secrets.env 2>/dev/null; then
    echo "[OK] .secrets.env has BETA_DJANGO_ADMIN_USERNAME set"
  else
    echo "[WARN] .secrets.env exists but BETA_DJANGO_ADMIN_USERNAME looks empty"
  fi
else
  echo "[WARN] .secrets.env missing"
fi
if [ -f ".secrets.enc" ]; then
  echo "[INFO] .secrets.enc present (need SECRETS_DECRYPTION_KEY if no .secrets.env)"
else
  echo "[INFO] .secrets.enc not found"
fi

echo ""
echo "--- try importing browser (may show missing .so on Linux) ---"
if python3 -c "
from playwright.sync_api import sync_playwright
p = sync_playwright().start()
b = p.chromium.launch(headless=True)
b.close()
p.stop()
print('[OK] Chromium launched headless')
" 2>&1; then
  :
else
  echo ""
  echo "[FAIL] Chromium did not start. On Ubuntu/Debian try:"
  echo "  source venv/bin/activate"
  echo "  sudo \$(which playwright) install-deps chromium"
  echo "  # or: playwright install-deps chromium"
fi

echo ""
echo "=== end check_setup ==="
