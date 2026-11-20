"""Persistence helpers for versioned AI routing and cost telemetry."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from flask import current_app
from sqlalchemy import event
from sqlalchemy.orm import Session

from . import db
from .ai_governance import (
    CREDIT_POLICY_VERSION,
    ROUTER_VERSION,
    credit_policy_mode,
    credits_for_provider_cost,
    router_mode,
)
from .billing_config import provider_cost_usd, to_public_plan
from .models import AIOperation, AIProviderAttempt
from .prompt_version import PROMPT_VERSION_HISTORY_KEY, PROMPT_VERSION_KEY, prompt_version


def new_operation_id():
    return str(uuid.uuid4())


def attach_governance(usage, *, decision, legacy_routes=None, operation_type=None):
    payload = dict(usage) if isinstance(usage, dict) else {}
    operation_id = str(payload.get('operation_id') or new_operation_id())
    payload['operation_id'] = operation_id
    payload['operation_type'] = str(operation_type or payload.get('operation_type') or 'ai_operation')
    payload['governance'] = {
        'router_mode': router_mode(current_app.config),
        'router_version': ROUTER_VERSION,
        'policy_mode': credit_policy_mode(current_app.config),
        'policy_version': CREDIT_POLICY_VERSION,
        'route_class': (decision or {}).get('route_class'),
        'routing_reasons': list((decision or {}).get('routing_reasons') or []),
        'selected_provider': (decision or {}).get('selected_provider'),
        'selected_model': (decision or {}).get('selected_model'),
        'escalated': bool((decision or {}).get('escalated')),
        'legacy_routes': list(legacy_routes or []),
    }
    return payload


def usage_is_billable_success(usage):
    usage = usage if isinstance(usage, dict) else {}
    return bool(not usage.get('degraded') or usage.get('billable_action_completed'))


def projected_charge_for_usage(usage):
    usage = usage if isinstance(usage, dict) else {}
    cost = _successful_provider_cost(usage) if usage_is_billable_success(usage) else 0.0
    return credits_for_provider_cost(cost, internal=True), cost


def _successful_provider_cost(usage):
    usage = usage if isinstance(usage, dict) else {}
    components = [
        item for item in (usage.get('component_usages') or []) if isinstance(item, dict)
    ]
    if components:
        return sum(
            provider_cost_usd(item.get('model'), item.get('input_tokens'), item.get('output_tokens'))
            for item in components
        )
    return provider_cost_usd(
        usage.get('model'),
        usage.get('input_tokens'),
        usage.get('output_tokens'),
    )


def _is_test_user(user):
    email = str(getattr(user, 'email', '') or '').strip().lower()
    return bool(
        current_app.config.get('TESTING')
        or email.endswith('@jaspen.local')
        or email.endswith('@example.com')
    )


def subsidy_classification(user, *, explicit=None, customer_visible=True):
    """Return the auditable reason Jaspen, rather than revenue, funds usage."""
    requested = str(explicit or '').strip().lower()
    allowed = {
        'free', 'test', 'admin', 'promotional', 'fully_comped',
        'internal', 'public_intake',
    }
    if requested:
        if requested not in allowed:
            raise ValueError(f'Unsupported subsidy classification: {requested}')
        return requested
    if not customer_visible:
        return 'internal'
    if user is None:
        return 'public_intake'
    if _is_test_user(user):
        return 'test'
    from .admin_policy import is_global_admin
    if is_global_admin(user, app_config=current_app.config):
        return 'admin'
    plan_key = to_public_plan(getattr(user, 'subscription_plan', None))
    if plan_key == 'free':
        return 'free'
    from .models import Payment, PersistentCreditGrant
    comped_payment = Payment.query.filter_by(user_id=str(user.id), is_comped=True).first()
    if comped_payment is not None:
        return 'fully_comped'
    promotional_grant = PersistentCreditGrant.query.filter(
        PersistentCreditGrant.user_id == str(user.id),
        PersistentCreditGrant.status == 'active',
        PersistentCreditGrant.remaining_amount > 0,
        PersistentCreditGrant.source == '300k_limited_time',
    ).first()
    if promotional_grant is not None:
        return 'promotional'
    return None


def _attempt_cost(item):
    raw = item.get('raw_provider_cost_usd')
    if raw is not None:
        try:
            return float(raw), False
        except (TypeError, ValueError):
            pass
    input_tokens = max(0, int(item.get('input_tokens') or 0))
    output_tokens = max(0, int(item.get('output_tokens') or 0))
    return provider_cost_usd(item.get('model'), input_tokens, output_tokens), True


def persist_operation(
    user,
    *,
    usage,
    charged_credits,
    operation_type=None,
    thread_id=None,
    success=True,
    error_code=None,
    is_comped=False,
    subsidy_reason=None,
    customer_visible=True,
    idempotency_key=None,
    request_fingerprint=None,
    result_json=None,
    prompt_family=None,
):
    """Queue an idempotent operation/attempt audit record in the current DB txn."""
    usage = usage if isinstance(usage, dict) else {}
    operation_id = str(usage.get('operation_id') or new_operation_id())
    existing = AIOperation.query.get(operation_id)
    claimed_lifecycle = dict(_turn_lifecycle(existing) or {})
    claimed_turn = _turn_lifecycle(existing) is not None
    if existing is None and idempotency_key:
        existing = AIOperation.query.filter_by(idempotency_key=str(idempotency_key)).first()
    claimed_key = existing.idempotency_key if existing is not None else None
    if claimed_turn:
        # A claimed conversation turn closes exactly once (P4.0).
        check_operation_transition(existing.status, _audit_status(usage, success))

    governance = usage.get('governance') if isinstance(usage.get('governance'), dict) else {}
    failover = usage.get('failover') if isinstance(usage.get('failover'), dict) else {}
    failed_attempts = [item for item in (failover.get('attempted_providers') or []) if isinstance(item, dict)]
    if usage.get('degraded') and not usage.get('billable_action_completed') and (usage.get('input_tokens') or usage.get('output_tokens')):
        # A syntactically invalid/thin plan may still incur provider cost.
        # Retain that attempt as absorbed cost, never as a successful generation.
        components = [
            item for item in (usage.get('component_usages') or []) if isinstance(item, dict)
        ]
        if components:
            failed_attempts.extend({**item, 'outcome': item.get('outcome') or 'invalid_response'} for item in components)
        else:
            failed_attempts.append({**usage, 'outcome': 'invalid_response', 'error_code': usage.get('error_code')})
    success = bool(success and usage_is_billable_success(usage))
    successful_cost = _successful_provider_cost(usage) if success else 0.0
    failed_costs = [_attempt_cost(item) for item in failed_attempts]
    failed_cost = sum(item[0] for item in failed_costs)
    total_cost = successful_cost + failed_cost
    projected = credits_for_provider_cost(successful_cost, internal=True) if success else 0
    classification = subsidy_classification(
        user,
        explicit=('fully_comped' if is_comped else subsidy_reason),
        customer_visible=customer_visible,
    )
    subsidized = bool(classification)
    legacy_routes = governance.get('legacy_routes') if isinstance(governance.get('legacy_routes'), list) else []
    legacy_first = legacy_routes[0] if legacy_routes and isinstance(legacy_routes[0], dict) else {}

    version_evidence = _prompt_version_evidence(
        existing, claimed_lifecycle if claimed_turn else None, prompt_family,
    )
    operation = existing or AIOperation(id=operation_id)
    if not claimed_turn:
        # A claimed chat turn keeps the member and organization it was
        # claimed for (the acting member), so its identity never changes.
        operation.user_id = str(user.id) if user is not None else None
        operation.organization_id = getattr(user, 'active_organization_id', None) if user is not None else None
    operation.thread_id = str(thread_id or '').strip() or None
    operation.operation_type = str(operation_type or usage.get('operation_type') or 'ai_operation')
    candidate_key = str(idempotency_key or operation.idempotency_key or '').strip() or None
    duplicate_of = None
    if claimed_turn and candidate_key and candidate_key != claimed_key:
        with db.session.no_autoflush:
            holder = AIOperation.query.filter(
                AIOperation.idempotency_key == candidate_key,
                AIOperation.id != operation.id,
            ).first()
        if holder is not None:
            # A second request with the same client key generated while the
            # first was still running. Both really generated, so both keep a
            # row; the unique key stays with the first.
            candidate_key = claimed_key
            duplicate_of = holder.id
    operation.idempotency_key = candidate_key
    operation.request_fingerprint = str(request_fingerprint or operation.request_fingerprint or '').strip() or None
    operation.status = _audit_status(usage, success)
    operation.customer_visible = bool(customer_visible)
    operation.subsidized = subsidized
    operation.subsidy_classification = classification
    operation.router_mode = str(governance.get('router_mode') or router_mode(current_app.config))
    operation.router_version = str(governance.get('router_version') or ROUTER_VERSION)
    operation.route_class = str(governance.get('route_class') or '').strip() or None
    operation.routing_reasons = list(governance.get('routing_reasons') or [])
    operation.legacy_provider = legacy_first.get('provider')
    operation.legacy_model = legacy_first.get('model')
    operation.selected_provider = governance.get('selected_provider')
    operation.selected_model = governance.get('selected_model')
    operation.final_provider = str(usage.get('provider') or '').strip() or None
    operation.final_model = str(usage.get('model') or '').strip() or None
    operation.escalated = bool(governance.get('escalated') or failed_attempts)
    operation.policy_mode = str(governance.get('policy_mode') or credit_policy_mode(current_app.config))
    operation.policy_version = str(governance.get('policy_version') or CREDIT_POLICY_VERSION)
    operation.successful_provider_cost_usd = Decimal(str(successful_cost or 0))
    operation.total_provider_cost_usd = Decimal(str(total_cost or 0))
    operation.projected_credits = int(projected)
    operation.charged_credits = int(charged_credits or 0)
    operation.settled_at = datetime.utcnow()
    operation.error_code = str(error_code or usage.get('error_code') or ('provider_fallback' if usage.get('degraded') else '')).strip() or None
    operation.result_json = result_json
    operation.metadata_json = {
        'degraded': bool(usage.get('degraded')),
        'generation_failed': bool(usage.get('generation_failed')),
        'operation_failed': bool(usage.get('operation_failed')),
        'billable_action_completed': bool(usage.get('billable_action_completed')),
        'charge_owner': usage.get('charge_owner'),
        'completed_action_ids': list(usage.get('completed_action_ids') or []),
        'failed_attempt_costs_absorbed': True,
        'failed_attempt_cost_known': bool(failed_attempts) and not any(estimated for _cost, estimated in failed_costs),
        'failed_attempt_cost_estimated': any(estimated for _cost, estimated in failed_costs),
        'failed_attempt_provider_cost_usd': float(failed_cost or 0),
        'customer_charged_once': bool(customer_visible),
        'internal_operation': not bool(customer_visible),
        'subsidy_classification': classification,
        'stop_reason': usage.get('stop_reason'),
        'stop_reasons': [
            item.get('stop_reason')
            for item in (usage.get('component_usages') or [])
            if isinstance(item, dict) and item.get('stop_reason')
        ],
        'plan_attempts': [
            {
                'attempt': item.get('attempt'),
                'duration_ms': item.get('duration_ms'),
                'output_tokens': int(item.get('output_tokens') or 0),
                'stop_reason': item.get('stop_reason'),
                'outcome': item.get('outcome'),
                'lineage_valid_task_count': item.get('lineage_valid_task_count'),
                'lineage_dropped_tasks': list(item.get('lineage_dropped_tasks') or []),
                'lineage_missing_sources': list(item.get('lineage_missing_sources') or []),
            }
            for item in (usage.get('component_usages') or ([usage] if usage.get('attempt') else []))
            if isinstance(item, dict)
        ],
    }
    if version_evidence:
        operation.metadata_json = {**operation.metadata_json, **version_evidence}
    if claimed_turn:
        lifecycle = claimed_lifecycle
        if duplicate_of:
            lifecycle['concurrent_duplicate_of'] = duplicate_of
        operation.metadata_json = {**operation.metadata_json, TURN_LIFECYCLE_KEY: lifecycle}
    if existing is None:
        db.session.add(operation)
    else:
        AIProviderAttempt.query.filter_by(operation_id=operation.id).delete(synchronize_session=False)
    operation_id = operation.id

    sequence = 1
    for item, (attempt_cost, cost_estimated) in zip(failed_attempts, failed_costs):
        db.session.add(AIProviderAttempt(
            operation_id=operation_id,
            sequence=sequence,
            provider=str(item.get('provider') or 'unknown'),
            model=str(item.get('model') or '').strip() or None,
            outcome=str(item.get('outcome') or 'failed'),
            status_code=item.get('status_code'),
            duration_ms=item.get('duration_ms'),
            input_tokens=int(item.get('input_tokens') or 0),
            output_tokens=int(item.get('output_tokens') or 0),
            raw_provider_cost_usd=Decimal(str(attempt_cost or 0)),
            customer_billable=False,
            error_code=str(item.get('outcome') or '').strip() or None,
            metadata_json={
                'provider_cost_estimated': bool(cost_estimated),
                'estimate_method': item.get('estimate_method') if cost_estimated else None,
                'attempt': item.get('attempt'),
                'stop_reason': item.get('stop_reason'),
                'lineage_valid_task_count': item.get('lineage_valid_task_count'),
                'lineage_dropped_tasks': list(item.get('lineage_dropped_tasks') or []),
                'lineage_missing_sources': list(item.get('lineage_missing_sources') or []),
            },
        ))
        sequence += 1

    if success:
        components = [
            item for item in (usage.get('component_usages') or []) if isinstance(item, dict)
        ] or [usage]
        for index, component in enumerate(components):
            component_cost = provider_cost_usd(
                component.get('model'),
                component.get('input_tokens'),
                component.get('output_tokens'),
            )
            db.session.add(AIProviderAttempt(
                operation_id=operation_id,
                sequence=sequence,
                provider=str(component.get('provider') or 'unknown'),
                model=str(component.get('model') or '').strip() or None,
                outcome='succeeded',
                duration_ms=component.get('duration_ms'),
                input_tokens=int(component.get('input_tokens') or 0),
                output_tokens=int(component.get('output_tokens') or 0),
                raw_provider_cost_usd=Decimal(str(component_cost or 0)),
                # The customer-visible result is the reply; a supporting call
                # (such as decision capture) is recorded but never the billed row.
                customer_billable=bool(customer_visible and (
                    component.get('role') == 'reply' if any(item.get('role') for item in components)
                    else index == len(components) - 1
                )),
                metadata_json={
                    'customer_visible_result': bool(customer_visible),
                    'component_index': index,
                    'role': component.get('role'),
                    'operation_type': component.get('operation_type'),
                    'component_operation_id': component.get('operation_id'),
                    'governance': component.get('governance'),
                    'settled_once_at_operation': True,
                    'stop_reason': component.get('stop_reason'),
                    'attempt': component.get('attempt'),
                    'lineage_valid_task_count': component.get('lineage_valid_task_count'),
                    'lineage_dropped_tasks': list(component.get('lineage_dropped_tasks') or []),
                    'lineage_missing_sources': list(component.get('lineage_missing_sources') or []),
                },
            ))
            sequence += 1
    return operation


def _prompt_version_evidence(existing, claimed_lifecycle, prompt_family):
    """The prompt-version keys a closing operation keeps (P5b).

    The version recorded when the operation was claimed wins: a claimed turn
    keeps its claim-time version, and a claimed runtime operation keeps the
    one its claim (or retry) stamped. Only a row created here is stamped from
    ``prompt_family``. A claimed turn is never re-stamped, so its version is
    always the one the turn was generated under.
    """
    prior = existing.metadata_json if existing is not None and isinstance(existing.metadata_json, dict) else {}
    if claimed_lifecycle is not None:
        version = claimed_lifecycle.get(PROMPT_VERSION_KEY) or prior.get(PROMPT_VERSION_KEY)
    else:
        version = prior.get(PROMPT_VERSION_KEY) or prompt_version(prompt_family)
    evidence = {}
    if version:
        evidence[PROMPT_VERSION_KEY] = version
    if prior.get(PROMPT_VERSION_HISTORY_KEY):
        evidence[PROMPT_VERSION_HISTORY_KEY] = list(prior[PROMPT_VERSION_HISTORY_KEY])
    return evidence


def _audit_status(usage, success):
    """The terminal status ``persist_operation`` records (unchanged rule)."""
    usage = usage if isinstance(usage, dict) else {}
    success = bool(success and usage_is_billable_success(usage))
    if usage.get('operation_failed'):
        return 'failed'
    if success:
        return 'succeeded'
    return 'degraded' if usage.get('degraded') else 'failed'


# ---------------------------------------------------------------------------
# Conversation-turn operation evidence (P4.0, F2-F4 decision stage S0)
#
# A chat turn's AIOperation is claimed ('started') and committed by itself
# before the turn reserves, and closed at the turn's existing terminal step.
# Nothing here reserves, settles, releases or prices anything: the legacy
# meter still decides every charge exactly as before. What is added is a
# durable record of what happened, so the F2/F3/F4 decision can be measured.
#
# Status vocabulary is the existing one (started -> succeeded | degraded |
# failed). The finer outcome (settled, released, refused, reply not saved,
# interrupted) lives in metadata_json['turn_lifecycle'].
# ---------------------------------------------------------------------------

TURN_LIFECYCLE_KEY = 'turn_lifecycle'
TURN_LIFECYCLE_VERSION = 'p4.0-s0'
STARTED = 'started'
TERMINAL_STATUSES = frozenset({'succeeded', 'degraded', 'failed'})

# Outcome -> the terminal status a close without a provider audit records.
TURN_OUTCOMES = {
    'settled': None,              # status comes from persist_operation
    'refused_at_reserve': 'failed',
    'refused_at_settle': 'failed',
    'generation_failed': None,    # status comes from persist_operation
    'provider_unavailable': None,  # status comes from persist_operation
    'failed_after_settle': 'failed',
    'reply_not_saved': 'failed',
    'interrupted': 'failed',
    'failed_unexpectedly': 'failed',
}


# Outcomes that end a turn with no saved reply. With a durable, non-zero
# settlement they are the F2 case (charged without a saved reply).
CHARGE_WITHOUT_REPLY_OUTCOMES = frozenset({
    'reply_not_saved', 'failed_after_settle', 'failed_unexpectedly',
})


class OperationTransitionError(ValueError):
    """An operation was moved to a state its current state does not allow."""


def check_operation_transition(current, target):
    """started -> any terminal status, once. Re-closing with the SAME status
    is an idempotent no-op; anything else is contradictory and refused."""
    current = str(current or '')
    target = str(target or '')
    if target not in TERMINAL_STATUSES:
        raise OperationTransitionError(f'{target!r} is not a terminal operation status')
    if current == STARTED:
        return
    if current == target:
        return
    raise OperationTransitionError(
        f'operation already closed as {current!r}; refusing {target!r}'
    )


def _turn_lifecycle(operation):
    if operation is None:
        return None
    metadata = operation.metadata_json if isinstance(operation.metadata_json, dict) else {}
    value = metadata.get(TURN_LIFECYCLE_KEY)
    return value if isinstance(value, dict) else None


# -- transaction observation -------------------------------------------------
# Counts commits and rollbacks per database session, and whether flushed
# writes are waiting for a commit. Read-only bookkeeping in ``session.info``.

def _tx_state(session):
    return session.info.setdefault('jaspen_tx', {'commits': 0, 'rollbacks': 0, 'flushed': False})


@event.listens_for(Session, 'after_flush')
def _jaspen_after_flush(session, _flush_context):
    _tx_state(session)['flushed'] = True


@event.listens_for(Session, 'after_commit')
def _jaspen_after_commit(session):
    state = _tx_state(session)
    state['commits'] += 1
    state['flushed'] = False


@event.listens_for(Session, 'after_soft_rollback')
def _jaspen_after_soft_rollback(session, previous_transaction):
    if getattr(previous_transaction, 'parent', None) is None:
        state = _tx_state(session)
        state['rollbacks'] += 1
        state['flushed'] = False


def transaction_counters():
    state = _tx_state(db.session())
    return {'commits': int(state['commits']), 'rollbacks': int(state['rollbacks'])}


def session_has_uncommitted_writes():
    session = db.session()
    if session.new or session.deleted or _tx_state(session)['flushed']:
        return True
    return any(session.is_modified(item) for item in session.dirty)


# -- claim and close ---------------------------------------------------------

CLIENT_IDEMPOTENCY_KEY_MAX = 200  # same bound as the route's validation


def _bounded_client_key(value):
    key = str(value or '').strip()
    return key[:CLIENT_IDEMPOTENCY_KEY_MAX] or None


def claim_turn_operation(user, *, thread_id, route=None, streaming=None,
                         project_organization_id=None, client_idempotency_key=None,
                         request_fingerprint=None, estimated_reservation=None,
                         cycle_marker=None):
    """Insert this turn's operation as 'started' and commit it by itself.

    Called immediately before the turn reserves. It commits only when the
    request's session holds no other uncommitted write, so the claim can
    never make anything else durable; otherwise the row is added and becomes
    durable with the turn's own next commit (recorded as such).
    """
    operation_id = new_operation_id()
    clean = not session_has_uncommitted_writes()
    independent = (not clean) and db.engine.dialect.name == 'postgresql'
    classification = subsidy_classification(user, customer_visible=True)
    now = datetime.utcnow()
    # P5b: the prompt version is part of the claim, so it survives every
    # close path. It is a new key; the lifecycle ``version`` is unchanged.
    turn_prompt_version = prompt_version('conversation')
    lifecycle = {
        'version': TURN_LIFECYCLE_VERSION,
        'route': route,
        'streaming': None if streaming is None else bool(streaming),
        'project_organization_id': project_organization_id,
        'client_idempotency_key_present': bool(client_idempotency_key),
        # C2 (F2_F4 decisions 1.4.1): the client's key as sent, so a refused,
        # failed or interrupted turn can be tied back to its retries. It is a
        # random client token (validated to <= 200 characters at the route)
        # and is already stored as given in the project's replay cache. Any
        # lookup by it must stay scoped to the operation's user/organization.
        'client_idempotency_key': _bounded_client_key(client_idempotency_key),
        'estimated_reservation': None if estimated_reservation is None else int(estimated_reservation),
        'cycle_marker': cycle_marker,
        'claimed_at': now.isoformat(),
        # True: committed alone in the request session. 'independent': the
        # session held another uncommitted write, so the row was committed on
        # its own connection (PostgreSQL). False: deferred to the turn's own
        # next commit (other databases), never committing anything early.
        'claim_committed': True if clean else ('independent' if independent else False),
        'outcome': None,
    }
    metadata = {TURN_LIFECYCLE_KEY: lifecycle}
    if turn_prompt_version:
        lifecycle[PROMPT_VERSION_KEY] = turn_prompt_version
        metadata[PROMPT_VERSION_KEY] = turn_prompt_version
    values = dict(
        id=operation_id,
        user_id=str(user.id) if user is not None else None,
        organization_id=getattr(user, 'active_organization_id', None) if user is not None else None,
        thread_id=str(thread_id or '').strip() or None,
        operation_type='conversation',
        request_fingerprint=str(request_fingerprint or '').strip() or None,
        status=STARTED,
        customer_visible=True,
        subsidized=bool(classification),
        subsidy_classification=classification,
        router_mode=router_mode(current_app.config),
        router_version=ROUTER_VERSION,
        escalated=False,
        policy_mode=credit_policy_mode(current_app.config),
        policy_version=CREDIT_POLICY_VERSION,
        projected_credits=0,
        charged_credits=0,
        metadata_json=metadata,
        created_at=now,
        updated_at=now,
    )
    if independent:
        with db.engine.begin() as connection:
            connection.execute(AIOperation.__table__.insert().values(**values))
        return operation_id, lifecycle
    db.session.add(AIOperation(**values))
    if clean:
        db.session.commit()
    return operation_id, lifecycle


def note_turn_operation(operation_id, updates):
    """Merge lifecycle facts into the claimed row in the CURRENT transaction.
    Never commits; the turn's existing commit makes it durable."""
    operation = db.session.get(AIOperation, operation_id) if operation_id else None
    if operation is None:
        return None
    metadata = dict(operation.metadata_json or {})
    lifecycle = dict(metadata.get(TURN_LIFECYCLE_KEY) or {})
    lifecycle.update(updates or {})
    metadata[TURN_LIFECYCLE_KEY] = lifecycle
    operation.metadata_json = metadata
    return operation


