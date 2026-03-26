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

**Why GitHub has no `.secrets.env`:** those files are listed in **`.gitignore`** so passwords are never pushed. The repo **does** include **`.secrets.env.example`** (placeholders only) so everyone knows which variables to set.

Create your real file from the example:

```bash
cp .secrets.env.example .secrets.env
nano .secrets.env
chmod 600 .secrets.env
```

Do **not** commit `.secrets.env` or `.secrets.enc`.

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

### Teammates and new computers (Phase 2 credentials)

Adding docs to the repo does **not** by itself log anyone into Django admin. Each developer machine still needs **local** credentials (or a saved session).

| Phase | Needs admin creds? |
|-------|---------------------|
| **Phase 1** ( `generate_input_*.py` ) | No — only reads/writes JSON from `input.json` etc. |
| **Phase 2** ( `run_*_updater.sh` , full pipeline part 2 ) | Yes — Playwright opens Django admin. |

These files are **intentionally not in Git** (see root `.gitignore`): `.secrets.env`, `.secrets.enc`, `beta_admin_session.json`, `prod_admin_session.json`. They contain passwords or session cookies.

**What each teammate should do after `git clone`:**

1. Create **`.secrets.env`** in the project root with real `BETA_*` / `PROD_*` values (get them from your team lead or company password manager — **not** via a public repo), **or**
2. Copy **`.secrets.enc`** through a **private** channel into the project root (same folder as `requirements.txt`), **or**
3. Run an updater once with username/password so **`beta_admin_session.json`** is created; scripts can reuse it until the session expires (then `.secrets.env` is used to re-login).

Until one of the above exists on that computer, **Phase 2 will fail with missing or invalid credentials** even though Phase 1 succeeds.

### Using `.secrets.enc` with `NON_INTERACTIVE=1` (full pipeline / CI)

`backend/scripts/lib_django_session.sh` decrypts `.secrets.enc` only when it has a **decryption key**. In **non-interactive** mode it does **not** prompt — it reads the key from the environment variable **`SECRETS_DECRYPTION_KEY`**.

If you run:

```bash
NON_INTERACTIVE=1 DJANGO_TARGET_ENV=beta bash backend/scripts/run_full_pipeline.sh
```

**without** `SECRETS_DECRYPTION_KEY` and **without** `.secrets.env` or `beta_admin_session.json`, decryption is skipped and you get:

`Missing DJANGO credentials and no session file beta_admin_session.json`

**Fix — export the same passphrase you used when creating `.secrets.enc`:**

```bash
export SECRETS_DECRYPTION_KEY='your-openssl-passphrase-here'
NON_INTERACTIVE=1 DJANGO_TARGET_ENV=beta bash backend/scripts/run_full_pipeline.sh
```

One line:

```bash
SECRETS_DECRYPTION_KEY='your-openssl-passphrase-here' NON_INTERACTIVE=1 DJANGO_TARGET_ENV=beta bash backend/scripts/run_full_pipeline.sh
```

**Requirements:** `.secrets.enc` must exist in the project root on that machine (copy it privately; it is not in Git). If the passphrase is wrong, you may see a warning and still no credentials — then use `.secrets.env` instead or fix the key.

**Interactive alternative:** run a single updater **without** `NON_INTERACTIVE=1` so the script can prompt for the decryption key (not ideal for `run_full_pipeline.sh`, which is usually non-interactive).

**Still failing?** Test decrypt only (same OpenSSL options as `setup_secrets.sh`):

```bash
cd /path/to/project
SECRETS_DECRYPTION_KEY='same-key-as-setup_secrets.sh' bash scripts/verify_secrets_enc.sh
```

If this prints `OK`, the key and file match; then run the pipeline with the same `SECRETS_DECRYPTION_KEY`. If it prints `FAILED`, the passphrase is wrong, `.secrets.enc` is from a different encryption command, or the file was corrupted when copying.

**OpenSSL note:** Decryption uses the same `-pass pass:...` style as `setup_secrets.sh`. If someone encrypted with a different OpenSSL command, re-run `bash setup_secrets.sh` from a plain `.secrets.env` and copy the new `.secrets.enc`.

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
