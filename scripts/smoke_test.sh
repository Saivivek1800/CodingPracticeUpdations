#!/usr/bin/env bash
# One-shot checks before/after deploy (no live Django admin actions).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="${ROOT}/venv/bin/python3"

echo "=== smoke_test (project: $ROOT) ==="
bash "$ROOT/scripts/check_setup.sh"
echo ""
echo "--- compileall ---"
"$PY" -m compileall -q -x 'venv/|sessions/' .
echo "[OK] compileall"
echo ""
echo "--- module imports (no side effects at import) ---"
"$PY" - <<'PY'
import importlib
mods = [
    "admin_playwright_util",
    "convert_extracted_to_coding_json",
    "extract_and_convert_coding_question",
    "auto_editorial_by_question_id",
    "auto_editorial_updater",
    "auto_code_updater",
    "auto_content_loader",
    "auto_description_updater",
    "auto_metadata_updater",
    "auto_weightage_updater",
    "auto_hints_updater",
    "auto_evaluation_metrics_updater",
]
for m in mods:
    importlib.import_module(m)
    print("import_ok", m)
print("ALL_IMPORTS_OK")
PY
echo ""
echo "--- Flask /health ---"
"$PY" - <<'PY'
from backend.api.server import app

c = app.test_client()
r = c.get("/health")
print("health_http", r.status_code)
data = r.get_json() or {}
print("healthy_ok", data.get("ok"))
pe = data.get("pipeline_environment") or {}
print("playwright_import_ok", pe.get("playwright_import_ok"))
print("blocking_issues", pe.get("blocking_issues") or [])
print("beta_django_credentials_ok", pe.get("beta_django_credentials_ok"))
p2 = data.get("phase2_django_auth") or {}
print("beta_ready", p2.get("beta_ready"), "prod_ready", p2.get("prod_ready"))
PY
echo ""
echo "=== smoke_test DONE ==="
