"""Load the production database URL from a protected local secret file."""

from __future__ import annotations

import os
import stat
from pathlib import Path


DEFAULT_DATABASE_URL_FILE = Path.home() / ".config" / "jaspen" / "database_url"


def load_database_url_secret(*, environ=None, path=None):
    """Prefer a mode-600 database URL file over process/service metadata.

    Returns ``True`` when a file was loaded and ``False`` when no configured or
    conventional file exists. An existing but insecure or malformed file fails
    closed so production cannot silently fall back to an exposed credential.
    """

    target_environ = environ if environ is not None else os.environ
    configured_path = target_environ.get("JASPEN_DATABASE_URL_FILE")
    candidate = Path(path or configured_path or DEFAULT_DATABASE_URL_FILE).expanduser()
    if not candidate.exists():
        return False

    file_mode = stat.S_IMODE(candidate.stat().st_mode)
    if file_mode & 0o077:
        raise RuntimeError(f"Database URL secret file must be mode 600: {candidate}")

    database_url = candidate.read_text(encoding="utf-8").strip()
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        raise RuntimeError(f"Database URL secret file is malformed: {candidate}")

    target_environ["DATABASE_URL"] = database_url
    target_environ["SQLALCHEMY_DATABASE_URI"] = database_url
    return True
