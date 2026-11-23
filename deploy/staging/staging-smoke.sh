#!/usr/bin/env bash
# Read-only staging smoke checks (GET and OPTIONS requests only), plus checks
# that production is unchanged. Run from the operator's machine after a deploy.
#
#   staging-smoke.sh [API_URL] [STAGING_WEB_URL] [PROD_API_URL] [PROD_WEB_URL] [PROD_CSP_SHA256] [EXPECTED_MAIN_SHA]
#
# G6 checks staging; G7 checks that production is unchanged. Both baselines
# are required (as arguments or environment variables):
#   PROD_CSP_SHA256    sha256 of production's Content-Security-Policy header
#                      value, recorded before the staging work;
#   EXPECTED_MAIN_SHA  the 40-hex commit GitHub main (production) must still be
#                      at, read with git ls-remote (read-only).
set -euo pipefail

API_URL="${1:-https://api-staging.jaspen.ai}"
STAGING_WEB_URL="${2:-https://staging.jaspen.ai}"
PROD_API_URL="${3:-https://api.jaspen.ai}"
PROD_WEB_URL="${4:-https://jaspen.ai}"
PROD_CSP_SHA256="${5:-${PROD_CSP_SHA256:-}}"
EXPECTED_MAIN_SHA="${6:-${EXPECTED_MAIN_SHA:-}}"
REPO_DIR="$(cd "$(dirname "$0")" && pwd -P)"
readonly STAGING_ORIGIN="https://staging.jaspen.ai"
readonly PRODUCTION_ORIGIN="https://jaspen.ai"
readonly UNRELATED_ORIGIN="https://unrelated-origin.example"

FAILURES=0
GATE="G6"
pass() { echo "PASS ${GATE} $1"; }
warn() { echo "WARN ${GATE} $1"; }
failed() {
  echo "FAIL ${GATE} $1" >&2
  FAILURES=$((FAILURES + 1))
}

http_get() {
  curl -sS --max-time 20 "$@"
}

# Prints the HTTP status code, or "connection error" when no response arrived.
status_of() {
  local code
  code="$(http_get -o /dev/null -w '%{http_code}' "$1" 2>/dev/null)" || code=""
  if [[ "${code}" =~ ^[1-5][0-9]{2}$ ]]; then
    echo "${code}"
  else
    echo "connection error"
  fi
}

headers_of() {
  http_get -o /dev/null -D - "$1" 2>/dev/null | tr -d '\r' || true
}

# Prints the Access-Control-Allow-Origin values a CORS preflight returns, or
# "connection error" when no response arrived.
preflight_allow_origins() {
  local url="$1" origin="$2" headers
  headers="$(http_get -o /dev/null -D - -X OPTIONS \
    -H "Origin: ${origin}" \
    -H "Access-Control-Request-Method: GET" \
    -H "Access-Control-Request-Headers: content-type,x-csrf-token" \
    "${url}" 2>/dev/null)" || { echo "connection error"; return 0; }
  printf '%s\n' "${headers}" | tr -d '\r' | grep -i '^access-control-allow-origin:' | sed 's/^[^:]*:[[:space:]]*//' || true
}

# PASS when a preflight from $2 to $1 returns no allow-origin at all.
expect_no_allow_origin() {
  local allowed
  allowed="$(preflight_allow_origins "$1" "$2")"
  if [[ -z "${allowed}" ]]; then
    pass "$3 preflight from $2 returns no allow-origin"
  elif [[ "${allowed}" == "connection error" ]]; then
    failed "$3 preflight from $2: connection error"
  else
    failed "$3 preflight from $2 returned an Access-Control-Allow-Origin"
  fi
}

header_value() {
  # $1 headers text, $2 lowercase header name
  printf '%s\n' "$1" | grep -i "^$2:" | head -n 1 | sed 's/^[^:]*:[[:space:]]*//' || true
}

sha256_text() {
  if command -v sha256sum >/dev/null 2>&1; then
    printf '%s' "$1" | sha256sum | awk '{print $1}'
  else
    printf '%s' "$1" | shasum -a 256 | awk '{print $1}'
  fi
}

echo "Staging API: ${API_URL}"
echo "Staging web: ${STAGING_WEB_URL}"
echo "Production API: ${PROD_API_URL}"
echo "Production web: ${PROD_WEB_URL}"

# --- G6 staging API ----------------------------------------------------------
GATE="G6"
health_body="$(http_get "${API_URL}/health" 2>/dev/null || true)"
health_status="$(status_of "${API_URL}/health")"
if [[ "${health_status}" == "200" ]] && printf '%s' "${health_body}" | grep -Eq '"database"[[:space:]]*:[[:space:]]*"ok"'; then
  pass "staging /health 200 with database ok"
