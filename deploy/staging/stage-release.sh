#!/usr/bin/env bash
# Operator script, run from a checkout of the repository on the operator's
# machine. Builds verifiable staging release artifacts (git bundle, offline
# wheelhouse, checksums) after the release gates pass.
#
#   stage-release.sh <40-hex sha> [--dry-run | --execute] [options]
#
# Dry run is the default: it builds the artifacts and prints the exact remote
# commands it would run. Nothing leaves this machine unless --execute is given.
#
# Options:
#   --local-suites-evidence <file>  required when the sha has no CI check runs
#   --previous-sha <sha>            also bundle wheels for this commit's
#                                   requirements (the commit staging runs now;
#                                   defaults to origin/staging)
#   --allow-migrations              pass --allow-migrations to the remote deploy
#                                   (only after Lydia approves the migration)
#   --artifacts-dir <dir>           where artifacts are written (outside the repo)
#   --no-fetch                      use the local origin/* refs without fetching
set -euo pipefail
umask 077

readonly REMOTE_WRAPPER="/usr/local/sbin/jaspen-staging-deploy"
readonly WHEEL_PLATFORM="manylinux2014_x86_64"
readonly WHEEL_PYTHON_VERSION="3.12"
# SQLAlchemy needs greenlet only on some machines (an environment marker), and
# pip download evaluates markers for this machine, so it is requested explicitly.
readonly GREENLET_REQUIREMENT="greenlet>=1"
# Staging-only extra (R-2 in the engineering risk register): production runs
# psycopg2-binary without declaring it, so staging keeps the same driver until
# R-2 settles the database driver.
readonly STAGING_EXTRA_REQUIREMENT="psycopg2-binary==2.9.11"

fail() {
  echo "STAGE RELEASE STOPPED: $1" >&2
  exit 1
}

usage() {
  sed -n '2,23p' "$0" | sed 's/^# \{0,1\}//'
  exit 2
}

