import os
import subprocess
import sys
import uuid

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text

from app import db


def test_alembic_upgrade_head_matches_model_metadata(
    app, validate_test_database_url, postgres_schema_url,
):
    base_url = validate_test_database_url(os.environ["TEST_DATABASE_URL"])
    schema = f"jaspen_migration_test_{uuid.uuid4().hex}"
    admin_engine = create_engine(base_url, isolation_level="AUTOCOMMIT")
    schema_url = postgres_schema_url(base_url, schema)
    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))

        env = os.environ.copy()
        env["DATABASE_URL"] = str(schema_url)
        env.pop("TEST_DATABASE_URL", None)
        subprocess.run(
            [sys.executable, "-m", "flask", "--app", "app:create_app", "db", "upgrade"],
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )

        # Import every model module that contributes tables before comparing.
        import app.models_decision_baseline  # noqa: F401
        import app.models_decision_record  # noqa: F401
        import app.models_pm_sync  # noqa: F401
        import app.models_studio  # noqa: F401

        migrated_engine = create_engine(schema_url)
        try:
            with migrated_engine.connect() as connection:
                context = MigrationContext.configure(
                    connection,
                    opts={
                        "include_object": lambda obj, name, type_, reflected, compare_to:
                            name != "alembic_version"
                    },
                )
                differences = compare_metadata(context, db.metadata)
        finally:
            migrated_engine.dispose()

        assert differences == [], f"migration/model schema differences: {differences!r}"
    finally:
        with admin_engine.connect() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()