else
  failed "staging /health returned ${health_status} or database not ok"
fi

health_headers="$(headers_of "${API_URL}/health")"
if header_value "${health_headers}" "x-robots-tag" | grep -qi 'noindex'; then
  pass "staging X-Robots-Tag noindex"
else
  failed "staging X-Robots-Tag noindex missing"
fi
if [[ -n "$(header_value "${health_headers}" "strict-transport-security")" ]]; then
  pass "staging HSTS present"
else
  failed "staging HSTS missing"
fi
if [[ "$(header_value "${health_headers}" "x-jaspen-environment")" == "staging" ]]; then
  pass "staging X-Jaspen-Environment staging"
else
  warn "X-Jaspen-Environment: staging header absent (optional)"
fi

staging_allowed="$(preflight_allow_origins "${API_URL}/api/v1/auth/me" "${STAGING_ORIGIN}")"
if [[ "$(printf '%s' "${staging_allowed}" | grep -c .)" == "1" && "${staging_allowed}" == "${STAGING_ORIGIN}" ]]; then
  pass "staging preflight from the staging origin allows exactly that origin"
else
  failed "staging preflight from ${STAGING_ORIGIN} did not return exactly one matching Access-Control-Allow-Origin"
fi
for origin in "${PRODUCTION_ORIGIN}" "${UNRELATED_ORIGIN}"; do
  expect_no_allow_origin "${API_URL}/api/v1/auth/me" "${origin}" "staging"
done

for path in /api/v1/auth/me /api/v1/billing/status /api/v1/admin/capabilities; do
  code="$(status_of "${API_URL}${path}")"
  if [[ "${code}" == "401" ]]; then
    pass "staging ${path} 401 without a session"
  elif [[ "${code}" == "404" ]]; then
    failed "staging ${path} returned 404 (backend is older than the frontend contract)"
  else
    failed "staging ${path} returned ${code}, expected 401"
  fi
done

# --- G6 staging web stays behind Vercel Authentication ------------------------
web_status="$(status_of "${STAGING_WEB_URL}")"
case "${web_status}" in
  401 | 403 | 302) pass "staging web is not public (${web_status})" ;;
  *) failed "staging web returned ${web_status}; expected 401/403/302 (Vercel Authentication on)" ;;
esac

# --- G7 production unchanged --------------------------------------------------
GATE="G7"
if [[ ! "${EXPECTED_MAIN_SHA}" =~ ^[0-9a-f]{40}$ ]]; then
  failed "EXPECTED_MAIN_SHA (40-hex production main baseline) is required"
else
  main_sha="$(git -C "${REPO_DIR}" ls-remote origin refs/heads/main 2>/dev/null | awk '{print $1}')" || main_sha=""
  if [[ -z "${main_sha}" ]]; then
    failed "GitHub main: connection error"
  elif [[ "${main_sha}" == "${EXPECTED_MAIN_SHA}" ]]; then
    pass "GitHub main is still ${EXPECTED_MAIN_SHA}"
  else
    failed "GitHub main is ${main_sha}, expected ${EXPECTED_MAIN_SHA}"
  fi
fi

prod_health="$(status_of "${PROD_API_URL}/health")"
[[ "${prod_health}" == "200" ]] && pass "production /health 200" || failed "production /health returned ${prod_health}"
prod_web="$(status_of "${PROD_WEB_URL}")"
[[ "${prod_web}" == "200" ]] && pass "production web 200" || failed "production web returned ${prod_web}"

prod_csp="$(header_value "$(headers_of "${PROD_WEB_URL}")" "content-security-policy")"
prod_csp_sha="$(sha256_text "${prod_csp}")"
if [[ -z "${prod_csp}" ]]; then
  failed "production CSP header missing (or connection error)"
elif [[ -z "${PROD_CSP_SHA256}" ]]; then
  failed "PROD_CSP_SHA256 baseline is required (current production CSP sha256 is ${prod_csp_sha})"
elif [[ -n "${prod_csp}" && "${prod_csp_sha}" == "${PROD_CSP_SHA256}" ]]; then
  pass "production CSP matches the baseline"
else
  failed "production CSP sha256 ${prod_csp_sha} differs from the baseline"
fi

expect_no_allow_origin "${PROD_API_URL}/api/v1/auth/me" "${STAGING_ORIGIN}" "production"

if (( FAILURES > 0 )); then
  echo "STAGING SMOKE FAILED: ${FAILURES} check(s) failed" >&2
  exit 1
fi
echo "Staging smoke checks passed."
