# backend/app/decision_report.py
#
# One assembly of the Decision Confidence report, read by every surface that
# renders it: the workspace, the emailed HTML, and the PowerPoint export.
#
# WHY THIS EXISTS RATHER THAN EACH EXPORT BUILDING ITS OWN
#
# The report makes claims about how much of a decision rests on evidence. If
# the email composed its own sentences from the same numbers, the three
# surfaces would drift, and a customer would eventually forward a deck saying
# one thing while the workspace said another about the same decision. Every
# claim here comes from exposure_claims() and decision_summary(); nothing in
# this module writes a sentence about a decision.
#
# SHAPE IS THE CALLER'S JOB. This returns content, not layout. The email is a
# document and renders all of it. The deck is read from across a room and
# renders a subset at a different density. That difference is deliberate: a
# deck that is the email with slide breaks is a bad deck.
#
# The two limits from the modules underneath travel with the content and must
# not be exceeded by any renderer:
#
#   PROVENANCE  `assessment` is Jaspen's own reasoning, not a source citation.
#               Only `evidence` entries were verified against the input.
#   SCOPE       Exposure is upside only. Resolving evidence can raise a score;
#               nothing here models what happens if an assumption is false.

from .decision_confidence import (
    SEVERITY_MATERIAL,
    SEVERITY_REVERSING,
    decision_exposure,
    decision_summary,
)

# How each grade reads in an export. Matches the workspace so a reader moving
# between them sees the same words for the same grade.
GRADE_LABELS = {
    "high": "Strong evidence",
    "medium": "Moderate evidence",
    "low": "Thin evidence",
    "assumed": "Assumed",
}

# Hedged for the same reason the workspace hedges: `source` is the model's own
# claim about a channel and nothing verifies it.
ASSESSMENT_BASIS = {
    "conversation": "Based on what you described",
    "connector": "Jaspen reports drawing on connected data",
    "inferred": "Inferred rather than stated",
    "assumed": "No supporting input identified",
}

# What a person can do about a criterion when the scoring pass named nothing.
# Mirrors FALLBACK_ACTION_BY_GRADE in DecisionConfidenceCard.jsx.
#
# This matters most OUTSIDE the workspace. The point of the guidance is that a
# report can be forwarded to Finance, Ops or Procurement as "here is the
# current analysis, get me these inputs and I will rerun it". An export that
# states the exposure and omits the ask cannot do that job.
#
# Deliberately generic: a fallback naming a specific document would imply
# Jaspen knew that document existed.
FALLBACK_ACTION_BY_GRADE = {
    "high": None,
    "medium": "Share the source behind this, a document, export, or connected system, so it can be verified rather than taken as reported.",
    "low": "Provide the underlying figures or documents for this criterion so more of it rests on evidence.",
    "assumed": "Nothing verifiable supports this yet. Upload or connect the source that would establish it.",
}

UNSUPPORTED_BY_GRADE = {
    "high": None,
    "medium": "Self-reported rather than verified, so this contributes at most 75.",
    "low": "Only partially supported, so this contributes at most 60.",
    "assumed": "Nothing verifiable behind this yet, so it contributes at most 45.",
}

PROVENANCE_NOTE = (
    "Jaspen's assessment is its own reasoning about the inputs it was given. "
    "Jaspen cannot yet identify the specific document, message, or record "
    "behind a judgment, so nothing here should be read as a source citation "
    "or an audit trail."
)


def _text(value):
    return str(value or "").strip()


def evidence_source_label(reference):
    """A short human source for one verified reference.

    Raw locators are provenance, not reading material, and are deliberately
    absent from every export. The stored locator remains on the scorecard for
    anyone who needs to trace it.
    """
    locator = reference.get("locator") or {}
    kind = reference.get("kind")
    if kind == "attachment":
        place = " · ".join(
            str(v) for v in (locator.get("location") or {}).values() if v
        )
        name = _text(locator.get("filename")) or "Uploaded file"
        return f"{name} · {place}" if place else name
    if kind == "connector":
        system = _text(locator.get("system")).upper() or "Connected system"
        parts = [system, _text(locator.get("field"))]
        retrieved = _text(locator.get("retrieved_at"))
        if retrieved:
            parts.append(f"retrieved {retrieved[:10]}")
        return " · ".join(p for p in parts if p)
    return "From your input"


