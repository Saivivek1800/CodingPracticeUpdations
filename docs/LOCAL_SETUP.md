# Local setup (complete)

Step-by-step commands to install and run **django_admin_automation** on your machine. Use this when cloning the repo on a new system.

**Shortcut:** from project root run `bash scripts/bootstrap.sh` (creates `venv`, installs `requirements.txt`, Playwright, Chromium). After any `git pull` that changes dependencies, run it again.

**All commands in one place:** [COMMANDS.md](COMMANDS.md)

## What you need

- **OS:** Linux (recommended) or macOS. On Windows, use **WSL2** with Ubuntu.
- **Python:** 3.10 or newer (`python3 --version`).
- **Network:** Access to your Django admin URLs (beta/prod).
- **Git** (to clone the repository).

---

## 1. Clone the repository

```bash
git clone <YOUR_REPO_URL> django_admin_automation
cd django_admin_automation
```

---

## 2. System packages (Linux — Ubuntu/Debian)

Install tools used by the shell scripts:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip curl
```

**macOS:** Python 3 from [python.org](https://www.python.org/downloads/) or Homebrew is fine; no `apt` step.

After you complete **step 4** (Playwright installed in venv), on Linux run Playwright’s OS dependency installer for Chromium (recommended):

```bash
source venv/bin/activate
playwright install-deps chromium
```

If permission errors appear, use: `sudo $(which playwright) install-deps chromium` (with venv activated).

---

## 3. Create a virtual environment

From the project root (same folder as `requirements.txt`):

```bash
python3 -m venv venv
source venv/bin/activate
```

On Windows CMD:

```bash
python -m venv venv
venv\Scripts\activate.bat
```

---

## 4. Install Python dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
pip install playwright
```

Install the Chromium browser used by automation:

```bash
playwright install chromium
```

---

## 5. Secrets and configuration

Do **not** commit real passwords. Create `.secrets.env` in the **project root** (same level as `requirements.txt`):

```bash
nano .secrets.env
```

For optional server/runtime variables (not Django passwords), see `deployment/env.example`.

Minimal example (replace values):

```env
BETA_DJANGO_ADMIN_USERNAME=your_user
BETA_DJANGO_ADMIN_PASSWORD=your_password
BETA_DJANGO_ADMIN_URL=https://nkb-backend-ccbp-beta.earlywave.in/admin/

PROD_DJANGO_ADMIN_USERNAME=your_prod_user
PROD_DJANGO_ADMIN_PASSWORD=your_prod_password
PROD_DJANGO_ADMIN_URL=https://nkb-backend-ccbp-prod-apis.ccbp.in/admin/
```

Lock the file on Linux/macOS:

```bash
chmod 600 .secrets.env
```

Optional: if evaluation metrics admin URL differs in your environment, add:

```env
DJANGO_EVAL_METRICS_MODEL_PATH=nkb_question/codingquestiontestcaseevalutionmetrics/
```

---

## 6. Prepare input data

- Main source file is typically **`input.json`** in the project root (your team’s format).
- Run generators when you need fresh derived JSON (examples):

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

Or run the full pipeline (see below), which runs these automatically.

---

## 7. Run the web dashboard (local)

```bash
source venv/bin/activate
export FLASK_DEBUG=0
python3 backend/api/server.py
```

Open in a browser:

- **UI:** [http://localhost:5000](http://localhost:5000)
- **Health:** [http://localhost:5000/health](http://localhost:5000/health)

Production-style (Gunicorn, same machine):

```bash
source venv/bin/activate
export FLASK_DEBUG=0
./run_production.sh
```

---

## 8. Run automation from the terminal (no UI)

Pick **beta** or **prod** with `DJANGO_TARGET_ENV`. Use `NON_INTERACTIVE=1` so scripts do not prompt.

**Full pipeline** (all formatters + all updaters in order):

```bash
cd /path/to/django_admin_automation
source venv/bin/activate
NON_INTERACTIVE=1 DJANGO_TARGET_ENV=beta bash backend/scripts/run_full_pipeline.sh
```

**Single step example** (evaluation metrics only):

```bash
NON_INTERACTIVE=1 DJANGO_TARGET_ENV=beta bash backend/scripts/run_evaluation_metrics_updater.sh input_evaluation_metrics.json
```

Other updaters follow the same pattern: `bash backend/scripts/run_<name>_updater.sh` (see `backend/scripts/` and root `run_*.sh` wrappers).

---

## 9. Quick verification checklist

| Step | Command / action |
|------|-------------------|
| Python | `python3 --version` → 3.10+ |
| Deps | `pip install -r requirements.txt` and `pip install playwright` succeed |
| Browser | `playwright install chromium` succeeds |
| Secrets | `.secrets.env` exists and is not committed to git |
| API | `curl -s http://127.0.0.1:5000/health` returns JSON with `"ok": true` |
| Admin | Run one small updater; confirm changes in Django admin |

---

## 10. Git: what to commit vs ignore

- **Commit:** application code, `requirements.txt`, `deployment/`, `docs/`, templates, scripts.
- **Never commit:** `.secrets.env`, `.secrets.enc`, `beta_admin_session.json`, `prod_admin_session.json`, `venv/`, large `sessions/` logs, `__pycache__/`.

The repository includes a **`.gitignore`** at the project root for common cases. Review it before your first push.

---

## Troubleshooting

- **Playwright / Chromium errors:** Re-run `playwright install chromium` and, on Linux, `playwright install-deps chromium`.
- **Module not found:** Ensure `venv` is activated and you ran `pip install -r requirements.txt` plus `pip install playwright`.
- **Admin login or 404:** Check `BETA_DJANGO_ADMIN_URL` / `PROD_DJANGO_ADMIN_URL` match the browser exactly; set `DJANGO_EVAL_METRICS_MODEL_PATH` if metrics changelist 404s.
- **Permission denied on scripts:** `chmod +x run_production.sh backend/scripts/*.sh` if needed.

For production deployment, see the root **`README.md`**.
