# Production deployment least-privilege contract

Status: repository safeguards and host-side templates are implemented locally.
The live host is not claimed compliant, and this document does not authorize a
production change. `production-security-cutover.md` lists the administrator
cutover and verification that remain.

## Identities

| Identity | May | Must not |
|---|---|---|
| GitHub production environment | Release an approved `main` revision through the production workflow | Expose deployment values to pull requests or unapproved jobs |
| Deployment account | Fast-forward the approved checkout and invoke fixed migration and restart operations | Read database credentials, obtain a general root shell, alter arbitrary services, or deploy an unapproved revision |
| Application runtime account | Run `gunicorn-sekki.service` and read only the runtime database credential | Log in interactively, use sudo, run migrations, or read the migration credential |
| Database migration account | Run the approved migration operation and read only the migration credential | Run the application, log in interactively, or expose the credential to the deployment shell |
| Database application role | Read and modify application data and use required sequences | Create schemas or objects, own production objects, inherit the migration role, or grant privileges |
| Database migration role | Own and migrate the application schema and grant the documented runtime defaults | Serve application traffic or be used by the runtime service |

## Required boundaries

1. The runtime and migration database URLs name different logins and the same host, port, and database. Each database URL credential file is owned by its corresponding service identity and is mode `0600`, as enforced when it is read. `/etc/jaspen/runtime.env` and `/etc/jaspen/migration.env` contain references and non-secret settings; they are owned by `root`, grouped to their corresponding service identity, and mode `0640`.
2. The deployment account owns neither credential file. Any allowed privilege escalation names a root-owned wrapper, fixed working directory, fixed service unit, and fixed command; it accepts no caller-controlled command or path.
3. A migration failure prevents restart. The currently running service remains untouched when checkout, dependency installation, or migration fails.
4. Production releases come only from protected `main`, through a protected GitHub Environment with human approval and environment-scoped deployment values. The workflow token is read-only unless a reviewed step proves a narrower additional permission is necessary.
5. SSH host identity is pinned from an administrator-verified public host key. A key mismatch stops the deployment before authentication.
6. Deployment logs and errors never contain private keys, database URLs, access tokens, or credential-file contents.
7. Runtime customer-data paths remain in the existing checkout for this cutover. They are ignored by Git, owned by `jaspen-app`, writable only where the systemd drop-in explicitly allows writes, and are never modified by deployment repository operations.

## Verification boundary

Automated repository tests cover workflow structure, fail-closed ordering,
credential separation, child-process isolation, runtime-environment restoration,
and sanitized command-line failure. They do not prove live GitHub protection,
host account membership, file ownership, sudo policy, or PostgreSQL grants.
Those controls require an administrator-reviewed, read-only live verification
before any cutover.

The existing deployment path remains in place until a separately approved
replacement satisfies this contract and has a tested rollback path.
