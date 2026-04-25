#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${1:-backend/.env}"

if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: $ENV_FILE not found. Copy backend/.env.example → backend/.env and fill it in."
    exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

REQUIRED_VARS=(
    BOT_TOKEN
    NAVIDROME_URL
    NAVIDROME_ADMIN_USER
    NAVIDROME_ADMIN_PASSWORD
    SFTP_HOST
    SFTP_USER
    SFTP_BASE
    SFTP_KEY_FILE
    BACKEND_PORT
)

missing=()
for var in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!var:-}" ]; then
        missing+=("$var")
    fi
done

if [ ${#missing[@]} -gt 0 ]; then
    echo "ERROR: The following required variables are not set in $ENV_FILE:"
    for var in "${missing[@]}"; do
        echo "  - $var"
    done
    exit 1
fi

echo "Environment OK."
