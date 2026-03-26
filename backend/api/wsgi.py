"""WSGI entry for production servers (e.g. gunicorn).

Use a single worker process so the in-memory pipeline queue and job registry stay
consistent. Scale concurrency with GUNICORN_THREADS instead of multiple workers.

Example:
  gunicorn -c gunicorn.conf.py backend.api.wsgi:app
"""

from backend.api.server import app

__all__ = ["app"]
