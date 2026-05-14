import os
import json
import re
import subprocess
import threading
import glob
import queue
import time
import uuid
from flask import Flask, render_template, request, jsonify, Response, send_file

# Paths for scripts (project root two levels above this file)
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SESSIONS_DIR = os.path.join(BASE_DIR, "sessions")
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
TEMPLATES_DIR = os.path.join(FRONTEND_DIR, "templates")


def _eager_load_secrets_decryption_key_into_os_environ() -> None:
    """
    Production / Gunicorn: load passphrase for .secrets.enc without manual `export`.
    Order: keep existing env; else `.secrets.key`; else `SECRETS_DECRYPTION_KEY=` in `.secrets.env`
    or `secrets.local.env`.
    Runs once when this module is imported (dev server, gunicorn workers).
    """
    if str(os.environ.get("SECRETS_DECRYPTION_KEY", "")).strip():
        return
    key_file = os.path.join(BASE_DIR, ".secrets.key")
    if os.path.isfile(key_file):
        try:
            with open(key_file, "r", encoding="utf-8") as f:
                k = f.read().strip()
            if k:
                os.environ["SECRETS_DECRYPTION_KEY"] = k
                return
        except OSError:
            pass
    for env_file in (
        os.path.join(BASE_DIR, ".secrets.env"),
        os.path.join(BASE_DIR, "secrets.local.env"),
    ):
        if not os.path.isfile(env_file):
            continue
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for raw in f:
                    line = raw.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.startswith("export "):
                        line = line[7:].strip()
                    if "=" not in line:
                        continue
                    name, _, val = line.partition("=")
                    if name.strip() != "SECRETS_DECRYPTION_KEY":
                        continue
                    val = val.strip()
                    if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                        val = val[1:-1]
                    if val:
                        os.environ["SECRETS_DECRYPTION_KEY"] = val
                        return
        except OSError:
            continue


_eager_load_secrets_decryption_key_into_os_environ()


def _normalize_django_target_env(value, default="beta"):
    t = (default if value is None else str(value)).strip().lower()
    return t if t in ("beta", "prod") else default


def _venv_python_executable():
    bindir = os.path.join(BASE_DIR, "venv", "bin")
    for name in ("python3", "python"):
        p = os.path.join(bindir, name)
        if os.path.isfile(p):
            return p
    return None


def pipeline_environment_blocking_issues():
    """
    Issues that always abort the full pipeline (fresh git clone without bootstrap).
    Not secrets-related: missing creds fail later with clearer updater logs.
    """
    issues = []
    activate = os.path.join(BASE_DIR, "venv", "bin", "activate")
    if not os.path.isfile(activate):
        issues.append(
            "venv is missing. After git clone, run from project root: bash scripts/bootstrap.sh "
            "then restart the Flask/Gunicorn server if it is already running."
        )
        return issues
    venv_py = _venv_python_executable()
    if not venv_py:
        issues.append("venv exists but bin/python is missing — run: bash scripts/bootstrap.sh")
        return issues
    try:
        r = subprocess.run(
            [venv_py, "-c", "import playwright"],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=45,
        )
        if r.returncode != 0:
            issues.append(
                "Playwright is not installed in this venv. Run: bash scripts/bootstrap.sh "
                "(installs requirements.txt and playwright install chromium)."
            )
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        issues.append(f"Could not verify Playwright in venv ({e}). Try: bash scripts/bootstrap.sh")
    return issues


def beta_django_credentials_resolved():
    """True if Beta admin username+password are available after the same merge/decrypt as pipeline children."""
    test_env = os.environ.copy()
    try:
        _prepare_django_child_env(test_env)
    except Exception:
        return False
    u = str(test_env.get("BETA_DJANGO_ADMIN_USERNAME", "")).strip()
    p = str(test_env.get("BETA_DJANGO_ADMIN_PASSWORD", "")).strip()
    return bool(u and p)


