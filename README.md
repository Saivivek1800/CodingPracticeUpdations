# Django admin automation

Web dashboard and CLI tools to bulk-update **coding questions** in Django admin: code, hints, descriptions, metadata, evaluation metrics, testcase weightages, and content-loader JSON. Uses **Python**, **Playwright** (Chromium), and **Flask** for a local API and live log streaming.

---

## Features

| Area | Description |
|------|-------------|
| **Main updater** | Generate inputs from `input.json`, run formatters, push updates to **Beta** or **Prod** admin (prod skips some steps—see pipeline section). |
| **Editorial** | Update learning-resource editorial content by **question UUID** — **Beta only** (no prod selector). |
| **Extract coding JSON** | Trigger `EXTRACT_CODING_QUESTION_CONTENT`, wait for completion, download result, convert to coding JSON; shows parsed errors (including bodies behind `exception` URLs). |
| **Queue / SSE** | Dashboard can queue pipeline jobs and stream logs over Server-Sent Events. |

---

## Requirements

- **Python 3.10+**
- **Linux** (or similar) with dependencies for Playwright Chromium
- Network access to your Django **admin** URLs
- Valid **Django admin** credentials (see secrets below)

---

## Quick start

```bash
cd django_admin_automation   # repository root
bash scripts/bootstrap.sh      # venv, pip, Playwright Chromium
source venv/bin/activate
bash scripts/check_setup.sh    # optional sanity check
```

**After `git clone`:** `venv/` is not in the repository (by design). You must run **`bash scripts/bootstrap.sh`** once on each machine, then start the server. If you skip this, the dashboard full pipeline returns **503** with a short explanation, and `/health` shows `pipeline_environment.blocking_issues`.

**Credentials:** Copy **`.secrets.env.example`** → **`.secrets.env`** and/or use **`.secrets.enc` + `.secrets.key`**. A clone without secrets will start the app but Phase 2 updaters will fail until these exist.

**Why Phase 2 works on your laptop but fails after `git clone`:** `beta_admin_session.json` (Playwright cookies) is **gitignored**. If you have that file locally, admin updates can run **without** passwords in `.secrets.env`. New clones do not get that file — teammates must add **username/password** (or encrypted secrets + **`.secrets.key`**) or copy a valid session file into the project root. Check **`GET /health`** → **`phase2_django_auth`** before running the full pipeline from the UI.

### Secrets (credentials)

| File | In git? | Notes |
|------|---------|--------|
| **`.secrets.key`** | **No** (gitignored) | Decryption key — never commit next to `.secrets.enc`. |
| **`.secrets.env`** / **`.secrets.enc`** | Optional | Not gitignored: a **private** repo may commit them so teammates can run after clone. **Public repos:** do not commit; use `.secrets.env.example` only. |

**Recommended — no plaintext passwords in `.secrets.env`:**

1. Copy **`.secrets.env.example`** and follow the **encrypted** workflow: build a full `.secrets.env` once, run **`bash setup_secrets.sh`**, then remove plaintext passwords from `.secrets.env` (URLs-only is fine).
2. Keep **`.secrets.key`** (one line = validation key) in the project root with **`chmod 600`**, **or** set **`SECRETS_DECRYPTION_KEY`** in the environment when running.
3. The app and **`backend/scripts/lib_django_session.sh`** decrypt **`.secrets.enc`** when username/password are not already in the environment.

Verify decrypt:

```bash
SECRETS_DECRYPTION_KEY="$(tr -d '\n\r' < .secrets.key)" bash scripts/verify_secrets_enc.sh
```

Session cookie files (`beta_admin_session.json`, `prod_admin_session.json`) are local and gitignored; they refresh using the same credential sources.

More detail: **[docs/LOCAL_SETUP.md](docs/LOCAL_SETUP.md)**

---

## Web UI

```bash
source venv/bin/activate
export FLASK_DEBUG=0
python3 backend/api/server.py
```

- Open **http://127.0.0.1:5000** (use `127.0.0.1`, not `0.0.0.0`, when testing from the same machine).
- Health: **http://127.0.0.1:5000/health**

**Production-style (Gunicorn):**

```bash
./run_production.sh
```

See **[deployment/](deployment/)** for systemd / nginx samples.

---

## CLI — full pipeline

From repository root, with venv activated:

```bash
export NON_INTERACTIVE=1
export DJANGO_TARGET_ENV=beta   # or prod
bash backend/scripts/run_full_pipeline.sh
```

- **Prod:** evaluation metrics and testcase weightage steps are **skipped** (by design in `run_full_pipeline.sh`).
- Individual step failures are **logged and skipped** so later steps still run.

**One-liner install + pipeline** (see also `scripts/run_pipeline.sh`):

```bash
bash scripts/run_pipeline.sh
```

