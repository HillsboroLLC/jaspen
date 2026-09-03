"""The "What changed" narrative — containment tests.

docs/DECISION_IMPACT_REPORT_SPEC.md §8. This is the only section of the report
a model writes, and every test here is about the fence around it: what it is
allowed to see, what it is allowed to say, and what happens when it says
something else.

The rule the tests exist to hold: a narrative that fails containment is
DISCARDED, never repaired. A half-corrected sentence is a sentence nobody
verified.
"""

import pathlib

import pytest

from app.decision_narrative import (
    FORBIDDEN_CLAIMS,
    MAX_NARRATIVE_CHARS,
    allowed_numbers,
    compose,
    grounding,
    passes_containment,
)

BACKEND = pathlib.Path(__file__).resolve().parents[1]

TEMPLATE = 'The deterministic paragraph.'


def _impact(**overrides):
    base = {
        'verdict': 'material',
        'verified_comparison': True,
        'moved': [
            {'id': 'B1', 'label': 'Evidence-backed share', 'from': 38, 'to': 71,
             'delta': 33, 'threshold': 'STRONG_PP', 'strong': True,
             'family': 'B'},
        ],
        'unmoved': [{'id': 'A1', 'label': 'Alternatives evaluated', 'from': 2, 'to': 2}],
        'interventions': [
            {'id': 'B4', 'label': 'Assumptions validated', 'count': 3,
             'qualifying': True, 'strong': True, 'family': 'B'},
            {'id': 'B5', 'label': 'Uncertainties made explicit', 'count': 0,
             'qualifying': False, 'strong': False, 'family': 'B'},
        ],
        'not_applicable': [{'id': 'A5', 'label': 'Execution dependencies',
                            'reason': 'no implementation phase'}],
        'attribution_cap_applied': False,
    }
    base.update(overrides)
    return base


CONTEXT = {'leading_option': 'Option A'}


# ---------------------------------------------------------------------------
# What the model is allowed to see
# ---------------------------------------------------------------------------

def test_the_model_never_sees_the_decision_itself():
    """It cannot introduce a fact because it is never given one to introduce."""
    grounded = grounding(_impact(), CONTEXT)

    assert set(grounded) == {
        'verdict', 'state_changes', 'unchanged', 'work_jaspen_did',
        'out_of_scope', 'attribution_withheld', 'leading_option',
    }
    # No transcript, no scorecards, no recommendation prose, no user words.
    serialized = str(grounded)
    for leaked in ('chat_history', 'executive_summary', 'rationale', 'submission'):
        assert leaked not in serialized


def test_interventions_reach_the_narrative_as_work_not_as_deltas():
    grounded = grounding(_impact(), CONTEXT)

    assert grounded['work_jaspen_did'] == [
        {'kind': 'Assumptions validated', 'count': 3},
    ]
    # An intervention never appears as a from/to pair.
    assert all('from' not in change or change['measure'] != 'Assumptions validated'
               for change in grounded['state_changes'])


def test_an_unqualifying_intervention_is_not_offered_to_the_model():
    grounded = grounding(_impact(), CONTEXT)
    assert all(work['kind'] != 'Uncertainties made explicit'
               for work in grounded['work_jaspen_did'])


# ---------------------------------------------------------------------------
# Containment
# ---------------------------------------------------------------------------

def test_a_figure_the_model_invented_fails_containment():
    grounded = grounding(_impact(), CONTEXT)
    ok, problem = passes_containment(
        'Evidence coverage rose from 38 to 71 and 12 risks were added.', grounded,
    )
    assert ok is False
    assert '12' in problem


def test_a_faithful_paragraph_passes():
    grounded = grounding(_impact(), CONTEXT)
    ok, problem = passes_containment(
        'The set of alternatives is unchanged at 2. What changed is the basis: '
        'the evidence-backed share moved from 38 to 71, and 3 assumptions that '
        'carried the decision at intake are now supported.',
        grounded,
    )
    assert ok is True and problem is None


