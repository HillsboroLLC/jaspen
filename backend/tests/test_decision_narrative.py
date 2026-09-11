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
        'excluded_unconfirmed': [],
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


# ---------------------------------------------------------------------------
# Causality (spec §8)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('sentence', [
    'The evidence-backed share moved from 38 to 71 because Jaspen asked for the source.',
    'Jaspen requested evidence; therefore the grade rose.',
    'Asking for the export led to 3 assumptions being supported.',
    'Jaspen challenged the criterion, resulting in a higher share.',
    'The request caused the figure to move.',
    'Analysis revealed that the basis was thin.',
    'Evidence coverage improved from 38 to 71.',
    'Validating 3 assumptions strengthened the basis.',
])
def test_at77_causal_language_fails_containment(sentence):
    """AT-77 Every figure in these is legitimate. The RELATIONSHIP is not.

    The ledger records that Jaspen asked for a source on a criterion, and
    separately that the criterion later graded higher. It does not record that
    the first caused the second — and asserting it would invent the single most
    valuable claim in the report.
    """
    grounded = grounding(_impact(), CONTEXT)
    ok, problem = passes_containment(sentence, grounded)
    assert ok is False
    assert 'causal claim' in problem


def test_at77b_additive_construction_passes():
    """AT-77b The same facts, stated without inventing a link between them."""
    grounded = grounding(_impact(), CONTEXT)
    ok, problem = passes_containment(
        'The set of alternatives is unchanged at 2. During the analysis the '
        'evidence-backed share moved from 38 to 71. Jaspen also recorded 3 '
        'assumptions validated.',
        grounded,
    )
    assert ok is True and problem is None


def test_at77c_word_boundaries_prevent_false_positives():
    """AT-77c A banned word inside an innocent one must not trip the check."""
    grounded = grounding(_impact(), CONTEXT)
    ok, problem = passes_containment(
        'The 3 items were tabled and the count of 2 was unchanged.', grounded,
    )
    assert ok is True, problem


def test_at77f_an_option_name_containing_a_digit_does_not_break_the_template():
    """AT-77f Found by the demo fixtures: the template names the leading
    option, so "Renew 5 years" put a digit in the paragraph that containment
    had no record of. The name is a fact the narrative was handed."""
    grounded = grounding(_impact(), {'leading_option': 'Renew 5 years'})
    ok, problem = passes_containment(
        'The leading option is Renew 5 years.', grounded,
    )
    assert ok is True, problem


def test_at77d_the_deterministic_template_obeys_the_same_rule(app, db, test_user):
    """AT-77d The fallback is held to the constraint it falls back to.

    A template that quietly used causal phrasing would make the rule cosmetic:
    most reports render the template.
    """
    from app.decision_impact import compose_narrative

    for verdict in ('material', 'limited', 'no_material_change'):
        for context in (CONTEXT, {'leading_option': 'Renew 5 years'}):
            impact = _impact(verdict=verdict)
            text = compose_narrative(impact, context)
            ok, problem = passes_containment(text, grounding(impact, context))
            assert ok is True, f'{verdict} / {context}: {problem}'


def test_at77e_the_prompt_tells_the_model_what_to_write_instead():
    """AT-77e Banning without an alternative just produces refusals."""
    from app.decision_narrative import PREFERRED_CONNECTIVES, SYSTEM_PROMPT

    lowered = SYSTEM_PROMPT.lower()
    assert 'because' in lowered and 'therefore' in lowered
    for preferred in PREFERRED_CONNECTIVES:
        assert preferred in lowered
    assert 'moved from' in lowered
