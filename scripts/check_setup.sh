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
if [ -f ".secrets.enc" ] && [ -f ".secrets.key" ]; then
  echo "[OK] .secrets.enc + .secrets.key — passwords need not live in .secrets.env"
elif [ -f ".secrets.enc" ] && [ -n "${SECRETS_DECRYPTION_KEY:-}" ]; then
  echo "[OK] .secrets.enc + SECRETS_DECRYPTION_KEY in environment"
elif [ -f ".secrets.env" ] && grep -qE '^[[:space:]]*BETA_DJANGO_ADMIN_USERNAME=[^[:space:]]' .secrets.env 2>/dev/null; then
  echo "[OK] .secrets.env has BETA_DJANGO_ADMIN_USERNAME set (plaintext mode)"
elif [ -f "secrets.local.env" ] && grep -qE '^[[:space:]]*BETA_DJANGO_ADMIN_USERNAME=[^[:space:]]' secrets.local.env 2>/dev/null; then
  echo "[OK] secrets.local.env has BETA_DJANGO_ADMIN_USERNAME (gitignored *.local.env)"
elif [ -f ".secrets.env" ]; then
  echo "[WARN] .secrets.env exists but no beta username line — add creds or use .secrets.enc + .secrets.key"
else
  echo "[WARN] No .secrets.env — OK if you use .secrets.enc + .secrets.key (see .secrets.env.example)"
fi
if [ -f ".secrets.enc" ]; then
  echo "[INFO] .secrets.enc present"
else
  echo "[INFO] .secrets.enc not found (optional if plaintext .secrets.env has full creds)"
fi
if [ -f ".secrets.key" ]; then
  echo "[INFO] .secrets.key present"
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
