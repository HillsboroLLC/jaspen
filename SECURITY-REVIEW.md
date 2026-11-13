# P2a Security Review

## Finding

| # | Severity | File | Lines | Vulnerability | Confidence |
|---|----------|------|-------|---------------|------------|
| 1 | 🟠 HIGH | `backend/app/session_access.py` | 188-189 | A caller's organization-bound historical fork could be used as a fallback when the caller's active organization had no canonical row for that thread. In report mode this could expose or mutate project data from another organization. | 9/10 |

## Remediation and verification

The canonical resolver now falls back to the caller's row only when it is
unbound to an organization. Otherwise it returns no row. The focused report-mode
regression exercises start, continue, regenerate, and undo, verifying that they
return 404 without model execution, credit reservation, or changes to canonical
or fork rows.

Focused verification: 12 tests passed, including fork isolation, canonical
project writes, owner reopen, and session ownership coverage. `git diff --check`
was clean.

The finding is resolved in the current uncommitted P2a worktree. This report
does not attest to a broader P2a security review.
