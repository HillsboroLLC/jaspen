import pytest


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://user:password@example.com/jaspen_test",
        "postgresql+psycopg://user:password@localhost/jaspen",
        "sqlite:////tmp/jaspen_test.sqlite",
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
        f"postgresql+psycopg://user:password@{host}/jaspen_test"
    )
    assert parsed.host == host
    assert parsed.database == "jaspen_test"
