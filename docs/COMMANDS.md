# Command reference

All commands assume you are in the **project root** (folder that contains `requirements.txt`), unless noted.

- **Full local install walkthrough:** [LOCAL_SETUP.md](LOCAL_SETUP.md)
- **After `git pull`:** run `bash scripts/bootstrap.sh` if `requirements.txt` or Playwright usage changed.

---

## 1. First-time clone and dependencies

```bash
git clone <YOUR_REPO_URL> django_admin_automation
cd django_admin_automation
```

**Ubuntu/Debian — system packages (once per machine):**

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip curl
```

**One script — venv + pip + Playwright Chromium:**

```bash
bash scripts/bootstrap.sh
source venv/bin/activate
```

**Linux — Playwright OS libraries for Chromium (recommended once):**

```bash
source venv/bin/activate
playwright install-deps chromium
```

**Secrets:** `.secrets.env` may live in the repo (private team setup). Otherwise create from `.secrets.env.example`. See [LOCAL_SETUP.md](LOCAL_SETUP.md).

---

## 2. Manual install (same as bootstrap, step by step)

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install playwright
playwright install chromium
```

---

## 3. Run the web dashboard

**Development (Flask built-in server):**

```bash
cd django_admin_automation
source venv/bin/activate
export FLASK_DEBUG=0
python3 backend/api/server.py
```

Open: `http://localhost:5000` — health: `http://localhost:5000/health`

**Production-style on the same machine (Gunicorn):**

```bash
source venv/bin/activate
export FLASK_DEBUG=0
./run_production.sh
```

---

## 4. Environment variables (CLI automation)

Most updater scripts use `lib_django_session.sh` and accept:

| Variable | Purpose |
|----------|---------|
| `DJANGO_TARGET_ENV` | `beta` or `prod` |
| `NON_INTERACTIVE` | `1` to skip prompts |
| `SECRETS_DECRYPTION_KEY` | Passphrase for `.secrets.enc` when `NON_INTERACTIVE=1` (no prompt). Without it, decrypt is skipped. |

If Phase 2 says *no credentials* but you use **only** `.secrets.enc`, run with:

```bash
SECRETS_DECRYPTION_KEY='your-passphrase' NON_INTERACTIVE=1 DJANGO_TARGET_ENV=beta bash backend/scripts/run_full_pipeline.sh
```

See **Using `.secrets.enc` with `NON_INTERACTIVE=1`** in [LOCAL_SETUP.md](LOCAL_SETUP.md).

For copy-paste below, set once in your shell (then run each step):

```bash
cd django_admin_automation
source venv/bin/activate
export NON_INTERACTIVE=1
export DJANGO_TARGET_ENV=beta   # or prod
```

---

## 5. Run everything (one command)

This matches `backend/scripts/run_full_pipeline.sh`: **all formatters**, then **all updaters**, in order. Failed steps are logged and later steps still run.

```bash
source venv/bin/activate
NON_INTERACTIVE=1 DJANGO_TARGET_ENV=beta bash backend/scripts/run_full_pipeline.sh
```

**Production target:**

```bash
NON_INTERACTIVE=1 DJANGO_TARGET_ENV=prod bash backend/scripts/run_full_pipeline.sh
```

**Skip testcase weightages** (skips `run_weightage_updater.sh` only):

```bash
SKIP_TESTCASES=1 NON_INTERACTIVE=1 DJANGO_TARGET_ENV=beta bash backend/scripts/run_full_pipeline.sh
```

---

## 6. Run step by step (same order as full pipeline)

Use this when you want to run **one script at a time**. Order is the same as `run_full_pipeline.sh`.

**0) Start from project root and set env (once per terminal session):**

```bash
cd django_admin_automation
source venv/bin/activate
export NON_INTERACTIVE=1
export DJANGO_TARGET_ENV=beta
```

### Phase 1 — Generate JSON from `input.json` (formatters)

Run in this order:

```bash
python3 generate_input_code_data.py
python3 generate_input_desc.py
python3 generate_input_metadata.py
python3 generate_input_evaluation_metrics.py
python3 generate_input_weightages.py
python3 generate_input.py
python3 generate_input_data.py
```