def close_turn_operation_alone(operation_id, *, outcome, updates=None, error_code=None,
                               claim=None, user=None, thread_id=None):
    """Close a claimed turn whose path ends with NO commit of its own.

    Such a path ends in the request teardown discarding every uncommitted
    change. Rolling back here first discards exactly the same changes, a
    little earlier, so the commit below carries this one row and nothing
    else: no balance can differ from before.
    """
    status = TURN_OUTCOMES.get(outcome) or 'failed'
    db.session.rollback()
    operation = db.session.get(AIOperation, operation_id) if operation_id else None
    lifecycle_updates = {'outcome': outcome, 'closed_at': datetime.utcnow().isoformat(),
                         'closed_alone': True, **(updates or {})}
    if operation is None:
        # The claim never became durable and was discarded with the rollback.
        operation = AIOperation(
            id=operation_id or new_operation_id(),
            user_id=str(user.id) if user is not None else None,
            organization_id=getattr(user, 'active_organization_id', None) if user is not None else None,
            thread_id=str(thread_id or '').strip() or None,
            operation_type='conversation',
            status=STARTED,
            router_mode=router_mode(current_app.config),
            router_version=ROUTER_VERSION,
            policy_mode=credit_policy_mode(current_app.config),
            policy_version=CREDIT_POLICY_VERSION,
            metadata_json={
                TURN_LIFECYCLE_KEY: {**(claim or {}), 'claim_lost': True},
                **({PROMPT_VERSION_KEY: claim[PROMPT_VERSION_KEY]}
                   if isinstance(claim, dict) and claim.get(PROMPT_VERSION_KEY) else {}),
            },
        )
        db.session.add(operation)
    if operation.status == STARTED:
        check_operation_transition(operation.status, status)
        operation.status = status
        operation.error_code = error_code or outcome
        operation.settled_at = datetime.utcnow()
    else:
        # Already closed by its own terminal step: keep that status and add
        # what happened afterwards (for example the replay cache not saved).
        previous = (_turn_lifecycle(operation) or {}).get('outcome')
        lifecycle_updates = {
            'after_close': [*((_turn_lifecycle(operation) or {}).get('after_close') or []),
                            {'event': outcome, **(updates or {})}],
        }
        if previous is None:
            lifecycle_updates['outcome'] = outcome
    note_turn_operation(operation.id, lifecycle_updates)
    db.session.commit()
    return operation.id


