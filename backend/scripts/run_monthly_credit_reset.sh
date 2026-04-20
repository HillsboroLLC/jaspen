#!/usr/bin/env bash
set -euo pipefail

BACKEND_DIR="/home/sekki/sekki-platform/backend"
LOG_DIR="/var/log/jaspen"
LOG_FILE="${LOG_DIR}/monthly-credit-reset.log"
LOCK_FILE="/tmp/jaspen-monthly-credit-reset.lock"

mkdir -p "${LOG_DIR}"

cd "${BACKEND_DIR}"

if [[ -f ".env" ]]; then
  # shellcheck disable=SC1091
  set -a
  source ".env"
  set +a
fi

export FLASK_APP="wsgi:app"

{
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] starting monthly credit reset"
  flock -n 9 || {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] another reset process is already running; exiting"
    exit 0
  }
  ./venv/bin/flask credits reset-monthly
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] completed monthly credit reset"
} 9>"${LOCK_FILE}" >> "${LOG_FILE}" 2>&1
