import pytest

from app.safe_redirect import safe_internal_path


FALLBACK = "/fallback"

REJECTED_PATHS = [
    "//evil.example",
    "/\\evil.example",
    "/\\/evil.example",
    "/\t/evil.example",
    "/\n/evil.example",
    "/.//evil.example",
    "/..//evil.example",
    "/x/..//evil.example",
    "/%2e%2e//evil.example",
    "/%2F%2Fevil.example",
    "/%5Cevil.example",
    "/%252F%252Fevil.example",
    "https://evil.example",
    "javascript:alert(1)",
    "evil.example",
    " //evil.example",
    "///evil.example",
    "/%5C%5Cevil.example",
    "/%09/evil.example",
    "/%00",
    "/%2525252F%2525252Fevil.example",
    "/%ZZ",
    "/%E0%A4%A",
    "",
    None,
    42,
]

ACCEPTED_PATHS = [
    "/new",
    "/new?sid=abc123",
    "/?auth=1",
    "/account?tab=plans",
    "/account?tab=plans#billing",
    "/decision-profile",
    "/connectors-manage?filter=active",
    "/limited-time/client-decisions?limited_time_checkout=resume",
    "/limited-time/strategic-planning?limited_time_checkout=resume&verified=1",
    "/new?ref=https://example.com//path",
    "/new?next=%2Fnew%3Fa%3D1",
    "/s/abc%20def",
    "/s/abc-123_DEF",
]


@pytest.mark.parametrize("candidate", REJECTED_PATHS)
def test_safe_internal_path_rejects_unsafe_values(candidate):
    assert safe_internal_path(candidate, FALLBACK) == FALLBACK


@pytest.mark.parametrize("candidate", ACCEPTED_PATHS)
def test_safe_internal_path_returns_safe_values_unchanged(candidate):
    assert safe_internal_path(candidate, FALLBACK) == candidate