@pytest.mark.parametrize('claim', ['better decision', 'more likely to succeed', 'guarantee'])
def test_outcome_claims_fail_containment(claim):
    """The report describes the RECORD. It never claims the decision improved."""
    grounded = grounding(_impact(), CONTEXT)
    ok, problem = passes_containment(f'This is a {claim} now.', grounded)
    assert ok is False
    assert 'forbidden claim' in problem


def test_an_over_long_paragraph_fails():
    grounded = grounding(_impact(), CONTEXT)
    ok, _ = passes_containment('word ' * (MAX_NARRATIVE_CHARS), grounded)
    assert ok is False


def test_allowed_numbers_are_exactly_what_was_handed_over():
    grounded = grounding(_impact(), CONTEXT)
    permitted = allowed_numbers(grounded)
    assert {'38', '71', '3'} <= permitted
    assert '99' not in permitted


# ---------------------------------------------------------------------------
# Fallback behaviour
# ---------------------------------------------------------------------------

def test_a_failing_narrative_is_discarded_not_repaired(app, monkeypatch):
    import app.decision_narrative as narrative

    monkeypatch.setattr(
        narrative, '_model_paragraph',
        lambda grounded: ('Coverage rose from 38 to 71 and 12 new risks appeared.', 'm'),
    )
    with app.app_context():
        text, generated_by, model_id = compose(_impact(), CONTEXT, template=TEMPLATE)

    assert text == TEMPLATE
    assert generated_by == 'template'
    assert model_id is None


def test_a_passing_narrative_is_used(app, monkeypatch):
    import app.decision_narrative as narrative

    good = 'The evidence-backed share moved from 38 to 71, and 3 assumptions are now supported.'
    monkeypatch.setattr(narrative, '_model_paragraph', lambda grounded: (good, 'test-model'))
    with app.app_context():
        text, generated_by, model_id = compose(_impact(), CONTEXT, template=TEMPLATE)

    assert text == good
    assert generated_by == 'model'
    assert model_id == 'test-model'


def test_with_no_model_available_the_template_renders(app):
    """The evidence layer never depends on a model being reachable."""
    with app.app_context():
        text, generated_by, model_id = compose(_impact(), CONTEXT, template=TEMPLATE)
    assert (text, generated_by, model_id) == (TEMPLATE, 'template', None)


def test_at74_an_unverified_baseline_gets_no_comparative_narrative(app, monkeypatch):
    """AT-74 There is no comparison to explain, and prose about one would be
    the fiction §5.6 refuses to publish in numbers."""
    import app.decision_narrative as narrative

    called = []
    monkeypatch.setattr(
        narrative, '_model_paragraph',
        lambda grounded: called.append(grounded) or ('anything at all', 'm'),
    )
    unverified = _impact(verdict='unverified_baseline', verified_comparison=False)

    with app.app_context():
        text, generated_by, model_id = compose(unverified, CONTEXT, template=TEMPLATE)

    assert text == TEMPLATE
    assert generated_by == 'template'
    assert called == []          # the model was never even asked


# ---------------------------------------------------------------------------
# Separation from the evidence layer
# ---------------------------------------------------------------------------

def test_at75_the_measure_path_remains_model_free():
    """AT-75 The narrative may describe the report; it may not be reachable
    from anything that computes it."""
    impact_source = (BACKEND / 'app' / 'decision_impact.py').read_text().lower()
    code = '\n'.join(
        line for line in impact_source.splitlines() if not line.strip().startswith('#')
    )
    for token in ('anthropic', 'openai', 'genai', 'gemini'):
        assert token not in code


def test_at76_the_narrative_cannot_alter_a_measure_or_a_verdict():
    """AT-76 It receives the finished impact block and returns a string."""
    import inspect as _inspect

    signature = _inspect.signature(compose)
    assert list(signature.parameters) == ['impact', 'context', 'template']

    source = _inspect.getsource(compose)
    for mutation in ("impact[", "impact.update", "context["):
        assert f'{mutation}' not in source or 'impact.get' in source


def test_forbidden_claims_cover_the_outcome_language_the_spec_bans():
    lowered = ' '.join(FORBIDDEN_CLAIMS)
    for required in ('better decision', 'guarantee', 'succeed'):
        assert required in lowered
