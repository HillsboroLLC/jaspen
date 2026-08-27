# backend/app/decision_retrieval.py
#
# Permission-aware retrieval over canonical Decision Records -- the first real
# organizational-memory source (Phase 4).
#
# Scope, deliberately narrow:
#   * Decision Records ONLY. `__user_memory__` is personal state and is never
#     read here; OrgIdeaLedger is de-identified benchmarking signal and is a
#     different question ("how do ideas like this usually score") from the one
#     this module answers ("what did we decide, and why"). Every result carries
#     an explicit `source_type` so a future second source cannot be silently
#     conflated with this one.
#   * Lexical/structured ranking over metadata the model already stores. No
#     embeddings, no vector store -- per docs/cross-session-memory-next-phase.md
#     item 5, semantic retrieval waits until a measured corpus justifies it.
#   * Compact summaries. The full record is fetched by id, on demand, by a
#     caller that has already decided it needs one. Nothing here assembles
#     long-form payloads or chat history.
#
# THE ORDERING RULE
#
#   authorized candidates -> ranking -> response
#
# never
#
#   broad query -> ranking -> filter
#
# Authorization is a property of the candidate set, not a post-processing step.
# authorized_candidates() is the only way rows enter this module, and rank() is
# a pure function of whatever it is handed, so the two cannot be reordered by
# accident. test_org_decision_retrieval.py asserts this directly.

from datetime import datetime

from sqlalchemy import or_

from .decision_records import can_read_record
from .models_decision_record import DecisionRecord
from .orgs import active_membership_for_user


SOURCE_TYPE = 'decision_record'

# Conservative on purpose. Retrieval feeds selection, not bulk export, and an
# unbounded default is how "retrieve a few relevant decisions" quietly becomes
# "load the organization's entire history".
DEFAULT_LIMIT = 10
MAX_LIMIT = 50

# How many rows may be considered before ranking. Bounds the work without
# affecting correctness: candidates are already authorization-scoped.
CANDIDATE_CEILING = 500


def _clip(text, limit=280):
    text = str(text or '').strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + '…'


def _tokens(query):
    return [t for t in str(query or '').lower().split() if len(t) > 1]


# --- 1. AUTHORIZED CANDIDATES ------------------------------------------------

def authorized_candidates(user, *, organization_id=None, status=None,
                          thread_id=None, decision_type=None,
                          human_decision=None, since=None, until=None,
                          ceiling=CANDIDATE_CEILING):
    """Every Decision Record this user may read, already filtered.

    The SQL narrows to organizations the user is an active member of, then
    can_read_record() applies per-project visibility. Nothing outside this set
    is ever seen by the ranker.
    """
    if user is None:
        return []

    # Organization scope first. A record whose organization the caller does not
    # belong to is not a candidate, full stop.
    from .models import OrganizationMember
    member_org_ids = [
        m.organization_id for m in
        OrganizationMember.query.filter_by(user_id=str(user.id), status='active').all()
    ]
    if organization_id:
        requested = str(organization_id)
        if requested not in set(member_org_ids):
            return []
        member_org_ids = [requested]

    scope = []
    if member_org_ids:
        scope.append(DecisionRecord.organization_id.in_(member_org_ids))
    # Personal-scope records (no organization) belong to their attributed user.
    scope.append(
        (DecisionRecord.organization_id.is_(None))
        & (DecisionRecord.user_id == str(user.id))
    )

    query = DecisionRecord.query.filter(or_(*scope))

    if status:
        query = query.filter(DecisionRecord.status == str(status).strip().lower())
    if thread_id:
        query = query.filter(DecisionRecord.thread_id == str(thread_id))
    if decision_type:
        query = query.filter(DecisionRecord.decision_type == str(decision_type))
    if human_decision is True:
        query = query.filter(DecisionRecord.final_decision.isnot(None))
    elif human_decision is False:
        query = query.filter(DecisionRecord.final_decision.is_(None))
    if isinstance(since, datetime):
        query = query.filter(DecisionRecord.updated_at >= since)
    if isinstance(until, datetime):
        query = query.filter(DecisionRecord.updated_at <= until)

    rows = (
        query.order_by(DecisionRecord.updated_at.desc())
        .limit(max(1, int(ceiling)))
        .all()
    )

    # Per-project visibility. Membership is resolved once per organization
    # rather than once per row.
    membership_cache = {}

    def _membership(org_id):
        if org_id not in membership_cache:
            membership_cache[org_id] = (
                active_membership_for_user(org_id, str(user.id)) if org_id else None
            )
        return membership_cache[org_id]

    return [
        row for row in rows
        if can_read_record(row, user, membership=_membership(row.organization_id))
    ]