def build_report(scorecard, *, peers=None):
    """Everything a surface needs to render the report, or None.

    `peers` enables standing and the could-change-the-leader claim, which no
    single scorecard can establish. Omitting them yields a report that simply
    does not make those claims rather than a weaker version of them.
    """
    if not isinstance(scorecard, dict):
        return None
    profile = scorecard.get("evidence_profile")
    if not isinstance(profile, dict) or not profile.get("criteria"):
        return None

    name = _text(scorecard.get("project_name")) or _text(scorecard.get("name"))
    weights = scorecard.get("scoring_weights") if isinstance(scorecard.get("scoring_weights"), dict) else {}

    exposure = None
    if peers and weights and len(peers) > 1:
        exposure = decision_exposure(peers, weights)

    summary = decision_summary(
        profile,
        exposure=exposure,
        option_name=name,
        score=scorecard.get("jaspen_score"),
        score_category=_text(scorecard.get("score_category")) or None,
    )

    criteria = []
    for entry in profile.get("criteria", []):
        grade = entry.get("confidence")
        criteria.append({
            "label": entry.get("label") or entry.get("key"),
            "weight_pct": int(round((entry.get("weight") or 0) * 100)),
            "contributes": entry.get("score"),
            "swing": entry.get("swing") or 0,
            "grade": grade,
            "grade_label": GRADE_LABELS.get(grade, grade),
            "severity": entry.get("severity"),
            "evidence": [
                {"excerpt": ref.get("excerpt"), "source": evidence_source_label(ref)}
                for ref in (entry.get("evidence_references") or [])
            ],
            # Reasoning, never a citation. Renderers must label it as such.
            "assessment": entry.get("rationale"),
            "assessment_basis": ASSESSMENT_BASIS.get(entry.get("source")),
            "unsupported": UNSUPPORTED_BY_GRADE.get(grade),
            "evidence_needed": (
                entry.get("resolution") or FALLBACK_ACTION_BY_GRADE.get(grade)
            ),
            # Set when a person rewrote the wording. Exports must show this,
            # or an edited narrative would leave the building as though it
            # were the system's own finding.
            "edited": bool(entry.get("_edited")),
        })

    counts = profile.get("counts") or {}
    return {
        "option_name": name,
        "score": scorecard.get("jaspen_score"),
        "score_category": _text(scorecard.get("score_category")) or None,
        "evidence_backed_pct": profile.get("evidence_backed_pct"),
        "assumption_dependent_pct": profile.get("assumption_dependent_pct"),
        "summary": summary or {},
        "claims": profile.get("claims") or [],
        "criteria": criteria,
        "counts": counts,
        # The criteria worth a deck slide: everything that could move the score
        # or the ranking, largest first. Criteria are already sorted by swing.
        "material": [
            c for c in criteria
            if c["severity"] in (SEVERITY_REVERSING, SEVERITY_MATERIAL)
        ],
        "risks": build_risk_register(scorecard),
        "provenance_note": PROVENANCE_NOTE,
    }


IMPACT_CATEGORY_LABELS = {
    "financial_health": "Financial",
    "operational_efficiency": "Operational",
    "market_position": "Market",
    "execution_readiness": "Execution",
}

_LEVEL_ORDER = {"High": 3, "Medium": 2, "Low": 1}



def _amount(value):
    """Numeric magnitude for ordering, or None when nothing was recorded."""
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(str(value).replace("$", "").replace(",", ""))
    except (TypeError, ValueError):
        return None


def _money(value):
    """Money at the precision a decision uses, or None."""
    try:
        amount = float(str(value).replace("$", "").replace(",", ""))
    except (TypeError, ValueError):
        return None
    if amount == 0:
        return "No cost"
    if abs(amount) >= 1_000_000:
        return f"${amount / 1_000_000:.1f}M"
    if abs(amount) >= 1_000:
        return f"${round(amount / 1_000)}K"
    return f"${amount:.0f}"


RISK_ORDER_BASIS = (
    "Ordered by unmitigated exposure. Residual assumes the mitigation is "
    "carried out; Jaspen does not track whether it has been."
)


def build_risk_register(scorecard):
    """The risks, ordered by UNMITIGATED exposure.

    Residual was the primary sort and that was wrong. Nothing in the system
    records whether a mitigation has been carried out: the scoring prompt asks
    for a residual level without defining it, and no mitigation status field
    exists anywhere. Residual is therefore the expected level IF the plan is
    executed, and ordering by it silently demoted large risks on the strength
    of plans nobody had confirmed were started.

    Impact and likelihood are what is actually known, so they order the
    register. Residual travels with each row, labelled as conditional.
    """
    risks = scorecard.get("top_risks") if isinstance(scorecard, dict) else None
    if not isinstance(risks, list):
        return []

    rows = []
    for item in risks:
        if not isinstance(item, dict):
            text = _text(item)
            if text:
                rows.append({"risk": text, "probability": None, "impact": None,
                             "impact_category": None, "mitigation": None,
                             "mitigation_cost": None, "residual": None, "edited": False})
            continue
        rows.append({
            "risk": _text(item.get("risk")),
            "probability": item.get("probability"),
            "impact": _money(item.get("impact_dollars") or item.get("impact")),
            # Derived here rather than read from the normalizer, which is the
            # only place impact_numeric is set. A scorecard that has not been
            # through it would otherwise sort every risk as zero exposure and
            # the ordering would quietly stop meaning anything.
            "impact_numeric": _amount(
                item.get("impact_numeric")
                if item.get("impact_numeric") is not None
                else (item.get("impact_dollars") or item.get("impact"))
            ),
            "impact_category": IMPACT_CATEGORY_LABELS.get(item.get("impact_category")),
            "mitigation": _text(item.get("mitigation")) or None,
            "mitigation_cost": _money(item.get("mitigation_cost")),
            "residual": item.get("residual_risk"),
            # Exports must show this, or a rewritten risk leaves the building
            # looking like Jaspen's own wording.
            "edited": bool(item.get("_edited")),
        })

    rows.sort(key=lambda r: (
        -(r.get("impact_numeric") or 0),
        -_LEVEL_ORDER.get(r.get("probability"), 0),
        -_LEVEL_ORDER.get(r.get("residual"), 0),
    ))
    return rows
