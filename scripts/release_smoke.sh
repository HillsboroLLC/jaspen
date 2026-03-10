#!/usr/bin/env bash
set -euo pipefail

WEB_URL="${1:-https://www.jaspen.ai}"
API_URL="${2:-https://api.jaspen.ai}"

fail() {
  echo "SMOKE CHECK FAILED: $1" >&2
  exit 1
}

echo "Running release smoke checks..."
echo "Web: ${WEB_URL}"
echo "API: ${API_URL}"

web_status="$(curl -sS -o /dev/null -w '%{http_code}' "${WEB_URL}")"
[[ "${web_status}" == "200" ]] || fail "web root returned ${web_status}, expected 200"

web_html="$(curl -sS "${WEB_URL}")"
echo "${web_html}" | grep -q '/static/js/main\.' || fail "web root does not look like deployed SPA bundle"

billing_status="$(curl -sS -o /dev/null -w '%{http_code}' "${API_URL}/api/billing/status")"
[[ "${billing_status}" == "401" ]] || fail "/api/billing/status returned ${billing_status}, expected 401 for unauthenticated probe"

admin_caps_status="$(curl -sS -o /dev/null -w '%{http_code}' "${API_URL}/api/admin/capabilities")"
if [[ "${admin_caps_status}" == "404" ]]; then
  fail "/api/admin/capabilities returned 404 (backend is older than frontend/admin contract)"
fi
[[ "${admin_caps_status}" == "401" ]] || fail "/api/admin/capabilities returned ${admin_caps_status}, expected 401 for unauthenticated probe"

echo "Smoke checks passed."
