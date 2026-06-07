#!/usr/bin/env bash
set -euo pipefail

BACKEND_DIR="/home/sekki/sekki-platform/backend"
LOG_DIR="/home/sekki/sekki-platform/backend/logs"
LOG_FILE="${LOG_DIR}/monthly-feedback-digest.log"
LOCK_FILE="/tmp/jaspen-monthly-feedback-digest.lock"

mkdir -p "${LOG_DIR}"

cd "${BACKEND_DIR}"

if [[ -f ".env" ]]; then
  while IFS= read -r raw_line || [[ -n "${raw_line}" ]]; do
    line="${raw_line#"${raw_line%%[![:space:]]*}"}"
    [[ -z "${line}" || "${line}" == \#* ]] && continue
    line="${line#export }"
    [[ "${line}" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]] || continue
    key="${line%%=*}"
    value="${line#*=}"
    if [[ "${value}" == \"*\" && "${value}" == *\" ]]; then
      value="${value:1:${#value}-2}"
    elif [[ "${value}" == \'*\' && "${value}" == *\' ]]; then
      value="${value:1:${#value}-2}"
    fi
    export "${key}=${value}"
  done < ".env"
fi

export FLASK_APP="wsgi:app"

{
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] starting monthly feedback digest"
  flock -n 9 || {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] another feedback digest process is already running; exiting"
    exit 0
  }
  ./venv/bin/flask feedback digest-monthly
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] completed monthly feedback digest"
} 9>"${LOCK_FILE}" >> "${LOG_FILE}" 2>&1
