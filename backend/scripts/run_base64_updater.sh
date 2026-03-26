#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"
# shellcheck source=lib_pipeline_exception.sh
source "$SCRIPT_DIR/lib_pipeline_exception.sh"

if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

if [ -f ".secrets.env" ]; then
    set -a
    source .secrets.env 2>/dev/null
    set +a
fi
export BETA_J="${BETA_JUPYTER_PASSWORD:-}"
export PROD_J="${PROD_JUPYTER_PASSWORD:-}"

echo -n "Environment (beta/prod) [default: beta]: "
read ENV_CHOICE
ENV_CHOICE=${ENV_CHOICE:-beta}

if [ -f ".secrets.enc" ] && [ -z "$BETA_J" ] && [ -z "$PROD_J" ]; then
    echo -n "Enter the decryption key (or press Enter to skip): "
    read -s DECRYPTION_KEY
    echo ""
    if [ -n "$DECRYPTION_KEY" ]; then
        WHILE_READ_VARS=$(openssl enc -aes-256-cbc -d -pbkdf2 -in .secrets.enc -k "$DECRYPTION_KEY" 2>/dev/null)
        if [ $? -eq 0 ] && [ -n "$WHILE_READ_VARS" ]; then
            export BETA_J=$(echo "$WHILE_READ_VARS" | grep "BETA_JUPYTER_PASSWORD" | cut -d '=' -f 2- | tr -d '"')
            export PROD_J=$(echo "$WHILE_READ_VARS" | grep "PROD_JUPYTER_PASSWORD" | cut -d '=' -f 2- | tr -d '"')
        else
            echo "Warning: Decryption key did not work for Jupyter secrets."
        fi
    fi
fi

if [[ "$ENV_CHOICE" == "prod" ]]; then
    export JUPYTER_URL="https://3.111.135.132:9944/notebooks/base64.ipynb"
    export JUPYTER_PASSWORD=${PROD_J}
else
    export JUPYTER_URL="https://3.111.135.132:2222/notebooks/base64.ipynb"
    export JUPYTER_PASSWORD=${BETA_J}
fi

if [ -z "$JUPYTER_PASSWORD" ]; then
    echo "Error: BETA_JUPYTER_PASSWORD / PROD_JUPYTER_PASSWORD not set. Add them to .secrets.env on the server."
    pipeline_exception "PHASE_2_PERFORM_ACTIONS" "run_base64_updater.sh (credentials)" 1 "JUPYTER_PASSWORD empty — set BETA_JUPYTER_PASSWORD in .secrets.env or use SKIP_JUPYTER=1"
fi

echo ">>>   [run_base64_updater] generate_base64_input.py"
python3 generate_base64_input.py || pipeline_exception "PHASE_2_PERFORM_ACTIONS" "run_base64_updater.sh → generate_base64_input.py" "$?" "see Python output above"
echo ">>>   [run_base64_updater] run_jupyter_base64.py"
python3 run_jupyter_base64.py || pipeline_exception "PHASE_2_PERFORM_ACTIONS" "run_base64_updater.sh → run_jupyter_base64.py" "$?" "Jupyter automation failed — network, login, or notebook UI"
