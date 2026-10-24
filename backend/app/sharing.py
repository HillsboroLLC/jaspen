"""Public share links: eligibility, limits, and snapshot sanitization.

A share link serves a frozen copy of a scorecard or trade-off comparison. The
copy is built here, from an allowlist, when the link is created. Nothing that
is not named below can reach a public page, so new scorecard fields stay
private until someone decides they are safe to share.
"""

from __future__ import annotations

import copy
import json
import os
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
    # One-pager report: code-owned verdict, metrics and gate outcomes.
    'recommendation', 'metrics', 'gates', 'decision_kit', 'decision_kit_version',
})

# Stated facts are shared as label/value pairs. The user's verbatim wording
# stays behind the include-evidence choice like every other quote.
FACT_FIELDS = ('value', 'unit', 'source', 'label')

# Owner edits to the one-pager presentation. Numbers are never editable:
# only colors, the listed wording slots, and section order/visibility.
PRESENTATION_COLOR_SLOTS = ('accent', 'ink', 'tint')
PRESENTATION_TEXT_SLOTS = {
    'headline': 200,
    'summary': 1200,
    'featured_question': 300,
    'takeaway_title': 120,
    'next_step_title': 160,
    'next_step_body': 600,
    'brand_name': 60,
    'company_name': 80,
    'report_label': 80,
    'tagline': 120,
}
PRESENTATION_SECTIONS = (
    'strength', 'executive', 'standings', 'featured', 'drivers', 'breakdown', 'change',
    'exposure', 'financials', 'framework', 'insights', 'sharpen', 'takeaways', 'criteria',
    'next_step',
)
PRESENTATION_EVIDENCE_VARIANTS = ('detailed', 'compact')
_HEX_COLOR = re.compile(r'^#[0-9a-fA-F]{6}$')
DISPLAY_OVERRIDE_FIELDS = frozenset({'title', 'tradeoff_included'})

FINANCIAL_FIELDS = frozenset({
    'financial_impact', 'before_after_financials', 'investment_analysis',
    'npv_irr_analysis', 'valuation',
})
DEFAULT_DISCLOSURE_SETTINGS = {
    'include_facts': False,
    'fact_keys': [],
    'include_metrics': False,
    'include_financials': False,
}
PUBLIC_RESPONSE_FIELDS = frozenset({
    'artifact_type', 'title', 'created_at', 'expires_at', 'include_evidence',
    'disclosure_settings', 'snapshot',
})
PUBLIC_SNAPSHOT_FIELDS = frozenset({
    'scorecard', 'scorecards', 'context', 'presentation', 'strategy_objective',
    'portfolio_summary',
})

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


def config_value(key, default=None):
    """App config first (tests), then the server environment."""
    value = current_app.config.get(key)
    if value in (None, ''):
        value = os.getenv(key)
    return default if value in (None, '') else value


def _config_int(key, default):
    try:
        return max(0, int(config_value(key, default)))
    except (TypeError, ValueError):
        return default


def daily_create_limit():
    return _config_int('SHARE_LINK_DAILY_CREATE_LIMIT', DEFAULT_DAILY_CREATE_LIMIT)


def active_link_limit():
    return _config_int('SHARE_LINK_ACTIVE_LIMIT', DEFAULT_ACTIVE_LIMIT)


def new_token():
    # 32 random bytes -> 43 URL-safe characters. Not guessable, not sequential.
    return secrets.token_urlsafe(32)


def is_sharing_disabled(user):
    from .models import AccountSharingControl
    control = AccountSharingControl.query.filter_by(user_id=str(user.id)).first()
    return bool(control and control.sharing_disabled)


def set_sharing_disabled(user, disabled):
    from . import db
    from .models import AccountSharingControl
    control = AccountSharingControl.query.filter_by(user_id=str(user.id)).first()
    if control is None:
        control = AccountSharingControl(user_id=str(user.id))
        db.session.add(control)
    control.sharing_disabled = bool(disabled)
    return control.sharing_disabled


def sharing_block_reason(user):
    """Why ``user`` cannot share right now, or None when they can."""
    if user is None:
        return 'user_not_found'
    if is_sharing_disabled(user):
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


