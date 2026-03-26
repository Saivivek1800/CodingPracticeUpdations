#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

INPUT_FILE="${1:-input_metadata.json}"

# shellcheck source=lib_django_session.sh
source "$SCRIPT_DIR/lib_django_session.sh"

python3 auto_metadata_updater.py "$INPUT_FILE"
