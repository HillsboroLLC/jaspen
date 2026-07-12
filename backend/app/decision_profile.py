"""Decision Style Assessment mapping and profile copy.

The public frontend owns the question copy, but the backend must verify the
submitted result before storing or emailing it. Keep this data aligned with
frontend/src/homeSections/HomePage/DecisionStyleAssessment/assessmentData.js.
"""

FALLBACK_STYLE_KEY = "practical_optimizer"

STYLES = {
    "evidence_builder": {
        "key": "evidence_builder",
        "name": "Evidence Builder",
        "blurb": (
            "You tend to feel most comfortable committing once you have enough "
            "information to explain why the decision makes sense."
        ),
    },
    "fast_mover": {
        "key": "fast_mover",
        "name": "Fast Mover",
        "blurb": (
            "You tend to read a situation quickly and act, trusting that "
            "momentum and a clear instinct will carry the decision."
        ),
    },
    "thoughtful_explorer": {
        "key": "thoughtful_explorer",
        "name": "Thoughtful Explorer",
        "blurb": (
            "You tend to open up several possibilities before settling, giving "
            "each option a genuine look before you choose."
        ),
    },
    "consensus_seeker": {
        "key": "consensus_seeker",
        "name": "Consensus Seeker",
        "blurb": (
            "You tend to decide with others in mind, weighing perspectives so "
            "the choice holds up for everyone it touches."
        ),
    },
    "practical_optimizer": {
        "key": "practical_optimizer",
        "name": "Practical Optimizer",
        "blurb": (
            "You tend to balance instinct and information, moving efficiently "
            "toward a choice that simply works."
        ),
    },
    "reflective_analyzer": {
        "key": "reflective_analyzer",
        "name": "Reflective Analyzer",
        "blurb": (
            "You tend to think decisions through carefully and revisit them "
            "later, learning from how they turned out."
        ),
    },
}

STYLE_ORDER = [
    "evidence_builder",
    "reflective_analyzer",
    "thoughtful_explorer",
    "practical_optimizer",
    "consensus_seeker",
    "fast_mover",
]

OPTION_SIGNALS = {
    "q1_a": {"fast_mover": 2},
    "q1_b": {"practical_optimizer": 2, "fast_mover": 1},
    "q1_c": {"consensus_seeker": 3, "practical_optimizer": 1},
    "q1_d": {"evidence_builder": 2, "thoughtful_explorer": 1},
    "q1_e": {"evidence_builder": 2, "reflective_analyzer": 1},
    "q2_a": {"reflective_analyzer": 2, "thoughtful_explorer": 1},
    "q2_b": {"reflective_analyzer": 1},
    "q2_c": {"practical_optimizer": 1},
    "q2_d": {"practical_optimizer": 1, "evidence_builder": 1},
    "q2_e": {"fast_mover": 2},
    "q3_a": {"fast_mover": 2},
    "q3_b": {"fast_mover": 1},
    "q3_c": {"practical_optimizer": 1},
    "q3_d": {"evidence_builder": 1, "reflective_analyzer": 1},
    "q3_e": {"evidence_builder": 2},
    "q3_na": {},
    "q4_none": {"fast_mover": 2},
    "q4_1_2": {"practical_optimizer": 2},
    "q4_3_5": {"thoughtful_explorer": 2, "evidence_builder": 1},
    "q4_5_plus": {"thoughtful_explorer": 2, "reflective_analyzer": 1},
    "q4_na": {},
    "q5_a": {"fast_mover": 2},
    "q5_b": {"practical_optimizer": 1},
    "q5_c": {"practical_optimizer": 1, "thoughtful_explorer": 1},
    "q5_d": {"evidence_builder": 1, "reflective_analyzer": 1},
    "q5_e": {"evidence_builder": 2},
    "q5_na": {},
    "q6_a": {"fast_mover": 2},
    "q6_b": {"practical_optimizer": 1},
    "q6_c": {"thoughtful_explorer": 1},
    "q6_d": {"evidence_builder": 1, "thoughtful_explorer": 1},
    "q6_e": {"evidence_builder": 2, "reflective_analyzer": 1},
    "q6_na": {},
    "q7_a": {"fast_mover": 1},
    "q7_b": {},
    "q7_c": {"practical_optimizer": 1},
    "q7_d": {"reflective_analyzer": 1},
    "q7_e": {"reflective_analyzer": 2},
}


def validate_answers(answers):
    if answers is None:
        raise ValueError("assessment_answers_required")
    if not isinstance(answers, dict):
        raise ValueError("assessment_answers_invalid")
    if not answers:
        raise ValueError("assessment_answers_required")
    if len(answers) > 7:
        raise ValueError("assessment_answers_invalid")
    for question_id, option_id in answers.items():
        if not isinstance(question_id, str) or not isinstance(option_id, str):
            raise ValueError("assessment_answers_invalid")
        if option_id not in OPTION_SIGNALS:
            raise ValueError("assessment_option_invalid")
    return dict(answers)


def tally_affinity(answers):
    totals = {key: 0 for key in STYLE_ORDER}
    for option_id in answers.values():
        for style_key, weight in OPTION_SIGNALS.get(option_id, {}).items():
            totals[style_key] += weight
    return totals


def derive_decision_style(answers):
    validated = validate_answers(answers)
    totals = tally_affinity(validated)
    best_key = FALLBACK_STYLE_KEY
    best_score = 0
    for key in STYLE_ORDER:
        if totals[key] > best_score:
            best_key = key
            best_score = totals[key]
    return {
        "style": STYLES[best_key],
        "is_fallback": best_score <= 0,
        "affinity": totals,
    }
