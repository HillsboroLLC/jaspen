#!/usr/bin/env bash
#
# Deploy outreach/qualify to the Jaspen Outreach DigitalOcean Functions namespace.
#
# Always builds REMOTELY on DigitalOcean. This is not optional: requirements.txt
# pins pydantic, whose pydantic-core dependency ships platform-specific compiled
# wheels. A local build on macOS produces darwin binaries that cannot run on the
# python:3.12 Linux runtime. --remote-build makes DigitalOcean build on a machine
# matching the runtime.
#
# Credentials load only from ~/.jaspen-outreach-deploy.env and are never printed.
#
# Usage:
#   ./deploy.sh --check    validate credentials + namespace, deploy nothing
#   ./deploy.sh            validate, then deploy
#
set -euo pipefail
set +x                      # never trace: would echo secrets
umask 077

ENV_FILE="${JASPEN_DEPLOY_ENV_FILE:-$HOME/.jaspen-outreach-deploy.env}"
EXPECTED_NAMESPACE="fn-80c02947-9ce2-4fe1-9da4-658c2bc0bbcc"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REQUIRED_VARS=(
  OPENAI_API_KEY
  OPENAI_MODEL
  JASPEN_OUTREACH_SHARED_SECRET
  JASPEN_FUNCTION_WEB_SECRET
  DIGITALOCEAN_ACCESS_TOKEN
)

CHECK_ONLY=0
[ "${1:-}" = "--check" ] && CHECK_ONLY=1

die() { printf 'ERROR: %s\n' "$1" >&2; exit 1; }

# --- credentials -------------------------------------------------------------
[ -f "$ENV_FILE" ] || die "Credential file not found: $ENV_FILE"

perms="$(stat -f '%Lp' "$ENV_FILE" 2>/dev/null || stat -c '%a' "$ENV_FILE")"
[ "$perms" = "600" ] || die "$ENV_FILE must be mode 600 (found $perms). Fix: chmod 600 $ENV_FILE"

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

echo "Credential check:"
missing=0
for v in "${REQUIRED_VARS[@]}"; do
  val="${!v:-}"
  if [ -n "$val" ]; then
    printf '  %-30s PRESENT (%d chars)\n' "$v" "${#val}"   # length only, never value
  else
    printf '  %-30s *** MISSING ***\n' "$v"
    missing=1
  fi
done
[ "$missing" -eq 0 ] || die "Required variables missing from $ENV_FILE"

# --- namespace ---------------------------------------------------------------
echo "Namespace check:"
if ! doctl serverless namespaces list --access-token "$DIGITALOCEAN_ACCESS_TOKEN" 2>/dev/null \
     | grep -q "$EXPECTED_NAMESPACE"; then
  die "Namespace $EXPECTED_NAMESPACE not reachable with this token."
fi
printf '  %-30s REACHABLE\n' "$EXPECTED_NAMESPACE"

# Assert where the deploy will actually land. This is stronger than `connect`,
# which calls a per-namespace endpoint the deploy token is not scoped for.
connected="$(doctl serverless status --access-token "$DIGITALOCEAN_ACCESS_TOKEN" 2>&1 || true)"
case "$connected" in
  *"$EXPECTED_NAMESPACE"*)
    printf '  %-30s CONNECTED\n' "deploy target" ;;
  *)
    die "doctl is not connected to $EXPECTED_NAMESPACE.
       Fix: doctl serverless connect jaspen-outreach" ;;
esac

if [ "$CHECK_ONLY" -eq 1 ]; then
  echo "--check passed. Nothing deployed."
  exit 0
fi

# --- deploy ------------------------------------------------------------------
echo "Deploying $PROJECT_DIR (remote build)..."
out=""
status=0
out="$(doctl serverless deploy "$PROJECT_DIR" --remote-build \
        --access-token "$DIGITALOCEAN_ACCESS_TOKEN" 2>&1)" || status=$?

# Defence in depth: doctl does not print parameter values, but scrub anyway.
for v in "${REQUIRED_VARS[@]}"; do
  val="${!v:-}"
  [ -n "$val" ] && [ "$v" != "OPENAI_MODEL" ] && out="${out//$val/[REDACTED]}"
done
printf '%s\n' "$out"

[ "$status" -eq 0 ] || die "Deploy failed (exit $status)"
echo "Deployed. Verify with: doctl sls fn get outreach/qualify --url"