def normalize_disclosure_settings(value):
    source = value if isinstance(value, dict) else {}
    fact_keys = source.get('fact_keys') if isinstance(source.get('fact_keys'), list) else []
    return {
        'include_facts': source.get('include_facts') is True,
        'fact_keys': sorted({str(key).strip() for key in fact_keys if str(key).strip()}),
        'include_metrics': source.get('include_metrics') is True,
        'include_financials': source.get('include_financials') is True,
    }


def disclosure_requires_review(settings):
    settings = normalize_disclosure_settings(settings)
    return not (
        settings['include_facts']
        and settings['include_metrics']
        and settings['include_financials']
    )


def share_fact_inventory(snapshot):
    """Return the fact choices an owner may include on this one link."""
    source = snapshot if isinstance(snapshot, dict) else {}
    cards = source.get('scorecards') if isinstance(source.get('scorecards'), list) else [source.get('scorecard')]
    inventory = {}
    for card in (item for item in cards if isinstance(item, dict)):
        for key, fact in (card.get('facts') or {}).items():
            if not isinstance(fact, dict) or fact.get('value') in (None, '', [], {}):
                continue
            fact_key = str(key)
            inventory.setdefault(fact_key, {
                'key': fact_key,
                'label': str(fact.get('label') or fact_key.replace('_', ' ').title()),
                'value': copy.deepcopy(fact.get('value')),
                'unit': fact.get('unit'),
            })
    return [inventory[key] for key in sorted(inventory)]


def sanitize_scorecard(card, *, include_evidence, public_id, disclosure_settings=None):
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
    facts = _shared_facts(card, include_evidence)
    if facts:
        kept['facts'] = facts
    kept = _scrub(kept, include_evidence)
    # Real ids are internal. The public copy gets stable positional ids that
    # only need to be unique inside this one snapshot.
    kept['id'] = public_id
    kept['analysis_id'] = public_id
    return kept if disclosure_settings is None else _filter_scorecard_disclosure(kept, disclosure_settings)


def _shared_facts(card, include_evidence):
    """Canonical stated facts as {key: {value, unit, source, label}}."""
    state = card.get('decision_state') if isinstance(card.get('decision_state'), dict) else {}
    facts = state.get('facts') if isinstance(state.get('facts'), dict) else {}
    shared = {}
    for key, fact in facts.items():
        if not isinstance(fact, dict) or fact.get('value') in (None, '', [], {}):
            continue
        item = {field: copy.deepcopy(fact[field]) for field in FACT_FIELDS if field in fact}
        if include_evidence and isinstance(fact.get('evidence'), str):
            item['evidence'] = fact['evidence']
        shared[str(key)] = item
    return shared


def _filter_scorecard_disclosure(card, settings):
    clean = copy.deepcopy(card) if isinstance(card, dict) else {}
    settings = normalize_disclosure_settings(settings)
    if settings['include_facts']:
        selected = set(settings['fact_keys'])
        facts = clean.get('facts') if isinstance(clean.get('facts'), dict) else {}
        clean['facts'] = {
            key: value for key, value in facts.items()
            if key in selected
        }
        if not clean['facts']:
            clean.pop('facts', None)
    else:
        clean.pop('facts', None)
    if not settings['include_metrics']:
        clean.pop('metrics', None)
    if not settings['include_financials']:
        for key in FINANCIAL_FIELDS:
            clean.pop(key, None)
    return clean


_HIDDEN_SECTION_FIELDS = {
    'financials': FINANCIAL_FIELDS | {'metrics'},
    'criteria': {'dimensions', 'scores', 'rubric', 'scoring_rubric', 'group_scores', 'groups'},
    'framework': {'decision_framework', 'strategic_decision_framework'},
    'insights': {'ai_insights', 'key_insights', 'key_considerations'},
    'exposure': {'assumptions'},
    'drivers': {'component_scores', 'component_rationale'},
}


def filter_public_snapshot(snapshot, disclosure_settings=None):
    """Apply protective per-link rules at read time, including old snapshots."""
    source = snapshot if isinstance(snapshot, dict) else {}
    result = {key: copy.deepcopy(source[key]) for key in PUBLIC_SNAPSHOT_FIELDS if key in source}
    if isinstance(result.get('scorecard'), dict):
        result['scorecard'] = _filter_scorecard_disclosure(result['scorecard'], disclosure_settings)
    if isinstance(result.get('scorecards'), list):
        result['scorecards'] = [
            _filter_scorecard_disclosure(card, disclosure_settings)
            for card in result['scorecards'] if isinstance(card, dict)
        ]
    presentation = result.get('presentation') if isinstance(result.get('presentation'), dict) else {}
    layout = presentation.get('layout') if isinstance(presentation.get('layout'), dict) else {}
    hidden = set(layout.get('hidden') or [])
    hidden_fields = set().union(*(_HIDDEN_SECTION_FIELDS.get(section, set()) for section in hidden)) if hidden else set()
    if hidden_fields:
        cards = ([result['scorecard']] if isinstance(result.get('scorecard'), dict) else result.get('scorecards') or [])
        for card in cards:
            for field in hidden_fields:
                card.pop(field, None)
    return result


