"""Public share links: eligibility, limits, and snapshot sanitization.

A share link serves a frozen copy of a scorecard or trade-off comparison. The
copy is built here, from an allowlist, when the link is created. Nothing that
is not named below can reach a public page, so new scorecard fields stay
private until someone decides they are safe to share.
"""

from __future__ import annotations

import copy
import json
import re
import secrets
from datetime import datetime, timedelta

from flask import current_app

from .billing_config import PLAN_RANK, effective_plan_key, normalize_plan_key


ARTIFACT_SCORECARD = 'scorecard'
ARTIFACT_TRADEOFF = 'tradeoff'
ARTIFACT_TYPES = (ARTIFACT_SCORECARD, ARTIFACT_TRADEOFF)

EXPIRY_CHOICES = (7, 30, 90, None)  # None = never expires
DEFAULT_EXPIRY_DAYS = 30

DEFAULT_DAILY_CREATE_LIMIT = 20
DEFAULT_ACTIVE_LIMIT = 50
MAX_SNAPSHOT_BYTES = 1_000_000

REPORT_REASONS = ('spam', 'abusive', 'private_information', 'misleading', 'other')

# Top-level scorecard fields a public page may show. Everything else (thread
# and user identifiers, model metadata, chat history, nested snapshots,
# baseline inputs, private "_" fields) is dropped.
SCORECARD_FIELDS = frozenset({
    'project_name', 'name', 'label', 'jaspen_score', 'score', 'tier',
    'primary_role', 'strategic_rationale', 'executive_summary',
    'executive_narrative', 'key_insights', 'key_considerations', 'top_risks',
    'risks', 'recommendations', 'assumptions', 'component_scores',
    'component_rationale', 'section_provenance', 'financial_impact',
    'before_after_financials', 'investment_analysis', 'npv_irr_analysis',
    'valuation', 'decision_framework', 'strategic_decision_framework',
    'ai_insights', 'data_confidence', 'confidence', 'evidence_quality',
    'evidence_profile', 'dimensions', 'scores', 'rubric', 'scoring_rubric',
    'group_scores', 'groups', 'locked', 'createdAt', 'display_overrides',
})
DISPLAY_OVERRIDE_FIELDS = frozenset({'title', 'tradeoff_included'})

# Verbatim passages of the user's own words. Removed everywhere in the
# snapshot unless the owner explicitly chooses to include evidence.
EVIDENCE_KEYS = frozenset({
    'evidence', 'evidence_references', 'supporting_evidence_references',
    'references', 'excerpt', 'excerpts', 'quote', 'quotes', 'evidence_quotes',
    'locator',
})

# Identifier-shaped keys are never shared at any depth.
_PRIVATE_KEY = re.compile(
    r'(^_)|(^|_)(user|owner|organization|org|thread|session|evaluation|analysis|scorecard)_?ids?$'
    r'|email',
    re.IGNORECASE,
)


def _config_int(key, default):
    try:
        return max(0, int(current_app.config.get(key) or default))
    except (TypeError, ValueError):
        return default


def daily_create_limit():
    return _config_int('SHARE_LINK_DAILY_CREATE_LIMIT', DEFAULT_DAILY_CREATE_LIMIT)


def active_link_limit():
    return _config_int('SHARE_LINK_ACTIVE_LIMIT', DEFAULT_ACTIVE_LIMIT)


def new_token():
    # 32 random bytes -> 43 URL-safe characters. Not guessable, not sequential.
    return secrets.token_urlsafe(32)


def sharing_block_reason(user):
    """Why ``user`` cannot share right now, or None when they can."""
    if user is None:
        return 'user_not_found'
    if bool(getattr(user, 'sharing_disabled', False)):
        return 'sharing_disabled'
    plan_key = normalize_plan_key(effective_plan_key(user, current_app.config))
    if PLAN_RANK.get(plan_key, 0) < PLAN_RANK['starter']:
        return 'paid_plan_required'
    return None


def parse_expiry_days(value):
    """Return (days_or_None, error). Missing means the 30-day default."""
    if value is None or value == '':
        return DEFAULT_EXPIRY_DAYS, None
    if isinstance(value, str) and value.strip().lower() in ('never', 'none', 'null'):
        return None, None
    try:
        days = int(value)
    except (TypeError, ValueError):
        return None, 'expires_in_days must be 7, 30, 90, or "never".'
    if days not in EXPIRY_CHOICES:
        return None, 'expires_in_days must be 7, 30, 90, or "never".'
    return days, None


def expiry_from_days(days, now=None):
    if days is None:
        return None
    return (now or datetime.utcnow()) + timedelta(days=days)


def link_is_live(link, now=None):
    if link is None or link.revoked_at is not None:
        return False
    if link.expires_at is not None and link.expires_at <= (now or datetime.utcnow()):
        return False
    return True


def _scrub(value, include_evidence):
    if isinstance(value, dict):
        out = {}
        for key, inner in value.items():
            key_text = str(key)
            if _PRIVATE_KEY.search(key_text):
                continue
            if not include_evidence and key_text in EVIDENCE_KEYS:
                continue
            out[key_text] = _scrub(inner, include_evidence)
        return out
    if isinstance(value, list):
        return [_scrub(item, include_evidence) for item in value]
    return value


