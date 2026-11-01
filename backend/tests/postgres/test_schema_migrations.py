import os
import subprocess
import sys
import uuid

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text

from app import db


KNOWN_SCHEMA_DIFFERENCES = {
    # Studio predates migration coverage; these model tables have no migration.
    ("add_table", "studio_artifacts", "studio_artifacts"),
    ("add_index", "studio_artifacts", "ix_studio_artifacts_archived_at"),
    ("add_index", "studio_artifacts", "ix_studio_artifacts_organization_id"),
    ("add_index", "studio_artifacts", "ix_studio_artifacts_type"),
    ("add_index", "studio_artifacts", "ix_studio_artifacts_user_id"),
    ("add_index", "studio_artifacts", "ix_studio_artifacts_workspace_id"),
    ("add_index", "studio_artifacts", "ix_studio_artifacts_workspace_position"),
    ("add_table", "studio_workspaces", "studio_workspaces"),
    ("add_index", "studio_workspaces", "ix_studio_workspaces_archived_at"),
    ("add_index", "studio_workspaces", "ix_studio_workspaces_created_by_user_id"),
    ("add_index", "studio_workspaces", "ix_studio_workspaces_organization_id"),
    ("add_index", "studio_workspaces", "ix_studio_workspaces_purge_after"),
    ("add_index", "studio_workspaces", "ix_studio_workspaces_user_id"),
    ("add_index", "studio_workspaces", "ix_studio_workspaces_user_updated"),
    ("add_index", "studio_workspaces", "ix_studio_workspaces_visibility"),
}


def _flatten_differences(differences):
    for difference in differences:
        if isinstance(difference, list):
            yield from _flatten_differences(difference)
        else:
            yield difference


def _describe_difference(difference):
    difference_type = difference[0]
    if difference_type in {"add_table", "remove_table"}:
        table = difference[1]
        return difference_type, table.name, table.name
    if difference_type in {"add_column", "remove_column"}:
        return difference_type, difference[2], difference[3].name
    if difference_type.startswith("modify_"):
        return difference_type, difference[2], difference[3]

    target = difference[1]
    table = getattr(target, "table", None)
    return (
        difference_type,
        getattr(table, "name", None),
        getattr(target, "name", None),
    )


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
        env["DATABASE_URL"] = schema_url.render_as_string(hide_password=False)
        env.pop("TEST_DATABASE_URL", None)
        subprocess.run(
            [sys.executable, "-m", "flask", "--app", "wsgi:app", "db", "upgrade"],
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

        descriptions = {
            _describe_difference(difference)
            for difference in _flatten_differences(differences)
        }
        assert descriptions == KNOWN_SCHEMA_DIFFERENCES, (
            "migration/model schema differences changed: "
            f"expected {sorted(KNOWN_SCHEMA_DIFFERENCES, key=repr)!r}, "
            f"found {sorted(descriptions, key=repr)!r}"
        )
    finally:
        with admin_engine.connect() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()
