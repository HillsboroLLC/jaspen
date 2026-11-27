#!/usr/bin/env python3
"""Install staging-only TEST pricing and capacity policies for Phase 12 (founder decisions D2/D3). Not for production.

  install --rules-file <json> --approval-reference <ref> --confirm-write

The rules file holds every number (capacity has no defaults; pricing rates
default to the repository rate tables). Both versions are labeled staging-test.
The command refuses a production runtime. Output is canonical JSON on stdout.
The database connection uses the same credential path as wsgi.py.

Usage: PYTHONPATH=. python scripts/billing_policies.py install [options]
"""

import argparse
import json
import sys


def _emit(value):
    sys.stdout.write(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True, default=str) + "\n")


def _parser():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    install = commands.add_parser("install", help="install the staging test pricing and capacity versions")
    install.add_argument("--rules-file", required=True)
    install.add_argument("--approval-reference", required=True)
    install.add_argument("--confirm-write", action="store_true")
    return parser


def run(argv=None, *, app=None):
    from app.rate_limits import is_production_runtime

    args = _parser().parse_args(argv)
    if is_production_runtime():
        _emit({"error": "refused: staging test policies never install in a production runtime"})
        return 2
    if not args.confirm_write:
        _emit({"error": "refused: install writes policy versions; pass --confirm-write to proceed"})
        return 2
    with open(args.rules_file, encoding="utf-8") as handle:
        rules = json.load(handle)
    if app is None:
        import os
        from database_secret import load_database_url_secret
        if not load_database_url_secret() and not os.environ.get("DATABASE_URL"):
            _emit({"error": "refused: no database URL; set JASPEN_DATABASE_URL_FILE to a mode-600 URL file"})
            return 2
        from app import create_app
        app = create_app()
    from app import db
    from app.billing_ai_operations import CapacityPolicyRequiredError
    from app.billing_runtime_policies import PolicyInstallError, install_test_policies

    with app.app_context():
        try:
            result = install_test_policies(db.session, rules=rules, approval_reference=args.approval_reference)
            db.session.commit()
        except (PolicyInstallError, CapacityPolicyRequiredError) as exc:
            db.session.rollback()
            _emit({"error": str(exc)})
            return 3
    _emit({kind: {"version": name, "state": state} for kind, (name, state) in result.items()})
    return 0


if __name__ == "__main__":
    sys.exit(run())
