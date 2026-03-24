import os


def _normalized_set(raw):
    return {
        str(item).strip().lower()
        for item in str(raw or "").split(",")
        if str(item).strip()
    }


def _normalized_id_set(raw):
    return {
        str(item).strip()
        for item in str(raw or "").split(",")
        if str(item).strip()
    }


def get_admin_user_ids(app_config=None):
    configured = ""
    if app_config:
        configured = app_config.get("ADMIN_USER_IDS") or ""
    configured = configured or os.getenv("ADMIN_USER_IDS") or ""
    return _normalized_id_set(configured)


def get_admin_email_allowlist(app_config=None):
    configured = ""
    if app_config:
        configured = app_config.get("ADMIN_EMAILS") or ""
    configured = configured or os.getenv("ADMIN_EMAILS") or ""
    return _normalized_set(configured)


def get_admin_email_blocklist(app_config=None):
    configured = ""
    if app_config:
        configured = app_config.get("ADMIN_BLOCKED_EMAILS") or ""
    configured = configured or os.getenv("ADMIN_BLOCKED_EMAILS") or ""
    return _normalized_set(configured)


def is_global_admin(user=None, *, user_id=None, email=None, app_config=None):
    normalized_user_id = str(user_id or getattr(user, "id", "") or "").strip()
    normalized_email = str(email or getattr(user, "email", "") or "").strip().lower()

    if normalized_user_id and normalized_user_id in get_admin_user_ids(app_config):
        return True

    if not normalized_email:
        return False

    if normalized_email in get_admin_email_blocklist(app_config):
        return False

    return normalized_email in get_admin_email_allowlist(app_config)


def is_global_admin_email(email, app_config=None):
    return is_global_admin(email=email, app_config=app_config)
