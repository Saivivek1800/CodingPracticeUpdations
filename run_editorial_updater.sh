#!/bin/bash

if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

echo -n "Environment (beta/prod) [default: beta]: "
read ENV_CHOICE
ENV_CHOICE=${ENV_CHOICE:-beta}

if [ -f ".secrets.enc" ]; then
    echo -n "Enter the decryption key: "
    read -s DECRYPTION_KEY
    echo ""
    
    if [ ! -z "$DECRYPTION_KEY" ]; then
        WHILE_READ_VARS=$(openssl enc -aes-256-cbc -d -pbkdf2 -in .secrets.enc -k "$DECRYPTION_KEY" 2>/dev/null)
        
        if [ $? -eq 0 ] && [ ! -z "$WHILE_READ_VARS" ]; then
            # Parse all vars
            export BETA_W_U=$(echo "$WHILE_READ_VARS" | grep "BETA_DJANGO_ADMIN_USERNAME" | cut -d '=' -f 2- | tr -d '"')
            export BETA_W_P=$(echo "$WHILE_READ_VARS" | grep "BETA_DJANGO_ADMIN_PASSWORD" | cut -d '=' -f 2- | tr -d '"')
            export BETA_W_L=$(echo "$WHILE_READ_VARS" | grep "BETA_DJANGO_ADMIN_URL" | cut -d '=' -f 2- | tr -d '"')
            
            export PROD_W_U=$(echo "$WHILE_READ_VARS" | grep "PROD_DJANGO_ADMIN_USERNAME" | cut -d '=' -f 2- | tr -d '"')
            export PROD_W_P=$(echo "$WHILE_READ_VARS" | grep "PROD_DJANGO_ADMIN_PASSWORD" | cut -d '=' -f 2- | tr -d '"')
            export PROD_W_L=$(echo "$WHILE_READ_VARS" | grep "PROD_DJANGO_ADMIN_URL" | cut -d '=' -f 2- | tr -d '"')
        else
            echo "Error: Pass key doesn't match"
            exit 1
        fi
    fi
fi

if [[ "$ENV_CHOICE" == "prod" ]]; then
    export SESSION_FILE="prod_admin_session.json"
    export DJANGO_ADMIN_USERNAME=${PROD_W_U:-$BETA_W_U}
    export DJANGO_ADMIN_PASSWORD=${PROD_W_P:-$BETA_W_P}
    export DJANGO_ADMIN_URL=${PROD_W_L}
else
    export SESSION_FILE="beta_admin_session.json"
    export DJANGO_ADMIN_USERNAME=$BETA_W_U
    export DJANGO_ADMIN_PASSWORD=$BETA_W_P
    export DJANGO_ADMIN_URL=${BETA_W_L}
fi

export DJANGO_ADMIN_USERNAME
export DJANGO_ADMIN_PASSWORD
export DJANGO_ADMIN_URL

if [ -z "$DJANGO_ADMIN_USERNAME" ] || [ -z "$DJANGO_ADMIN_PASSWORD" ] || [ -z "$DJANGO_ADMIN_URL" ]; then
    echo "Error: Credentials could not be loaded. Please ensure you provided the correct decryption key."
    exit 1
fi

if [ -z "$1" ]; then
    echo "Usage: ./run_editorial_updater.sh <path_to_input_json>"
    exit 1
fi

python3 auto_editorial_updater.py "$1"
