# Staging deployment runbook

Staging is deployed by an operator, never by GitHub. The GitHub staging
workflow (`.github/workflows/deploy-staging.yml`) stays disabled. The staging
server is egress-locked, so code arrives as a git bundle and Python
dependencies as an offline wheelhouse. The server-side wrapper mirrors
production's in-place model (exact sha, clean tree, fast-forward only,
migrate before restart) so every staging deploy rehearses a production deploy.

No IP addresses, host names, accounts or credentials belong in this
directory. Host-specific values live in two files outside the repository:
`/etc/jaspen-staging/deploy.conf` on the server (see `deploy.conf.example`)
and `~/.config/jaspen/staging-operator.conf` on the operator's machine (see
`staging-operator.conf.example`).

## Roles

| Role | Who | Does |
| --- | --- | --- |
| Approver | Lydia | Approves each deploy, every migration, the one-time install, and any database restore. |
| Operator | Claude | Runs `stage-release.sh` and `staging-smoke.sh`, reads results, reports. |
| Implementer | Codex or Claude | Changes code on `develop` only; never touches staging. |

## Files

| File | Runs on | Purpose |
| --- | --- | --- |
| `stage-release.sh` | operator machine | Gates G0, G1 and the local half of G3; builds bundle, wheelhouse and checksums; dry run by default. |
| `jaspen-staging-deploy` | server, as root | `--check` (G2), `--deploy` and `--rollback` (G2–G5), `--status`. |
| `staging_config_check.py` | server | `env-file` audit (root, stdlib only) and `app` factory check (app user). Prints names and PASS/FAIL only. |
| `staging_database.py` | server, as the app user (`census-compare` as root) | Read-only Alembic revision, pending migrations, D1 copied-user counts and the per-table `census`; `census-compare` compares two census files without a database. |
| `staging_db_roles.py` | server, as the app user with the owner URL file | BI-2 database role policy: `plan`, `verify`, `snapshot`, `apply`, `rollback`. |
| `recovery-validation.sh` | operator machine | Isolated point-in-time restore cluster for recovery validation (dry run by default). |
| `staging-smoke.sh` | operator machine | Read-only GET/OPTIONS checks of staging (G6) and of production being unchanged (G7). |

## One-time install (requires Lydia's approval)

On the server, as root:

1. Copy `jaspen-staging-deploy` to `/usr/local/sbin/jaspen-staging-deploy`
   (root-owned, mode 0755).
2. Copy `staging_config_check.py`, `staging_database.py` and `staging_db_roles.py` to the configured
   `HELPER_DIR` (root-owned directory and files, mode 0755/0644).
3. Write `/etc/jaspen-staging/deploy.conf` from `deploy.conf.example`
   (root-owned, mode 0644 or stricter).
4. The operator SSH login is currently root, so no sudoers rule is needed.
   If a non-root operator is introduced later, allow it the wrapper path
   only. The wrapper validates every argument and builds the `systemd-run`
   and `journalctl` command lines itself, so they need no sudoers entries
   (a `*` in sudoers also matches spaces and would let options through):

   ```sudoers
   # /etc/sudoers.d/jaspen-staging (only for a future non-root operator)
   staging-operator ALL=(root) NOPASSWD: /usr/local/sbin/jaspen-staging-deploy
   ```
5. Run `jaspen-staging-deploy --check` and confirm every line is PASS.

## Routine deploy

1. Lydia approves deploying a specific 40-hex sha that is already on `develop`.
2. Run the full local suites if the sha has no CI check runs and keep the output.
3. Dry run (default):
   `deploy/staging/stage-release.sh <sha> [--local-suites-evidence <file>]`
   Review the gate lines and the printed remote commands.
4. Execute: the same command with `--execute` (add `--allow-migrations` only
   when Lydia has approved the pending migrations by revision id). This runs
   `jaspen-staging-deploy --deploy-detached`: the wrapper starts the deploy in
   a transient systemd unit it names itself (`TimeoutStopSec=15min`), so a
   dropped SSH session cannot stop it, and streams its journal. Re-attach with
   `jaspen-staging-deploy --log <unit>`.
5. Run `deploy/staging/staging-smoke.sh` with the recorded production CSP
   sha256 and the expected production `main` sha as the fifth and sixth
   arguments. Every line must be PASS. WARN is allowed only for the optional
   `X-Jaspen-Environment` header and for known exception R-3 (below); an
   "R-3 ... not observed" WARN means remediation may be done, so report it.
6. Move the `staging` branch to the deployed sha (fast-forward) and report the
   deploy record from `jaspen-staging-deploy --status`.

## Gates

Lydia approves every deploy by sha, and separately every migration, before
any gate runs.