SHA=""
EXECUTE=0
DRY_RUN_FLAG=0
ALLOW_MIGRATIONS=0
FETCH=1
EVIDENCE_FILE=""
PREVIOUS_SHA=""
ARTIFACTS_DIR="${JASPEN_STAGE_ARTIFACTS_DIR:-${TMPDIR:-/tmp}/jaspen-staging-artifacts}"
OPERATOR_CONFIG="${JASPEN_STAGING_OPERATOR_CONFIG:-${HOME}/.config/jaspen/staging-operator.conf}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN_FLAG=1 ;;
    --execute) EXECUTE=1 ;;
    --allow-migrations) ALLOW_MIGRATIONS=1 ;;
    --no-fetch) FETCH=0 ;;
    --local-suites-evidence) [[ $# -ge 2 ]] || usage; EVIDENCE_FILE="$2"; shift ;;
    --previous-sha) [[ $# -ge 2 ]] || usage; PREVIOUS_SHA="$2"; shift ;;
    --artifacts-dir) [[ $# -ge 2 ]] || usage; ARTIFACTS_DIR="$2"; shift ;;
    -h | --help) usage ;;
    -*) fail "unknown option $1" ;;
    *) [[ -z "${SHA}" ]] || fail "only one sha is accepted"; SHA="$1" ;;
  esac
  shift
done
(( EXECUTE == 0 || DRY_RUN_FLAG == 0 )) || fail "--dry-run and --execute cannot be combined"

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || fail "run from inside the repository"
readonly REPO_ROOT
repo_git() {
  git -C "${REPO_ROOT}" "$@"
}

# Gate numbers follow the staging plan: G0 CI, G1 ancestry, G2 isolation
# preflight, G3 artifacts/config, G4 migrations, G5 restart/health/rollback,
# G6 staging smoke, G7 production unchanged. G1 runs before G0 here because it
# is local and cheap.

# G1: exact release sha.
gate_sha_format() {
  [[ "$1" =~ ^[0-9a-f]{40}$ ]]
}

# G1: the sha is on develop, or (transitional, until the staging-only commits
# are integrated into develop) it is exactly the current origin/staging tip.
release_ref_gate() {
  local sha="$1" staging_tip
  repo_git cat-file -e "${sha}^{commit}" 2>/dev/null || return 1
  if repo_git merge-base --is-ancestor "${sha}" refs/remotes/origin/develop 2>/dev/null; then
    echo "develop"
    return 0
  fi
  staging_tip="$(repo_git rev-parse --verify --quiet refs/remotes/origin/staging || true)"
  if [[ -n "${staging_tip}" && "${sha}" == "${staging_tip}" ]]; then
    echo "staging-tip"
    return 0
  fi
  return 1
}

gate_sha_format "${SHA}" || fail "release sha must be exactly 40 lowercase hex characters"
if [[ -n "${PREVIOUS_SHA}" ]]; then
  gate_sha_format "${PREVIOUS_SHA}" || fail "--previous-sha must be exactly 40 lowercase hex characters"
fi
if (( FETCH == 1 )); then
  repo_git fetch --quiet origin develop staging || fail "git fetch origin develop staging"
fi
REF_GATE="$(release_ref_gate "${SHA}")" || fail "${SHA} is not on origin/develop and is not the origin/staging tip"
echo "PASS G1 release ref (${REF_GATE})"

# G0: GitHub Actions CI jobs for the sha (other apps' checks, such as Vercel
# preview comments, do not count as CI). Every required job must be present
# and successful. security-audit is advisory by design in ci.yml
# (continue-on-error; dependency advisories are tracked separately): a
# non-success is a WARNING recorded in the manifest, not a stop. Any other
# non-successful run stops. Staging branch pushes do not run CI today; with no
# runs at all, local full-suite evidence is required.
readonly REQUIRED_CI_JOBS=(backend backend-postgres frontend secret-scan)
readonly ADVISORY_CI_JOBS=(security-audit)

# Reads "status conclusion name" lines on stdin. Prints "WARNING ..." lines
# for advisory jobs and a final "SUMMARY ..." line; returns 1 (reasons on
# stderr) when a required job is missing or any non-advisory run failed.
evaluate_ci_check_runs() {
  local status conclusion name job advisory found ok=0 total=0
  local -a successful=() warnings=()
  while read -r status conclusion name; do
    [[ -n "${status}" ]] || continue
    total=$((total + 1))
    if [[ "${status}" == "completed" && "${conclusion}" == "success" ]]; then
      successful+=("${name}")
      continue
    fi
    advisory=0
    for job in "${ADVISORY_CI_JOBS[@]}"; do
      [[ "${name}" == "${job}" ]] && advisory=1
    done
    if (( advisory == 1 )); then
      warnings+=("advisory CI job ${name} is ${status} ${conclusion}")
    else
      echo "  not successful: ${name} (${status} ${conclusion})" >&2
      ok=1
    fi
  done
  for job in "${REQUIRED_CI_JOBS[@]}"; do
    found=0
    for name in "${successful[@]+"${successful[@]}"}"; do
      [[ "${name}" == "${job}" ]] && found=1
    done
    if (( found == 0 )); then
      echo "  required CI job missing or not successful: ${job}" >&2
      ok=1
    fi
  done
  (( ok == 0 )) || return 1
  for job in "${warnings[@]+"${warnings[@]}"}"; do
    echo "WARNING ${job}"
  done
  echo "SUMMARY ${total} GitHub Actions CI run(s); required jobs ${REQUIRED_CI_JOBS[*]} all success"
}

CI_SUMMARY=""
CI_ADVISORY="none"
check_runs="$(cd "${REPO_ROOT}" && gh api --paginate "repos/{owner}/{repo}/commits/${SHA}/check-runs" \
  --jq '.check_runs[] | select(.app.slug == "github-actions") | "\(.status) \(.conclusion) \(.name)"')" \
  || fail "gh api check-runs (read-only) failed"
if [[ -z "${check_runs}" ]]; then
  [[ -n "${EVIDENCE_FILE}" ]] || fail "no GitHub Actions CI check runs for ${SHA}; pass --local-suites-evidence <file> from the full local suites"
  [[ -f "${EVIDENCE_FILE}" && -s "${EVIDENCE_FILE}" ]] || fail "local suites evidence file is missing or empty"
  CI_SUMMARY="no GitHub Actions CI check runs; local suites evidence recorded"
else
  ci_result="$(printf '%s\n' "${check_runs}" | evaluate_ci_check_runs)" || fail "required CI jobs are not all successful"
  CI_SUMMARY="$(printf '%s\n' "${ci_result}" | sed -n 's/^SUMMARY //p')"
  ci_warnings="$(printf '%s\n' "${ci_result}" | sed -n 's/^WARNING //p')"
  if [[ -n "${ci_warnings}" ]]; then
    printf '%s\n' "${ci_warnings}" | sed 's/^/WARNING G0 /'
    CI_ADVISORY="$(printf '%s' "${ci_warnings}" | tr '\n' ';')"
  fi
fi
echo "PASS G0 ${CI_SUMMARY}"

# G3: build artifacts outside the repository.
mkdir -p "${ARTIFACTS_DIR}"
ARTIFACTS_DIR="$(cd "${ARTIFACTS_DIR}" && pwd -P)"
case "${ARTIFACTS_DIR}/" in
  "$(cd "${REPO_ROOT}" && pwd -P)/"*) fail "artifacts directory must be outside the repository" ;;
