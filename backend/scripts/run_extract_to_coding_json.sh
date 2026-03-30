#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

INPUT_FILE="${1:-input_extract_question.json}"
RAW_OUTPUT_FILE="${2:-extracted_coding_questions.json}"
CONVERTED_OUTPUT_FILE="${3:-coding_questions_output.json}"

# shellcheck source=lib_django_session.sh
source "$SCRIPT_DIR/lib_django_session.sh"

exec python3 -u extract_and_convert_coding_question.py "$INPUT_FILE" --raw-output "$RAW_OUTPUT_FILE" --output "$CONVERTED_OUTPUT_FILE"