With encrypted secrets only:

```bash
SECRETS_DECRYPTION_KEY='your-key' bash scripts/run_pipeline.sh
```

**Skip testcase weightages:** `SKIP_TESTCASES=1` with the same pipeline command.

**Phase 1 — generators only** (run in order): `generate_input_code_data.py`, `generate_input_desc.py`, `generate_input_metadata.py`, `generate_input_evaluation_metrics.py`, `generate_input_weightages.py`, `generate_input.py`, `generate_input_data.py`.

**Phase 2 — admin updaters** (see `run_full_pipeline.sh` for exact list): `backend/scripts/run_*_updater.sh`, `run_loader.sh`.

Full command reference: **[docs/COMMANDS.md](docs/COMMANDS.md)**

---

## Extract coding questions (CLI)

```bash
# input_extract_question.json: { "question_ids": [ "uuid", ... ] }
python3 extract_and_convert_coding_question.py input_extract_question.json \
  --raw-output extracted_coding_questions.json \
  --output coding_questions_output.json
```

Uses the same session/credentials as other updaters (`DJANGO_TARGET_ENV`, `.secrets.*`).

---

## Project layout

| Path | Role |
|------|------|
| `backend/api/server.py` | Flask app, APIs, SSE, job queue |
| `backend/api/wsgi.py` | Gunicorn entrypoint |
| `backend/scripts/run_full_pipeline.sh` | End-to-end formatters + updaters |
| `backend/scripts/lib_django_session.sh` | Session + `.secrets.env` / `.secrets.enc` handling |
| `auto_*.py` | Playwright admin updaters |
| `generate_input*.py` | JSON generators / formatters |
| `extract_and_convert_coding_question.py` | Admin extract task + S3 download + convert |
| `frontend/templates/` | Dashboard HTML (main, editorial, extract) |
| `scripts/bootstrap.sh` | Install venv, requirements, Playwright |
| `scripts/check_setup.sh` | Quick environment check |
| `deployment/` | Example systemd, nginx, env |

---

## Environment variables (common)

| Variable | Purpose |
|----------|---------|
| `DJANGO_TARGET_ENV` | `beta` or `prod` for pipelines and extract (editorial UI is always beta). |
| `NON_INTERACTIVE` | `1` — no prompts; needs credentials or decrypt key for session refresh. |
| `SECRETS_DECRYPTION_KEY` | Passphrase for `.secrets.enc` when not using interactive decrypt. |
| `SKIP_TESTCASES` | `1` — skip testcase weightage step in full pipeline. |
| `EXTRACT_MAX_WAIT_SEC` | Optional longer wait for large extract batches. |

---

## Evaluation metrics admin path

If the metrics changelist **404**s, set in env or secrets:

```env
DJANGO_EVAL_METRICS_MODEL_PATH=nkb_question/codingquestiontestcaseevalutionmetrics/
```

(Adjust if your Django admin URL slug differs.)

---

## Concurrency (important)

Keep **Gunicorn workers at 1** for this app: in-process queue and SSE state do not span workers. Scale with **`GUNICORN_THREADS`** and **`PIPELINE_WORKERS`** instead. See **`gunicorn.conf.py`** and **`deployment/`**.

---

## Troubleshooting

| Symptom | What to check |
|---------|----------------|
| Phase 2 fails for teammates, works for you | They have no `beta_admin_session.json`; add real credentials or share `.secrets.key` + `.secrets.enc`. UI returns **503** with an explanation if Phase 2 auth is not ready. |
| Login page instead of admin | Expired session; ensure `.secrets.enc` + `.secrets.key` or plaintext creds; delete stale `*_admin_session.json` if needed. |
| Admin 404 | `DJANGO_ADMIN_URL` host and model paths (e.g. eval metrics). |
| Playwright / Chromium errors | `bash scripts/bootstrap.sh`; on Linux, `playwright install-deps chromium` (may need `sudo`). |
| Extract shows only a link | Use current `extract_and_convert_coding_question.py` — it follows `exception` URLs to fetch the real traceback. |
| Pipeline “stuck” or empty UI logs | Thread pool / wrong bind address; use `127.0.0.1:5000`; see health endpoint. |

---

## Security

- Treat **`.secrets.key`** and **`.secrets.enc`** like passwords; never commit them to a public repo.
- Restrict the dashboard (VPN, IP allow-list, or proxy auth). Optional: **`AUTOMATION_API_TOKEN`** — see **`deployment/env.example`**.
- Rotate Django passwords if credentials or keys are ever exposed.

---

## Further reading

- **[docs/LOCAL_SETUP.md](docs/LOCAL_SETUP.md)** — detailed local and team setup  
- **[docs/COMMANDS.md](docs/COMMANDS.md)** — all scripts and options  
- **`backend/README.md`** — short backend note  
