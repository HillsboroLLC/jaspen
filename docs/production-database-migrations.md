# Production database migrations

Production runtime reads `~/.config/jaspen/database_url` as `jaspen_app_prod`.
Deployments run `backend/migrate_production.py`, using the separate database-owner
URL in `~/.config/jaspen/migration_database_url`. Both files must be mode 600,
owned by the deployment user. Never commit or print either credential.

The helper refuses missing/insecure files, different database targets, or an
identical runtime/migration login. It sets the owner credential only in the
Flask migration subprocess. The service continues using its existing app file.

Before upgrading, it configures PostgreSQL default privileges for objects the
migration login subsequently creates in `public`: app SELECT/INSERT/UPDATE/DELETE
on tables and USAGE/SELECT on sequences. It does not grant schema creation,
object ownership, or owner-role membership to the app. Existing objects are not
changed by these default grants. If a table predates this setup and lacks app
access, an owner must grant that table's required permissions separately.

The production workflow restarts Gunicorn only after the helper succeeds.
Overrides: `JASPEN_DATABASE_URL_FILE` selects the app file and
`JASPEN_MIGRATION_DATABASE_URL_FILE` selects the migration file. Both must point
to the same host, port, and database. Staging is unchanged.