# -- report-only sweep -------------------------------------------------------

DEFAULT_MAX_TURN_SECONDS = 30 * 60


# -- unclosed-operation classification (P4.1 X1) ------------------------------
#
# Billing migration treats an account as in flight while any of its
# operations is 'started' (Phase 14 ``_in_flight_legacy_operations``). Since
# P4.0 a chat turn killed mid-generation also leaves a 'started' row. That row
# is evidence, not a reservation: S0 never commits a reservation with its
# claim, and no code path will ever settle or release a P4.0 turn after its
# process is gone. Whatever the turn's balance write did, the meter already
# shows it. So once a P4.0 turn is older than the maximum turn duration it
# can no longer change any balance.
#
# This classifier says which is which. It reads only. It never closes,
# releases, or edits a row: a stale row stays 'started' and is reported for
# the deferred F3 review (a mid-turn commit may have kept its reservation),
# never silently dropped. Anything it does not positively recognise as P4.0
# evidence is treated as outstanding (fail closed).

UNCLOSED_IN_PROGRESS = 'in_progress'
UNCLOSED_STALE_TURN_EVIDENCE = 'stale_turn_evidence'
UNCLOSED_OUTSTANDING = 'outstanding'
UNCLOSED_CLASSES = (UNCLOSED_IN_PROGRESS, UNCLOSED_STALE_TURN_EVIDENCE, UNCLOSED_OUTSTANDING)


