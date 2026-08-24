#!/usr/bin/env bash
set -euo pipefail

cd /home/sekki/jaspen-outreach
set -a
source ./.env
set +a

exec .venv/bin/uvicorn app:app --host 127.0.0.1 --port 8091
