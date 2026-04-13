#!/usr/bin/env bash
# Shared by run_helper_updater.sh and run_base64_updater.sh (source after cd to project root).
# Loads Jupyter URLs/passwords from .secrets.env, secrets.local.env (*.local.env, gitignored), and .secrets.enc.
# Decrypt matches setup_secrets.sh (aes-256-cbc, -pbkdf2, -salt). Uses -passin env: so passphrases with
# special shell characters (e.g. ! $) still work. Temp file avoids bash "null byte" warnings.

jupyter_inject_secrets_decryption_key() {
  if [ -n "${SECRETS_DECRYPTION_KEY:-}" ]; then
    return 0
  fi
  if [ -f ".secrets.key" ]; then
    SECRETS_DECRYPTION_KEY="$(tr -d '\n\r' < .secrets.key)"
    export SECRETS_DECRYPTION_KEY
    [ -n "$SECRETS_DECRYPTION_KEY" ] && return 0
  fi
  if [ -n "${SECRETS_DECRYPTION_KEY_FILE:-}" ] && [ -f "${SECRETS_DECRYPTION_KEY_FILE}" ]; then
    SECRETS_DECRYPTION_KEY="$(tr -d '\n\r' < "${SECRETS_DECRYPTION_KEY_FILE}")"
    export SECRETS_DECRYPTION_KEY
    [ -n "$SECRETS_DECRYPTION_KEY" ] && return 0
  fi
  if _jupyter_try_inject_secrets_key_from_file ".secrets.env"; then
    return 0
  fi
  if _jupyter_try_inject_secrets_key_from_file "secrets.local.env"; then
    return 0
  fi
}