def _operation_started_at(operation, lifecycle):
    if getattr(operation, 'created_at', None) is not None:
        return operation.created_at
    claimed_at = (lifecycle or {}).get('claimed_at')
    try:
        return datetime.fromisoformat(str(claimed_at)) if claimed_at else None
    except ValueError:
        return None


def classify_unclosed_operation(operation, *, now=None, max_turn_seconds=DEFAULT_MAX_TURN_SECONDS):
    """Classify one operation that has not reached a terminal status.

    Returns None for a closed operation. Otherwise a dict whose ``class`` is:

    - ``in_progress``: a P4.0 chat turn younger than ``max_turn_seconds``; it
      may still settle, so it is in flight.
    - ``stale_turn_evidence``: a P4.0 chat turn ('started', unbound, claim
      version ``p4.0-s0``) older than the bound. Not in flight.
    - ``outstanding``: everything else that is not terminal, including
      runtime operations whose reservation was committed with the claim,
      rows bound to a billing account, unknown lifecycle versions, statuses
      added later, and rows with no usable timestamp. In flight.

    Reads only.
    """
    status = str(getattr(operation, 'status', '') or '')
    if status in TERMINAL_STATUSES:
        return None
    now = now or datetime.utcnow()
    lifecycle = _turn_lifecycle(operation)
    started_at = _operation_started_at(operation, lifecycle)
    age = int((now - started_at).total_seconds()) if started_at is not None else None
    result = {
        'operation_id': operation.id,
        'status': status,
        'operation_type': operation.operation_type,
        'age_seconds': age,
        'max_turn_seconds': int(max_turn_seconds),
    }
    p4_0_evidence = (
        status == STARTED
        and operation.operation_type == 'conversation'
        and lifecycle is not None
        and lifecycle.get('version') == TURN_LIFECYCLE_VERSION
        and getattr(operation, 'billing_account_id', None) is None
    )
    if not p4_0_evidence:
        reason = ('not_a_p4_0_turn_claim' if lifecycle is None or operation.operation_type != 'conversation'
                  else 'unrecognised_turn_claim')
        return {**result, 'class': UNCLOSED_OUTSTANDING, 'in_flight': True, 'reason': reason}
    if age is None:
        return {**result, 'class': UNCLOSED_OUTSTANDING, 'in_flight': True, 'reason': 'no_start_time'}
    if age < int(max_turn_seconds):
        return {**result, 'class': UNCLOSED_IN_PROGRESS, 'in_flight': True, 'reason': 'within_turn_bound'}
    return {
        **result,
        'class': UNCLOSED_STALE_TURN_EVIDENCE,
        'in_flight': False,
        'reason': 'p4_0_turn_past_bound',
        # S0 records no durable reservation; whether a mid-turn commit kept
        # one is unknown from the row. Kept for the deferred F3 review.
        'reservation_durability': 'not_recorded',
        'estimated_reservation': lifecycle.get('estimated_reservation'),
        'cycle_marker': lifecycle.get('cycle_marker'),
        'f3_review': True,
    }


