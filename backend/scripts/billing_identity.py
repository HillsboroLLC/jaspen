#!/usr/bin/env python3
"""Operator commands for the modern billing identity family (I1, D18 row 17). Not for production.

Every command refuses a production runtime (``rate_limits.is_production_runtime``)
before it touches the database. Output is canonical JSON on stdout.

  status     read-only: the family switches, the organization's billing model,
             its assignment and billing account, and every legacy-footprint reason
             it could not be assigned (the transaction is always rolled back)
  establish  writes: the onboarding command for a new-model organization (billing
             account, owner role, assignment). Needs --confirm-write and the
             identity family enabled in BILLING_MODERN_FAMILIES.

The database connection uses the same credential path as wsgi.py: the mode-600
URL file named by JASPEN_DATABASE_URL_FILE.

Usage: PYTHONPATH=. python scripts/billing_identity.py <command> [options]
"""

import argparse
import json
import sys


def _emit(value):
    sys.stdout.write(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True, default=str) + "\n")


def _parser():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    status = commands.add_parser("status", help="read-only billing model status of one organization")
    status.add_argument("--organization-id", required=True)
    establish = commands.add_parser("establish", help="establish a new-model organization's billing identity")
    establish.add_argument("--organization-id", required=True)
    establish.add_argument("--actor-user-id", required=True, help="the organization's owner")
    establish.add_argument("--currency", required=True, help="lowercase ISO code, e.g. usd")
    establish.add_argument("--origin-id", required=True, help="the approval or seed reference")
    establish.add_argument("--confirm-write", action="store_true")
    return parser


def run(argv=None, *, app=None):
    """Run one command; returns the process exit code. ``app`` lets tests pass their application."""
    from app.rate_limits import is_production_runtime

    args = _parser().parse_args(argv)
    if is_production_runtime():
        _emit({"error": "refused: billing identity commands never run in a production runtime"})
        return 2
    if args.command == "establish" and not args.confirm_write:
        _emit({"error": "refused: establish writes; pass --confirm-write to proceed"})
        return 2
    if app is None:
        import os
        from database_secret import load_database_url_secret
        if not load_database_url_secret() and not os.environ.get("DATABASE_URL"):
            _emit({"error": "refused: no database URL; set JASPEN_DATABASE_URL_FILE to a mode-600 URL file"})
            return 2
        from app import create_app
        app = create_app()
    from app import db
    from app import billing_cutover as bc
    from app.models import BillingAccount

    with app.app_context():
        session = db.session
        try:
            if args.command == "status":
                config = bc.cutover_config()
                assignment = bc.assignment_for_organization(session, args.organization_id)
                account = session.get(BillingAccount, assignment.billing_account_id) if assignment else None
                _emit({
                    "families_enabled": sorted(config.families), "configuration_errors": list(config.errors),
                    "organization_id": args.organization_id,
                    "billing_model": bc.organization_billing_model(session, args.organization_id),
                    "assignment_id": assignment.id if assignment else None,
                    "billing_account": None if account is None else {
                        "id": account.id, "status": account.status, "currency": account.currency,
                        "processor_bound": account.processor_customer_id is not None},
                    "footprint": [] if assignment else bc.legacy_billing_footprint(session, args.organization_id),
                })
                session.rollback()
            else:
                assignment, state = bc.establish_modern_billing_identity(
                    session, organization_id=args.organization_id, actor_user_id=args.actor_user_id,
                    currency=args.currency, origin_type="operator_command", origin_id=args.origin_id)
                session.commit()
                _emit({"state": state, "assignment_id": assignment.id,
                       "billing_account_id": assignment.billing_account_id,
                       "organization_id": assignment.organization_id})
        except bc.BillingCutoverError as exc:
            session.rollback()
            _emit({"error": str(exc), "codes": list(getattr(exc, "codes", ()))})
            return 3
    return 0


if __name__ == "__main__":
    sys.exit(run())
