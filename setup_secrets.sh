#!/bin/bash
# Encrypt .secrets.env → .secrets.enc. You can then delete plain .secrets.env and use only
# .secrets.enc + .secrets.key (or SECRETS_DECRYPTION_KEY). See .secrets.env.example.

SECRETS_FILE=".secrets.env"
ENCRYPTED_FILE=".secrets.enc"

if [ ! -f "$SECRETS_FILE" ]; then
    echo "Error: $SECRETS_FILE not found. Please create it first with your credentials."
    exit 1
fi

echo "This script will encrypt your '$SECRETS_FILE' into a secure file."
echo "You will be asked to enter a Validation Key (Password)."
echo "You will need this key every time you run the automation."
echo ""

# Read Password
echo -n "Enter Validation Key (Password): "
read -s KEY
echo ""
echo -n "Verify Validation Key: "
read -s KEY_VERIFY
echo ""

if [ "$KEY" != "$KEY_VERIFY" ]; then
    echo "Error: Passwords do not match. Exiting."
    exit 1
fi

if [ -z "$KEY" ]; then
    echo "Error: Password cannot be empty."
    exit 1
fi

# Encrypt
openssl enc -aes-256-cbc -salt -in "$SECRETS_FILE" -out "$ENCRYPTED_FILE" -pbkdf2 -pass pass:"$KEY"

if [ $? -eq 0 ]; then
    echo ""
    echo "Success! Encrypted file '$ENCRYPTED_FILE' created."
    echo "Is it safe to delete the plain text '$SECRETS_FILE' now? (y/n)"
    read -r response
    if [[ "$response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
        rm "$SECRETS_FILE"
        echo "Deleted '$SECRETS_FILE'. Your credentials are now secure."
    else
        echo "Kept '$SECRETS_FILE'. Warning: This file contains plain text passwords."
    fi
else
    echo "Encryption failed."
    exit 1
fi
