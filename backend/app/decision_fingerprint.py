"""Compatibility wrapper around the shared canonical decision state."""

from .decision_state import canonical_decision_state, decision_state_fingerprint


def scoring_fingerprint(
    *, option_key, attributes, rubric, objective, decision_kit,
    decision_kit_version, evidence_corpus=None, facts_text=None,
    option_name=None, canonical_evidence=None, gates=None,
    methodology_key=None, methodology_version=None, model_tier=None,
):
    # Raw prose is intentionally excluded. The extraction layer must turn any
    # material semantic change into validated facts/evidence before scoring.
    state = canonical_decision_state(
        option_key=option_key,
        option_name=option_name,
        attributes=attributes,
        rubric=rubric,
        objective=objective,
        gates=gates or ((rubric or {}).get("criteria") or []),
        decision_kit=decision_kit,
        decision_kit_version=decision_kit_version,
        canonical_evidence=canonical_evidence,
        **({"methodology_key": methodology_key} if methodology_key is not None else {}),
        **({"methodology_version": methodology_version} if methodology_version is not None else {}),
        model_tier=model_tier,
    )
    return decision_state_fingerprint(state)