esac
ART_NAME="${SHA}-$(date -u +%Y%m%dT%H%M%SZ)"
ART="${ARTIFACTS_DIR}/${ART_NAME}"
mkdir "${ART}" "${ART}/wheelhouse"
BUNDLE_NAME="jaspen-staging-${SHA}.bundle"

PREVIOUS_IS_DEFAULT=0
if [[ -z "${PREVIOUS_SHA}" ]]; then
  PREVIOUS_SHA="$(repo_git rev-parse --verify --quiet refs/remotes/origin/staging || true)"
  PREVIOUS_IS_DEFAULT=1
fi
[[ "${PREVIOUS_SHA}" != "${SHA}" ]] || PREVIOUS_SHA=""
if [[ -n "${PREVIOUS_SHA}" ]] && ! repo_git merge-base --is-ancestor "${PREVIOUS_SHA}" "${SHA}"; then
  (( PREVIOUS_IS_DEFAULT == 1 )) || fail "--previous-sha must be an ancestor of the release (deploys are fast-forwards)"
  echo "WARNING G3 origin/staging is not an ancestor of the release; no rollback target included (pass --previous-sha)"
  PREVIOUS_SHA=""
fi

RELEASE_REF="refs/jaspen-staging-release/${SHA}"
PREVIOUS_REF="refs/jaspen-staging-release/${PREVIOUS_SHA:-none}"
cleanup() {
  repo_git update-ref -d "${RELEASE_REF}" 2>/dev/null || true
  [[ -z "${PREVIOUS_SHA}" ]] || repo_git update-ref -d "${PREVIOUS_REF}" 2>/dev/null || true
}
trap cleanup EXIT
repo_git update-ref "${RELEASE_REF}" "${SHA}"
BUNDLE_REFS=("${RELEASE_REF}")
if [[ -n "${PREVIOUS_SHA}" ]]; then
  # The previous commit is also a bundle head, so the same artifacts can roll
  # staging back to it.
  repo_git update-ref "${PREVIOUS_REF}" "${PREVIOUS_SHA}"
  BUNDLE_REFS+=("${PREVIOUS_REF}")
fi
# Full history of the release commit, so the bundle has no prerequisites and
# includes every commit the server already runs (deploys are fast-forwards).
repo_git bundle create --quiet "${ART}/${BUNDLE_NAME}" "${BUNDLE_REFS[@]}"
repo_git bundle verify --quiet "${ART}/${BUNDLE_NAME}" >/dev/null 2>&1 || fail "git bundle verify"
cleanup

PYTHON="${JASPEN_STAGE_PYTHON:-${REPO_ROOT}/backend/venv/bin/python}"
[[ -x "${PYTHON}" ]] || PYTHON="$(command -v python3)" || fail "python3 not found"

download_wheels() {
  local requirements_file="$1"
  "${PYTHON}" -m pip download --quiet --disable-pip-version-check \
    --only-binary=:all: --platform "${WHEEL_PLATFORM}" --python-version "${WHEEL_PYTHON_VERSION}" \
    --dest "${ART}/wheelhouse" -r "${requirements_file}" \
    "${GREENLET_REQUIREMENT}" "${STAGING_EXTRA_REQUIREMENT}"
}

repo_git show "${SHA}:backend/requirements.txt" >"${ART}/requirements-${SHA}.txt"
download_wheels "${ART}/requirements-${SHA}.txt" || fail "pip download for ${SHA}"
if [[ -n "${PREVIOUS_SHA}" ]]; then
  repo_git show "${PREVIOUS_SHA}:backend/requirements.txt" >"${ART}/requirements-${PREVIOUS_SHA}.txt"
  if ! cmp -s "${ART}/requirements-${SHA}.txt" "${ART}/requirements-${PREVIOUS_SHA}.txt"; then
    download_wheels "${ART}/requirements-${PREVIOUS_SHA}.txt" || fail "pip download for ${PREVIOUS_SHA}"
  fi
