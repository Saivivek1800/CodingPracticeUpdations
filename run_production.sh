#!/usr/bin/env bash
# Production entry: single Gunicorn process, many threads (in-memory job state is not
# shared across Gunicorn worker processes — do not raise GUNICORN_WORKERS above 1).
set -euo pipefail
cd "$(dirname "$0")"

export FLASK_DEBUG="${FLASK_DEBUG:-0}"
export GUNICORN_WORKERS="${GUNICORN_WORKERS:-1}"
export GUNICORN_THREADS="${GUNICORN_THREADS:-16}"

# Use project venv so `gunicorn` works without activating venv first.
if [ -x "venv/bin/gunicorn" ]; then
  exec "venv/bin/gunicorn" -c gunicorn.conf.py backend.api.wsgi:app
fi
if [ -f "venv/bin/python3" ]; then
  exec "venv/bin/python3" -m gunicorn -c gunicorn.conf.py backend.api.wsgi:app
fi
echo "gunicorn not found. Install into venv: ./venv/bin/python3 -m pip install -r requirements.txt" >&2
exit 1
