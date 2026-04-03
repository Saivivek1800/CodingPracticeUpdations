import os
import json
import re
import subprocess
import threading
import glob
import queue
import time
import uuid
from flask import Flask, render_template, request, jsonify, Response

# Paths for scripts (project root two levels above this file)
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SESSIONS_DIR = os.path.join(BASE_DIR, "sessions")
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
TEMPLATES_DIR = os.path.join(FRONTEND_DIR, "templates")


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
        try:
            _job_update(job_id, status="running", started_at=time.time())
            _job_append(job_id, ">>> QUEUE: job started")
            script_path = os.path.join(session_dir, "run_full_pipeline.sh")
            if not os.path.isfile(script_path):
                _job_append(job_id, ">>> ERROR: run_full_pipeline.sh not found in session.")
                _job_update(job_id, status="failed", done=True, exit_code=1, finished_at=time.time())
                continue

            run_env = os.environ.copy()
            run_env["PYTHONUNBUFFERED"] = "1"
            run_env["NON_INTERACTIVE"] = "1"
            run_env["DJANGO_TARGET_ENV"] = run_env.get("DJANGO_TARGET_ENV", "beta")
            if skip_jupyter:
                run_env["SKIP_JUPYTER"] = "1"
                _job_append(job_id, ">>> NOTE: SKIP_JUPYTER=1 enabled for this job.")
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
            else:
                _job_append(job_id, f">>> FAILED (partial run): run_full_pipeline.sh exited with code {rc}")
                _job_append(job_id, ">>> Later steps still ran after earlier failures. Search for PIPELINE_SKIP and PIPELINE_SUMMARY above.")
                _job_update(job_id, status="failed", done=True, exit_code=rc, finished_at=time.time())
        except Exception as e:
            _job_append(job_id, f">>> ERROR: Worker exception: {e}")
            _job_update(job_id, status="failed", done=True, exit_code=1, finished_at=time.time())
        finally:
            PIPELINE_QUEUE.task_done()


def _create_pipeline_job(session_dir, skip_jupyter, skip_testcases=False):
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


def generate_output(scripts, session_id, is_bash=False):
    try:
        session_dir = init_session(session_id)
    except Exception as e:
        yield f"data: >>> ERROR: Failed to initialize session: {e}\n\n"
        yield "data: >>> DONE\n\n"
        return

    for script in scripts:
        yield f"data: >>> RUNNING: {script}\n\n"
        try:
            script_path = os.path.join(session_dir, script)
            run_env = {**os.environ, "PYTHONUNBUFFERED": "1"}
            run_env["NON_INTERACTIVE"] = "1"
            run_env["DJANGO_TARGET_ENV"] = run_env.get("DJANGO_TARGET_ENV", "beta")
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
                        process.stdin.write("beta\n\n")
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


def generate_testcases_only(content: str):
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
            run_env["DJANGO_TARGET_ENV"] = run_env.get("DJANGO_TARGET_ENV", "beta")
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
                        process.stdin.write("beta\n\n")
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
    run_env["DJANGO_TARGET_ENV"] = run_env.get("DJANGO_TARGET_ENV", "beta")
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
                process.stdin.write("beta\n\n")
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
                    converted_obj = json.load(f)
                converted_compact = json.dumps(converted_obj, separators=(",", ":"), ensure_ascii=False)
                yield f"data: >>> CONVERTED_JSON: {converted_compact}\n\n"
            except Exception as e:
                yield f"data: >>> WARN: could not stream converted JSON content: {e}\n\n"
    except Exception as e:
        yield f"data: >>> ERROR: Exception while running extract-to-coding pipeline: {e}\n\n"
    yield "data: >>> DONE\n\n"


@app.route("/api/run_format", methods=["POST"])
def run_format():
    data = request.json
    session_id = data.get("session_id", "")
    if not session_id:
        return jsonify({"success": False, "message": "Missing session_id"}), 400
    return Response(generate_output(FORMAT_SCRIPTS, session_id, is_bash=False), mimetype="text/event-stream")


@app.route("/api/run_updater", methods=["POST"])
def run_updater():
    data = request.json
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

    return Response(generate_output(scripts_to_run, session_id, is_bash=True), mimetype="text/event-stream")


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

    skip_jupyter = bool(data.get("skip_jupyter"))
    skip_testcases = bool(data.get("skip_testcases"))
    job_id = _create_pipeline_job(session_dir, skip_jupyter, skip_testcases)
    return Response(_stream_job_logs(job_id), mimetype="text/event-stream")


@app.route("/api/run_testcases_only", methods=["POST"])
def run_testcases_only():
    data = request.json or {}
    content = data.get("content")
    if content is None or not str(content).strip():
        return jsonify({"success": False, "message": "input.json is required."}), 400
    return Response(generate_testcases_only(content), mimetype="text/event-stream")


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


@app.route("/health", methods=["GET"])
def health():
    return jsonify(
        {
            "ok": True,
            "status": "healthy",
            "pipeline_workers": PIPELINE_WORKERS,
            "queue_depth": PIPELINE_QUEUE.qsize(),
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
