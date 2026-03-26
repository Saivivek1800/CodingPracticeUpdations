# Shared Django admin env: session-first, then .secrets.env, then optional .secrets.enc
# Source from project root: source "$(dirname "$0")/lib_django_session.sh" (after cd to project root)

BETA_ADMIN_URL="${BETA_DJANGO_ADMIN_URL:-https://nkb-backend-ccbp-beta.earlywave.in/admin/}"
PROD_ADMIN_URL="${PROD_DJANGO_ADMIN_URL:-https://nkb-backend-ccbp-prod-apis.ccbp.in/admin/}"

if [ -f ".secrets.env" ]; then
    set -a
    source .secrets.env 2>/dev/null
    set +a
    BETA_W_U="${BETA_DJANGO_ADMIN_USERNAME:-}"
    BETA_W_P="${BETA_DJANGO_ADMIN_PASSWORD:-}"
    BETA_W_L="${BETA_DJANGO_ADMIN_URL:-}"
    PROD_W_U="${PROD_DJANGO_ADMIN_USERNAME:-}"
    PROD_W_P="${PROD_DJANGO_ADMIN_PASSWORD:-}"
    PROD_W_L="${PROD_DJANGO_ADMIN_URL:-}"
fi

echo -n "Environment (beta/prod) [default: beta]: "
read ENV_CHOICE
ENV_CHOICE=${ENV_CHOICE:-beta}

if [[ "$ENV_CHOICE" == "prod" ]]; then
    export SESSION_FILE="prod_admin_session.json"
    export DJANGO_ADMIN_URL="$PROD_ADMIN_URL"
else
    export SESSION_FILE="beta_admin_session.json"
    export DJANGO_ADMIN_URL="$BETA_ADMIN_URL"
fi

USE_SESSION=false
if [ -f "$SESSION_FILE" ]; then
    echo "Using saved session ($SESSION_FILE). No password needed."
    USE_SESSION=true
    export DJANGO_ADMIN_USERNAME=""
    export DJANGO_ADMIN_PASSWORD=""
fi

if [ "$USE_SESSION" != "true" ]; then
    if [ -f ".secrets.enc" ]; then
        echo -n "Enter the decryption key (or press Enter to skip): "
        read -s DECRYPTION_KEY
        echo ""
        if [ -n "$DECRYPTION_KEY" ]; then
            WHILE_READ_VARS=$(openssl enc -aes-256-cbc -d -pbkdf2 -in .secrets.enc -k "$DECRYPTION_KEY" 2>/dev/null)
            if [ $? -eq 0 ] && [ -n "$WHILE_READ_VARS" ]; then
                export BETA_W_U=$(echo "$WHILE_READ_VARS" | grep "BETA_DJANGO_ADMIN_USERNAME" | cut -d '=' -f 2- | tr -d '"')
                export BETA_W_P=$(echo "$WHILE_READ_VARS" | grep "BETA_DJANGO_ADMIN_PASSWORD" | cut -d '=' -f 2- | tr -d '"')
                export BETA_W_L=$(echo "$WHILE_READ_VARS" | grep "BETA_DJANGO_ADMIN_URL" | cut -d '=' -f 2- | tr -d '"')
                export PROD_W_U=$(echo "$WHILE_READ_VARS" | grep "PROD_DJANGO_ADMIN_USERNAME" | cut -d '=' -f 2- | tr -d '"')
                export PROD_W_P=$(echo "$WHILE_READ_VARS" | grep "PROD_DJANGO_ADMIN_PASSWORD" | cut -d '=' -f 2- | tr -d '"')
                export PROD_W_L=$(echo "$WHILE_READ_VARS" | grep "PROD_DJANGO_ADMIN_URL" | cut -d '=' -f 2- | tr -d '"')
            else
                echo "Warning: Decryption key did not work. Will try with .secrets.env if present."
            fi
        fi
    fi

    if [[ "$ENV_CHOICE" == "prod" ]]; then
        export DJANGO_ADMIN_USERNAME="${PROD_W_U:-$BETA_W_U}"
        export DJANGO_ADMIN_PASSWORD="${PROD_W_P:-$BETA_W_P}"
        export DJANGO_ADMIN_URL="${PROD_W_L:-$PROD_ADMIN_URL}"
    else
        export DJANGO_ADMIN_USERNAME="${BETA_W_U}"
        export DJANGO_ADMIN_PASSWORD="${BETA_W_P}"
        export DJANGO_ADMIN_URL="${BETA_W_L:-$BETA_ADMIN_URL}"
    fi

    if [ -z "$DJANGO_ADMIN_USERNAME" ] || [ -z "$DJANGO_ADMIN_PASSWORD" ]; then
        echo "Error: No saved session found and no credentials loaded."
        echo "  - Run once with credentials to create $SESSION_FILE, or add .secrets.env."
        echo ""
        echo ">>> PIPELINE_EXCEPTION"
        echo ">>>   phase:   PHASE_2_PERFORM_ACTIONS (Django env)"
        echo ">>>   step:    lib_django_session.sh"
        echo ">>>   code:    1"
        echo ">>>   detail:  Missing DJANGO credentials and no session file $SESSION_FILE"
        exit 1
    fi
fi

export DJANGO_ADMIN_USERNAME
export DJANGO_ADMIN_PASSWORD
export DJANGO_ADMIN_URL
export SESSION_FILE
