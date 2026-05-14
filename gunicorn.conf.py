# Gunicorn config for django_admin_automation Flask API.
# Load with: gunicorn -c gunicorn.conf.py backend.api.wsgi:app
#
# IMPORTANT: Use workers = 1. Pipeline jobs and SSE log buffers live in process
# memory; multiple workers split traffic and break job lookup / streaming.
# Increase concurrency with threads instead.

import os

# Replit / PaaS: listen on $PORT when set (BIND overrides if you need a full host:port).
if os.environ.get("BIND"):
    bind = os.environ["BIND"]
elif os.environ.get("PORT"):
    bind = f"0.0.0.0:{os.environ['PORT']}"
else:
    bind = "0.0.0.0:5000"
workers = int(os.environ.get("GUNICORN_WORKERS", "1"))
# Each open SSE stream (e.g. pipeline logs) holds a worker thread until the job ends.
# Default 16 was too low — exhausted pool looks like "blank page / loading forever" on / and /health.
threads = int(os.environ.get("GUNICORN_THREADS", "64"))
worker_class = "gthread"
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "0"))
graceful_timeout = int(os.environ.get("GUNICORN_GRACEFUL_TIMEOUT", "120"))
accesslog = os.environ.get("GUNICORN_ACCESSLOG", "-")
errorlog = os.environ.get("GUNICORN_ERRORLOG", "-")
loglevel = os.environ.get("GUNICORN_LOGLEVEL", "info")
preload_app = os.environ.get("GUNICORN_PRELOAD", "0") in ("1", "true", "yes")

if workers != 1:
    # Forking multiple workers duplicates threads + queue state; jobs will 404 randomly.
    workers = 1
