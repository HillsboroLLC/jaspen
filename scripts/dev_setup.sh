#!/usr/bin/env bash
# One-command local dev setup for Jaspen. Idempotent — safe to re-run.
#
#   ./scripts/dev_setup.sh
#
# Does: backend venv (Python 3.12) + deps, backend/.env with generated secrets
# (if missing), local SQLite dev DB + seed users, frontend npm install.
# Touches NOTHING outside this repo. Never contacts production.

set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

# ---- 0. Check Node (CI uses Node 20 — see .github/workflows/ci.yml) --------
if ! command -v node >/dev/null 2>&1; then
  echo "ERROR: Node.js not found. Install Node 20+ (e.g. 'brew install node@20')." >&2
  exit 1
fi
NODE_MAJOR=$(node --version | sed 's/^v//' | cut -d. -f1)
if [ "$NODE_MAJOR" -lt 18 ]; then
  echo "ERROR: Node $(node --version) is too old — react-scripts needs 18+, CI uses 20." >&2
  exit 1
fi
if [ "$NODE_MAJOR" -lt 20 ]; then
  echo "WARNING: Node $(node --version) is older than CI (Node 20). Builds may differ." >&2
fi
echo "==> Using Node $(node --version)"

# ---- 1. Find Python 3.10+ -------------------------------------------------
PY=""
for cand in python3.12 python3.13 python3.11 /opt/homebrew/bin/python3.12; do
  if command -v "$cand" >/dev/null 2>&1; then PY="$cand"; break; fi
done
if [ -z "$PY" ]; then
  echo "ERROR: Python 3.10+ not found. Install with:  brew install python@3.12" >&2
  exit 1
fi
echo "==> Using $($PY --version) ($PY)"

# ---- 2. Backend venv + dependencies ----------------------------------------
cd "$ROOT/backend"
if [ ! -d venv ]; then
  echo "==> Creating backend/venv"
  "$PY" -m venv venv
fi
echo "==> Installing backend dependencies (this can take a few minutes first run)"
./venv/bin/pip install --quiet --upgrade pip
./venv/bin/pip install --quiet -r requirements.txt

# ---- 3. backend/.env -------------------------------------------------------
if [ ! -f .env ]; then
  echo "==> Generating backend/.env from .env.example with fresh dev secrets"
  SECRET=$(./venv/bin/python -c "import secrets; print(secrets.token_hex(32))")
  JWTSECRET=$(./venv/bin/python -c "import secrets; print(secrets.token_hex(32))")
  FERNET=$(./venv/bin/python -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())")
  sed -e "s|^SECRET_KEY=.*|SECRET_KEY=${SECRET}|" \
      -e "s|^JWT_SECRET_KEY=.*|JWT_SECRET_KEY=${JWTSECRET}|" \
      -e "s|^CONNECTOR_ENCRYPTION_KEY=.*|CONNECTOR_ENCRYPTION_KEY=${FERNET}|" \
      .env.example > .env
else
  echo "==> backend/.env already exists — leaving it untouched"
fi

# ---- 4. Dev database + seed users ------------------------------------------
echo "==> Initializing local dev database (SQLite, idempotent)"
./venv/bin/python scripts/init_dev_db.py

# ---- 5. Frontend dependencies ----------------------------------------------
cd "$ROOT/frontend"
if [ ! -d node_modules ]; then
  echo "==> Installing frontend dependencies"
  npm install
else
  echo "==> frontend/node_modules present — skipping npm install (run 'npm install' manually to refresh)"
fi

cat <<'EOF'

Dev setup complete. To run:

  Backend  (http://localhost:8000):   ./scripts/dev_backend.sh
  Frontend (http://localhost:3000):   cd frontend && npm start

Log in with:  dev@jaspen.local / jaspen-dev-password
Admin user:   dev-admin@jaspen.local / jaspen-dev-password

Full guide: docs/DEVELOPMENT.md
EOF