def _dotenv_has_secrets_decryption_key() -> bool:
    """True if .secrets.env contains a non-empty SECRETS_DECRYPTION_KEY= line (read from disk)."""
    path = os.path.join(BASE_DIR, ".secrets.env")
    if not os.path.isfile(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                parsed = _parse_secrets_env_line(line)
                if parsed and parsed[0] == "SECRETS_DECRYPTION_KEY" and str(parsed[1]).strip():
                    return True
    except OSError:
        pass
    return False


def phase2_django_auth_ready(django_target_env: str) -> tuple[bool, str | None]:
    """
    Phase 2 Playwright updaters need either DJANGO_ADMIN_USERNAME/PASSWORD (after merge/decrypt)
    or a saved session file at project root. Session files are gitignored — clones often have neither
    until secrets are configured, while the maintainer's laptop still has beta_admin_session.json.
    """
    t = _normalize_django_target_env(django_target_env)
    test_env = os.environ.copy()
    test_env["DJANGO_TARGET_ENV"] = t
    try:
        _prepare_django_child_env(test_env)
    except Exception:
        return False, "Could not load project secrets (.secrets.env or .secrets.enc decrypt)."
    u = str(test_env.get("DJANGO_ADMIN_USERNAME", "")).strip()
    p = str(test_env.get("DJANGO_ADMIN_PASSWORD", "")).strip()
    if u and p:
        return True, None
    sess_name = "prod_admin_session.json" if t == "prod" else "beta_admin_session.json"
    if os.path.isfile(os.path.join(BASE_DIR, sess_name)):
        return True, None

    enc_path = os.path.join(BASE_DIR, ".secrets.enc")
    key_path = os.path.join(BASE_DIR, ".secrets.key")
    env_path = os.path.join(BASE_DIR, ".secrets.env")
    has_enc = os.path.isfile(enc_path)
    has_key_file = os.path.isfile(key_path)
    has_key_env = bool(str(os.environ.get("SECRETS_DECRYPTION_KEY", "")).strip())
    has_key_dotenv = _dotenv_has_secrets_decryption_key()
    any_decrypt_key = has_key_file or has_key_env or has_key_dotenv

    lines = [
        "Phase 2 cannot log into Django admin: no username/password loaded and no saved session file.",
        "(Maintainers often still have beta_admin_session.json locally — it is gitignored, so clones do not.)",
        "",
        "Fix — pick ONE, then restart the Flask/Gunicorn server:",
        "  1) Edit .secrets.env — set BETA_DJANGO_ADMIN_USERNAME and BETA_DJANGO_ADMIN_PASSWORD (not URL-only).",
        "  2) Encrypted team file: keep .secrets.enc in repo root, then EITHER add .secrets.key (one line, chmod 600) OR add to .secrets.env: SECRETS_DECRYPTION_KEY=same-passphrase-as-setup_secrets.sh (restart server after edit).",
        "  3) Or export SECRETS_DECRYPTION_KEY before start (optional — run_production.sh and the app auto-read .secrets.key / .secrets.env).",
        "  4) Or copy a valid beta_admin_session.json into the project root (temporary; expires).",
        "",
        "Verify decrypt: SECRETS_DECRYPTION_KEY=$(tr -d '\\n\\r' < .secrets.key) bash scripts/verify_secrets_enc.sh",
        "Check status: GET /health → phase2_django_auth",
    ]
    if has_enc and not any_decrypt_key:
        lines.insert(
            4,
            "→ Detected .secrets.enc but no decryption key: add SECRETS_DECRYPTION_KEY=... to .secrets.env, or .secrets.key, or export SECRETS_DECRYPTION_KEY; then restart the server.",
        )
    elif has_enc and any_decrypt_key:
        lines.insert(
            4,
            "→ .secrets.enc + a key are present; if the passphrase is wrong, decrypt fails silently — run verify_secrets_enc.sh below.",
        )
    elif os.path.isfile(env_path) and not has_enc:
        lines.insert(
            4,
            "→ .secrets.env exists but has no usable BETA passwords (URL-only is not enough). Add USERNAME/PASSWORD lines.",
        )
    return False, "\n".join(lines)


_EXTRACT_SESSION_ID_RE = re.compile(r"^extract_[0-9a-f]{32}$")


def _resolve_extract_coding_output_path(session_id: str) -> str | None:
    """Return path to coding_questions_output.json for a valid extract_* session, or None."""
    if not session_id or not _EXTRACT_SESSION_ID_RE.fullmatch(session_id):
        return None
    session_dir = os.path.join(SESSIONS_DIR, session_id)
    out_path = os.path.join(session_dir, "coding_questions_output.json")
    real_sessions = os.path.realpath(SESSIONS_DIR)
    real_out = os.path.realpath(out_path)
    if not real_out.startswith(real_sessions + os.sep):
        return None
    if not os.path.isfile(real_out):
        return None
    return real_out


def _env_truthy(name: str, default: bool = False) -> bool:
    v = os.environ.get(name, "")
    if v == "":
        return default
    return v.lower() in ("1", "true", "yes", "on")


app = Flask(__name__, template_folder=TEMPLATES_DIR)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or os.urandom(24)

FORMAT_SCRIPTS = [
    "generate_input_code_data.py",
    "generate_input_desc.py",
    "generate_input_metadata.py",
    "generate_input_evaluation_metrics.py",
    "generate_input_weightages.py",
    "generate_input.py",
    "generate_input_data.py",
]

UPDATER_SCRIPTS = {
    "run_code_updater.sh": "Code & Solution",
    "run_hints_updater.sh": "Hints",
    "run_description_updater.sh": "Description",
    "run_metadata_updater.sh": "Metadata",
    "run_evaluation_metrics_updater.sh": "Evaluation metrics",
    "run_weightage_updater.sh": "Weightages",
    "run_loader.sh": "Testcases",
}

RUN_ALL_ORDER = [
    "run_code_updater.sh",
    "run_hints_updater.sh",
    "run_description_updater.sh",
    "run_metadata_updater.sh",
    "run_evaluation_metrics_updater.sh",
    "run_weightage_updater.sh",
    "run_loader.sh",
]

PIPELINE_QUEUE = queue.Queue()
PIPELINE_JOBS = {}
PIPELINE_LOCK = threading.Lock()
# Background threads that run full-pipeline jobs from /api/run_everything (queued).
# Unrelated to Gunicorn/HTTP workers; raise for more parallel pipeline runs on one machine.
PIPELINE_WORKERS = max(1, int(os.environ.get("PIPELINE_WORKERS", "5")))


def _parse_secrets_env_line(line: str):
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith("export "):
        line = line[7:].strip()
    if "=" not in line:
        return None
    key, _, value = line.partition("=")
    key = key.strip()
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return key, value


def _merge_secrets_file_into(env: dict, path: str) -> None:
    """Merge known secret keys from a single env file into env (only if target slot is empty)."""
    if not os.path.isfile(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                parsed = _parse_secrets_env_line(line)
                if not parsed:
                    continue
                k, v = parsed
                if k in ("SECRETS_DECRYPTION_KEY", "SECRETS_DECRYPTION_KEY_FILE"):
                    if str(v).strip() and not str(env.get(k, "")).strip():
                        env[k] = v.strip()
                    continue
                if not (
                    k.startswith("BETA_DJANGO_")
                    or k.startswith("PROD_DJANGO_")
                    or k.startswith("BETA_JUPYTER_")
                    or k.startswith("PROD_JUPYTER_")
                    or k.startswith("DJANGO_EVAL_")
                    or k in ("DJANGO_ADMIN_USERNAME", "DJANGO_ADMIN_PASSWORD", "DJANGO_ADMIN_URL")
                ):
                    continue
                if not str(env.get(k, "")).strip():
                    env[k] = v
    except OSError:
        pass


def _merge_project_secrets_env_into(env: dict) -> None:
    """Load BETA_/PROD_/DJANGO_* from project .secrets.env and optional secrets.local.env (gitignored)."""
    _merge_secrets_file_into(env, os.path.join(BASE_DIR, ".secrets.env"))
    _merge_secrets_file_into(env, os.path.join(BASE_DIR, "secrets.local.env"))


def _inject_secrets_decryption_key(env: dict) -> None:
    """Ensure SECRETS_DECRYPTION_KEY is set for NON_INTERACTIVE .secrets.enc decrypt (UI cwd is sessions/*)."""
    if str(env.get("SECRETS_DECRYPTION_KEY", "")).strip():
        return
    key_file = (env.get("SECRETS_DECRYPTION_KEY_FILE") or "").strip()
    if key_file and os.path.isfile(key_file):
        try:
            with open(key_file, "r", encoding="utf-8") as f:
                env["SECRETS_DECRYPTION_KEY"] = f.read().strip()
        except OSError:
            pass
    if str(env.get("SECRETS_DECRYPTION_KEY", "")).strip():
        return
    root_key = os.path.join(BASE_DIR, ".secrets.key")
    if os.path.isfile(root_key):
        try:
            with open(root_key, "r", encoding="utf-8") as f:
                env["SECRETS_DECRYPTION_KEY"] = f.read().strip()
        except OSError:
            pass


def _decrypt_secrets_enc_into_env(env: dict) -> None:
    """Decrypt .secrets.enc when SECRETS_DECRYPTION_KEY is set; merge missing Django + Jupyter + eval keys."""
    key = str(env.get("SECRETS_DECRYPTION_KEY", "")).strip()
    if not key:
        return
    enc_path = os.path.join(BASE_DIR, ".secrets.enc")
    if not os.path.isfile(enc_path):
        return
    try:
        proc = subprocess.run(
            [
                "openssl",
                "enc",
                "-aes-256-cbc",
                "-d",
                "-pbkdf2",
                "-in",
                enc_path,
                "-pass",
                f"pass:{key}",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if proc.returncode != 0:
            return
        for line in proc.stdout.splitlines():
            parsed = _parse_secrets_env_line(line)
            if not parsed:
                continue
            k, v = parsed
            if (
                k.startswith("BETA_DJANGO_")
                or k.startswith("PROD_DJANGO_")
                or k.startswith("DJANGO_EVAL_")
                or k in ("DJANGO_ADMIN_USERNAME", "DJANGO_ADMIN_PASSWORD", "DJANGO_ADMIN_URL")
            ):
                if not str(env.get(k, "")).strip():
                    env[k] = v
                continue
            if k.startswith("BETA_JUPYTER_") or k.startswith("PROD_JUPYTER_"):
                if not str(env.get(k, "")).strip():
                    env[k] = v
    except (OSError, subprocess.SubprocessError, ValueError):
        pass


def _sync_django_admin_login_env(env: dict) -> None:
    """Copy BETA_/PROD_* (or existing DJANGO_ADMIN_* from .secrets.env) into DJANGO_ADMIN_* for Playwright."""
    t = (env.get("DJANGO_TARGET_ENV") or "beta").strip().lower()
    beta_url_default = "https://nkb-backend-ccbp-beta.earlywave.in/admin/"
    prod_url_default = "https://nkb-backend-ccbp-prod-apis.ccbp.in/admin/"
    if t == "prod":
        u = str(env.get("PROD_DJANGO_ADMIN_USERNAME", "")).strip() or str(env.get("BETA_DJANGO_ADMIN_USERNAME", "")).strip()
        p = str(env.get("PROD_DJANGO_ADMIN_PASSWORD", "")).strip() or str(env.get("BETA_DJANGO_ADMIN_PASSWORD", "")).strip()
        url = str(env.get("PROD_DJANGO_ADMIN_URL", "")).strip() or str(env.get("BETA_DJANGO_ADMIN_URL", "")).strip()
    else:
        u = str(env.get("BETA_DJANGO_ADMIN_USERNAME", "")).strip()
        p = str(env.get("BETA_DJANGO_ADMIN_PASSWORD", "")).strip()
        url = str(env.get("BETA_DJANGO_ADMIN_URL", "")).strip()
    if not u:
        u = str(env.get("DJANGO_ADMIN_USERNAME", "")).strip()
    if not p:
        p = str(env.get("DJANGO_ADMIN_PASSWORD", "")).strip()
    if not url:
        url = str(env.get("DJANGO_ADMIN_URL", "")).strip()
    if not url:
        url = prod_url_default if t == "prod" else beta_url_default
    # Always set (even empty) so stale empty strings from the parent shell cannot block re-login.
    env["DJANGO_ADMIN_USERNAME"] = u
    env["DJANGO_ADMIN_PASSWORD"] = p
    env["DJANGO_ADMIN_URL"] = url


def _prepare_django_child_env(run_env: dict) -> None:
    """Load project .secrets.env / .secrets.key / .secrets.enc into env for pipeline and updaters (Flask often never sourced .secrets.env)."""
    run_env.setdefault("DJANGO_TARGET_ENV", "beta")
    _merge_project_secrets_env_into(run_env)
    _inject_secrets_decryption_key(run_env)
    _decrypt_secrets_enc_into_env(run_env)
    _sync_django_admin_login_env(run_env)


def _sanitize_log_line(line: str) -> str:
    """Mask obvious secrets before writing logs/SSE output."""
    if not isinstance(line, str):
        line = str(line)
    patterns = [
        r"(?i)\b([A-Z0-9_]*(?:PASSWORD|TOKEN|SECRET|API_KEY)[A-Z0-9_]*)\s*=\s*([^\s\"']+)",
        r"(?i)\b(password|token|secret|api[_-]?key)\s*[:=]\s*([^\s\"']+)",
        r"(?i)(X-Amz-Signature=)[0-9a-f]+",
    ]
    out = line
    out = re.sub(patterns[0], r"\1=***", out)
    out = re.sub(patterns[1], r"\1=***", out)
    out = re.sub(patterns[2], r"\1***", out)
    return out


def _job_append(job_id, line):
    line = _sanitize_log_line(line)
    log_file = None
    with PIPELINE_LOCK:
        job = PIPELINE_JOBS.get(job_id)
        if job is not None:
            job["logs"].append(line.rstrip("\n"))
            log_file = job.get("log_file")
    if log_file:
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(line.rstrip("\n") + "\n")
        except Exception:
            pass


def _job_update(job_id, **kwargs):
    with PIPELINE_LOCK:
        job = PIPELINE_JOBS.get(job_id)
        if job is not None:
            job.update(kwargs)


def _queue_position(job_id):
    with PIPELINE_LOCK:
        ids = [item["job_id"] for item in list(PIPELINE_QUEUE.queue)]
    return ids.index(job_id) + 1 if job_id in ids else 0


def _pipeline_worker():
    while True:
        payload = PIPELINE_QUEUE.get()
        job_id = payload["job_id"]
        session_dir = payload["session_dir"]
        skip_jupyter = payload["skip_jupyter"]
        skip_testcases = payload.get("skip_testcases", False)
        django_target_env = _normalize_django_target_env(payload.get("django_target_env"))
        try:
            _job_update(job_id, status="running", started_at=time.time())
            _job_append(job_id, ">>> QUEUE: job started")
            _job_append(
                job_id,
                f">>> NOTE: DJANGO_TARGET_ENV={django_target_env} — "
                "failed steps are skipped so remaining steps still run.",
            )
            script_path = os.path.join(session_dir, "run_full_pipeline.sh")
            if not os.path.isfile(script_path):
                _job_append(job_id, ">>> ERROR: run_full_pipeline.sh not found in session.")
                _job_update(job_id, status="failed", done=True, exit_code=1, finished_at=time.time())
                continue

            run_env = os.environ.copy()
            run_env["PYTHONUNBUFFERED"] = "1"
            run_env["NON_INTERACTIVE"] = "1"
            run_env["DJANGO_TARGET_ENV"] = django_target_env
            _prepare_django_child_env(run_env)
            if skip_jupyter:
                _job_append(
                    job_id,
                    ">>> NOTE: skip_jupyter in request — run_full_pipeline.sh only runs Django admin updaters; "
                    "Jupyter helper/base64 are separate scripts (./run_helper_updater.sh, ./run_base64_updater.sh).",
                )
            if skip_testcases:
                run_env["SKIP_TESTCASES"] = "1"
                _job_append(job_id, ">>> NOTE: SKIP_TESTCASES=1 enabled for this job.")

            process = subprocess.Popen(
                ["/bin/bash", script_path],
                cwd=session_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=run_env,
            )
            for line in iter(process.stdout.readline, ""):
                _job_append(job_id, _sanitize_log_line(line))
            process.stdout.close()
            rc = process.wait()

            if rc == 0:
                _job_append(job_id, ">>> SUCCESS: full pipeline completed (all steps OK).")
                _job_update(job_id, status="success", done=True, exit_code=0, finished_at=time.time())
            elif rc == 2:
                _job_append(
                    job_id,
                    ">>> FAILED: environment not ready (venv or Playwright). Fresh clone: bash scripts/bootstrap.sh from project root, then restart the server.",
                )
                _job_update(job_id, status="failed", done=True, exit_code=rc, finished_at=time.time())
            else:
                _job_append(job_id, f">>> FAILED (partial run): run_full_pipeline.sh exited with code {rc}")
                _job_append(job_id, ">>> Later steps still ran after earlier failures. Search for PIPELINE_SKIP and PIPELINE_SUMMARY above.")
                _job_update(job_id, status="failed", done=True, exit_code=rc, finished_at=time.time())
        except Exception as e:
            _job_append(job_id, f">>> ERROR: Worker exception: {e}")
            _job_update(job_id, status="failed", done=True, exit_code=1, finished_at=time.time())
        finally:
            PIPELINE_QUEUE.task_done()


def _create_pipeline_job(session_dir, skip_jupyter, skip_testcases=False, django_target_env="beta"):
    job_id = uuid.uuid4().hex
    log_file = os.path.join(session_dir, f"{job_id}.log")
    with PIPELINE_LOCK:
        PIPELINE_JOBS[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "logs": [">>> QUEUE: job accepted"],
            "log_file": log_file,
            "done": False,
            "exit_code": None,
            "created_at": time.time(),
            "started_at": None,
            "finished_at": None,
        }
    PIPELINE_QUEUE.put(
        {
            "job_id": job_id,
            "session_dir": session_dir,
            "skip_jupyter": skip_jupyter,
            "skip_testcases": skip_testcases,
            "django_target_env": _normalize_django_target_env(django_target_env),
        }
    )
    pos = _queue_position(job_id)
    _job_append(job_id, f">>> QUEUE: position {pos} (1 means next to run)")
    return job_id


def _stream_job_logs(job_id):
    idx = 0
    while True:
        with PIPELINE_LOCK:
            job = PIPELINE_JOBS.get(job_id)
            if not job:
                yield "data: >>> ERROR: job not found\n\n"
                yield "data: >>> DONE\n\n"
                return
            logs = job["logs"]
            done = job["done"]
            status = job["status"]
        while idx < len(logs):
            yield f"data: {logs[idx]}\n\n"
            idx += 1
        if done:
            yield "data: >>> DONE\n\n"
            return
        time.sleep(0.35)


_worker_threads = []
for _ in range(PIPELINE_WORKERS):
    t = threading.Thread(target=_pipeline_worker, daemon=True)
    t.start()
    _worker_threads.append(t)


@app.before_request
def _require_api_token_for_mutating_api():
    """When AUTOMATION_API_TOKEN is set, POST/PUT/PATCH/DELETE under /api/ must send it."""
    if request.method == "OPTIONS":
        return None
    if request.method not in ("POST", "PUT", "DELETE", "PATCH"):
        return None
    path = request.path or ""
    if not path.startswith("/api/"):
        return None
    token = os.environ.get("AUTOMATION_API_TOKEN")
    if not token:
        return None
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        got = auth[7:].strip()
    else:
        got = request.headers.get("X-API-Token", "")
    if got != token:
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    return None


def init_session(session_id):
    if not session_id:
        raise ValueError("No session_id provided")

    session_dir = os.path.join(SESSIONS_DIR, session_id)
    os.makedirs(session_dir, exist_ok=True)

    items_to_link = glob.glob(os.path.join(BASE_DIR, "*.py")) + glob.glob(os.path.join(BASE_DIR, "*.sh"))
    items_to_link.append(os.path.join(BASE_DIR, "venv"))
    items_to_link.append(os.path.join(BASE_DIR, ".secrets.enc"))

    for item in items_to_link:
        basename = os.path.basename(item)
        dest = os.path.join(session_dir, basename)
        if not os.path.exists(dest):
            try:
                os.symlink(item, dest)
            except OSError:
                pass

    for extra in (
        "beta_admin_session.json",
        "prod_admin_session.json",
        "lib_django_session.sh",
        "lib_pipeline_exception.sh",
        "backend",
        ".secrets.env",
        "secrets.local.env",
        ".secrets.key",
    ):
        src = os.path.join(BASE_DIR, extra)
        dest = os.path.join(session_dir, extra)
        if os.path.exists(src) and not os.path.exists(dest):
            try:
                os.symlink(src, dest)
            except OSError:
                pass
    return session_dir


@app.route("/")
def index():
    return render_template("index.html", input_content="", formatters=FORMAT_SCRIPTS, updaters=UPDATER_SCRIPTS, run_all_order=RUN_ALL_ORDER)


@app.route("/api/save_json", methods=["POST"])
def save_json():
    data = request.json
    content = data.get("content", "")
    session_id = data.get("session_id", "")

    if not content or not session_id:
        return jsonify({"success": False, "message": "Content or session_id missing."})

    try:
        json.loads(content)
        session_dir = init_session(session_id)
        input_json_path = os.path.join(session_dir, "input.json")
        with open(input_json_path, "w", encoding="utf-8") as f:
            f.write(content)
        return jsonify({"success": True, "message": "Successfully saved isolated input.json"})
    except json.JSONDecodeError as e:
        return jsonify({"success": False, "message": f"Invalid JSON format: {e}"})
    except Exception as e:
        return jsonify({"success": False, "message": f"Error saving file: {e}"})


def generate_output(scripts, session_id, is_bash=False, django_target_env=None):
    try:
        session_dir = init_session(session_id)
    except Exception as e:
        yield f"data: >>> ERROR: Failed to initialize session: {e}\n\n"
        yield "data: >>> DONE\n\n"
        return

    tgt = _normalize_django_target_env(django_target_env)
    for script in scripts:
        yield f"data: >>> RUNNING: {script}\n\n"
        try:
            script_path = os.path.join(session_dir, script)
            run_env = {**os.environ, "PYTHONUNBUFFERED": "1"}
            run_env["NON_INTERACTIVE"] = "1"
            run_env["DJANGO_TARGET_ENV"] = tgt
            _prepare_django_child_env(run_env)
            if is_bash:
                process = subprocess.Popen(
                    ["/bin/bash", script_path],
                    cwd=session_dir,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    env=run_env,
                )
                if process.stdin:
                    try:
                        process.stdin.write(f"{tgt}\n\n")
                        process.stdin.flush()
                        process.stdin.close()
                    except BrokenPipeError:
                        pass
            else:
                python_exec = os.environ.get("VIRTUAL_ENV", "/usr/bin/python3") + "/bin/python3" if os.environ.get("VIRTUAL_ENV") else "python3"
                process = subprocess.Popen(
                    [python_exec, script_path],
                    cwd=session_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    env=run_env,
                )

            for line in iter(process.stdout.readline, ""):
                yield f"data: {_sanitize_log_line(line)}\n\n"

            process.stdout.close()
            return_code = process.wait()
            if return_code != 0:
                yield f"data: >>> PIPELINE_SKIP: '{script}' ended with code {return_code} — continuing.\n\n"
            else:
                yield f"data: >>> SUCCESS: '{script}' completed successfully.\n\n"
        except Exception as e:
            yield f"data: >>> PIPELINE_SKIP: Exception in '{script}': {e} — continuing.\n\n"

    yield "data: >>> DONE\n\n"


def generate_testcases_only(content: str, django_target_env=None):
    try:
        json.loads(content)
        session_id = f"job_{uuid.uuid4().hex}"
        session_dir = init_session(session_id)
        input_json_path = os.path.join(session_dir, "input.json")
        with open(input_json_path, "w", encoding="utf-8") as f:
            f.write(content)
    except json.JSONDecodeError as e:
        yield f"data: >>> ERROR: Invalid JSON in content: {e}\n\n"
        yield "data: >>> DONE\n\n"
        return
    except Exception as e:
        yield f"data: >>> ERROR: Failed to prepare session: {e}\n\n"
        yield "data: >>> DONE\n\n"
        return

    tgt = _normalize_django_target_env(django_target_env)
    steps = [
        {"name": "generate_input_data.py", "kind": "py"},
        {"name": "run_loader.sh", "kind": "bash"},
    ]

    for step in steps:
        script = step["name"]
        kind = step["kind"]
        yield f"data: >>> RUNNING: {script}\n\n"
        try:
            script_path = os.path.join(session_dir, script)
            run_env = {**os.environ, "PYTHONUNBUFFERED": "1"}
            run_env["NON_INTERACTIVE"] = "1"
            run_env["DJANGO_TARGET_ENV"] = tgt
            _prepare_django_child_env(run_env)
            if kind == "bash":
                process = subprocess.Popen(
                    ["/bin/bash", script_path],
                    cwd=session_dir,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    env=run_env,
                )
                if process.stdin:
                    try:
                        process.stdin.write(f"{tgt}\n\n")
                        process.stdin.flush()
                        process.stdin.close()
                    except BrokenPipeError:
                        pass
            else:
                python_exec = os.environ.get("VIRTUAL_ENV", "/usr/bin/python3") + "/bin/python3" if os.environ.get("VIRTUAL_ENV") else "python3"
                process = subprocess.Popen(
                    [python_exec, script_path],
                    cwd=session_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    env=run_env,
                )

            for line in iter(process.stdout.readline, ""):
                yield f"data: {_sanitize_log_line(line)}\n\n"
            process.stdout.close()
            rc = process.wait()
            if rc != 0:
                yield f"data: >>> PIPELINE_SKIP: '{script}' ended with code {rc} — stopping testcases-only run.\n\n"
                yield "data: >>> DONE\n\n"
                return
            yield f"data: >>> SUCCESS: '{script}' completed successfully.\n\n"
        except Exception as e:
            yield f"data: >>> ERROR: Exception in '{script}': {e}\n\n"
            yield "data: >>> DONE\n\n"
            return

    yield "data: >>> DONE\n\n"


def generate_editorial_update(content: str):
    # Editorial by question id is supported on Beta only.
    tgt = _normalize_django_target_env("beta")
    try:
        json.loads(content)
        session_id = f"editorial_{uuid.uuid4().hex}"
        session_dir = init_session(session_id)
        input_path = os.path.join(session_dir, "input_editorial_by_question_id.json")
        with open(input_path, "w", encoding="utf-8") as f:
            f.write(content)
    except json.JSONDecodeError as e:
        yield f"data: >>> ERROR: Invalid JSON in content: {e}\n\n"
        yield "data: >>> DONE\n\n"
        return
    except Exception as e:
        yield f"data: >>> ERROR: Failed to prepare session: {e}\n\n"
        yield "data: >>> DONE\n\n"
        return

    script_path = os.path.join(session_dir, "backend", "scripts", "run_editorial_by_question_id.sh")
    run_env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    run_env["NON_INTERACTIVE"] = "1"
    run_env["DJANGO_TARGET_ENV"] = tgt
    _prepare_django_child_env(run_env)
    yield f"data: >>> TARGET: {tgt} (Django admin)\n\n"
    yield "data: >>> RUNNING: run_editorial_by_question_id.sh input_editorial_by_question_id.json\n\n"
    current_qid = None
    updated_qids = []
    missing_lr_qids = []
    failed_qids = []
    seen_updated = set()
    seen_missing = set()
    seen_failed = set()
    qid_line_re = re.compile(r"^\s*Question id:\s*([0-9a-fA-F-]+)\s*$")
    missing_re = re.compile(r"Question ID\s+([0-9a-fA-F-]+)\s+not found learning resource", re.I)
    skipped_qid_re = re.compile(r"Skipping Question ID\s+([0-9a-fA-F-]+)", re.I)
    try:
        process = subprocess.Popen(
            ["/bin/bash", script_path, "input_editorial_by_question_id.json"],
            cwd=session_dir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=run_env,
        )
        if process.stdin:
            try:
                process.stdin.write(f"{tgt}\n\n")
                process.stdin.flush()
                process.stdin.close()
            except BrokenPipeError:
                pass
        for line in iter(process.stdout.readline, ""):
            stripped = line.strip()
            m_q = qid_line_re.match(stripped)
            if m_q:
                current_qid = m_q.group(1)
            m_missing = missing_re.search(stripped)
            if m_missing:
                qid = m_missing.group(1)
                if qid not in seen_missing:
                    seen_missing.add(qid)
                    missing_lr_qids.append(qid)
                if qid not in seen_failed:
                    seen_failed.add(qid)
                    failed_qids.append(qid)
            m_skipped = skipped_qid_re.search(stripped)
            if m_skipped:
                qid = m_skipped.group(1)
                if qid not in seen_failed:
                    seen_failed.add(qid)
                    failed_qids.append(qid)
            if "SUCCESS: Editorial/Tutorial updated for" in stripped and current_qid:
                if current_qid not in seen_updated:
                    seen_updated.add(current_qid)
                    updated_qids.append(current_qid)
            if ("FAILURE: Could not verify success for" in stripped or "Error while updating learning resource" in stripped) and current_qid:
                if current_qid not in seen_failed:
                    seen_failed.add(current_qid)
                    failed_qids.append(current_qid)
            yield f"data: {_sanitize_log_line(line)}\n\n"
        process.stdout.close()
        rc = process.wait()
        yield (
            f"data: >>> EDITORIAL_SUMMARY: updated_count={len(updated_qids)}, "
            f"missing_learning_resource_count={len(missing_lr_qids)}, failed_count={len(failed_qids)}\n\n"
        )
        if updated_qids:
            yield f"data: >>> EDITORIAL_UPDATED_QIDS: {', '.join(updated_qids)}\n\n"
        if missing_lr_qids:
            yield f"data: >>> EDITORIAL_MISSING_LR_QIDS: {', '.join(missing_lr_qids)}\n\n"
        if failed_qids:
            yield f"data: >>> EDITORIAL_FAILED_QIDS: {', '.join(failed_qids)}\n\n"
        if rc != 0:
            yield f"data: >>> FAILED: editorial update exited with code {rc}\n\n"
        else:
            yield "data: >>> SUCCESS: editorial update completed successfully.\n\n"
    except Exception as e:
        yield f"data: >>> ERROR: Exception while running editorial update: {e}\n\n"
    yield "data: >>> DONE\n\n"


def generate_extract_coding_json(content: str, django_target_env: str = "beta"):
    target = (django_target_env or "beta").strip().lower()
    if target not in ("beta", "prod"):
        yield f"data: >>> ERROR: django_target_env must be 'beta' or 'prod', got {django_target_env!r}\n\n"
        yield "data: >>> DONE\n\n"
        return

    try:
        payload = json.loads(content)
        if not isinstance(payload, dict) or not isinstance(payload.get("question_ids"), list) or not payload.get("question_ids"):
            raise ValueError("Input must be JSON object with non-empty 'question_ids' array.")
        session_id = f"extract_{uuid.uuid4().hex}"
        session_dir = init_session(session_id)
        input_path = os.path.join(session_dir, "input_extract_question.json")
        with open(input_path, "w", encoding="utf-8") as f:
            f.write(content)
    except json.JSONDecodeError as e:
        yield f"data: >>> ERROR: Invalid JSON in content: {e}\n\n"
        yield "data: >>> DONE\n\n"
        return
    except Exception as e:
        yield f"data: >>> ERROR: Failed to prepare extraction input: {e}\n\n"
        yield "data: >>> DONE\n\n"
        return

    script_path = os.path.join(session_dir, "backend", "scripts", "run_extract_to_coding_json.sh")
    run_env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    run_env["NON_INTERACTIVE"] = "1"
    run_env["DJANGO_TARGET_ENV"] = target
    _prepare_django_child_env(run_env)
    yield f"data: >>> TARGET: {target} (Django admin)\n\n"
    yield "data: >>> RUNNING: run_extract_to_coding_json.sh input_extract_question.json extracted_coding_questions.json coding_questions_output.json\n\n"
    try:
        process = subprocess.Popen(
            [
                "/bin/bash",
                script_path,
                "input_extract_question.json",
                "extracted_coding_questions.json",
                "coding_questions_output.json",
            ],
            cwd=session_dir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=run_env,
        )
        if process.stdin:
            try:
                process.stdin.write(f"{target}\n\n")
                process.stdin.flush()
                process.stdin.close()
            except BrokenPipeError:
                pass
        for line in iter(process.stdout.readline, ""):
            yield f"data: {_sanitize_log_line(line)}\n\n"
        process.stdout.close()
        rc = process.wait()
        if rc != 0:
            yield f"data: >>> FAILED: extract-to-coding pipeline exited with code {rc}\n\n"
        else:
            yield "data: >>> SUCCESS: extracted and converted coding JSON successfully.\n\n"
            out_path = os.path.join(session_dir, "coding_questions_output.json")
            raw_path = os.path.join(session_dir, "extracted_coding_questions.json")
            yield f"data: >>> OUTPUT: {out_path}\n\n"
            yield f"data: >>> RAW_OUTPUT: {raw_path}\n\n"
            try:
                with open(out_path, "r", encoding="utf-8") as f:
                    json.load(f)
                yield f"data: >>> CONVERTED_SESSION: {session_id}\n\n"
            except json.JSONDecodeError as e:
                yield f"data: >>> WARN: converted output is not valid JSON: {e}\n\n"
            except Exception as e:
                yield f"data: >>> WARN: could not read converted JSON for download: {e}\n\n"
    except Exception as e:
        yield f"data: >>> ERROR: Exception while running extract-to-coding pipeline: {e}\n\n"
    yield "data: >>> DONE\n\n"


@app.route("/api/run_format", methods=["POST"])
def run_format():
    data = request.json or {}
    session_id = data.get("session_id", "")
    if not session_id:
        return jsonify({"success": False, "message": "Missing session_id"}), 400
    tgt = data.get("django_target_env")
    return Response(generate_output(FORMAT_SCRIPTS, session_id, is_bash=False, django_target_env=tgt), mimetype="text/event-stream")


@app.route("/api/run_updater", methods=["POST"])
def run_updater():
    data = request.json or {}
    action = data.get("action")
    session_id = data.get("session_id", "")
    if not session_id:
        return jsonify({"success": False, "message": "Missing session_id"}), 400

    if action == "all":
        scripts_to_run = RUN_ALL_ORDER
    elif action in UPDATER_SCRIPTS:
        scripts_to_run = [action]
    else:
        return jsonify({"success": False, "message": "Unknown action."}), 400

    tgt = data.get("django_target_env")
    return Response(generate_output(scripts_to_run, session_id, is_bash=True, django_target_env=tgt), mimetype="text/event-stream")


@app.route("/api/run_everything", methods=["POST"])
def run_everything():
    data = request.json or {}
    content = data.get("content")
    if content is None or not str(content).strip():
        return jsonify(
            {
                "success": False,
                "message": "input.json is required: send a non-empty JSON string in the request body field `content`.",
            }
        ), 400

    try:
        json.loads(content)
        session_id = data.get("session_id") or f"job_{uuid.uuid4().hex}"
        session_dir = init_session(session_id)
        path = os.path.join(session_dir, "input.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    except json.JSONDecodeError as e:
        return jsonify({"success": False, "message": f"Invalid JSON in content: {e}"}), 400
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 400

    blocking = pipeline_environment_blocking_issues()
    if blocking:
        return jsonify(
            {
                "success": False,
                "message": " ".join(blocking),
                "hint": "From project root: bash scripts/bootstrap.sh then restart the server.",
            }
        ), 503

    django_target_env = _normalize_django_target_env(data.get("django_target_env"))
    auth_ok, auth_msg = phase2_django_auth_ready(django_target_env)
    if not auth_ok:
        return jsonify(
            {
                "success": False,
                "message": auth_msg or "Phase 2 authentication not configured.",
                "hint": "Restart the server after editing .secrets.env or adding .secrets.key.",
            }
        ), 503

    skip_jupyter = bool(data.get("skip_jupyter"))
    skip_testcases = bool(data.get("skip_testcases"))
    job_id = _create_pipeline_job(session_dir, skip_jupyter, skip_testcases, django_target_env=django_target_env)
    return Response(_stream_job_logs(job_id), mimetype="text/event-stream")


@app.route("/api/run_testcases_only", methods=["POST"])
def run_testcases_only():
    data = request.json or {}
    content = data.get("content")
    if content is None or not str(content).strip():
        return jsonify({"success": False, "message": "input.json is required."}), 400
    tgt = data.get("django_target_env")
    return Response(generate_testcases_only(content, django_target_env=tgt), mimetype="text/event-stream")


@app.route("/editorial")
def editorial_page():
    return render_template("editorial.html")


@app.route("/extract-coding")
def extract_coding_page():
    return render_template("extract_coding.html")


@app.route("/api/run_editorial_update", methods=["POST"])
def run_editorial_update():
    data = request.json or {}
    content = data.get("content")
    if content is None or not str(content).strip():
        return jsonify({"success": False, "message": "Editorial JSON is required."}), 400
    return Response(generate_editorial_update(content), mimetype="text/event-stream")


@app.route("/api/run_extract_coding", methods=["POST"])
def run_extract_coding():
    data = request.json or {}
    content = data.get("content")
    if content is None or not str(content).strip():
        return jsonify({"success": False, "message": "Extract input JSON is required."}), 400
    django_target_env = data.get("django_target_env", "beta")
    return Response(
        generate_extract_coding_json(content, django_target_env=django_target_env),
        mimetype="text/event-stream",
    )


@app.route("/api/extract_coding_result/<session_id>", methods=["GET"])
def extract_coding_result(session_id):
    """Serve full converted JSON (avoids megabyte lines in SSE)."""
    path = _resolve_extract_coding_output_path(session_id)
    if not path:
        return jsonify({"success": False, "message": "Not found or invalid session."}), 404
    return send_file(
        path,
        mimetype="application/json",
        as_attachment=True,
        download_name="coding_questions_output.json",
    )


@app.route("/health", methods=["GET"])
def health():
    env_issues = pipeline_environment_blocking_issues()
    b_ok, b_msg = phase2_django_auth_ready("beta")
    p_ok, p_msg = phase2_django_auth_ready("prod")
    return jsonify(
        {
            "ok": True,
            "status": "healthy",
            "pipeline_workers": PIPELINE_WORKERS,
            "queue_depth": PIPELINE_QUEUE.qsize(),
            "pipeline_environment": {
                "venv_bin_activate": os.path.isfile(os.path.join(BASE_DIR, "venv", "bin", "activate")),
                "playwright_import_ok": not bool(env_issues),
                "blocking_issues": env_issues,
                "beta_django_credentials_ok": beta_django_credentials_resolved(),
                "after_git_clone_run": "bash scripts/bootstrap.sh",
            },
            "phase2_django_auth": {
                "beta_ready": b_ok,
                "beta_hint_if_not_ready": None if b_ok else b_msg,
                "prod_ready": p_ok,
                "prod_hint_if_not_ready": None if p_ok else p_msg,
                "has_beta_admin_session_json": os.path.isfile(os.path.join(BASE_DIR, "beta_admin_session.json")),
                "has_prod_admin_session_json": os.path.isfile(os.path.join(BASE_DIR, "prod_admin_session.json")),
            },
            "django_secrets_files": {
                "project_root": BASE_DIR,
                "has_dot_secrets_env": os.path.isfile(os.path.join(BASE_DIR, ".secrets.env")),
                "has_dot_secrets_key": os.path.isfile(os.path.join(BASE_DIR, ".secrets.key")),
                "has_dot_secrets_enc": os.path.isfile(os.path.join(BASE_DIR, ".secrets.enc")),
            },
        }
    ), 200


def run_dev_server():
    """Local development only. Production: use gunicorn (see gunicorn.conf.py)."""
    host = os.environ.get("FLASK_HOST", "0.0.0.0")
    port = int(os.environ.get("FLASK_PORT", "5000"))
    debug = _env_truthy("FLASK_DEBUG", default=False)
    threaded = _env_truthy("FLASK_THREADED", default=True)
    app.run(
        debug=debug,
        host=host,
        port=port,
        use_reloader=False,
        threaded=threaded,
    )


if __name__ == "__main__":
    run_dev_server()
