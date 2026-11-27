# Reliable-delivery worker: the interface for AI turns (I3 → I4)

Status: **I3 interface, inactive.** This is the contract the AI-reservation
family runtime (I4, `app/billing_runtime_ai.py`) uses to run a Phase 12-bound
chat turn through the durable worker in `app/billing_delivery_worker.py`. It
closes Phase 12 activation-gate criteria 1, 3 and 5 when the journeys below pass
and the increment is independently accepted. Nothing here enables charging:
every call path starts from a turn that I4 has already routed to a modern
organization with the `ai_reservation` family on (OD-1 Option C).

Authorities are unchanged. Phase 3 is the only balance authority. Phase 12 is
the only authority for authorization, lease renewal, call usage, settlement,
absorption and expiry. Phase 17 (`billing_reliable_delivery.py`) is the only
boundary the worker calls, and the only caller of `settle_delivered_operation`.

## 1. Moving parts

| Part | Owner | Durable state |
|---|---|---|
| Delivery job: one per Phase 12 operation | I3 | `ai_delivery_jobs` (new): identity copy, executor name, request payload and digest, state, job lease (owner, token, expiry), claim count, attempts started, cancel request, timing, outcome |
| Streamed output | I3 | `ai_delivery_stream_chunks` (new, append-only): `(operation_id, attempt_number, seq)` → text |
| Saved response | Phase 17 | `ai_operations.result_json.reliable_delivery` envelope (unchanged) |
| Financial outcome | Phase 12 | `ai_billing_operations`, ledger, absorbed usage (unchanged) |
| Provider work | **I4** | An *executor*: a function registered by name that makes the provider calls (with tools and fallback) through the context the worker gives it |

## 2. How a chat turn hands its provider work to the worker

In the request, inside one transaction, after I4 has routed the turn
(`modern_context(..., family="ai_reservation")`) and authorized it:

```python
from app import billing_delivery_worker as worker

auth = authorize_ai_operation(session, operation_id=op_id, actor_user_id=user_id, ...)   # Phase 12
if auth.outcome != "authorized":
    ...  # capacity_denied / credit_exhausted: nothing was reserved; I4 answers as today
try:
    job = worker.submit_delivery(
        session,
        operation_id=op_id, organization_id=org_id, actor_user_id=user_id,
        executor="chat_turn",               # registered by I4
        payload={...},                      # JSON: everything the executor needs to (re)run the turn
        provider_timeout_seconds=...,       # the HTTP timeout the executor will pass to the provider client
        heartbeat_interval_seconds=...,     # optional; default from the worker settings
    )
except worker.DeliveryTimingError:
    worker.release_unsubmitted_operation(session, operation_id=op_id,
                                         organization_id=org_id, actor_user_id=user_id)
    raise
session.commit()                            # the job is durable before any provider call
worker.start_in_process(op_id)              # optional fast start; see §5
return stream_response(op_id)               # §3
```

`submit_delivery`:

- fails closed before any write unless the bound capacity version's
  `reservation_lease_seconds` > `provider_timeout_seconds` +
  `heartbeat_interval_seconds` (criterion 3), the operation is Phase 12-bound
  and `authorized`, and the identity matches the durable binding;
- is idempotent: the same operation and the same payload digest return the same
  job; a different payload for the same operation is refused;
- refuses a payload above `MAX_PAYLOAD_BYTES` (8 MB of canonical JSON: chat
  history plus attachment references) before any write;
- writes only the job row. It never calls a provider.

**The executor (I4 writes it).** Register once at import time:

```python
@worker.executor("chat_turn")
def run_chat_turn(ctx: worker.DeliveryContext) -> worker.DeliveryResult:
    attempt = ctx.begin_attempt()                       # durable attempt number; refuses if this worker lost its lease
    ctx.check_call(attempt_number=attempt, call_index=0, provider=p, model=m,
                   max_input_tokens=..., max_output_tokens=...)     # Phase 12 runaway/lapse check
    started = ctx.now()
    for text in provider.stream(..., timeout=ctx.provider_timeout_seconds):
        if ctx.should_stop():                           # cancel requested, lease lost, or response already saved
            break
        ctx.emit(attempt, text)                         # buffered, persisted for the browser
    ctx.record_call(attempt_number=attempt, call_index=0, component="primary", provider=p, model=m,
                    outcome="succeeded", usage_label="reported", input_tokens=..., output_tokens=...,
                    requested_at=started, finished_at=ctx.now(), provider_request_id=...,
                    duration_ms=..., status_code=200)
    return worker.DeliveryResult(delivered_attempt_number=attempt,
                                 response={...},        # the saved response the customer can recover
                                 on_persist=save_chat_message)   # optional, see below
```

Executor rules:

- Every provider request is preceded by `ctx.check_call` and followed by
  `ctx.record_call`, whatever its outcome (timeout, refusal, error,
  cancellation). `record_call` records the Phase 12 call usage and appends the
  Phase 17 operational attempt in one committed transaction.
- Fallback and retries are new attempts (`ctx.begin_attempt()` again). Tool
  iterations are new `call_index` values in the same attempt. One operation is
  one user-visible turn.
- The executor passes `ctx.provider_timeout_seconds` to the provider client. It
  must not block longer than that per request.
- Return values: `DeliveryResult` (a response to save and settle),
  `worker.NoBillableUsage()` (no provider usage happened, for example the
  executor refused before calling), or raise `worker.DeliveryFailed(code)`
  (no usable response; operational code only, no customer wording).
- `ctx.should_stop()` is true after a cancellation, after this worker lost its
  job lease, or once another worker saved the response. The executor stops at
  the next safe point, records the call it was in, and returns or raises.
- The executor runs with the Flask app context pushed (`current_app` is
  available). `ctx.operation_id`, `ctx.organization_id`, `ctx.actor_user_id` and
  `ctx.payload` identify the turn.
- `on_persist(session, response)` runs **inside the transaction that saves the
  envelope**, exactly once (never on a replay). In the runtime mode
  (`DeliveryWorker(app=...)`, which `start_in_process` and the CLI use) that
  `session` is the step's own app context's Flask-SQLAlchemy `db.session`, so the
  conversation store can write through `db.session`; the store write, the
  envelope and the job state commit or roll back together. The heartbeat always
  uses a separate session on its own connection. I4 uses it to write the
  assistant message into the conversation store, so the visible history and the
  saved response commit together. It must not commit and must not call a
  provider. If it raises, nothing is saved, and the worker retries persistence
  (bounded) and then closes the operation undelivered.
- The executor never touches billing tables, never calls Phase 12 directly and
  never settles. Settlement is the worker's job (M2, §6).

## 3. How the route streams persisted output to the browser

The route never runs the provider. It polls durable state:

```python
def stream_response(op_id):
    @stream_with_context
    def events():
        cursor = None
        while True:
            view = worker.read_delivery(session, operation_id=op_id, organization_id=org_id,
                                        actor_user_id=user_id, after=cursor)
            for chunk in view.chunks:                    # in order; chunk.restart = a new attempt began
                yield sse(chunk)
            cursor = view.cursor
            if view.response is not None or view.finished:
                yield sse_final(view)                    # saved response (authoritative) or outcome
                return
            session.rollback()                           # end the read snapshot; holds no locks
            time.sleep(worker.STREAM_POLL_SECONDS)
    return Response(events(), mimetype="text/event-stream", headers=...)
```

- `read_delivery` is a pure read. Once Phase 12 records an outcome it also
  carries `billing_state`, `delivery_status`, `charged_credits` and
  `absorbed_credits`; `delivery_outcome(...)` returns the same facts without
  chunks, for JSON and governed operations. It checks the durable organization and an
  **active** membership of the actor (criterion 8), returns the chunks after the
  cursor, the job state, the saved response once persisted (integrity-checked),
  and the final outcome.