fi

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

EVIDENCE_LINE="none (CI check runs passed)"
if [[ -n "${EVIDENCE_FILE}" ]]; then
  cp "${EVIDENCE_FILE}" "${ART}/local-suites-evidence.txt"
  EVIDENCE_LINE="local-suites-evidence.txt sha256 $(sha256_of "${ART}/local-suites-evidence.txt")"
fi

{
  echo "release_sha ${SHA}"
  echo "created_utc $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "release_ref_gate ${REF_GATE}"
  echo "ci ${CI_SUMMARY}"
  echo "ci_advisory ${CI_ADVISORY}"
  echo "local_suites_evidence ${EVIDENCE_LINE}"
  echo "previous_sha ${PREVIOUS_SHA:-none} (bundle head and wheels included for rollback)"
  echo "wheel_platform ${WHEEL_PLATFORM} python ${WHEEL_PYTHON_VERSION}"
  echo "explicit_wheels ${GREENLET_REQUIREMENT} ${STAGING_EXTRA_REQUIREMENT} (staging-only, R-2)"
  echo "wheel_count $(find "${ART}/wheelhouse" -type f -name '*.whl' | wc -l | tr -d ' ')"
} >"${ART}/release-manifest.txt"

(
  cd "${ART}"
  find . -type f ! -name SHA256SUMS | sed 's|^\./||' | LC_ALL=C sort | while IFS= read -r path; do
    printf '%s  %s\n' "$(sha256_of "${path}")" "${path}"
  done >SHA256SUMS
)
echo "PASS G3 artifacts built: ${ART}"

# Remote commands. G2-G5 run on the server inside the wrapper; G6 and G7 are
# staging-smoke.sh.
SSH_TARGET="<SSH_USER>@<SSH_HOST>"
REMOTE_UPLOAD_DIR="<REMOTE_UPLOAD_DIR>"
SSH_PROGRAM="ssh"
SSH_OPTIONS=(-o BatchMode=yes -o StrictHostKeyChecking=yes)

