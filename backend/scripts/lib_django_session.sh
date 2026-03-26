# Shared Django admin env: session-first, then .secrets.env, then optional .secrets.enc
# Source from project root: source "$(dirname "$0")/lib_django_session.sh" (after cd to project root)

BETA_ADMIN_URL="${BETA_DJANGO_ADMIN_URL:-https://nkb-backend-ccbp-beta.earlywave.in/admin/}"
PROD_ADMIN_URL="${PROD_DJANGO_ADMIN_URL:-https://nkb-backend-ccbp-prod-apis.ccbp.in/admin/}"
NON_INTERACTIVE="${NON_INTERACTIVE:-0}"

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

if [ -n "${DJANGO_TARGET_ENV:-}" ]; then
    ENV_CHOICE="${DJANGO_TARGET_ENV}"
elif [ "$NON_INTERACTIVE" = "1" ]; then
    ENV_CHOICE="${DEFAULT_DJANGO_ENV:-beta}"
    echo "Environment (non-interactive): $ENV_CHOICE"
else
    echo -n "Environment (beta/prod) [default: beta]: "
    read ENV_CHOICE
    ENV_CHOICE=${ENV_CHOICE:-beta}
fi

if [[ "$ENV_CHOICE" == "prod" ]]; then
    export SESSION_FILE="prod_admin_session.json"
    export DJANGO_ADMIN_URL="$PROD_ADMIN_URL"
else
    export SESSION_FILE="beta_admin_session.json"
    export DJANGO_ADMIN_URL="$BETA_ADMIN_URL"
fi

USE_SESSION=false
if [ -f "$SESSION_FILE" ]; then
    echo "Using saved session ($SESSION_FILE). If it expires, the same credentials as other updaters (.secrets.env / .secrets.enc) are used to re-login."
    USE_SESSION=true
fi

# Decrypt .secrets.enc when: no session file (always try), or session file exists but creds still missing for this env
RUN_SECRETS_DECRYPT=false
if [ -f ".secrets.enc" ]; then
    if [ "$USE_SESSION" != "true" ]; then
        RUN_SECRETS_DECRYPT=true
    else
        if [[ "$ENV_CHOICE" == "prod" ]]; then
            [ -z "${PROD_W_U:-}" ] && [ -z "${BETA_W_U:-}" ] && RUN_SECRETS_DECRYPT=true
        else
            [ -z "${BETA_W_U:-}" ] && RUN_SECRETS_DECRYPT=true
        fi
    fi
fi

if [ "$RUN_SECRETS_DECRYPT" = "true" ]; then
    if [ "$NON_INTERACTIVE" = "1" ]; then
        DECRYPTION_KEY="${SECRETS_DECRYPTION_KEY:-}"
    else
        echo -n "Enter the decryption key (or press Enter to skip): "
        read -s DECRYPTION_KEY
        echo ""
    fi
    if [ -n "$DECRYPTION_KEY" ]; then
        # Must match setup_secrets.sh: openssl enc -aes-256-cbc -salt -pbkdf2 -pass pass:"$KEY"
        _OPENSSL_ERR="${TMPDIR:-/tmp}/lib_django_openssl_$$.err"
        WHILE_READ_VARS=$(openssl enc -aes-256-cbc -d -pbkdf2 -in .secrets.enc -pass pass:"$DECRYPTION_KEY" 2>"$_OPENSSL_ERR")
        _OPENSSL_EC=$?
        WHILE_READ_VARS=$(printf '%s' "$WHILE_READ_VARS" | tr -d '\r')
        if [ "$_OPENSSL_EC" -eq 0 ] && [ -n "$WHILE_READ_VARS" ]; then
            export BETA_W_U=$(echo "$WHILE_READ_VARS" | grep "BETA_DJANGO_ADMIN_USERNAME" | head -1 | cut -d '=' -f 2- | tr -d '"' | tr -d '\r')
            export BETA_W_P=$(echo "$WHILE_READ_VARS" | grep "BETA_DJANGO_ADMIN_PASSWORD" | head -1 | cut -d '=' -f 2- | tr -d '"' | tr -d '\r')
            export BETA_W_L=$(echo "$WHILE_READ_VARS" | grep "BETA_DJANGO_ADMIN_URL" | head -1 | cut -d '=' -f 2- | tr -d '"' | tr -d '\r')
            export PROD_W_U=$(echo "$WHILE_READ_VARS" | grep "PROD_DJANGO_ADMIN_USERNAME" | head -1 | cut -d '=' -f 2- | tr -d '"' | tr -d '\r')
            export PROD_W_P=$(echo "$WHILE_READ_VARS" | grep "PROD_DJANGO_ADMIN_PASSWORD" | head -1 | cut -d '=' -f 2- | tr -d '"' | tr -d '\r')
            export PROD_W_L=$(echo "$WHILE_READ_VARS" | grep "PROD_DJANGO_ADMIN_URL" | head -1 | cut -d '=' -f 2- | tr -d '"' | tr -d '\r')
        else
            echo "Warning: .secrets.enc decrypt failed (wrong SECRETS_DECRYPTION_KEY, corrupt file, or OpenSSL mismatch)." >&2
            if [ -s "$_OPENSSL_ERR" ]; then
                echo "  openssl: $(tr -d '\n' < "$_OPENSSL_ERR" | head -c 200)" >&2
            fi
            echo "  Will try with .secrets.env if present." >&2
        fi
        rm -f "$_OPENSSL_ERR"
    elif [ "$NON_INTERACTIVE" = "1" ] && [ -f ".secrets.enc" ]; then
        echo "Warning: NON_INTERACTIVE=1 but SECRETS_DECRYPTION_KEY is empty — cannot decrypt .secrets.enc." >&2
        echo "  Export it: SECRETS_DECRYPTION_KEY='your-validation-key' ..." >&2
    fi
fi

# Same credential sources as all other updaters (always export for Python child processes)
if [[ "$ENV_CHOICE" == "prod" ]]; then
    export DJANGO_ADMIN_USERNAME="${PROD_W_U:-$BETA_W_U}"
    export DJANGO_ADMIN_PASSWORD="${PROD_W_P:-$BETA_W_P}"
    export DJANGO_ADMIN_URL="${PROD_W_L:-$PROD_ADMIN_URL}"
else
    export DJANGO_ADMIN_USERNAME="${BETA_W_U}"
    export DJANGO_ADMIN_PASSWORD="${BETA_W_P}"
    export DJANGO_ADMIN_URL="${BETA_W_L:-$BETA_ADMIN_URL}"
fi

if [ "$USE_SESSION" != "true" ]; then
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
