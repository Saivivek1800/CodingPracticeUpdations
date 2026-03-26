# CodingPracticeUpdations

Web UI and CLI automation for bulk-updating coding-question content in Django admin.

This project converts structured JSON inputs into admin updates (code, hints, description, metadata, evaluation metrics, weightages, and loader/testcase data) using Python + Playwright.

## Quick commands

Use these after **clone** or **`git pull`** when dependencies may have changed:

```bash
cd django_admin_automation
bash scripts/bootstrap.sh
source venv/bin/activate
```

**`.secrets.env` is not on GitHub** (gitignored). Copy the template: `cp .secrets.env.example .secrets.env` then edit with real values. See [docs/LOCAL_SETUP.md](docs/LOCAL_SETUP.md). **Phase 2** (admin updaters) needs these credentials on **each** machine — `.secrets.enc` / session files are also gitignored; teammates must add secrets locally. Details: [LOCAL_SETUP.md — Teammates and new computers](docs/LOCAL_SETUP.md#teammates-and-new-computers-phase-2-credentials).

**Web UI (local):**

```bash
source venv/bin/activate
export FLASK_DEBUG=0
python3 backend/api/server.py
```

Open [http://localhost:5000](http://localhost:5000) — health check: [http://localhost:5000/health](http://localhost:5000/health).

**Production-style server (Gunicorn, same machine):**

```bash
source venv/bin/activate
./run_production.sh
```

**Run all formatters + all updaters at once (beta, no prompts):**

```bash
source venv/bin/activate
NON_INTERACTIVE=1 DJANGO_TARGET_ENV=beta bash backend/scripts/run_full_pipeline.sh
```

**Prod target:** use `DJANGO_TARGET_ENV=prod` instead of `beta`.

**Skip testcase weightages only:** `SKIP_TESTCASES=1 NON_INTERACTIVE=1 DJANGO_TARGET_ENV=beta bash backend/scripts/run_full_pipeline.sh`

### Run step by step (one command at a time)

Set once per terminal:

```bash
cd django_admin_automation
source venv/bin/activate
export NON_INTERACTIVE=1
export DJANGO_TARGET_ENV=beta
```

**Phase 1 — generate JSON (run in order):**

```bash
python3 generate_input_code_data.py
python3 generate_input_desc.py
python3 generate_input_metadata.py
python3 generate_input_evaluation_metrics.py
python3 generate_input_weightages.py
python3 generate_input.py
python3 generate_input_data.py
```

**Phase 2 — push to Django admin (run in order):**

```bash
bash backend/scripts/run_code_updater.sh
bash backend/scripts/run_hints_updater.sh
bash backend/scripts/run_description_updater.sh
bash backend/scripts/run_metadata_updater.sh
bash backend/scripts/run_evaluation_metrics_updater.sh
bash backend/scripts/run_weightage_updater.sh
bash backend/scripts/run_loader.sh
```

Optional scripts **not** included in the full pipeline: `run_helper_updater.sh`, `run_base64_updater.sh`, `run_editorial_by_question_id.sh` — see [docs/COMMANDS.md](docs/COMMANDS.md).

**Complete command reference:** [docs/COMMANDS.md](docs/COMMANDS.md)

## What It Does

- Reads source input data and generates per-feature JSON files.
- Opens Django admin pages and updates records automatically.
- Supports beta/prod targets through environment variables.
- Provides a Flask dashboard with:
  - one-click pipeline runs,
  - queued background jobs,
  - live log streaming.

## Project Layout

- `backend/api/server.py` - Flask app, queue worker, pipeline API.
- `backend/api/wsgi.py` - Gunicorn entrypoint.
- `backend/scripts/run_full_pipeline.sh` - end-to-end formatter + updater run.
- `backend/scripts/lib_django_session.sh` - shared env/session bootstrap.
- `auto_*_updater.py` - Playwright admin updaters.
- `generate_input_*.py` - JSON formatter/generator scripts.
- `frontend/templates/` - dashboard UI templates.
- `deployment/` - sample systemd, nginx, and env files.

## Prerequisites

- Linux server or workstation
- Python 3.10+
- Chromium dependencies required by Playwright
- Access to target Django admin URLs
- Valid credentials in `.secrets.env` (or working saved session files)

## Local Setup

- **Install / refresh dependencies:** `bash scripts/bootstrap.sh` then `source venv/bin/activate`
- **Full checklist:** [docs/LOCAL_SETUP.md](docs/LOCAL_SETUP.md)
- **All commands:** [docs/COMMANDS.md](docs/COMMANDS.md)

Manual equivalent of bootstrap:

```bash
cd django_admin_automation
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/pip install playwright
./venv/bin/playwright install chromium
```

Create `.secrets.env` in project root:

```env
BETA_DJANGO_ADMIN_USERNAME=...
BETA_DJANGO_ADMIN_PASSWORD=...
BETA_DJANGO_ADMIN_URL=https://<beta-host>/admin/

PROD_DJANGO_ADMIN_USERNAME=...
PROD_DJANGO_ADMIN_PASSWORD=...
PROD_DJANGO_ADMIN_URL=https://<prod-host>/admin/
```

## Run Options

See **[docs/COMMANDS.md](docs/COMMANDS.md)** for every updater script, generators, and examples.

**Dashboard (dev):** `./venv/bin/python3 backend/api/server.py` → `http://localhost:5000`

**One updater (example — evaluation metrics):**

```bash
NON_INTERACTIVE=1 DJANGO_TARGET_ENV=beta bash backend/scripts/run_evaluation_metrics_updater.sh input_evaluation_metrics.json
```

**Full pipeline:**

```bash
NON_INTERACTIVE=1 DJANGO_TARGET_ENV=beta bash backend/scripts/run_full_pipeline.sh
```

## Evaluation Metrics URL Path Note

Different environments may register different Django admin model URLs.

If evaluation metrics changelist returns 404, set:

- `DJANGO_EVAL_METRICS_MODEL_PATH`
- `DJANGO_EVAL_METRICS_MODEL_PATH_ALTERNATES`

Example (beta in this project currently uses typo slug):

```env
DJANGO_EVAL_METRICS_MODEL_PATH=nkb_question/codingquestiontestcaseevalutionmetrics/
```

## Production Deployment (UI Live)

Use Gunicorn + systemd + Nginx.

### 1) App host layout (recommended)

- Code: `/opt/django_admin_automation`
- Venv: `/opt/django_admin_automation/venv`
- Runtime env file: `/etc/django-admin-automation.env`

### 2) Install and configure

```bash
cd /opt/django_admin_automation
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/pip install playwright
./venv/bin/playwright install chromium
```

Set `/etc/django-admin-automation.env` from `deployment/env.example` and include at least:

- `FLASK_SECRET_KEY`
- `BIND`
- `GUNICORN_THREADS`
- `PIPELINE_WORKERS`
- `DJANGO_TARGET_ENV`

Keep `.secrets.env` in project root for admin credentials.

### 3) Systemd service

Copy and adjust `deployment/django-admin-automation.service` for your paths/user:

```bash
sudo cp deployment/django-admin-automation.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now django-admin-automation
```

### 4) Nginx reverse proxy

Use `deployment/nginx-django-admin-automation.conf` as base, set your `server_name`, then:

```bash
sudo ln -s /etc/nginx/sites-available/django-admin-automation.conf /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

Add TLS (Let's Encrypt) for public access.

## Important Concurrency Rule

Keep Gunicorn workers at **1** for this app.

Reason: queue/job state and log streaming are held in-process memory. Scale with:

- `GUNICORN_THREADS`
- `PIPELINE_WORKERS`

Do not scale by increasing Gunicorn worker processes.

## Health Check

```bash
curl http://127.0.0.1:5000/health
```

Expected JSON includes `"ok": true`.

## Troubleshooting

- **Admin 404 on updater**
  - Verify `DJANGO_ADMIN_URL` host is exact.
  - Configure model path env vars for that environment.
- **Gets login page instead of changelist**
  - Session expired; refresh session or verify credentials in `.secrets.env`.
- **Pipeline run seems stuck**
  - Check job logs in `sessions/`.
  - Ensure Playwright browser install succeeded.
- **Intermittent missing job/log updates in production**
  - Confirm `GUNICORN_WORKERS=1`.

## Security Notes

- Do not commit `.secrets.env` or session JSON files.
- Restrict dashboard access behind VPN/IP allow-list or authentication at proxy level.
- If needed, use API token protection (`AUTOMATION_API_TOKEN`) as documented in `deployment/env.example`.
