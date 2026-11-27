#!/usr/bin/env python3
"""Operator commands for the modern financial-event and credit-funding families (I2, D18 row 17). Not for production.

Every command refuses a production runtime (``rate_limits.is_production_runtime``)
before it touches the database. Every command writes, so each needs --confirm-write.
Output is canonical JSON on stdout.

  define-test-catalog  D2: record the staging test-pricing entitlement definitions,
                       copied from the configured catalog (credit_funding family)
  allocate-free        D4: open each modern organization's current monthly Free lot
                       from its account anchor (credit_funding family)
  allocate-annual      open the current monthly release of each modern paid annual
                       term from its paid line, and re-apply open disputes to new lots
                       (credit_funding family)
  process              claim and apply recorded processor events from the inbox, in a
                       bounded batch (financial_events family; funding steps also need
                       credit_funding)

The database connection uses the same credential path as wsgi.py: the mode-600
URL file named by JASPEN_DATABASE_URL_FILE.

Usage: PYTHONPATH=. python scripts/billing_events.py <command> [options] --confirm-write
"""

import argparse
from datetime import datetime
import json
import sys

MAX_BATCH = 500


def _emit(value):
    sys.stdout.write(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True, default=str) + "\n")


def _parser():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    catalog = commands.add_parser("define-test-catalog", help="record the D2 staging test catalog")
    catalog.add_argument("--approver-user-id", required=True, help="the approving user (staging admin)")
    catalog.add_argument("--effective-at", help="ISO-8601 UTC time the definitions take effect (default: now)")
    catalog.add_argument("--confirm-write", action="store_true")
    free = commands.add_parser("allocate-free", help="open each modern organization's monthly Free lot")
    free.add_argument("--organization-id", help="only this organization")
    free.add_argument("--confirm-write", action="store_true")
    annual = commands.add_parser("allocate-annual", help="open the current monthly release of each annual term")
    annual.add_argument("--organization-id", help="only this organization")
    annual.add_argument("--confirm-write", action="store_true")
    process = commands.add_parser("process", help="apply a bounded batch of inbox events")
    process.add_argument("--limit", type=int, default=50, help=f"events to claim (1-{MAX_BATCH})")
    process.add_argument("--confirm-write", action="store_true")
    return parser


def _effective_at(value):
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("--effective-at must include a UTC offset")
    return parsed


def run(argv=None, *, app=None):
    """Run one command; returns the process exit code. ``app`` lets tests pass their application."""
    from app.rate_limits import is_production_runtime

    args = _parser().parse_args(argv)
    if is_production_runtime():
        _emit({"error": "refused: billing event commands never run in a production runtime"})
        return 2
    if not args.confirm_write:
        _emit({"error": f"refused: {args.command} writes; pass --confirm-write to proceed"})
        return 2
    if args.command == "process" and not 1 <= args.limit <= MAX_BATCH:
        _emit({"error": f"refused: --limit must be between 1 and {MAX_BATCH}"})
        return 2
    if app is None:
        import os
        from database_secret import load_database_url_secret
        if not load_database_url_secret() and not os.environ.get("DATABASE_URL"):
            _emit({"error": "refused: no database URL; set JASPEN_DATABASE_URL_FILE to a mode-600 URL file"})
            return 2
        from app import create_app
        app = create_app()
    from flask import current_app
    from app import db
    from app import billing_cutover as bc
    from app import billing_runtime_funding as funding

    with app.app_context():
        session = db.session
        try:
            if args.command == "define-test-catalog":
                results = funding.define_test_catalog(
                    session, approver_user_id=args.approver_user_id, app_config=current_app.config,
                    effective_at=_effective_at(args.effective_at))
                session.commit()
                _emit({"definitions": [{"key": k, "version": v, "state": s} for k, v, s in results]})
            elif args.command in ("allocate-free", "allocate-annual"):
                funding.require_family()
                contexts = funding.modern_contexts(session)
                if args.organization_id:
                    contexts = [c for c in contexts if c.organization_id == args.organization_id]
                session.rollback()
                outcomes = []
                for context in contexts:
                    try:
                        result = (funding.allocate_free if args.command == "allocate-free"
                                  else funding.allocate_annual_release)(session, context)
                        session.commit()
                        outcomes.append(result.__dict__)
                    except funding.FundingRuntimeError as exc:
                        session.rollback()
                        outcomes.append({"organization_id": context.organization_id, "outcome": "error",
                                         "error": str(exc)})
                _emit({"organizations": outcomes})
                if any(o["outcome"] == "error" for o in outcomes):
                    return 1
            else:
                from app import billing_runtime_financial as financial
                summary = financial.process_events(session, limit=args.limit)
                _emit(summary)
        except (bc.BillingCutoverError, funding.FundingRuntimeError, ValueError) as exc:
            session.rollback()
            _emit({"error": str(exc), "codes": list(getattr(exc, "codes", ()))})
            return 3
    return 0


if __name__ == "__main__":
    sys.exit(run())