### Phase 2 — Push to Django admin (updaters)

Run in this order:

```bash
bash backend/scripts/run_code_updater.sh
bash backend/scripts/run_hints_updater.sh
bash backend/scripts/run_description_updater.sh
bash backend/scripts/run_metadata_updater.sh
bash backend/scripts/run_evaluation_metrics_updater.sh
bash backend/scripts/run_weightage_updater.sh
bash backend/scripts/run_loader.sh
```

**Evaluation metrics** default input file is `input_evaluation_metrics.json`. To use another file:

```bash
bash backend/scripts/run_evaluation_metrics_updater.sh path/to/your_metrics.json
```

**If you used `SKIP_TESTCASES=1` in the full pipeline:** omit `run_weightage_updater.sh` above.

---

## 7. Individual updaters (backend/scripts)

Use root wrappers (`./run_*.sh`) or call `backend/scripts/` directly. Pass `NON_INTERACTIVE=1` and `DJANGO_TARGET_ENV` as above.

| Script | Purpose |
|--------|---------|
| `backend/scripts/run_code_updater.sh` | Code & solution |
| `backend/scripts/run_hints_updater.sh` | Hints |
| `backend/scripts/run_description_updater.sh` | Description |
| `backend/scripts/run_metadata_updater.sh` | Metadata |
| `backend/scripts/run_evaluation_metrics_updater.sh` | Evaluation metrics (optional file arg, default `input_evaluation_metrics.json`) |
| `backend/scripts/run_weightage_updater.sh` | Weightages |
| `backend/scripts/run_loader.sh` | Testcases / loader |
| `backend/scripts/run_helper_updater.sh` | Helper content |
| `backend/scripts/run_base64_updater.sh` | Base64-related flow |
| `backend/scripts/run_editorial_by_question_id.sh` | Editorial by question id |

**Examples:**

```bash
NON_INTERACTIVE=1 DJANGO_TARGET_ENV=beta bash backend/scripts/run_code_updater.sh
NON_INTERACTIVE=1 DJANGO_TARGET_ENV=beta bash backend/scripts/run_evaluation_metrics_updater.sh input_evaluation_metrics.json
NON_INTERACTIVE=1 DJANGO_TARGET_ENV=beta bash backend/scripts/run_editorial_by_question_id.sh
```

Root-level `run_*.sh` files forward to `backend/scripts/` with the same name.

**Not part of `run_full_pipeline.sh`** (run only when you need them):

```bash
bash backend/scripts/run_helper_updater.sh
bash backend/scripts/run_base64_updater.sh
bash backend/scripts/run_editorial_by_question_id.sh
```

---

## 8. Input generators (from `input.json` / project data)

Same commands as **Phase 1** in [section 6](#6-run-step-by-step-same-order-as-full-pipeline). Listed again for quick copy:

```bash
source venv/bin/activate
python3 generate_input_code_data.py
python3 generate_input_desc.py
python3 generate_input_metadata.py
python3 generate_input_evaluation_metrics.py
python3 generate_input_weightages.py
python3 generate_input.py
python3 generate_input_data.py
```

---

## 9. Health and logs

```bash
curl -s http://127.0.0.1:5000/health
```

Pipeline and UI jobs write under `sessions/` (ignored by git).

---

## 10. Git workflow (reminder)

`git pull` does **not** install packages. After pulling dependency changes:

```bash
bash scripts/bootstrap.sh
```

Session JSON and `venv/` stay local — see root `.gitignore`. `.secrets.env` may be committed if your team chose that (private repo only).

---

## 11. Production server (summary)

See root **README.md** for systemd, Nginx, and `/etc/django-admin-automation.env`. Templates live in `deployment/`.

```bash
./run_production.sh
```

On a server, prefer the systemd unit in `deployment/django-admin-automation.service`.

---

## 12. Optional evaluation metrics admin path

If the metrics changelist returns 404, set in `.secrets.env` or environment:

```env
DJANGO_EVAL_METRICS_MODEL_PATH=nkb_question/codingquestiontestcaseevalutionmetrics/
```

See `deployment/env.example` for more variables.
