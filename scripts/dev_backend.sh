#!/usr/bin/env bash
# Run the Jaspen backend locally with auto-reload on http://localhost:8000.
# Reads config from backend/.env (created by scripts/dev_setup.sh).

set -euo pipefail
cd "$(dirname "$0")/../backend"

if [ ! -d venv ] || [ ! -f .env ]; then
  echo "Backend not set up yet — run ./scripts/dev_setup.sh first." >&2
  exit 1
fi

exec ./venv/bin/flask --app wsgi:app run --port "${PORT:-8000}" --debug