def _excluded_values(snapshot, settings):
    settings = normalize_disclosure_settings(settings)
    cards = snapshot.get('scorecards') if isinstance(snapshot.get('scorecards'), list) else [snapshot.get('scorecard')]
    excluded = []
    for card in (item for item in cards if isinstance(item, dict)):
        facts = card.get('facts') if isinstance(card.get('facts'), dict) else {}
        selected = set(settings['fact_keys'])
        for key, fact in facts.items():
            if settings['include_facts'] and key in selected:
                continue
            if isinstance(fact, dict) and fact.get('value') not in (None, '', [], {}):
                excluded.append({'field': f'facts.{key}', 'value': fact.get('value'), 'unit': fact.get('unit'), 'key': key})
        if not settings['include_metrics']:
            for key, metric in (card.get('metrics') or {}).items():
                if isinstance(metric, dict) and metric.get('value') not in (None, '', [], {}):
                    excluded.append({'field': f'metrics.{key}', 'value': metric.get('value'), 'unit': metric.get('unit'), 'key': key})
        if not settings['include_financials']:
            for group in FINANCIAL_FIELDS:
                for path, value, unit, key in _financial_numeric_values(card.get(group), prefix=group):
                    excluded.append({'field': path, 'value': value, 'unit': unit, 'key': key})
    return excluded


_FINANCIAL_PERCENT_KEYS = frozenset({
    'irr', 'roi', 'margin', 'rate', 'percent', 'percentage', 'pct',
})
_FINANCIAL_CURRENCY_KEYS = frozenset({
    'amount', 'benefit', 'cost', 'ebitda', 'investment', 'loss', 'npv',
    'profit', 'return', 'revenue', 'savings', 'value',
})
_FINANCIAL_COUNT_KEYS = frozenset({
    'day', 'days', 'duration', 'month', 'months', 'multiple', 'rating',
    'ratings', 'year', 'years',
})


def _financial_numeric_values(value, prefix=''):
    """Yield only typed monetary/percentage numbers from financial sections.

    Financial groups also contain narrative labels, confidence words, duration
    counts, ratings, and display strings. Those are useful presentation data,
    but treating every scalar as a secret produces false disclosure warnings.
    The canonical field name supplies the type here; display strings are never
    scanned as source values.
    """
    if isinstance(value, dict):
        for key, inner in value.items():
            child = f'{prefix}.{key}' if prefix else str(key)
            if isinstance(inner, (int, float)) and not isinstance(inner, bool):
                words = {part for part in re.split(r'[^a-z0-9]+', str(key).lower()) if part}
                if words & _FINANCIAL_PERCENT_KEYS:
                    yield child, inner, 'percent', str(key)
                elif words & _FINANCIAL_CURRENCY_KEYS:
                    yield child, inner, 'currency', str(key)
                elif words & _FINANCIAL_COUNT_KEYS:
                    continue
            else:
                yield from _financial_numeric_values(inner, child)
    elif isinstance(value, list):
        for index, inner in enumerate(value):
            yield from _financial_numeric_values(inner, f'{prefix}.{index}')


_NARRATIVE_KEYS = frozenset({
    'summary', 'executive_summary', 'executive_narrative', 'strategic_rationale',
    'rationale', 'risk', 'risks', 'top_risks', 'recommendation', 'recommendations',
    'action', 'basis', 'note', 'notes', 'mitigation', 'key_insights',
    'key_considerations', 'assumptions', 'text',
})


def _narrative_strings(value, path=''):
    if isinstance(value, dict):
        for key, inner in value.items():
            child = f'{path}.{key}' if path else str(key)
            if isinstance(inner, str) and (key in _NARRATIVE_KEYS or any(part in _NARRATIVE_KEYS for part in child.split('.'))):
                yield child, inner
            else:
                yield from _narrative_strings(inner, child)
    elif isinstance(value, list):
        for index, inner in enumerate(value):
            yield from _narrative_strings(inner, f'{path}.{index}')


