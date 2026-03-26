#!/usr/bin/env bash
# Test decrypt of .secrets.enc (same openssl options as setup_secrets.sh / lib_django_session.sh).
# Usage:
#   SECRETS_DECRYPTION_KEY='your-key' bash scripts/verify_secrets_enc.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ ! -f ".secrets.enc" ]; then
  echo "Error: .secrets.enc not found in project root: $ROOT" >&2
  exit 1
fi

if [ -z "${SECRETS_DECRYPTION_KEY:-}" ]; then
  echo "Error: set SECRETS_DECRYPTION_KEY to the same Validation Key used with setup_secrets.sh" >&2
  echo "  Example: SECRETS_DECRYPTION_KEY='...' bash scripts/verify_secrets_enc.sh" >&2
  exit 1
fi

_OUT="/tmp/verify_secrets_enc_out_$$"
_ERR="/tmp/verify_secrets_enc_err_$$"
trap 'rm -f "$_OUT" "$_ERR"' EXIT

if ! openssl enc -aes-256-cbc -d -pbkdf2 -in .secrets.enc -pass pass:"$SECRETS_DECRYPTION_KEY" -out "$_OUT" 2>"$_ERR"; then
  echo "FAILED: openssl could not decrypt (wrong key or file not created by setup_secrets.sh)." >&2
  cat "$_ERR" >&2
  exit 1
fi

OUT=$(tr -d '\r' < "$_OUT")
U=$(echo "$OUT" | grep "BETA_DJANGO_ADMIN_USERNAME" | head -1 | cut -d '=' -f 2- | tr -d '"' || true)
if [ -z "$U" ]; then
  echo "FAILED: decrypted text has no BETA_DJANGO_ADMIN_USERNAME= line." >&2
  echo "  Ensure .secrets.env had lines like BETA_DJANGO_ADMIN_USERNAME=... before encryption." >&2
  exit 1
fi

echo "OK: .secrets.enc decrypts successfully."
echo "    BETA_DJANGO_ADMIN_USERNAME is present (length ${#U} chars)."
