import pytest
from sqlalchemy.engine import URL


@pytest.mark.parametrize(
    "url",
    [
        URL.create(
            "postgresql+psycopg",
            username="user",
            password="placeholder",
            host="example.com",
            database="jaspen_test",
        ),
        URL.create(
            "postgresql+psycopg",
            username="user",
            password="placeholder",
            host="localhost",
            database="jaspen",
        ),
        URL.create("sqlite", database="/tmp/jaspen_test.sqlite"),
    ],
)
def test_test_database_url_rejects_unsafe_targets(url, validate_test_database_url):
    with pytest.raises(pytest.UsageError):
        validate_test_database_url(url)


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "postgres"])
def test_test_database_url_accepts_only_named_local_test_databases(
    host, validate_test_database_url,
):
    parsed = validate_test_database_url(
        URL.create(
            "postgresql+psycopg",
            username="user",
            password="placeholder",
            host=host,
            database="jaspen_test",
        )
    )
    assert parsed.host == host
    assert parsed.database == "jaspen_test"
