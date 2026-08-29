# backend/app/confidence_check.py
#
# The first-run Confidence Check: what Jaspen can honestly tell someone before
# a scorecard exists.
#
# WHY THIS IS A SEPARATE MODULE FROM THE THING IT SOUNDS LIKE
#
# app/decision_confidence.py computes Decision Confidence from a SCORED
# decision: graded criteria, rubric weights, caps, exposure. None of that
# exists at first run. The pre-signup intake is deterministic by design (see
# routes/public_intake.py): no model call, no session, no scorecard. There are
# no criteria to grade and no weights to grade them against.
#
# So this module must never present its numbers as Decision Confidence.
# It measures something genuinely different:
#
#   Decision Confidence   how much of a SCORED decision stands on evidence
#   Context coverage      how much of the CONTEXT Jaspen needs has been given
#
# Both are honest. They are not the same measurement, and relabelling one as
# the other would be exactly the unfounded number the product exists to
# surface. Every field below is named for what it actually measures, and
# `measures` carries that definition alongside the figure so no surface can
# quietly restate it as something stronger.
#
# WHAT MAKES THE OUTPUT WORTH READING ANYWAY
#
# The readiness engine already scores an evidence baseline directly: whether a
# number, a metric type, a timeframe, a baseline, and a source are present.
# That is a real evidence signal, available before anyone signs up. Combined
# with the published cap table, it supports a statement that is both true and
# useful on a first visit:
#
#   "You have given a number and a timeframe, but no source. In Jaspen a
#    judgment with nothing verifiable behind it is graded assumed, and an
#    assumed judgment contributes at most 45 of 100 however strong the case
#    sounds."
#
# That describes the mechanism and the input. It does not predict what a model
# will grade, because the grade is a model judgment this module cannot make.
# Read the difference carefully before extending anything here.
#
# This module imports from intake_readiness read-only and never mutates the
# spec, the questions, or the thresholds. Changing what the homepage asks is
# explicitly out of scope: see that module's header.

from .decision_confidence import CONFIDENCE_CAPS
from .intake_readiness import _active_readiness_spec

# What each evidence-baseline check means to a person, and the order they read
# in. Mirrors the checks _score_data_evidence performs. Kept here rather than
# in the readiness engine so adding a sentence never risks touching scoring.
EVIDENCE_CHECKS = (
    ("has_number", "A number to anchor the decision"),
    ("has_metric_type", "A financial or KPI metric it belongs to"),
    ("has_timeframe", "A timeframe it applies over"),
    ("has_baseline_target", "A baseline or target to measure against"),
    ("has_source", "A source the number can be traced to"),
)

# The cap an ungrounded judgment cannot exceed. Quoted from the same table the
# scoring engine enforces, so the promise made at first run and the arithmetic
# applied after signup cannot drift.
ASSUMED_CAP = CONFIDENCE_CAPS["assumed"]

CONTEXT_COVERAGE_MEANING = (
    "Share of the context Jaspen needs before it can score this decision. "
    "This is not an evidence-backed percentage: nothing has been scored yet."
)


def _categories(readiness):
    raw = readiness.get("categories") if isinstance(readiness, dict) else None
    return [c for c in (raw or []) if isinstance(c, dict)]


def _questions_by_category(spec):
    """Follow-up prompts the active spec already defines, keyed by category."""
    mapping = {}
    for cat in (spec.get("categories") or []):
        if isinstance(cat, dict) and cat.get("key"):
            mapping[str(cat["key"])] = cat
    return mapping


def evidence_baseline(readiness):
    """Which parts of a measurable baseline are present, and which are not.

    Returns None when the active spec has no evidence category, rather than
    inventing a result. A profile that does not measure evidence has not
    measured it.
    """
    if not isinstance(readiness, dict):
        return None
    checks = readiness.get("evidence_quality")
    if not isinstance(checks, dict):
        return None

    present, missing = [], []
    for key, label in EVIDENCE_CHECKS:
        (present if checks.get(key) else missing).append({"key": key, "label": label})

    return {
        "present": present,
        "missing": missing,
        "quality_score": checks.get("quality_score"),
        "metric_type": checks.get("metric_type_detected"),
        # Stated as a property of the input, not a prediction of a grade. The
        # confidence grade is a model judgment made after scoring; what is
        # knowable here is only that nothing verifiable has been supplied yet.
        "ungrounded": not checks.get("has_source"),
        "assumed_cap": ASSUMED_CAP,
    }