def _value_patterns(item):
    value, unit, key = item.get('value'), str(item.get('unit') or '').lower(), str(item.get('key') or '').lower()
    patterns = []
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        plain = f'{number:g}'
        is_percentage = 'percent' in unit or 'pct' in key or 'margin' in key or 'probability' in key or key.endswith('irr')
        is_currency = unit in {'usd', 'currency', '$'} or any(word in key for word in ('cost', 'value', 'revenue', 'investment', 'npv', 'ebitda', 'return'))
        # Typed figures keep their type. An excluded 18% margin must not match
        # unrelated prose such as "18 tasks", and an excluded $18 must not
        # match a count of 18. Untyped numbers retain the conservative bare
        # number scan.
        if not is_percentage and not is_currency:
            patterns.extend([rf'(?<![\d.]){re.escape(plain)}(?![\d.])', rf'(?<!\d){re.escape(f"{number:,.0f}")}(?!\d)'])
        if is_percentage:
            patterns.extend([rf'(?<![\d.]){re.escape(plain)}\s*%', rf'(?<![\d.]){re.escape(plain)}\s+percent\b'])
        if is_currency:
            patterns.append(rf'\$\s*{re.escape(f"{number:,.0f}")}\b')
            for divisor, suffix, word in ((1_000_000_000, 'B', 'billion'), (1_000_000, 'M', 'million'), (1_000, 'K', 'thousand')):
                if abs(number) >= divisor:
                    short = f'{number / divisor:g}'
                    patterns.extend([rf'\$?\s*{re.escape(short)}\s*{suffix}\b', rf'\$?\s*{re.escape(short)}\s+{word}\b'])
                    break
    elif isinstance(value, str) and len(value.strip()) >= 3:
        patterns.append(re.escape(value.strip()))
    return patterns


def disclosure_narrative_matches(raw_snapshot, filtered_snapshot, settings):
    excluded = _excluded_values(raw_snapshot, settings)
    matches = []
    for path, text in _narrative_strings(filtered_snapshot):
        for item in excluded:
            if any(re.search(pattern, text, re.IGNORECASE) for pattern in _value_patterns(item)):
                matches.append({'path': path, 'excluded_field': item['field'], 'excluded_value': item['value']})
    unique = {(item['path'], item['excluded_field'], str(item['excluded_value'])): item for item in matches}
    return list(unique.values())


