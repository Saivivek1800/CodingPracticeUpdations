#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

INPUT_FILE="${1:-input_editorial.json}"

# shellcheck source=lib_django_session.sh
source "$SCRIPT_DIR/lib_django_session.sh"

if [ -z "$DJANGO_ADMIN_USERNAME" ] || [ -z "$DJANGO_ADMIN_PASSWORD" ]; then
    if [[ "$DJANGO_ADMIN_URL" == *"prod"* ]]; then
        export DJANGO_ADMIN_USERNAME="${PROD_DJANGO_ADMIN_USERNAME:-$DJANGO_ADMIN_USERNAME}"
        export DJANGO_ADMIN_PASSWORD="${PROD_DJANGO_ADMIN_PASSWORD:-$DJANGO_ADMIN_PASSWORD}"
    else
        export DJANGO_ADMIN_USERNAME="${BETA_DJANGO_ADMIN_USERNAME:-$DJANGO_ADMIN_USERNAME}"
        export DJANGO_ADMIN_PASSWORD="${BETA_DJANGO_ADMIN_PASSWORD:-$DJANGO_ADMIN_PASSWORD}"
    fi
fi

exec python3 -u auto_editorial_updater.py "$INPUT_FILE"
