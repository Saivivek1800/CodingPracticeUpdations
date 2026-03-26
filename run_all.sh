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
            export BETA_J=$(echo "$WHILE_READ_VARS" | grep "BETA_JUPYTER_PASSWORD" | cut -d '=' -f 2- | tr -d '"')
            export PROD_J=$(echo "$WHILE_READ_VARS" | grep "PROD_JUPYTER_PASSWORD" | cut -d '=' -f 2- | tr -d '"')
        else
            echo "Error: Pass key doesn't match"
            exit 1
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
    echo "Error: Credentials could not be loaded. Please ensure you provided the correct decryption key."
    exit 1
fi

# Run the python scripts
python3 generate_base64_input.py
python3 run_jupyter_base64.py
