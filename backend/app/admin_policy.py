import os


DEFAULT_ADMIN_EMAILS = {"support@jaspen.ai"}
DEFAULT_ADMIN_BLOCKLIST = {"ldbailey303@gmail.com"}


def _normalized_set(raw):
    return {
        str(item).strip().lower()
        for item in str(raw or "").split(",")
        if str(item).strip()
    }


def get_admin_email_allowlist(app_config=None):
    configured = ""
    if app_config:
        configured = app_config.get("ADMIN_EMAILS") or ""
    configured = configured or os.getenv("ADMIN_EMAILS") or ""
    emails = _normalized_set(configured)
    return emails or set(DEFAULT_ADMIN_EMAILS)


def get_admin_email_blocklist(app_config=None):
    configured = ""
    if app_config:
        configured = app_config.get("ADMIN_BLOCKED_EMAILS") or ""
    configured = configured or os.getenv("ADMIN_BLOCKED_EMAILS") or ""
    emails = _normalized_set(configured)
    return emails or set(DEFAULT_ADMIN_BLOCKLIST)


def is_global_admin_email(email, app_config=None):
    normalized = str(email or "").strip().lower()
    if not normalized:
        return False
    if normalized in get_admin_email_blocklist(app_config):
        return False
    return normalized in get_admin_email_allowlist(app_config)

