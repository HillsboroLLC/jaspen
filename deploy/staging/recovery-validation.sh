#!/usr/bin/env bash
# Staging-only recovery validation (BI-2): prove point-in-time recovery of the
# staging cluster by restoring it into a SEPARATE, isolated cluster. The active
# staging database is never changed, connected to by the restore, or replaced.
#
#   recovery-validation.sh plan    <source-cluster> <restore-name> <UTC timestamp>
#   recovery-validation.sh create  <source-cluster> <restore-name> <UTC timestamp> --execute
#   recovery-validation.sh status  <restore-name>
#   recovery-validation.sh destroy <restore-name> --execute
#
# The UTC timestamp is a deploy record's pre_migration_utc, e.g. 2026-11-24T20:29:14Z.
# Dry run (plan) is the default for create and destroy; nothing is created or
# deleted without --execute, and each --execute needs Lydia's approval.
#
# The source must be the staging cluster named in the operator config
# (~/.config/jaspen/staging-operator.conf: STAGING_DB_CLUSTER), never any other
# cluster. Right after the restore cluster comes online, its only trusted source
# is set to the staging Droplet (STAGING_DROPLET_ID in the same file): a new
# DigitalOcean cluster with no trusted sources accepts connections from any
# address, so the window is limited to the provider's creation time.
# Never prints credentials; doctl prints the restore cluster's connection
# details only when asked for them explicitly (not by this script).
set -euo pipefail

readonly NAME_PATTERN='^[a-z0-9][a-z0-9-]{2,62}$'
readonly STAMP_PATTERN='^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$'
readonly RESTORE_PREFIX='jaspen-staging-restore-'

fail() { echo "FAIL: $1" >&2; exit 1; }

command="${1:-}"
[[ "${command}" =~ ^(plan|create|status|destroy)$ ]] || fail "usage: see the header of this script"

readonly OPERATOR_CONF="${HOME}/.config/jaspen/staging-operator.conf"
operator_value() {
  [[ -f "${OPERATOR_CONF}" ]] || fail "operator config ${OPERATOR_CONF} missing"
  local value
  value="$(grep -E "^$1=" "${OPERATOR_CONF}" | tail -1 | cut -d= -f2-)"
  [[ -n "${value}" ]] || fail "$1 is not set in ${OPERATOR_CONF}"
  printf '%s' "${value}"
}

restore_name_ok() {
  [[ "$1" =~ ${NAME_PATTERN} && "$1" == ${RESTORE_PREFIX}* ]] \
    || fail "the restore cluster name must start with ${RESTORE_PREFIX} (so it can never name the active cluster)"
}

case "${command}" in
  plan | create)
    [[ $# -ge 4 ]] || fail "usage: ${command} <source-cluster> <restore-name> <UTC timestamp>"
    source_cluster="$2"; restore_name="$3"; stamp="$4"; execute="${5:-}"
    [[ "${source_cluster}" =~ ${NAME_PATTERN} ]] || fail "source cluster name"
    staging_cluster="$(operator_value STAGING_DB_CLUSTER)"
    [[ "${source_cluster}" == "${staging_cluster}" ]] \
      || fail "the source must be the staging cluster (${staging_cluster}); no other cluster is ever restored here"
    droplet_id="$(operator_value STAGING_DROPLET_ID)"
    [[ "${droplet_id}" =~ ^[0-9]+$ ]] || fail "STAGING_DROPLET_ID must be numeric"
    restore_name_ok "${restore_name}"
    [[ "${restore_name}" != "${source_cluster}" ]] || fail "the restore must be a different cluster"
    [[ "${stamp}" =~ ${STAMP_PATTERN} ]] || fail "timestamp must be UTC like 2026-11-24T20:29:14Z"
    doctl_stamp="${stamp:0:10} ${stamp:11:8} +0000 UTC"
    source_json="$(doctl databases list -o json)" || fail "doctl databases list failed (doctl auth?)"
    read -r region size version engine <<<"$(printf '%s' "${source_json}" | /usr/bin/python3 -I -c '
import json, sys
name = sys.argv[1]
match = [c for c in json.load(sys.stdin) if c["name"] == name]
if len(match) != 1:
    sys.exit("source cluster not found exactly once")
c = match[0]
print(c["region"], c["size"], c["version"], c["engine"])
' "${source_cluster}")"
    if printf '%s' "${source_json}" | /usr/bin/python3 -I -c '
import json, sys
sys.exit(0 if any(c["name"] == sys.argv[1] for c in json.load(sys.stdin)) else 1)' "${restore_name}"; then
      fail "a cluster named ${restore_name} already exists"
    fi
    cmd=(doctl databases create "${restore_name}" --restore-from-cluster-name "${source_cluster}"
         --restore-from-timestamp "${doctl_stamp}" --engine "${engine}" --version "${version}"
         --region "${region}" --size "${size}" --num-nodes 1 --wait)
    echo "Restore of ${source_cluster} to ${stamp} into NEW cluster ${restore_name} (${engine} ${version}, ${size}, ${region})."
    printf 'Command:'; printf ' %q' "${cmd[@]}"; echo
    echo "Then: trusted source of ${restore_name} = droplet:${droplet_id} only."
    if [[ "${command}" == "create" && "${execute}" == "--execute" ]]; then
      created="$("${cmd[@]}" --format ID --no-header)"
      [[ "${created}" =~ ^[0-9a-f-]{36}$ ]] || fail "could not read the restore cluster id; set its trusted source now"
      doctl databases firewalls append "${created}" --rule "droplet:${droplet_id}" >/dev/null || {
        echo "WARNING: ${restore_name} was created but its trusted source could NOT be set; it accepts" >&2
        echo "WARNING: connections from any address. Set the trusted source or destroy it now." >&2
        exit 1
      }
      doctl databases firewalls list "${created}" --format Type,Value --no-header
      echo "Created ${restore_name}; its only trusted source is the staging Droplet. Next: README.md step 3."
    else
      echo "DRY RUN: nothing was created. Add --execute (after Lydia's approval) to create the restore cluster."
    fi
    ;;
  status)
    [[ $# -eq 2 ]] || fail "usage: status <restore-name>"
    restore_name_ok "$2"
    doctl databases list -o json | /usr/bin/python3 -I -c '
import json, sys
for c in json.load(sys.stdin):
    if c["name"] == sys.argv[1]:
        print(c["name"], c["status"], c["engine"], c["version"], c["size"], c["region"], c["created_at"])
' "$2"
    ;;
  destroy)
    [[ $# -ge 2 ]] || fail "usage: destroy <restore-name> --execute"
    restore_name_ok "$2"
    if [[ "${3:-}" == "--execute" ]]; then
      id="$(doctl databases list -o json | /usr/bin/python3 -I -c '
import json, sys
m = [c["id"] for c in json.load(sys.stdin) if c["name"] == sys.argv[1]]
print(m[0] if len(m) == 1 else "")' "$2")"
      [[ -n "${id}" ]] || fail "restore cluster not found exactly once"
      doctl databases delete "${id}" --force
      echo "Destroyed ${2}."
    else
      echo "DRY RUN: would destroy ${2} (only clusters named ${RESTORE_PREFIX}*). Add --execute after approval."
    fi
    ;;
esac
