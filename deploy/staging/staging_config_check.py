#!/usr/bin/env python3
"""Staging configuration checks that print only check names and PASS/FAIL.

Two modes:

* ``env-file``: standard library only, run by the root deploy wrapper with
  ``python3 -I``. Audits the staging environment file and database URL files
  without importing the application.
* ``app``: run as the staging application user with the staging environment
  loaded (the deploy wrapper uses ``systemd-run`` with the service's
  EnvironmentFile). Builds the application factory without serving requests
  and checks the settings the application actually resolved.

No mode ever prints an environment value, a URL or a secret. The expected
values below are not secret; they are the staging isolation contract.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit


APP_ENV = "staging"
SENTRY_ENVIRONMENT = "staging"
COOKIE_DOMAIN = ".jaspen.ai"
CORS_ORIGINS = ["https://staging.jaspen.ai"]
COOKIE_NAMES = {
    "JWT_ACCESS_COOKIE_NAME": "jaspen_staging_access",
    "JWT_ACCESS_CSRF_COOKIE_NAME": "staging_csrf_access_token",
    "GOOGLE_MFA_PENDING_COOKIE_NAME": "jaspen_staging_mfa_pending",
    "SSO_STATE_COOKIE_NAME": "jaspen_staging_sso_state",
}
LIVE_STRIPE_PREFIXES = ("sk_live_", "rk_live_", "pk_live_")
TEST_STRIPE_SECRET_PREFIX = "sk_test_"
DATABASE_URL_SETTINGS = ("DATABASE_URL", "SQLALCHEMY_DATABASE_URI")


class Report:
    def __init__(self) -> None:
        self.failures = 0

    def check(self, name: str, passed: bool, detail: str = "") -> None:
        # ``detail`` is only ever a count or a list of setting NAMES.
        suffix = f" ({detail})" if detail else ""
        print(f"{'PASS' if passed else 'FAIL'} {name}{suffix}")
        if not passed:
            self.failures += 1

    @property
    def exit_code(self) -> int:
        return 1 if self.failures else 0


def parse_env_file(text: str) -> dict[str, str]:
    """Parse a systemd EnvironmentFile (KEY=VALUE lines, optional quotes)."""
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if name:
            values[name] = value
    return values


def live_stripe_setting_names(values: dict[str, str]) -> list[str]:
    return sorted(
        name
        for name, value in values.items()
        if any(prefix in value for prefix in LIVE_STRIPE_PREFIXES)
    )


def url_host(url: str) -> str:
    return (urlsplit(url.strip()).hostname or "").casefold()


def audit_env_file(
    values: dict[str, str],
    *,
    database_host: str,
    url_file_texts: list[str],
    forbidden_keys: list[str],
) -> Report:
    report = Report()

    live = live_stripe_setting_names(values)
    report.check("no_live_stripe_values", not live, ", ".join(live))
    report.check(
        "stripe_secret_key_is_test_mode",
        values.get("STRIPE_SECRET_KEY", "").startswith(TEST_STRIPE_SECRET_PREFIX),
    )

    filled = sorted(name for name in forbidden_keys if values.get(name, "").strip())
    report.check("disabled_integration_secrets_empty", not filled, ", ".join(filled))

    report.check("app_env_staging", values.get("APP_ENV") == APP_ENV)
    report.check("sentry_environment_staging", values.get("SENTRY_ENVIRONMENT") == SENTRY_ENVIRONMENT)
    for name, expected in COOKIE_NAMES.items():
        report.check(f"cookie_name {name}", values.get(name) == expected)
    report.check("cookie_domain", values.get("JWT_COOKIE_DOMAIN") == COOKIE_DOMAIN)

    expected_host = database_host.strip().casefold()
    hosts = [url_host(values[name]) for name in DATABASE_URL_SETTINGS if values.get(name, "").strip()]
    if values.get("JASPEN_APP_DB_HOST", "").strip():
        hosts.append(values["JASPEN_APP_DB_HOST"].strip().casefold())
    hosts.extend(url_host(text) for text in url_file_texts)
    report.check(
        "database_host_is_staging_fork",
        bool(expected_host) and bool(hosts) and all(host == expected_host for host in hosts),
        f"{len(hosts)} source(s)",
    )
    return report


def run_env_file_mode(args: argparse.Namespace) -> int:
    try:
        values = parse_env_file(Path(args.env_file).read_text(encoding="utf-8"))
        url_texts = [Path(path).read_text(encoding="utf-8") for path in args.url_file]
    except Exception as exc:
        print(f"FAIL staging_env_file_readable ({type(exc).__name__})")
        return 2
    report = audit_env_file(
        values,
        database_host=args.database_host,
        url_file_texts=url_texts,
        forbidden_keys=args.forbidden_keys.split(),
    )
    return report.exit_code


def build_app(backend_dir: Path):
    """Build the application factory exactly as wsgi.py does, without serving."""
    sys.path.insert(0, str(backend_dir))
    # Validate the environment systemd provides, not a stray backend/.env file
    # (the deploy wrapper's preflight refuses a deployment if one exists).
    import dotenv

    dotenv.load_dotenv = lambda *args, **kwargs: False
    from database_secret import load_database_url_secret

    load_database_url_secret()
    import app as app_module

    return app_module, app_module.create_app()


def run_app_mode(args: argparse.Namespace) -> int:
    captured = io.StringIO()
    try:
        # Application start-up logging is discarded so nothing it prints can
        # reach the deploy output.
        with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
            app_module, app = build_app(Path(args.backend_dir).resolve())
    except Exception as exc:
        print(f"FAIL app_factory_builds ({type(exc).__name__})")
        return 2

    report = Report()
    report.check("app_factory_builds", True)
    report.check("app_env_staging", os.getenv("APP_ENV") == APP_ENV)
    report.check("sentry_environment_staging", os.getenv("SENTRY_ENVIRONMENT") == SENTRY_ENVIRONMENT)
    for name, expected in COOKIE_NAMES.items():
        report.check(f"cookie_name {name}", app.config.get(name) == expected)
    report.check("cookie_domain", app.config.get("JWT_COOKIE_DOMAIN") == COOKIE_DOMAIN)
    report.check(
        "cors_origins_staging_only",
        app_module._derive_cors_origins(app.config.get("FRONTEND_BASE_URL")) == CORS_ORIGINS,
    )
    report.check(
        "flask_cors_disabled",
        app_module._should_enable_flask_cors(os.getenv("FRONTEND_BASE_URL")) is False,
    )
    stripe_values = {
        name: str(app.config.get(name) or "")
        for name in ("STRIPE_SECRET_KEY", "STRIPE_PUBLISHABLE_KEY", "STRIPE_WEBHOOK_SECRET")
    }
    live = sorted(set(live_stripe_setting_names(stripe_values)) | set(live_stripe_setting_names(dict(os.environ))))
    report.check("no_live_stripe_values", not live, ", ".join(live))
    return report.exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    modes = parser.add_subparsers(dest="mode", required=True)

    env_parser = modes.add_parser("env-file")
    env_parser.add_argument("--env-file", required=True)
    env_parser.add_argument("--database-host", required=True)
    env_parser.add_argument("--url-file", action="append", default=[])
    env_parser.add_argument("--forbidden-keys", default="")

    app_parser = modes.add_parser("app")
    app_parser.add_argument("--backend-dir", required=True)

    args = parser.parse_args(argv)
    if args.mode == "env-file":
        return run_env_file_mode(args)
    return run_app_mode(args)


if __name__ == "__main__":
    raise SystemExit(main())