# Helper for jupyter_inject_secrets_decryption_key — grep one file for SECRETS_DECRYPTION_KEY=.
_jupyter_try_inject_secrets_key_from_file() {
  local _f="$1" _raw _val
  [ ! -f "$_f" ] && return 1
  _raw=$(grep -E '^[[:space:]]*(export[[:space:]]+)?SECRETS_DECRYPTION_KEY[[:space:]]*=' "$_f" 2>/dev/null | grep -Ev '^[[:space:]]*#' | head -1 || true)
  [ -z "$_raw" ] && return 1
  _val="${_raw#*=}"
  _val=$(printf '%s' "$_val" | tr -d '\r' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
  _val="$(jupyter_strip_quotes "$_val")"
  [ -z "$_val" ] && return 1
  export SECRETS_DECRYPTION_KEY="$_val"
  return 0
}

jupyter_strip_quotes() {
  local s="$1"
  s="${s%\"}"
  s="${s#\"}"
  s="${s%\'}"
  s="${s#\'}"
  printf '%s' "$s"
}

# After sourcing env files, still fill from disk when a line exists but bash did not assign (BOM, odd quoting, etc.).
jupyter_merge_missing_jupyter_from_dotenv() {
  _jupyter_merge_jupyter_passwords_from_file ".secrets.env"
  _jupyter_merge_jupyter_passwords_from_file "secrets.local.env"
  return 0
}

_jupyter_merge_jupyter_passwords_from_file() {
  local _f="$1" _raw _val
  [ ! -f "$_f" ] && return 0
  if [ -z "${BETA_JUPYTER_PASSWORD:-}" ]; then
    _raw=$(grep -E '^[[:space:]]*(export[[:space:]]+)?BETA_JUPYTER_PASSWORD[[:space:]]*=' "$_f" 2>/dev/null | grep -Ev '^[[:space:]]*#' | head -1 || true)
    if [ -z "$_raw" ]; then
      _raw=$(grep -E '^[[:space:]]*(export[[:space:]]+)?JUPYTER_PASSWORD[[:space:]]*=' "$_f" 2>/dev/null | grep -Ev '^[[:space:]]*#' | head -1 || true)
    fi
    if [ -n "$_raw" ]; then
      _val="${_raw#*=}"
      _val=$(printf '%s' "$_val" | tr -d '\r' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
      _val="$(jupyter_strip_quotes "$_val")"
      [ -n "$_val" ] && export BETA_JUPYTER_PASSWORD="$_val"
    fi
  fi
  if [ -z "${PROD_JUPYTER_PASSWORD:-}" ]; then
    _raw=$(grep -E '^[[:space:]]*(export[[:space:]]+)?PROD_JUPYTER_PASSWORD[[:space:]]*=' "$_f" 2>/dev/null | grep -Ev '^[[:space:]]*#' | head -1 || true)
    if [ -n "$_raw" ]; then
      _val="${_raw#*=}"
      _val=$(printf '%s' "$_val" | tr -d '\r' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
      _val="$(jupyter_strip_quotes "$_val")"
      [ -n "$_val" ] && export PROD_JUPYTER_PASSWORD="$_val"
    fi
  fi
  return 0
}

# No secrets printed — counts and file presence only.
jupyter_diagnose_missing_jupyter_password() {
  echo "  Diagnosis (no values shown):" >&2
  if [ ! -f ".secrets.env" ]; then
    echo "    • .secrets.env: missing at project root $(pwd)" >&2
  else
    echo "    • .secrets.env: present" >&2
    local _c
    _c=$(grep -E '^[[:space:]]*(export[[:space:]]+)?BETA_JUPYTER_PASSWORD[[:space:]]*=' .secrets.env 2>/dev/null | grep -Ev '^[[:space:]]*#' | wc -l | tr -d ' \n' || echo 0)
    echo "    • uncommented BETA_JUPYTER_PASSWORD= lines: ${_c:-0}" >&2
    _c=$(grep -E '^[[:space:]]*(export[[:space:]]+)?JUPYTER_PASSWORD[[:space:]]*=' .secrets.env 2>/dev/null | grep -Ev '^[[:space:]]*#' | wc -l | tr -d ' \n' || echo 0)
    echo "    • uncommented JUPYTER_PASSWORD= lines (alias for beta): ${_c:-0}" >&2
    _c=$(grep -E '^[[:space:]]*(export[[:space:]]+)?SECRETS_DECRYPTION_KEY[[:space:]]*=' .secrets.env 2>/dev/null | grep -Ev '^[[:space:]]*#' | wc -l | tr -d ' \n' || echo 0)
    echo "    • uncommented SECRETS_DECRYPTION_KEY= lines: ${_c:-0}" >&2
  fi
  if [ -f "secrets.local.env" ]; then
    echo "    • secrets.local.env: present (gitignored *.local.env — Jupyter passwords safe here)" >&2
    _c=$(grep -E '^[[:space:]]*(export[[:space:]]+)?BETA_JUPYTER_PASSWORD[[:space:]]*=' secrets.local.env 2>/dev/null | grep -Ev '^[[:space:]]*#' | wc -l | tr -d ' \n' || echo 0)
    echo "    • secrets.local.env BETA_JUPYTER_PASSWORD= lines: ${_c:-0}" >&2
  else
    echo "    • secrets.local.env: absent (optional; use for Jupyter creds without touching .secrets.env)" >&2
  fi
  if [ -f ".secrets.key" ]; then
    echo "    • .secrets.key: present" >&2
  else
    echo "    • .secrets.key: missing (optional one-line file = same passphrase as setup_secrets.sh)" >&2
  fi
  if [ -f ".secrets.enc" ]; then
    echo "    • .secrets.enc: present (needs SECRETS_DECRYPTION_KEY or .secrets.key to read Jupyter lines inside)" >&2
  else
    echo "    • .secrets.enc: absent" >&2
  fi
  return 0
}

jupyter_export_jupyter_password_vars() {
  # Only set from plaintext env — never assign empty (would block decrypt merge and confuse -z checks).
  [ -n "${BETA_JUPYTER_PASSWORD:-}" ] && export BETA_J="${BETA_JUPYTER_PASSWORD}"
  [ -n "${PROD_JUPYTER_PASSWORD:-}" ] && export PROD_J="${PROD_JUPYTER_PASSWORD}"
  return 0
}

# Read decrypted plaintext file; fill missing env vars (passwords + optional notebook/tree URLs).
jupyter_apply_jupyter_secrets_from_decrypted_file() {
  local _f="$1"
  [ ! -f "$_f" ] && return 1
  local _b _p _bu _pu _raw
  # Match plain KEY= and export KEY= (same as Python _parse_secrets_env_line / setup_secrets plaintext).
  _raw=$(grep -E '^[[:space:]]*(export[[:space:]]+)?BETA_JUPYTER_PASSWORD=' "$_f" 2>/dev/null | head -1 || true)
  _b=$(printf '%s' "$_raw" | tr -d '\r\0')
  _b="${_b#*=}"
  _raw=$(grep -E '^[[:space:]]*(export[[:space:]]+)?PROD_JUPYTER_PASSWORD=' "$_f" 2>/dev/null | head -1 || true)
  _p=$(printf '%s' "$_raw" | tr -d '\r\0')
  _p="${_p#*=}"
  _raw=$(grep -E '^[[:space:]]*(export[[:space:]]+)?BETA_JUPYTER_URL=' "$_f" 2>/dev/null | head -1 || true)
  _bu=$(printf '%s' "$_raw" | tr -d '\r\0')
  _bu="${_bu#*=}"
  _raw=$(grep -E '^[[:space:]]*(export[[:space:]]+)?PROD_JUPYTER_URL=' "$_f" 2>/dev/null | head -1 || true)
  _pu=$(printf '%s' "$_raw" | tr -d '\r\0')
  _pu="${_pu#*=}"
  _b="$(jupyter_strip_quotes "$_b")"
  _p="$(jupyter_strip_quotes "$_p")"
  _bu="$(jupyter_strip_quotes "$_bu")"
  _pu="$(jupyter_strip_quotes "$_pu")"
  if [ -z "${BETA_J:-}" ] && [ -n "$_b" ]; then
    export BETA_J="$_b"
  fi
  if [ -z "${PROD_J:-}" ] && [ -n "$_p" ]; then
    export PROD_J="$_p"
  fi
  if [ -z "${BETA_JUPYTER_URL:-}" ] && [ -n "$_bu" ]; then
    export BETA_JUPYTER_URL="$_bu"
  fi
  if [ -z "${PROD_JUPYTER_URL:-}" ] && [ -n "$_pu" ]; then
    export PROD_JUPYTER_URL="$_pu"
  fi
  if [ -n "$BETA_J" ] || [ -n "$PROD_J" ]; then
    return 0
  fi
  return 2
}

# Returns 0 = got Jupyter passwords; 1 = openssl failed; 2 = decrypt ok but no JUPYTER_* password lines
jupyter_decrypt_jupyter_passwords_from_enc() {
  local pass="$1"
  [ -z "$pass" ] && return 1
  [ ! -f .secrets.enc ] && return 1
  local _tmp _err _st
  _tmp="$(mktemp)" || return 1
  _err="$(mktemp)" || {
    rm -f "$_tmp"
    return 1
  }
  export JUPYTER_ENC_PASSPHRASE="$pass"
  set +e
  openssl enc -aes-256-cbc -d -pbkdf2 -in .secrets.enc -passin env:JUPYTER_ENC_PASSPHRASE -out "$_tmp" 2>"$_err"
  _st=$?
  set -e
  unset JUPYTER_ENC_PASSPHRASE
  if [ "$_st" -ne 0 ]; then
    echo "OpenSSL decrypt failed (wrong validation key, or .secrets.enc was not created with bash setup_secrets.sh)." >&2
    if [ -s "$_err" ]; then
      tr -d '\0' < "$_err" | head -c 400 >&2 || true
      echo "" >&2
    fi
    echo "  Test: SECRETS_DECRYPTION_KEY='same-key' bash scripts/verify_secrets_enc.sh" >&2
    rm -f "$_tmp" "$_err"
    return 1
  fi
  rm -f "$_err"
  jupyter_apply_jupyter_secrets_from_decrypted_file "$_tmp"
  _st=$?
  rm -f "$_tmp"
  if [ "$_st" -eq 2 ]; then
    echo "Decryption succeeded, but the decrypted file has no non-empty BETA_JUPYTER_PASSWORD= or PROD_JUPYTER_PASSWORD= lines." >&2
    echo "  Edit plain .secrets.env, add those variables, then run: bash setup_secrets.sh" >&2
    return 2
  fi
  return "$_st"
}