def operation_is_in_flight(operation, *, now=None, max_turn_seconds=DEFAULT_MAX_TURN_SECONDS):
    """True when the operation may still change a balance (see above)."""
    classified = classify_unclosed_operation(operation, now=now, max_turn_seconds=max_turn_seconds)
    return bool(classified and classified['in_flight'])


def report_turn_operations(*, now=None, max_turn_seconds=DEFAULT_MAX_TURN_SECONDS, since_days=30):
    """List operations that never closed and chat turns whose evidence does
    not reconcile. Reads only; changes nothing."""
    from .models import UsageEvent

    now = now or datetime.utcnow()
    # since_days=0 reads all history (billing migration looks at any age).
    all_history = since_days is not None and int(since_days) == 0
    since = None if all_history else now - timedelta(days=max(1, int(since_days or 30)))
    stale_before = now - timedelta(seconds=max(0, int(max_turn_seconds)))
    unclosed = []
    unclosed_classes = {name: 0 for name in UNCLOSED_CLASSES}
    unclosed_query = AIOperation.query.filter(
        AIOperation.status.notin_(sorted(TERMINAL_STATUSES)), AIOperation.created_at < stale_before,
    )
    if since is not None:
        unclosed_query = unclosed_query.filter(AIOperation.created_at >= since)
    unclosed_ids = []
    for op in unclosed_query.order_by(AIOperation.created_at, AIOperation.id).all():
        classified = classify_unclosed_operation(op, now=now, max_turn_seconds=max_turn_seconds)
        unclosed_classes[classified['class']] += 1
        unclosed_ids.append(op.id)
        unclosed.append({
            'operation_id': op.id, 'operation_type': op.operation_type, 'status': op.status,
            'conversation_turn': _turn_lifecycle(op) is not None,
            'user_id': op.user_id, 'organization_id': op.organization_id, 'thread_id': op.thread_id,
            'age_seconds': int((now - op.created_at).total_seconds()),
            'estimated_reservation': (_turn_lifecycle(op) or {}).get('estimated_reservation'),
            'class': classified['class'],
            'in_flight': classified['in_flight'],
            'reason': classified['reason'],
        })

    usage_by_operation = {}
    usage_query = UsageEvent.query.filter(UsageEvent.endpoint == 'ai.conversation')
    if since is not None:
        usage_query = usage_query.filter(UsageEvent.created_at >= since)
    for row in usage_query.all():
        linked = (row.metadata_json or {}).get('operation_id') if isinstance(row.metadata_json, dict) else None
        if linked:
            usage_by_operation.setdefault(linked, []).append(row)

    for entry in unclosed:
        # A usage row points at a turn whose close never landed.
        linked = usage_by_operation.get(entry['operation_id'], [])
        entry['usage_rows'] = len(linked)
        entry['usage_charged_credits'] = sum(int(row.credits_charged or 0) for row in linked)

    findings = []
    outcomes = {}
    closed_query = AIOperation.query.filter(AIOperation.status != STARTED)
    if since is not None:
        closed_query = closed_query.filter(AIOperation.created_at >= since)
    for op in closed_query.all():
        lifecycle = _turn_lifecycle(op)
        if lifecycle is None:
            continue
        outcome = lifecycle.get('outcome') or 'unrecorded'
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        usage_rows = usage_by_operation.get(op.id, [])
        usage_charged = sum(int(row.credits_charged or 0) for row in usage_rows)
        reasons = []
        if outcome == 'settled':
            if not usage_rows:
                reasons.append('no_usage_row')
            elif usage_charged != int(op.charged_credits or 0):
                reasons.append('usage_and_operation_charge_differ')
            if lifecycle.get('settled_credits') is not None and int(lifecycle['settled_credits']) != int(op.charged_credits or 0):
                reasons.append('settlement_and_operation_charge_differ')
        if (outcome in CHARGE_WITHOUT_REPLY_OUTCOMES
                and lifecycle.get('balance_committed') is True
                and int(lifecycle.get('settled_credits') or 0) > 0):
            reasons.append('charge_committed_without_saved_reply')  # F2
        if outcome != 'settled' and int(lifecycle.get('generation_commits') or 0) > 0:
            reasons.append('reservation_possibly_kept_by_mid_turn_commit')  # F3
        if int(lifecycle.get('generation_rollbacks') or 0) > 0:
            reasons.append('reservation_possibly_discarded_by_rollback')  # F4
        if lifecycle.get('concurrent_duplicate_of'):
            reasons.append('concurrent_duplicate_request')
        if reasons:
            findings.append({
                'operation_id': op.id, 'thread_id': op.thread_id, 'user_id': op.user_id,
                'organization_id': op.organization_id, 'status': op.status, 'outcome': outcome,
                'charged_credits': int(op.charged_credits or 0), 'usage_charged_credits': usage_charged,
                'reserved_credits': lifecycle.get('reserved_credits'),
                'settled_credits': lifecycle.get('settled_credits'),
                'reasons': reasons,
            })
    return {
        'generated_at': now.isoformat(),
        'max_turn_seconds': int(max_turn_seconds),
        'since': since.isoformat() if since is not None else None,
        'unclosed': unclosed,
        'unclosed_by_class': unclosed_classes,
        'mismatched': findings,
        'turn_outcomes': dict(sorted(outcomes.items())),
        'changes_made': 0,
    }
