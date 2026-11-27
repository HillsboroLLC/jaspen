#!/usr/bin/env python3
"""Operator commands for the reliable-delivery worker (I3, Phase 12 gate). Not for production.

Every command refuses a production runtime (``rate_limits.is_production_runtime``)
and refuses unless the ``ai_reservation`` family is enabled in
``BILLING_MODERN_FAMILIES``, before it touches the database. Output is
canonical JSON on stdout.

  recover  one bounded recovery round: settle saved responses, expire lapsed
           leases, close abandoned jobs. Exit 3 when any row is blocked (alert).
  run      the worker loop: claim and run jobs whose executor is registered (from
           --executor-module), and run recovery every --recover-every seconds.
           --once runs one pass of each and exits. SIGTERM/SIGINT stop claiming
           new jobs and let running ones finish.

Running this as a service is a separate infrastructure approval; there is no
service unit. The database connection uses the same credential path as wsgi.py:
the mode-600 URL file named by JASPEN_DATABASE_URL_FILE.

Exit codes: 0 done, 1 systemic error (recovery stopped), 2 refused, 3 blocked rows.

Usage: PYTHONPATH=. python scripts/billing_delivery_worker.py <command> [options]
"""

import argparse
import importlib
import json
import signal
import sys
import threading


def _emit(value):
    sys.stdout.write(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True, default=str) + "\n")
    sys.stdout.flush()


def _parser():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    recover = commands.add_parser("recover", help="one bounded recovery round")
    recover.add_argument("--limit", type=int, default=100)
    recover.add_argument("--scan-limit", type=int, default=1000)
    run = commands.add_parser("run", help="the worker loop")
    run.add_argument("--executor-module", action="append", default=[],
                     help="a module that registers executors on import (repeatable)")
    run.add_argument("--concurrency", type=int, default=2)
    run.add_argument("--idle-seconds", type=float, default=0.5)
    run.add_argument("--recover-every", type=float, default=30.0)
    run.add_argument("--limit", type=int, default=100)
    run.add_argument("--scan-limit", type=int, default=1000)
    run.add_argument("--once", action="store_true")
    return parser


def _summary(report):
    return {
        "jobs_settled": len(report["jobs_settled"]), "jobs_closed": len(report["jobs_closed"]),
        "settled": len(report["settled"]), "expired": len(report["expired"]),
        "blocked": report["blocked"],
    }


def _recover(worker, args):
    from app.billing_reliable_delivery import RecoverySystemicError
    try:
        report = worker.recover(limit=args.limit, scan_limit=args.scan_limit)
    except RecoverySystemicError as exc:
        _emit({"error": "recovery stopped: systemic error", "reason": str(exc)})
        return 1, None
    except Exception as exc:  # a database or connection failure is systemic, never a per-row block
        _emit({"error": "recovery stopped: systemic error", "reason": type(exc).__name__})
        return 1, None
    _emit({"recovery": _summary(report)})
    return (3 if report["blocked"] else 0), report


def _run(worker, args):
    from app import billing_delivery_worker as bdw

    for name in args.executor_module:
        importlib.import_module(name)
    if not bdw.registered_executors():
        _emit({"warning": "no executor registered; only recovery runs"})
    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_args: stop.set())
    results = {"jobs": 0}
    lock = threading.Lock()

    def loop():
        while not stop.is_set():
            outcomes = worker.run_once()
            with lock:
                results["jobs"] += len(outcomes)
            if args.once:
                return
            if not outcomes:
                stop.wait(args.idle_seconds)

    threads = [threading.Thread(target=loop, name=f"delivery-runner-{index}", daemon=True)
               for index in range(max(1, args.concurrency))] if bdw.registered_executors() else []
    for thread in threads:
        thread.start()
    code = 0
    while True:
        code, _report = _recover(worker, args)
        if code == 1 or args.once or stop.wait(args.recover_every):
            break
    stop.set()
    for thread in threads:
        thread.join()
    _emit({"jobs_run": results["jobs"]})
    return code


def run(argv=None, *, app=None, session_factory=None):
    """Run one command; returns the process exit code. Tests pass their application and sessions."""
    from app.rate_limits import is_production_runtime

    args = _parser().parse_args(argv)
    if is_production_runtime():
        _emit({"error": "refused: the delivery worker never runs in a production runtime"})
        return 2
    from app import billing_cutover as bc
    if not bc.cutover_config().enabled("ai_reservation"):
        _emit({"error": "refused: the ai_reservation billing family is not enabled"})
        return 2
    if app is None:
        import os
        from database_secret import load_database_url_secret
        if not load_database_url_secret() and not os.environ.get("DATABASE_URL"):
            _emit({"error": "refused: no database URL; set JASPEN_DATABASE_URL_FILE to a mode-600 URL file"})
            return 2
        from app import create_app
        app = create_app()
    from app import billing_delivery_worker as bdw

    with app.app_context():
        worker = bdw.DeliveryWorker(session_factory, app=app)  # None: each step on its app context's db.session
        if args.command == "recover":
            return _recover(worker, args)[0]
        return _run(worker, args)


if __name__ == "__main__":
    sys.exit(run())
