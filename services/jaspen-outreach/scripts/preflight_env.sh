#!/usr/bin/env bash
# Reports PRESENT/MISSING for deploy vars. Never prints values.
set -u
status=0
for v in OPENAI_API_KEY DIGITALOCEAN_ACCESS_TOKEN OPENAI_MODEL \
         JASPEN_OUTREACH_SHARED_SECRET JASPEN_FUNCTION_WEB_SECRET; do
  val="${!v:-}"
  if [ -n "$val" ]; then
    printf '  %-32s PRESENT (%d chars)\n' "$v" "${#val}"
  else
    printf '  %-32s *** MISSING ***\n' "$v"
    status=1
  fi
done
[ $status -eq 0 ] && echo "  -> all deploy vars present" || echo "  -> NOT READY"
exit $status
