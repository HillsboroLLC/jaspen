# backend/app/decision_narrative.py
#
# "What changed" — the one section of the Decision Impact Report a model is
# allowed to write (spec §8). Phase 3.
#
# WHY THIS IS A SEPARATE MODULE
#
# decision_impact.py must stay provably model-free: its measures, its deltas
# and its verdict are the report's claim to being checkable, and a test asserts
# no model client is reachable from that file. The narrative is the only place
# where prose is generated, so it lives on its own side of that line. Nothing
# in here can change a measure, a movement, an intervention count or a verdict
# — it receives them already computed and may only describe them.
#
# CONTAINMENT, AND WHY IT IS MECHANICAL
#
# The model gets the deltas and the qualifying ledger events. It does not get
# the transcript, the scorecards, the recommendation, or the user's own words.
# It cannot introduce a fact because it is never given one to introduce.
#
# That is not enough on its own, because a model can still invent. So every
# numeral in the returned prose must match a value it was handed, and a short
# list of claims the report is never allowed to make is checked for outright.
# A narrative failing either check is DISCARDED, not repaired: a half-corrected
# sentence is a sentence nobody verified. The deterministic template then
# renders instead, which is also what renders when no model is available at
# all. The evidence layer never depends on a model being reachable.

import os
import re

from flask import current_app

# Claims the report may never make, however fluently. These are about the
# DECISION or its outcome; this report only ever describes the decision RECORD
# (spec §0.1). Matched case-insensitively as substrings.
FORBIDDEN_CLAIMS = (
    'better decision',
    'right decision',
    'more likely to succeed',
    'will succeed',
    'guarantee',
    'guaranteed',
    'proves',
    'proven',
    'i think',
    'i believe',
    'in my view',
    'we recommend',
    'you should',
)

MAX_NARRATIVE_CHARS = 1200

SYSTEM_PROMPT = (
    'You write one short paragraph explaining what changed about a decision '
    'record during analysis. You are given computed figures and a list of '
    'recorded analytical events. Explain those and nothing else.\n\n'
    'Absolute rules:\n'
    '- Never introduce a fact, number, cause, risk or conclusion that is not '
    'in the input. Every figure you write must appear in the input.\n'
    '- Never claim the decision improved, is more likely to be correct, or '
    'that value was created. You are describing the RECORD, not the decision.\n'
    '- Never characterise what the user originally believed or thought. The '
    'input records what was submitted, not anyone\'s state of mind.\n'
    '- Never restate the verdict as your own judgment.\n'
    '- Do not use headings, bullets or markdown. One paragraph, plain prose, '
    'at most six sentences.'
)


def _numbers_in(text):
    return {match.group() for match in re.finditer(r'\d+(?:\.\d+)?', str(text or ''))}


def grounding(impact, context):
    """The complete and only input the model may see.

    Everything here was computed by decision_impact. Assembling it explicitly,
    rather than handing over the impact dict, is what keeps the transcript, the
    scorecards and the recommendation out of reach.
    """
    return {
        'verdict': impact['verdict'],
        'state_changes': [
            {
                'measure': movement['label'],
                'from': movement['from'],
                'to': movement['to'],
                'kind': 'percentage' if movement['id'] in ('B1', 'B2') else 'count',
            }
            for movement in impact.get('moved', [])
        ],
        # Values, not just labels: what held still is half of what makes the
        # report credible, and the paragraph should be able to say so plainly
        # ("the two alternatives are unchanged") rather than gesture at it.
        # These are deterministic state facts the report already publishes.
        'unchanged': [
            {'measure': entry['label'], 'value': entry.get('to')}
            for entry in impact.get('unmoved', [])
        ],
        'work_jaspen_did': [
            {'kind': entry['label'], 'count': entry['count']}
            for entry in impact.get('interventions', []) if entry['qualifying']
        ],
        'out_of_scope': [entry['label'] for entry in impact.get('not_applicable', [])],
        'attribution_withheld': impact.get('attribution_cap_applied', False),
        'leading_option': context.get('leading_option'),
    }


