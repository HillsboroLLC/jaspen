#!/usr/bin/env python3
"""Operator commands for the billing migration evidence run (BI-1). Not for production.

Every command refuses a production runtime (``rate_limits.is_production_runtime``)
before it touches the database, and the underlying Phase 14-16 commands keep all
of their own guards. Output is canonical JSON on stdout.

Read-only (the transaction is always rolled back):

  operation-review       every unclosed legacy AI operation, its Phase 14 class,
                         whether it blocks, and for each one needing a decision
                         the evidence and a recommended disposition (never applied)
  preconditions          the Phase 15 start checks for --environment
  shadow                 the Phase 16 shadow comparison (its own read-only
                         transaction; restore_copy stays refused until an approved
                         restore-copy authorization mechanism exists)

Writes (each needs --confirm-write; nothing is written without it):

  record-operation-decision   one reviewer's decision, or a correction with
                              --supersedes-decision-id (append-only)
  rehearse                    one Phase 15 rehearsal run (Phase 14 commands)

The operation age limit comes only from BILLING_MIGRATION_MAX_TURN_SECONDS.
Unset, every unclosed operation blocks and no decision can be recorded.

Usage: PYTHONPATH=. python scripts/billing_migration_evidence.py <command> [options]
"""

import argparse
import json
import sys


def _emit(value):
    sys.stdout.write(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True, default=str) + "\n")


def _json_file(path):
    if path is None:
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _parser():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("operation-review", help="read-only review of unclosed legacy operations")

    pre = commands.add_parser("preconditions", help="read-only Phase 15 start checks")
    pre.add_argument("--environment", required=True, choices=("fixtures", "restore_copy"))
    pre.add_argument("--runtime-role")
    pre.add_argument("--writer-freeze-reference")

    decide = commands.add_parser("record-operation-decision", help="record one reviewed decision (writes)")
    decide.add_argument("--decision-command-id", required=True)
    decide.add_argument("--operation-id", required=True)
    decide.add_argument("--disposition", required=True, choices=("no_compensation_owed", "compensation_owed"))
    decide.add_argument("--evidence-reference", required=True)
    decide.add_argument("--reason", required=True)
    decide.add_argument("--reviewer-user-id", required=True)
    decide.add_argument("--amount", type=int)
    decide.add_argument("--beneficiary-billing-account-id")
    decide.add_argument("--supersedes-decision-id")
    decide.add_argument("--confirm-write", action="store_true")

    rehearse = commands.add_parser("rehearse", help="one Phase 15 rehearsal run (writes Phase 14 evidence)")
    rehearse.add_argument("--run-key", required=True)
    rehearse.add_argument("--authorization-reference", required=True)
    rehearse.add_argument("--operator-user-id", required=True)
    rehearse.add_argument("--organization-id", action="append", required=True, dest="organization_ids")
    rehearse.add_argument("--environment", required=True, choices=("fixtures", "restore_copy"))
    rehearse.add_argument("--test-activity-attestation-file",
                          help='JSON {"reference": ..., "payer_user_ids": [...]} (a founder attestation)')
    rehearse.add_argument("--runtime-role")
    rehearse.add_argument("--writer-freeze-reference")
    rehearse.add_argument("--confirm-write", action="store_true")

    shadow = commands.add_parser("shadow", help="read-only Phase 16 shadow comparison")
    shadow.add_argument("--organization-id", action="append", required=True, dest="organization_ids")
    shadow.add_argument("--environment", required=True, choices=("fixtures", "restore_copy"))
    shadow.add_argument("--test-activity-attestation-file")
    return parser


WRITE_COMMANDS = frozenset({"record-operation-decision", "rehearse"})


def run(argv=None, *, app=None):
    """Run one command; returns the process exit code. ``app`` lets tests pass their application."""
    from app.rate_limits import is_production_runtime

    args = _parser().parse_args(argv)
    if is_production_runtime():
        _emit({"error": "refused: billing migration evidence commands never run in a production runtime"})
        return 2
    if args.command in WRITE_COMMANDS and not args.confirm_write:
        _emit({"error": f"refused: {args.command} writes evidence; pass --confirm-write to proceed"})
        return 2
    if app is None:
        from app import create_app
        app = create_app()
    from app import db
    from app.billing_migration import MigrationError, record_operation_decision, unclosed_operation_review
    from app.billing_rehearsal import rehearsal_preconditions, run_rehearsal
    from app.billing_shadow import export_shadow_report, run_shadow_reconciliation

    with app.app_context():
        session = db.session
        try:
            if args.command == "operation-review":
                _emit(unclosed_operation_review(session))
                session.rollback()
            elif args.command == "preconditions":
                _emit(rehearsal_preconditions(session, environment=args.environment, runtime_role=args.runtime_role,
                                              writer_freeze_reference=args.writer_freeze_reference))
                session.rollback()
            elif args.command == "record-operation-decision":
                decision, state = record_operation_decision(
                    session, decision_command_id=args.decision_command_id, ai_operation_id=args.operation_id,
                    disposition=args.disposition, evidence_reference=args.evidence_reference, reason=args.reason,
                    reviewer_user_id=args.reviewer_user_id, amount=args.amount,
                    beneficiary_billing_account_id=args.beneficiary_billing_account_id,
                    supersedes_decision_id=args.supersedes_decision_id)
                session.commit()
                _emit({"state": state, "decision_id": decision.id, "disposition": decision.disposition,
                       "operation_id": decision.ai_operation_id,
                       "supersedes_decision_id": decision.supersedes_decision_id})
            elif args.command == "rehearse":
                _emit(run_rehearsal(
                    session, run_key=args.run_key, authorization_reference=args.authorization_reference,
                    operator_user_id=args.operator_user_id, organization_ids=args.organization_ids,
                    environment=args.environment,
                    test_activity_attestation=_json_file(args.test_activity_attestation_file),
                    runtime_role=args.runtime_role, writer_freeze_reference=args.writer_freeze_reference))
            elif args.command == "shadow":
                result = run_shadow_reconciliation(
                    organization_ids=args.organization_ids, environment=args.environment,
                    test_activity_attestation=_json_file(args.test_activity_attestation_file))
                sys.stdout.write(export_shadow_report(result) + "\n")
        except MigrationError as exc:
            session.rollback()
            _emit({"error": str(exc), "type": type(exc).__name__})
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(run())