def _contrast_ratio(hex_a, hex_b):
    def luminance(hex_value):
        channels = [int(hex_value[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    light, dark = sorted((luminance(hex_a), luminance(hex_b)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


# What each sanitize_presentation() error code means, in words an owner can act
# on. Shared by every endpoint that saves report edits.
PRESENTATION_ERRORS = {
    'invalid_presentation': 'Send the report edits as an object.',
    'invalid_colors': 'Colors must be six-digit hex values like #A0036C.',
    'low_contrast': 'That color is too light to read on white. Choose a darker shade.',
    'invalid_text': 'Report wording must be plain text.',
    'text_too_long': 'One of the text fields is too long.',
    'invalid_layout': 'That section layout is not supported.',
}


def sanitize_presentation(payload):
    """Validate owner presentation edits. Raises ValueError(code) on bad input."""
    if not isinstance(payload, dict):
        raise ValueError('invalid_presentation')
    clean = {}

    colors = payload.get('colors') or {}
    if not isinstance(colors, dict):
        raise ValueError('invalid_colors')
    kept_colors = {}
    for slot in PRESENTATION_COLOR_SLOTS:
        value = colors.get(slot)
        if value in (None, ''):
            continue
        if not isinstance(value, str) or not _HEX_COLOR.match(value):
            raise ValueError('invalid_colors')
        kept_colors[slot] = value.upper()
    # Accent and ink carry white or body text; both must stay readable on white.
    for slot in ('accent', 'ink'):
        if slot in kept_colors and _contrast_ratio(kept_colors[slot], '#FFFFFF') < 4.5:
            raise ValueError('low_contrast')
    if kept_colors:
        clean['colors'] = kept_colors

    text = payload.get('text') or {}
    if not isinstance(text, dict):
        raise ValueError('invalid_text')
    kept_text = {}
    for slot, limit in PRESENTATION_TEXT_SLOTS.items():
        value = text.get(slot)
        if value is None:
            continue
        if not isinstance(value, str):
            raise ValueError('invalid_text')
        value = value.strip()
        if len(value) > limit:
            raise ValueError('text_too_long')
        if value:
            kept_text[slot] = value
    if kept_text:
        clean['text'] = kept_text

    layout = payload.get('layout') or {}
    if not isinstance(layout, dict):
        raise ValueError('invalid_layout')
    order = layout.get('order')
    if order is not None:
        if not isinstance(order, list) or sorted(order) != sorted(PRESENTATION_SECTIONS):
            raise ValueError('invalid_layout')
    hidden = layout.get('hidden') or []
    if not isinstance(hidden, list) or any(item not in PRESENTATION_SECTIONS for item in hidden):
        raise ValueError('invalid_layout')
    variant = layout.get('evidence_variant')
    if variant is not None and variant not in PRESENTATION_EVIDENCE_VARIANTS:
        raise ValueError('invalid_layout')
    kept_layout = {}
    if order:
        kept_layout['order'] = list(order)
    if hidden:
        kept_layout['hidden'] = sorted(set(hidden), key=PRESENTATION_SECTIONS.index)
    if variant:
        kept_layout['evidence_variant'] = variant
    if kept_layout:
        clean['layout'] = kept_layout
    return clean


def card_title(card):
    if not isinstance(card, dict):
        return 'Scorecard'
    overrides = card.get('display_overrides') if isinstance(card.get('display_overrides'), dict) else {}
    for value in (overrides.get('title'), card.get('project_name'), card.get('name'), card.get('label')):
        text = str(value or '').strip()
        if text:
            return text[:255]
    return 'Scorecard'


def _report_context(strategy_objective, decision_kit, data_sources):
    """Decision framing shown as tags on the one-pager."""
    context = {}
    objective = str(strategy_objective or '').strip()
    if objective:
        context['strategy_objective'] = objective
    kit = str(decision_kit or '').strip()
    if kit:
        context['decision_kit'] = kit
    sources = [str(item).strip() for item in (data_sources or []) if str(item or '').strip()]
    if sources:
        context['data_sources'] = sources
    return context


def build_snapshot(*, artifact_type, cards, include_evidence, scorecard_id=None,
                   thread_name=None, strategy_objective=None, portfolio_summary=None,
                   decision_kit=None, data_sources=None):
    """Return (snapshot, title, source_id, evidence_available) or raise ValueError."""
    cards = [card for card in (cards or []) if isinstance(card, dict)]
    context = _report_context(strategy_objective, decision_kit, data_sources)
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
        if context:
            snapshot['context'] = context
        # A share made from the scorecard carries the owner's Workspace edits.
        overrides = card.get('display_overrides') if isinstance(card.get('display_overrides'), dict) else {}
        try:
            presentation = sanitize_presentation(overrides.get('report_presentation') or {})
        except ValueError:
            presentation = {}
        # A brand color set from chat (legacy accent_color) colors the shared
        # one-pager too, unless the report has its own accent.
        legacy_accent = str(overrides.get('accent_color') or '').strip()
        if (not (presentation.get('colors') or {}).get('accent')
                and _HEX_COLOR.match(legacy_accent)
                and _contrast_ratio(legacy_accent, '#FFFFFF') >= 4.5):
            presentation['colors'] = {**(presentation.get('colors') or {}), 'accent': legacy_accent.upper()}
        if presentation:
            snapshot['presentation'] = presentation
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
        if context:
            snapshot['context'] = context
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


def content_summary(snapshot, *, include_evidence, evidence_available, available_facts=None):
    """What a viewer will see, for the owner's preview before sharing."""
    cards = snapshot.get('scorecards') if isinstance(snapshot.get('scorecards'), list) else [snapshot.get('scorecard')]
    cards = [c for c in cards if isinstance(c, dict)]

    def _has(*keys):
        return any(c.get(k) not in (None, '', [], {}) for c in cards for k in keys)

    return {
        'scorecard_count': len(cards),
        'evidence_quotes_available': int(evidence_available),
        'evidence_quotes_included': bool(include_evidence and evidence_available),
        'available_facts': list(available_facts or []),
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
