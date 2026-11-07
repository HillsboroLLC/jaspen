import pytest


@pytest.fixture(autouse=True)
def _postgres_only(app):
    with app.app_context():
        from app import db

        if db.engine.dialect.name != "postgresql":
            pytest.skip("Postgres integration test")