| Gate | Where | Check | On failure |
| --- | --- | --- | --- |
| G0 | `stage-release.sh` | GitHub Actions jobs `backend`, `backend-postgres`, `frontend`, `secret-scan` all success; `security-audit` is advisory (WARNING, recorded in the manifest); any other failed run stops. With no runs at all, local suites evidence is required and recorded. | Stop. |
| G1 | `stage-release.sh` | Exact 40-hex sha, reachable from `origin/develop` (or, transitionally, equal to the `origin/staging` tip). | Stop. |
| G2 | `--check` (also first step of `--deploy`) | Egress lock active and OUTPUT policy DROP; runtime unit requires the lock; copied production units masked; nginx enabled sites exactly the allowed set; env file root-owned and not world-readable; no live Stripe values; disabled integration secrets empty; staging cookie names and `.jaspen.ai` domain; database host is the staging fork; quarantine entry count; clean tree; no stray `backend/.env`; D1: copied accounts (created before the configured cutoff) all deactivated with no usable password hash. | Stop; nothing changed. |
| G3 | both | Bundle and wheelhouse built outside the repo with `SHA256SUMS`; the wrapper copies them into a root-controlled directory, verifies the copy and rejects unlisted files; `git bundle verify`; fast-forward only; checkout verified; offline install plus `pip check`; staging app factory config check. | Before checkout: stop. After: code rollback. |
| G4 | `--deploy` | Pending migrations refused before checkout unless `--allow-migrations`; pre-migration UTC timestamp written to the deploy record immediately before migrating; the migration always runs to completion; D1 check again after. | Refusal leaves staging untouched; later failures roll back code. |
| G5 | `--deploy` | Restart, socket `/health` with retries, journal Traceback/ERROR count in the record. Any failure, error or signal after checkout rolls the code back and writes a final record (`rolled_back_code`, `interrupted` or `rollback_failed`). | Automatic code rollback. |
| G6 | `staging-smoke.sh` | Staging `/health`, CORS preflights, 401s, `noindex`, HSTS, staging web not public. | Report; Lydia decides on rollback. |
| G7 | `staging-smoke.sh` | Production unchanged: `/health` 200, web 200, CSP sha256 equals the full 64-hex baseline, GitHub `main` equals the expected sha. For the staging origin and an unrelated origin: the actual `/api/v1/auth/me` response is 401 and grants no allow-origin, and the preflight grants none, except known exception R-3 (below). | Stop and report to Lydia at once. |

## Production baselines for G7

- `PROD_CSP_SHA256`: the full sha256 of production's `Content-Security-Policy`
  header value. GET the production web URL, take the first CSP header, strip
  CR, drop the header name, then `printf '%s' "$value" | sha256sum`.
  `staging-smoke.sh` uses exactly this method and prints the current value on
  every run. Record the baseline in the deploy plan, never in this repository.
- `EXPECTED_MAIN_SHA`: the 40-hex commit GitHub `main` must still be at.

## Known exception R-3 (temporary)

R-3 is an open item in the engineering risk register: the production API's
CORS preflight echoes the requesting origin. While it is open, G7 reports a
preflight that echoes **exactly** the requesting origin, with the recorded
header signature `R3_PREFLIGHT_SIGNATURE_SHA256`, as `WARN ... KNOWN R-3 (not
resolved)`, and only when the actual response for that origin grants nothing.
Everything else fails: a wildcard, a different or repeated origin, a changed
header signature, a connection error, a granting actual response or an
unexpected status. The exception does not mean R-3 is resolved. Once R-3 is
remediated and confirmed, remove `R3_EXCEPTION_DEFAULT` and the exception
branch, and their tests. Until then `JASPEN_SMOKE_R3_EXCEPTION=0` runs G7 strict.

## Rollback levels

| Level | How | Approval |
| --- | --- | --- |
| Code | Automatic on any failure after checkout. Manually: the rollback command `stage-release.sh` prints (the release bundle also carries the previous sha and its wheels), i.e. `jaspen-staging-deploy --rollback-detached <previous sha> <bundle> <wheelhouse>`. Refused if the older sha's Alembic head is not in the database history; the schema stays at the newer head. | Lydia |
| Frontend | Vercel: redeploy the previous staging deployment, or move the `staging` branch back to the previous sha. | Lydia |
| Database | Migrations are not downgradable. Point-in-time restore of the staging cluster to the `pre_migration_utc` in the deploy record; rehearse it first with "Recovery validation" below. | Lydia, every time |

## Data census (every deploy and rollback)

Before anything changes, the wrapper takes a census: the row count of every
table, the Alembic revision and the database identity. After the health check
it takes a second one and compares them:

- `INFO census expected created_empty_by_migration <table>`: a table a
  migration created, still empty. This is the only expected difference.
- `WARN census unexpected ...`: any other difference. That includes a table
  created without a migration or with rows, a table that disappeared, and a
  changed row count. The deploy record's `census` is then
  `unexpected_changes`; report it to Lydia.

If the first census can't be taken, the deploy stops with nothing changed.
Both census files stay next to the deploy record in the root-only log
directory, never in this repository. They hold counts, never row data.

## Database role policy (BI-2)

`staging_db_roles.py` keeps three database roles apart:

- **The owner (the managed database's admin user):** runs Alembic migrations
  and this script.
- **The runtime role (`RUNTIME_DB_ROLE`):** keeps everything it has, except
  INSERT, UPDATE, DELETE and TRUNCATE on the migration evidence tables.
- **The billing migrator (`MIGRATOR_DB_ROLE`):** runs the evidence commands.
  - It reads everything.
  - It may INSERT the evidence tables and write only the target tables the
    commands maintain.
  - On tables it only locks, it holds UPDATE on `id` alone, and a trigger
    rejects any change it attempts.

The migrator login is created by DigitalOcean (`doctl databases user create`),
so this script never handles a password. Its URL file is root-owned, mode 600,
like the other URL files.

| Command | Effect | Approval |
|---|---|---|
| `plan` | Prints the SQL | None |
| `verify`, `snapshot` | Read-only | None |
| `apply --confirm` | Runs the policy in one transaction (idempotent) | Lydia |
| `rollback --snapshot-file <file> --confirm` | Restores a snapshot exactly and removes the triggers | Lydia |

With `ROLE_POLICY=enforce` in deploy.conf, the preflight runs `verify`. A
deploy that ran migrations re-applies the policy, because the owner's default
privileges open every new table to the runtime role, and then verifies it.

## Restore-copy authorization (review N4)

A rehearsal or shadow comparison on `restore_copy` runs only with the
founder's authorization in the staging environment file. Without it (or with
it expired, malformed or mismatched), the shadow comparison is refused before
any connection opens, and the rehearsal's `restore_copy_authorized`
precondition fails. These are the settings:

In the environment file the JSON must be a single line. It is wrapped here only
for reading:

```text
BILLING_RESTORE_COPY_AUTHORIZATION={"approval_reference": "...", "approved_by": "founder",
  "approved_at": "<UTC>", "expires_at": "<UTC, at most 14 days later>",
  "database": {"host": "<the restore copy's host>", "name": "<database>", "system_identifier": "<decimal>"},
  "restore_provenance": {"source_cluster": "...", "restore_cluster": "...", "method": "...",
                         "restored_from_utc": "<UTC>"}}
BILLING_PRODUCTION_DATABASE_HOSTS=<comma-separated production database hosts>   (required)
BILLING_PRODUCTION_LOGIN_ROLES=<comma-separated roles that mark production>     (default jaspen_app_prod)
```

The connected host, database name and `system_identifier` must all match. A
physical restore keeps its source's identifier, so the host is part of the
identity. The host must not be a production host, and no production login role
may exist on the database.

## Recovery validation (isolated restore cluster)

This proves the point-in-time restore without touching the active staging
database. It needs Lydia's approval for steps 2–5. A note on `archive_mode`:
the managed service does not archive WAL through `archive_command`. Its backup
agent streams WAL over a physical replication slot (`pghoard_local`, visible in
`pg_replication_slots` and `pg_stat_replication`), so `archive_mode=off` is
expected. This procedure is the proof that the streamed WAL restores.

1. `recovery-validation.sh plan <source> jaspen-staging-restore-<stamp> <pre_migration_utc>`
   (dry run). Record the active database's census
   (`staging_database.py census`) on the server.
2. `... create ... --execute` creates a NEW cluster restored to that moment.
   - The source must be the staging cluster named in the operator config
     (`STAGING_DB_CLUSTER`), and the restore name must start with
     `jaspen-staging-restore-`, so neither the active nor the production
     cluster can be targeted.
   - As soon as it is online, the script sets its only trusted source to the
     staging Droplet (`STAGING_DROPLET_ID`). Until then the provider accepts
     connections from any address to the copied credentials, so run steps 2
     and 3 together.
3. Add a temporary egress rule on the Droplet for the restore cluster's
   private address and port only. Write its URL file (root-owned, mode 600)
   on the server.
4. On the server, run `staging_database.py --url-file <restore URL file> census`.
   Compare it with the deploy's `-census-before.json` from the log directory
   (taken just before that deploy changed anything) using `census-compare
   --migrations-ran false`. Expected:
   - `PASS census_compare ... unexpected=0`, apart from live writes in the few
     seconds between the census and `pre_migration_utc`, listed by name;
   - the restore's Alembic revision equals the deploy record's `alembic_before`;
   - the `system_identifier` is the same.
   For the BI-1 deploy there is no census-before. Compare with the active
   database instead and read the result by hand: the only expected difference
   is `dropped billing_migration_operation_decisions`, meaning the restore
   predates the migration that created it.
5. Remove the egress rule and the URL file, then
   `recovery-validation.sh destroy jaspen-staging-restore-<stamp> --execute`.
   Run `--check`; it must be all PASS again.

The restore cluster is never attached to the application, gets no other
trusted source, and is destroyed the same day.

## What stays disabled on staging

- The GitHub staging deploy workflow.
- AI provider calls, email sending, integrations (Jira, Smartsheet,
  Salesforce, Snowflake, Workfront) and Sentry egress: their secrets are empty
  and the egress lock blocks everything except the staging database.
- Billing beyond the Stripe test key: no live Stripe values anywhere.

## Branch rule

`staging` only ever points at a commit that is already on `develop`, moved by
fast-forward. After the current staging-only commits are integrated into
`develop`, `staging` never carries its own commits again, and the
transitional "equals the `origin/staging` tip" allowance in G1 is removed.