def context_gaps(readiness, spec=None):
    """Incomplete categories, ranked by how much of the context they carry.

    Ranking by weight is the intake-level analogue of ranking assumptions by
    swing: a gap worth a fifth of the context matters more than one worth
    nothing, and a register in spec order buries that.
    """
    spec = spec or _active_readiness_spec()
    defined = _questions_by_category(spec)

    gaps = []
    for cat in _categories(readiness):
        if cat.get("completed"):
            continue
        key = str(cat.get("key") or "")
        weight = float(cat.get("weight") or 0)
        source = defined.get(key, {})
        gaps.append({
            "key": key,
            "label": cat.get("label") or key,
            "weight": round(weight, 4),
            "required": bool(cat.get("required")),
            "percent": int(cat.get("percent") or 0),
            "step": source.get("step") or cat.get("step"),
        })

    # Required gates first: they block scoring outright regardless of weight,
    # so presenting a heavier optional gap above them would misdirect effort.
    gaps.sort(key=lambda g: (not g["required"], -g["weight"], g["key"]))
    return gaps


def build_confidence_check(readiness, spec=None):
    """The first-run finding, assembled from a readiness payload.

    Pure: takes the payload the readiness engine already produced and returns
    a rendering-ready structure. No model call, no spec mutation, no scoring.
    """
    if not isinstance(readiness, dict):
        return None

    spec = spec or _active_readiness_spec()
    categories = _categories(readiness)
    if not categories:
        return None

    overall = readiness.get("overall") if isinstance(readiness.get("overall"), dict) else {}
    coverage = int(overall.get("percent") or readiness.get("percent") or 0)

    gaps = context_gaps(readiness, spec)
    baseline = evidence_baseline(readiness)
    covered = [c for c in categories if c.get("completed")]

    return {
        # Named for what it measures. Deliberately NOT evidence_backed_pct.
        "context_coverage_pct": coverage,
        "measures": CONTEXT_COVERAGE_MEANING,
        "scored": False,
        "covered": [
            {"key": c.get("key"), "label": c.get("label"), "weight": c.get("weight")}
            for c in covered
        ],
        "gaps": gaps,
        "evidence_baseline": baseline,
        "counts": {
            "categories": len(categories),
            "covered": len(covered),
            "gaps": len(gaps),
            "blocking": sum(1 for g in gaps if g["required"]),
        },
        "claims": check_claims(coverage, gaps, baseline),
    }


def check_claims(coverage, gaps, baseline):
    """The sentences this check supports, and only those.

    Same contract as decision_confidence.exposure_claims: a claim absent from
    this list was not computed and must not be rendered. Phrasing lives here so
    the homepage, the workspace, and any export cannot each invent their own.

    Order is deliberate and is the point of this branch. Coverage is last, not
    first. A first-time user arrives with a sentence and legitimately scores
    near zero, and opening on "Jaspen has 0% of the context it needs" is the
    same wall the old readiness checklist put up, only rephrased. Leading with
    what Jaspen can already tell them from that sentence, and closing with how
    much context remains, changes the finding from a refusal into a result
    without changing a single number.
    """
    claims = []

    blocking = [g for g in gaps if g["required"]]
    if blocking:
        names = ", ".join(g["label"] for g in blocking)
        claims.append({
            "kind": "blocking",
            "text": f"Two things have to be in place before any score is meaningful: {names}."
            if len(blocking) > 1
            else f"One thing has to be in place before any score is meaningful: {names}.",
        })

    if baseline and baseline["missing"]:
        missing = baseline["missing"]
        claims.append({
            "kind": "evidence_baseline",
            "text": (
                f"Your evidence baseline is missing {len(missing)} of "
                f"{len(EVIDENCE_CHECKS)} parts: "
                + ", ".join(m["label"].lower() for m in missing)
                + "."
            ),
        })

    if baseline and baseline["ungrounded"]:
        claims.append({
            "kind": "cap_consequence",
            "text": (
                "Nothing here is traceable to a source yet. In Jaspen a judgment "
                "with nothing verifiable behind it is graded assumed, and an "
                f"assumed judgment contributes at most {ASSUMED_CAP} out of 100 "
                "however strong the case sounds. Better evidence raises that "
                "ceiling. A better argument does not."
            ),
        })

    claims.append({
        "kind": "coverage",
        "text": (
            f"Jaspen has {coverage}% of the context it needs to score this decision."
        ),
    })

    return claims