_QUOTE_LIST_KEYS = frozenset({'evidence', 'quotes', 'evidence_quotes', 'excerpts'})
_QUOTE_TEXT_KEYS = frozenset({'excerpt', 'quote'})


def _add_passage(found, text):
    if isinstance(text, str) and text.strip():
        found.add(' '.join(text.split()).lower())


def _collect_passages(value, found):
    if isinstance(value, dict):
        for key, inner in value.items():
            if key in _QUOTE_TEXT_KEYS:
                _add_passage(found, inner)
            elif key in _QUOTE_LIST_KEYS and isinstance(inner, list):
                for item in inner:
                    if isinstance(item, str):
                        _add_passage(found, item)
                    else:
                        _collect_passages(item, found)
            else:
                _collect_passages(inner, found)
    elif isinstance(value, list):
        for item in value:
            _collect_passages(item, found)


def count_evidence_passages(value):
    """How many distinct verbatim evidence passages ``value`` carries.

    The same quote is stored on the dimension and again on its verified
    reference, so passages are de-duplicated by text.
    """
    found = set()
    _collect_passages(value, found)
    return len(found)


def sanitize_scorecard(card, *, include_evidence, public_id):
    if not isinstance(card, dict):
        return None
    kept = {key: copy.deepcopy(card[key]) for key in SCORECARD_FIELDS if key in card}
    overrides = kept.get('display_overrides')
    if isinstance(overrides, dict):
        kept['display_overrides'] = {
            key: overrides[key] for key in DISPLAY_OVERRIDE_FIELDS if key in overrides
        }
    else:
        kept.pop('display_overrides', None)
    kept = _scrub(kept, include_evidence)
    # Real ids are internal. The public copy gets stable positional ids that
    # only need to be unique inside this one snapshot.
    kept['id'] = public_id
    kept['analysis_id'] = public_id
    return kept


def card_title(card):
    if not isinstance(card, dict):
        return 'Scorecard'
    overrides = card.get('display_overrides') if isinstance(card.get('display_overrides'), dict) else {}
    for value in (overrides.get('title'), card.get('project_name'), card.get('name'), card.get('label')):
        text = str(value or '').strip()
        if text:
            return text[:255]
    return 'Scorecard'


def build_snapshot(*, artifact_type, cards, include_evidence, scorecard_id=None,
                   thread_name=None, strategy_objective=None, portfolio_summary=None):
    """Return (snapshot, title, source_id, evidence_available) or raise ValueError."""
    cards = [card for card in (cards or []) if isinstance(card, dict)]
    if artifact_type == ARTIFACT_SCORECARD:
        wanted = str(scorecard_id or '').strip()
        card = next(
            (c for c in cards if str(c.get('id') or c.get('analysis_id') or '') == wanted),
            None,
        )
        if card is None:
            raise ValueError('scorecard_not_found')
        snapshot = {
            'scorecard': sanitize_scorecard(card, include_evidence=include_evidence, public_id='c1'),
        }
        return snapshot, card_title(card), wanted, count_evidence_passages(card)

    if artifact_type == ARTIFACT_TRADEOFF:
        included = [
            c for c in cards
            if not (isinstance(c.get('display_overrides'), dict)
                    and c['display_overrides'].get('tradeoff_included') is False)
        ]
        if len(included) < 2:
            raise ValueError('not_enough_scorecards')
        snapshot = {
            'scorecards': [
                sanitize_scorecard(c, include_evidence=include_evidence, public_id=f'c{index + 1}')
                for index, c in enumerate(included)
            ],
            'strategy_objective': str(strategy_objective or '').strip() or None,
        }
        if isinstance(portfolio_summary, dict):
            snapshot['portfolio_summary'] = {
                key: str(portfolio_summary.get(key) or '').strip()
                for key in ('structure', 'recommended_sequence')
            }
        title = str(thread_name or '').strip()[:255] or 'Trade-off comparison'
        evidence = sum(count_evidence_passages(c) for c in included)
        return snapshot, title, None, evidence

    raise ValueError('invalid_artifact_type')


def snapshot_size_ok(snapshot):
    try:
        return len(json.dumps(snapshot, default=str)) <= MAX_SNAPSHOT_BYTES
    except (TypeError, ValueError):
        return False


def content_summary(snapshot, *, include_evidence, evidence_available):
    """What a viewer will see, for the owner's preview before sharing."""
    cards = snapshot.get('scorecards') if isinstance(snapshot.get('scorecards'), list) else [snapshot.get('scorecard')]
    cards = [c for c in cards if isinstance(c, dict)]

    def _has(*keys):
        return any(c.get(k) not in (None, '', [], {}) for c in cards for k in keys)

    return {
        'scorecard_count': len(cards),
        'evidence_quotes_available': int(evidence_available),
        'evidence_quotes_included': bool(include_evidence and evidence_available),
        'includes_financials': _has('financial_impact', 'before_after_financials',
                                    'investment_analysis', 'npv_irr_analysis', 'valuation'),
        'includes_rationale': _has('strategic_rationale', 'executive_summary',
                                   'component_rationale', 'executive_narrative'),
        'includes_risks': _has('top_risks', 'risks', 'key_considerations'),
        'includes_assumptions': _has('assumptions'),
        'excluded_always': [
            'Chat conversation',
            'Uploaded files',
            'Connected data (Salesforce, Jira, Snowflake, etc.)',
            'Your name, email, and account details',
        ],
    }