# --- 2. RANKING (pure) -------------------------------------------------------

def score_record(record, tokens):
    """Deterministic lexical score for one record against query tokens.

    Structured and explainable rather than clever: Phase 4 exists to prove that
    the RIGHT organizational decisions can be retrieved safely, not to maximize
    recall. Field weights reflect how identifying each field is.
    """
    if not tokens:
        return 0.0

    payload = record.record if isinstance(record.record, dict) else {}
    objectives = payload.get('objectives') if isinstance(payload.get('objectives'), dict) else {}
    alternatives = payload.get('alternatives') if isinstance(payload.get('alternatives'), list) else []
    rubric = payload.get('rubric') if isinstance(payload.get('rubric'), dict) else {}
    rubric_keys = [
        str(c.get('key') or c.get('label') or '')
        for c in (rubric.get('criteria') or []) if isinstance(c, dict)
    ]

    weighted = (
        (str(record.title or ''), 3.0),
        (str(record.decision_statement or ''), 2.5),
        (str(record.final_decision or ''), 2.5),
        (str(payload.get('recommendation') or ''), 2.0),
        (' '.join(str(a) for a in alternatives), 1.5),
        (' '.join(str(t) for t in (record.tags or [])), 1.5),
        (str(objectives.get('strategy_objective') or ''), 1.0),
        (' '.join(rubric_keys), 1.0),
        (str(payload.get('conversation_summary') or ''), 0.5),
    )

    total = 0.0
    for text, weight in weighted:
        haystack = text.lower()
        if not haystack:
            continue
        for token in tokens:
            if token in haystack:
                total += weight
    return total


def rank(records, query=None, *, limit=DEFAULT_LIMIT):
    """Order an ALREADY-AUTHORIZED list. Pure: no queries, no side effects.

    Ties break on recency, then id, so results are stable across calls.
    """
    tokens = _tokens(query)
    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))

    def _key(record):
        return (
            -score_record(record, tokens),
            -(record.updated_at or record.created_at or datetime.min).timestamp(),
            str(record.id),
        )

    ordered = sorted(records, key=_key)
    if tokens:
        # With a query, drop non-matches rather than padding the result with
        # arbitrary recent records.
        ordered = [r for r in ordered if score_record(r, tokens) > 0]
    return ordered[:limit]


# --- 3. COMPACT SUMMARY ------------------------------------------------------

def summarize(record):
    """Selection-sized view of a record.

    Enough to decide whether the full record is worth fetching, and no more.
    `id` is the link back to the canonical artifact -- this is a pointer, never
    a replacement for the primary record.
    """
    payload = record.record if isinstance(record.record, dict) else {}
    objectives = payload.get('objectives') if isinstance(payload.get('objectives'), dict) else {}
    confidence = payload.get('confidence') if isinstance(payload.get('confidence'), dict) else {}
    decided = bool(record.final_decision)

    return {
        'source_type': SOURCE_TYPE,
        'id': record.id,
        'organization_id': record.organization_id,
        'thread_id': record.thread_id,
        'title': record.title,
        'objective': objectives.get('strategy_objective'),
        'recommendation_summary': _clip(payload.get('recommendation')),
        # Never collapsed into a single "decision" field: the model's
        # recommendation and the organization's decision are different facts.
        'human_decision': {
            'recorded': decided,
            'summary': _clip(record.final_decision) if decided else None,
            'decided_at': record.decided_at.isoformat() if record.decided_at else None,
        },
        'status': record.status,
        # Status and timestamps are reported as-is. Phase 4 has no supersession
        # signal, so nothing here asserts that a record is CURRENT truth --
        # historical records are returned as history.
        'is_current': None,
        'confidence_mean': confidence.get('mean'),
        'scorecard_ids': payload.get('scorecard_ids') if isinstance(payload.get('scorecard_ids'), list) else [],
        'created_at': record.created_at.isoformat() if record.created_at else None,
        'updated_at': record.updated_at.isoformat() if record.updated_at else None,
    }


# --- 4. THE ONE ENTRY POINT --------------------------------------------------

def search(user, query=None, *, limit=DEFAULT_LIMIT, **filters):
    """Authorize, then rank, then summarize. In that order, always.

    Read-only: retrieval never creates or mutates a record.
    """
    candidates = authorized_candidates(user, **filters)
    ordered = rank(candidates, query, limit=limit)
    return [summarize(record) for record in ordered]