- **Disconnect:** when the browser goes away, the generator stops
  (`GeneratorExit`). The route does nothing else: no cancel, no settle, no
  release. The worker keeps going. The customer recovers the saved response
  later with `worker.read_delivery(...)` (or `recover_persisted_response`),
  with or without settlement.
- **Cancel** (the customer's stop button) is a separate request:
  `worker.request_cancellation(session, operation_id=..., organization_id=...,
  actor_user_id=...)`; commit. It is not a disconnect.
- Chunks are display progress, not the result. When an attempt restarts (a
  fallback, or a recovery worker after a crash), its first chunk has
  `restart=True` and the client clears partial text. The saved response always
  replaces the streamed text.

## 4. Heartbeat: reservation renewal independent of the provider call

While a worker holds a job, a **separate heartbeat thread with its own database
session** runs every `heartbeat_interval_seconds`. Each tick is one short
transaction that:

1. renews the job lease by compare-and-set on the lease token (a lost token
   means another worker owns the job: this worker stops, `should_stop()` is
   true, and it records only the call it was in);
2. calls `heartbeat_reliable_delivery` → Phase 12 `renew_ai_operation_reservation`.

The provider call runs on the worker thread and never blocks the heartbeat.
Phase 12 caps renewal at the execution deadline plus one lease period and never
revives a lapsed lease. If the reservation lapses (for example the deadline
cap), the heartbeat stops renewing it and the turn continues: a response that
still arrives is saved and recorded as delivered with no charge (founder
decision 2026-11-17). The job lease is shorter than the reservation lease, so a
dead worker's job is reclaimed while its reservation is still live.

## 5. Running the worker

- `worker.DeliveryWorker(session_factory, owner=...)`: `run_job(op_id)` claims
  one job and runs it to an outcome; `run_once()` claims and runs the next
  available jobs; `recover()` runs one bounded recovery sweep (§7).
- `scripts/billing_delivery_worker.py run|recover`: the standalone worker. It
  refuses a production runtime and refuses to run unless `ai_reservation` is
  enabled. No systemd unit: running it as a service is a later infrastructure
  approval.
- `worker.start_in_process(op_id)` (optional for I4) runs `run_job` on a daemon
  thread in the web process for low latency. It is the same claim and lease, so
  it is never a second runner of the same job. If the web process dies, the job
  lease lapses and any worker (the CLI, or another process's `run_once`)
  reclaims it. **Without a running standalone worker, recovery happens only when
  something calls `run_once()`/`recover()`**; that is the infrastructure
  decision above. Note D1: a Gunicorn worker timeout kills in-process threads
  with the request worker, so in-process mode is a latency option, not the
  reliability guarantee.

## 6. Commit persistence before settlement (M2)

The worker's sequence for a `DeliveryResult`:

1. **Persist** (one transaction, committed): `persist_successful_response`
   (envelope: response, SHA-256, delivered attempt, request id), `on_persist`,
   job state `persisted`. First save wins; a different response for the same
   operation is a conflict, and the worker then settles the saved one.
2. **Settle** (a later transaction): `settle_persisted_response` only, retried
   with bounded backoff on transient errors; then job state `finished` with the
   Phase 12 outcome. If settlement still fails, the job stays `persisted` and
   recovery settles it (criterion 4).

Guard (M2): the AI runtime settles only through `settle_persisted_response`.
- **Static:** a test scans `app/` and `scripts/`; only
  `billing_reliable_delivery.py` may name `settle_delivered_operation`
  (`billing_ai_operations.py` defines it).
- **Database:** for an operation that has a delivery job, Phase 12 may record
  `delivered` only if the operation's envelope exists and names the same
  delivered attempt (trigger on `ai_billing_operations`, PostgreSQL and SQLite).
  Operations without a job (Phase 12's own tests) are unaffected.

## 7. Failure and recovery semantics

| Situation | What happens | Charge |
|---|---|---|
| Browser disconnects | Nothing; the worker continues and saves the response | Delivered response settled once |
| Customer cancels before any provider call | `release_without_billable_usage`; outcome `no_billable_usage` | 0 |
| Customer cancels during a call | The executor stops; the call is recorded; outcome `undelivered` unless a response was already saved | 0, usage absorbed |
| Cancel after the response is saved | No effect: the response was delivered | Settled once |
| Provider error or timeout, no fallback left | `record_undelivered_operation` | 0, usage absorbed |
| Fallback delivers | Only the delivering attempt is settled; others absorbed (Phase 12) | Delivering attempt only |
| Worker dies before saving | Job lease lapses; another worker reclaims, records the abandoned attempt as a failed call with `unknown` usage (absorbed), and runs a new attempt if the reservation is live and the claim and attempt bounds allow; otherwise closes undelivered | 0 for the lost attempt |
| Worker dies after saving, before settling | Recovery settles the saved response (job fast path, then the Phase 12 sweep as backstop) | Settled once |
| Response arrives after the reservation lapsed | Saved and recorded `delivered` | 0 (absorbed) |
| Two workers race (lost lease, reclaim) | First save wins; the other conflicts and settles the saved one; each attempt's usage is recorded | Delivering attempt only, once |
| Settlement replay, worker restart, repeated sweeps | Phase 12 idempotency and the envelope's recorded outcome | No duplicate |
| Malformed row (identity disagrees) | Recovery reports it `blocked` and backs it off; other rows continue | 0; hold stays (fail closed) |
| Systemic error (wrong isolation level, lost connection) | Recovery stops at once and reports it; the CLI exits non-zero (O1/O2) | No effect |

**Bounded recovery sweep** (fixes the remaining B2 starvation and O1/O2):
- each sweep scans at most `scan_limit` candidate rows and acts on at most
  `limit`; a durable cursor per pass makes successive sweeps continue where the
  last stopped and wrap around, so no row is starved by rows ahead of it,
  including permanently blocked ones;
- systemic errors (`AIBillingIsolationLevelError`, connection and operational
  database errors) abort the sweep and are reported, never recorded as
  per-row blocks; row errors (identity, state, conflict, guard integrity) are
  isolated in a savepoint and reported as `blocked`;
- the job fast path settles `persisted` jobs and reclaims jobs with lapsed job
  leases before the Phase 12 sweep runs.

**Not resumable.** An executor that cannot rebuild the turn (I4's in-memory
closure is missing after a reclaim) raises `DeliveryFailed("not_resumable")`.
The reclaiming worker has already recorded the lost call (unknown usage,
absorbed); the operation closes undelivered with no charge, and the job is
finished, so it is never claimed again. Any executor failure closes the job the
same way; only a worker that dies is reclaimed, at most `max_claims` times.

## 8. What I4 must not do

- Call a provider in the request thread for a modern turn.
- Call `settle_delivered_operation`, `record_undelivered_operation` or
  `expire_ai_operation` directly for a worker-managed operation.
- Cancel, release or settle on a client disconnect.
- Write canned chat wording on the worker's behalf. The worker returns
  operational codes only.
- Reassign or clear `ai_operations.result_json`, or change its identity columns
  (`organization_id`, `user_id`, `billing_account_id`), on a Phase 12-bound
  operation. Other keys may be merged alongside `reliable_delivery`. The M3
  database guard refuses the legacy whole-column writes (`ai_audit.py`
  `persist_operation`, `ai_runtime.py` clearing the result) for bound operations.

## 9. Open items for the coordinator

- **M3** is implemented in migration `d7e9b1c3a5f8`: a bound operation's identity
  is never rewritten to another value, and its saved envelope is immutable except
  that `settlement` is recorded once.
- A cancelled turn whose partial text was already streamed is `undelivered`
  with no charge (coordinator: follows the approved Nov 11 billability policy).
- Running the standalone worker as a service on staging (infrastructure
  approval) and D1.