load_operator_config() {
  [[ -f "${OPERATOR_CONFIG}" ]] || return 1
  [[ "$(stat -f '%u' "${OPERATOR_CONFIG}" 2>/dev/null || stat -c '%u' "${OPERATOR_CONFIG}")" == "$(id -u)" ]] \
    || fail "operator config must be owned by you"
  local mode
  mode="$(stat -f '%Lp' "${OPERATOR_CONFIG}" 2>/dev/null || stat -c '%a' "${OPERATOR_CONFIG}")"
  (( (8#${mode} & 8#077) == 0 )) || fail "operator config must be mode 600"
  # shellcheck source=/dev/null
  source "${OPERATOR_CONFIG}"
  [[ "${SSH_HOST:-}" =~ ^[A-Za-z0-9._-]+$ ]] || fail "operator config SSH_HOST"
  [[ "${SSH_USER:-}" =~ ^[a-z_][a-z0-9_-]*$ ]] || fail "operator config SSH_USER"
  [[ "${REMOTE_UPLOAD_DIR:-}" =~ ^/[A-Za-z0-9._/-]+$ ]] || fail "operator config REMOTE_UPLOAD_DIR"
  SSH_TARGET="${SSH_USER}@${SSH_HOST}"
  if [[ -n "${SSH_IDENTITY_FILE:-}" ]]; then
    [[ -f "${SSH_IDENTITY_FILE}" ]] || fail "operator config SSH_IDENTITY_FILE"
    SSH_OPTIONS+=(-o IdentitiesOnly=yes -i "${SSH_IDENTITY_FILE}")
  fi
  if [[ -n "${SSH_KNOWN_HOSTS_FILE:-}" ]]; then
    [[ -f "${SSH_KNOWN_HOSTS_FILE}" ]] || fail "operator config SSH_KNOWN_HOSTS_FILE"
    SSH_OPTIONS+=(-o UserKnownHostsFile="${SSH_KNOWN_HOSTS_FILE}")
  fi
  if [[ -n "${SSH_HELPER:-}" ]]; then
    [[ -x "${SSH_HELPER}" ]] || fail "operator config SSH_HELPER"
    SSH_PROGRAM="${SSH_HELPER}"
  fi
}

if (( EXECUTE == 1 )); then
  load_operator_config || fail "operator config ${OPERATOR_CONFIG} is required for --execute"
else
  load_operator_config || true
fi

REMOTE_DIR="${REMOTE_UPLOAD_DIR}/${ART_NAME}"
REMOTE_BUNDLE="${REMOTE_DIR}/${BUNDLE_NAME}"
REMOTE_WHEELHOUSE="${REMOTE_DIR}/wheelhouse"
DEPLOY_ARGS=(--deploy "${SHA}" "${REMOTE_BUNDLE}" "${REMOTE_WHEELHOUSE}")
(( ALLOW_MIGRATIONS == 0 )) || DEPLOY_ARGS+=(--allow-migrations)
# --deploy-detached runs the deploy in a transient systemd unit that the
# wrapper names and starts itself, so a dropped SSH session cannot stop it; it
# streams the unit's journal, and --log <unit> re-attaches.
DEPLOY_COMMAND=(sudo -n "${REMOTE_WRAPPER}" --deploy-detached "${DEPLOY_ARGS[@]:1}")
ROLLBACK_COMMAND=()
if [[ -n "${PREVIOUS_SHA}" ]]; then
  ROLLBACK_COMMAND=(sudo -n "${REMOTE_WRAPPER}" --rollback-detached "${PREVIOUS_SHA}" "${REMOTE_BUNDLE}" "${REMOTE_WHEELHOUSE}")
fi

remote() {
  "${SSH_PROGRAM}" "${SSH_OPTIONS[@]}" "${SSH_TARGET}" "$@"
}

upload() {
  scp -q -r -S "${SSH_PROGRAM}" "${SSH_OPTIONS[@]}" "${ART}" "${SSH_TARGET}:${REMOTE_UPLOAD_DIR}/"
}

print_rollback_command() {
  if (( ${#ROLLBACK_COMMAND[@]} > 0 )); then
    echo "Code rollback to the previous sha, if needed (requires Lydia's approval):"
    echo "  ${SSH_PROGRAM} ${SSH_OPTIONS[*]} ${SSH_TARGET} ${ROLLBACK_COMMAND[*]}"
  else
    echo "No previous sha known; pass --previous-sha to include a rollback target."
  fi
}

if (( EXECUTE == 0 )); then
  echo
  echo "DRY RUN: nothing was copied or run remotely. With --execute this script would run:"
  echo "  ${SSH_PROGRAM} ${SSH_OPTIONS[*]} ${SSH_TARGET} sudo -n ${REMOTE_WRAPPER} --check"
  echo "  ${SSH_PROGRAM} ${SSH_OPTIONS[*]} ${SSH_TARGET} mkdir -p -m 0700 ${REMOTE_UPLOAD_DIR}"
  echo "  scp -q -r -S ${SSH_PROGRAM} ${SSH_OPTIONS[*]} ${ART} ${SSH_TARGET}:${REMOTE_UPLOAD_DIR}/"
  echo "  ${SSH_PROGRAM} ${SSH_OPTIONS[*]} ${SSH_TARGET} ${DEPLOY_COMMAND[*]}"
  echo "  ${SSH_PROGRAM} ${SSH_OPTIONS[*]} ${SSH_TARGET} sudo -n ${REMOTE_WRAPPER} --status"
  print_rollback_command
  echo "Then run deploy/staging/staging-smoke.sh (G6, G7) with the production CSP baseline and the expected main sha."
  exit 0
fi

echo "EXECUTE: deploying ${SHA} to staging."
remote sudo -n "${REMOTE_WRAPPER}" --check || fail "remote G2 preflight"
remote mkdir -p -m 0700 "${REMOTE_UPLOAD_DIR}" || fail "remote upload directory"
upload || fail "artifact upload"
remote "${DEPLOY_COMMAND[@]}" || {
  echo "If the SSH session dropped, the deploy keeps running on the server; re-attach with:" >&2
  echo "  ${SSH_PROGRAM} ${SSH_OPTIONS[*]} ${SSH_TARGET} sudo -n ${REMOTE_WRAPPER} --log <unit printed above>" >&2
  fail "remote deploy (see the wrapper output above)"
}
remote sudo -n "${REMOTE_WRAPPER}" --status || true
print_rollback_command
echo "Staging deploy finished. Next: deploy/staging/staging-smoke.sh (G6, G7) with the production CSP baseline and the expected main sha."