def allowed_numbers(grounded):
    """Every numeral the narrative is permitted to contain."""
    allowed = set()
    for change in grounded['state_changes']:
        allowed |= _numbers_in(change['from']) | _numbers_in(change['to'])
    for entry in grounded['unchanged']:
        allowed |= _numbers_in(entry.get('value'))
    for work in grounded['work_jaspen_did']:
        allowed |= _numbers_in(work['count'])
    # Counts of the lists themselves: "three measures were unchanged".
    for size in (
        len(grounded['state_changes']), len(grounded['unchanged']),
        len(grounded['work_jaspen_did']), len(grounded['out_of_scope']),
    ):
        allowed.add(str(size))
    return allowed


def passes_containment(text, grounded):
    """Would this paragraph survive someone checking it against the figures?"""
    body = str(text or '').strip()
    if not body or len(body) > MAX_NARRATIVE_CHARS:
        return False, 'empty or over length'

    lowered = body.lower()
    for phrase in FORBIDDEN_CLAIMS:
        if phrase in lowered:
            return False, f'forbidden claim: {phrase!r}'

    permitted = allowed_numbers(grounded)
    for number in _numbers_in(body):
        if number not in permitted:
            return False, f'figure not in the input: {number}'

    return True, None


def _model_paragraph(grounded):
    """One attempt at model prose. Returns (text, model_id) or (None, None)."""
    if str(os.getenv('DECISION_IMPACT_NARRATIVE', 'on')).strip().lower() in ('off', '0', 'false'):
        return None, None

    api_key = (
        current_app.config.get('ANTHROPIC_API_KEY')
        or current_app.config.get('CLAUDE_API_KEY')
        or os.getenv('ANTHROPIC_API_KEY')
        or os.getenv('CLAUDE_API_KEY')
    )
    if not api_key:
        return None, None

    # Same resolution chain as the existing report renderer, so the model in
    # use is configured in one place rather than pinned here.
    model_name = (
        current_app.config.get('AI_REPORT_MODEL')
        or os.getenv('AI_REPORT_MODEL')
        or current_app.config.get('AI_AGENT_ANTHROPIC_MODEL')
        or os.getenv('AI_AGENT_ANTHROPIC_MODEL')
    )
    if not model_name:
        return None, None

    try:
        import json

        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model_name,
            temperature=0.1,
            max_tokens=500,
            system=SYSTEM_PROMPT,
            messages=[{'role': 'user', 'content': json.dumps(grounded, indent=2)}],
        )
        parts = [
            str(getattr(block, 'text', '') or '').strip()
            for block in (getattr(response, 'content', []) or [])
            if getattr(block, 'type', None) == 'text'
        ]
        return ' '.join(part for part in parts if part).strip() or None, model_name
    except Exception:  # noqa: BLE001 — the template is always a valid answer
        current_app.logger.info(
            'decision_impact: narrative model unavailable, using the template',
            exc_info=True,
        )
        return None, None


def compose(impact, context, *, template):
    """The "What changed" section.

    Returns (text, generated_by, model_id). `template` is the deterministic
    paragraph decision_impact already composed — it is the fallback, and for an
    unverified baseline it is the ONLY answer: there is no comparison to
    explain, and prose about one would be the exact fiction §5.6 refuses to
    publish in numbers.
    """
    if impact.get('verified_comparison') is False:
        return template, 'template', None

    grounded = grounding(impact, context)
    text, model_name = _model_paragraph(grounded)
    if not text:
        return template, 'template', None

    ok, problem = passes_containment(text, grounded)
    if not ok:
        current_app.logger.warning(
            'decision_impact: narrative discarded (%s); using the template', problem,
        )
        return template, 'template', None

    return text, 'model', model_name
