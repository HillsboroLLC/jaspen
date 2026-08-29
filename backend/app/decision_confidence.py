# backend/app/decision_confidence.py
#
# Decision Confidence and Assumption Exposure: the deterministic arithmetic
# behind two product claims.
#
#   "68% of this decision is evidence-backed, 32% is assumption-dependent."
#   "Three assumptions are material. One could change which option leads."
#
# Nothing here calls a model. Every number is a function of the per-criterion
# confidence labels the scoring pass already produced, the rubric weights the
# decision already carries, and (for reversal) the peer options already scored.
# That separation is the point. A claim about how much of a decision rests on
# assumption cannot itself be a model's opinion, or it inherits exactly the
# problem it exists to expose.
#
# Two axes, deliberately kept apart:
#
#   SEVERITY (reversing / material / other / none) is magnitude. How far could
#     this criterion move the score if its evidence were actually obtained?
#   RESOLVABLE is actionability. Is there a named next step that would raise
#     this criterion's confidence grade?
#
# They answer different questions, and one entry can be both. The most useful
# line in the register is precisely the one that is reversing AND resolvable:
# it could change the answer, and something can be done about it before the
# commitment is made.
#
# SCOPE LIMIT, load-bearing, do not let UI or marketing copy exceed it:
# a confidence cap only ever LOWERS a judgment, so obtaining evidence can only
# move a score UP, toward what the model already judged. This module therefore
# computes upside only. It can support "obtaining this evidence could lift
# Option B above Option A." It cannot support "if this assumption proves false
# the score drops," because nothing here models a downside floor, and inventing
# one would be precisely the kind of unfounded number the product exists to
# surface. See exposure_claims() for the claims the arithmetic will carry.

# Ceiling a judgment may contribute at each evidence grade. This is the single
# source of truth: routes/strategy.py imports these rather than defining its own
# copy, so the caps enforced in scoring and the caps used to measure exposure
# can never drift apart.
CONFIDENCE_CAPS = {"high": 100, "medium": 75, "low": 60, "assumed": 45}

# How much of a criterion's weight counts toward the evidence-backed share at
# each grade. High evidence counts fully. An assumption contributes nothing,
# which is what makes it an assumption rather than a weak fact.
EVIDENCE_FACTOR = {"high": 1.0, "medium": 0.75, "low": 0.4, "assumed": 0.0}

# Score band floors, mirroring the score_category thresholds in
# routes/strategy.py. A swing that carries an option into a higher band is
# material: the decision would be described differently in the room, even if
# the ranking holds.
SCORE_BANDS = (40, 60, 80)

# The other half of materiality. Band crossing alone under-reports whenever an
# option sits mid-band: a criterion carrying a quarter of the decision with
# nearly nine points of unresolved exposure is not immaterial simply because
# the option happened to start in the middle of "Good". Five points on a
# hundred point score is large enough to matter and small enough to state
# without a percentage calculation, so an assumption is material when it can
# move the option by at least this much OR carry it into a different band.
MATERIAL_SWING_POINTS = 5.0

SEVERITY_REVERSING = "reversing"
SEVERITY_MATERIAL = "material"
# Real but sub-threshold exposure. Deliberately not called "minor": something
# can be immaterial arithmetically while being nothing of the sort in ordinary
# English, and the label is read by people deciding where to spend effort.
SEVERITY_OTHER = "other"
# No exposure to the score. Either the evidence already supports the judgment,
# or the judgment happened to land at or below its own cap, so obtaining better
# evidence would not move the number. Note the second case: a criterion can sit
# here while still being resolvable, because raising its confidence grade is
# worth doing even when today it changes nothing. The label therefore speaks
# only about score movement and never asserts the evidence is strong.
SEVERITY_NONE = "none"

# What each tier is called in front of a user. Kept here with exposure_claims()
# so no surface can invent its own vocabulary for the same computation.
SEVERITY_LABELS = {
    SEVERITY_REVERSING: "Could change the leading option",
    SEVERITY_MATERIAL: "Material exposure",
    SEVERITY_OTHER: "Other assumption exposure",
    SEVERITY_NONE: "No score exposure",
}

# Grades that count as evidence rather than assumption when a reader wants the
# split as a binary rather than a graded share.
EVIDENCED_GRADES = frozenset({"high", "medium"})


def _confidence_of(dim):
    return str((dim or {}).get("confidence") or "").strip().lower()


def _text(value):
    return str(value or "").strip()


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _band_index(score):
    """Which score band a value sits in. Higher index is a better band."""
    idx = 0
    for floor in SCORE_BANDS:
        if score >= floor:
            idx += 1
    return idx


def criterion_entries(dimensions, weights):
    """One record per weighted criterion, carrying its exposure arithmetic.

    `swing` is the number of points the overall score would gain if this
    criterion's evidence were obtained and its cap lifted to the judgment the
    model already made. It is expressed in final score points, so entries are
    directly comparable against the gap between two options.

    Criteria the caller did not weight are skipped rather than assumed equal:
    a rubric that omits a dimension omitted it on purpose.
    """
    if not isinstance(dimensions, dict) or not isinstance(weights, dict):
        return []

    total_w = 0.0
    usable = []
    for key, weight in weights.items():
        dim = dimensions.get(key)
        if not isinstance(dim, dict):
            continue
        w = _number(weight)
        if w is None or w <= 0:
            continue
        # Prefer the preserved pre-cap judgment, and fall back to "score" when
        # it is absent. Deriving the cap here rather than trusting a stored
        # capped value keeps this module correct for all three shapes a
        # dimension arrives in:
        #
        #   scored    raw_score plus a capped score, the normal case
        #   legacy    score only, already capped, so min() is a no-op and the
        #             swing is honestly zero rather than invented
        #   raw       score only, straight from the model and never capped,
        #             where the cap has to be applied before anything is read
        raw = _number(dim.get("raw_score"))
        if raw is None:
            raw = _number(dim.get("score"))
        if raw is None:
            continue
        raw = max(0.0, min(100.0, raw))
        grade = _confidence_of(dim)
        capped = min(raw, CONFIDENCE_CAPS.get(grade, 100))
        usable.append((key, dim, w, raw, capped, grade))
        total_w += w

    if total_w <= 0:
        return []

    entries = []
    for key, dim, w, raw, capped, grade in usable:
        weight_norm = w / total_w
        resolution = _text(dim.get("what_would_improve"))
        entries.append({
            "key": key,
            "label": _text(dim.get("label")) or key,
            "weight": round(weight_norm, 4),
            "confidence": grade or "unknown",
            "raw_score": int(round(raw)),
            "score": int(round(capped)),
            "cap": CONFIDENCE_CAPS.get(grade),
            "capped": raw > capped,
            "swing": round(weight_norm * (raw - capped), 2),
            "evidence_factor": EVIDENCE_FACTOR.get(grade, 0.0),
            "evidenced": grade in EVIDENCED_GRADES,
            "resolvable": bool(resolution) and grade not in EVIDENCED_GRADES,
            "resolution": resolution or None,
        })
    return entries


def weighted_score(entries):
    """The capped weighted score these entries produce, in score points."""
    if not entries:
        return None
    return int(round(sum(e["weight"] * e["score"] for e in entries)))


def evidence_ratio(entries):
    """Share of decision weight standing on evidence, as a 0-100 int.

    Weighted, not averaged. A criterion carrying 30% of the decision moves
    this number six times as far as one carrying 5%, which is the whole
    reason the figure is worth publishing.
    """
    if not entries:
        return None
    backed = sum(e["weight"] * e["evidence_factor"] for e in entries)
    return int(round(max(0.0, min(1.0, backed)) * 100))


def _severity(entry, score, leader_score):
    """Highest claim the arithmetic supports for one entry.

    `reversing` requires a peer to overtake, so it is only ever reachable for
    an option that currently trails. The leading option cannot reverse itself
    by gaining points, and this module does not model the downside that would
    let it fall. See the scope limit at the top of this file.
    """
    swing = entry["swing"]
    if swing <= 0:
        return SEVERITY_NONE
    if (
        leader_score is not None
        and score is not None
        and score < leader_score
        and score + swing >= leader_score
    ):
        return SEVERITY_REVERSING
    if swing >= MATERIAL_SWING_POINTS:
        return SEVERITY_MATERIAL
    if score is not None and _band_index(score + swing) > _band_index(score):
        return SEVERITY_MATERIAL
    return SEVERITY_OTHER


def evidence_profile(dimensions, weights, *, score=None, leader_score=None):
    """The Decision Confidence and Assumption Exposure profile for one option.

    `leader_score` is the best score among the other options under
    consideration. Pass it to enable reversal detection; omit it and the
    profile still reports the ratio, the register, and materiality, which is
    the correct behaviour for a decision with a single option on the table.
    """
    entries = criterion_entries(dimensions, weights)
    if not entries:
        return None

    resolved_score = score if score is not None else weighted_score(entries)
    for entry in entries:
        entry["severity"] = _severity(entry, resolved_score, leader_score)

    # Largest movers first. This ordering is the product: an assumption
    # register sorted by anything other than its power to change the answer
    # is just a list of caveats.
    entries.sort(key=lambda e: (-e["swing"], -e["weight"], e["key"]))

    backed = evidence_ratio(entries)
    reversing = sum(1 for e in entries if e["severity"] == SEVERITY_REVERSING)
    material = sum(1 for e in entries if e["severity"] == SEVERITY_MATERIAL)
    return {
        "evidence_backed_pct": backed,
        "assumption_dependent_pct": 100 - backed,
        "score": resolved_score,
        "criteria": entries,
        "counts": {
            "total": len(entries),
            "evidenced": sum(1 for e in entries if e["evidenced"]),
            "assumption_dependent": sum(1 for e in entries if not e["evidenced"]),
            "reversing": reversing,
            "material": material,
            # Severity tiers are exclusive, so a reversing assumption is not
            # counted under material. This is for the surfaces that want one
            # number for "exposure worth acting on" rather than a breakdown.
            "material_or_higher": reversing + material,
            "other": sum(1 for e in entries if e["severity"] == SEVERITY_OTHER),
            "resolvable": sum(1 for e in entries if e["resolvable"]),
        },
        "top_exposure": [e for e in entries if e["swing"] > 0][:3],
    }


def exposure_claims(profile):
    """The sentences this profile actually supports, ready for rendering.

    Centralised so the workspace, the export, and the email cannot each invent
    their own phrasing and drift past what was computed. A claim absent from
    this list was not computed and must not be displayed.
    """
    if not profile:
        return []
    counts = profile["counts"]
    claims = []
    if counts["reversing"]:
        n = counts["reversing"]
        claims.append({
            "kind": SEVERITY_REVERSING,
            "count": n,
            "text": (
                f"{n} assumption could change which option leads"
                if n == 1
                else f"{n} assumptions could change which option leads"
            ),
        })
    if counts["material"]:
        n = counts["material"]
        claims.append({
            "kind": SEVERITY_MATERIAL,
            "count": n,
            "text": (
                f"{n} assumption could materially change the score"
                if n == 1
                else f"{n} assumptions could materially change the score"
            ),
        })
    if counts["resolvable"]:
        n = counts["resolvable"]
        claims.append({
            "kind": "resolvable",
            "count": n,
            "text": (
                f"{n} gap can be resolved before you commit"
                if n == 1
                else f"{n} gaps can be resolved before you commit"
            ),
        })
    return claims


def decision_exposure(scorecards, weights):
    """Exposure across every option on the table, not just one card.

    Reversal is a property of the option set, so it cannot be computed from a
    single scorecard. This walks the peers, profiles each against the current
    leader, and reports which trailing options could overtake it and on which
    assumption.

    `scorecards` is a sequence of dicts each carrying at least `dimensions`,
    and optionally `project_name` and `jaspen_score`.
    """
    cards = [c for c in (scorecards or []) if isinstance(c, dict)]
    if not cards:
        return None

    scored = []
    for card in cards:
        entries = criterion_entries(card.get("dimensions"), weights)
        if not entries:
            continue
        score = _number(card.get("jaspen_score"))
        score = int(round(score)) if score is not None else weighted_score(entries)
        scored.append({
            "name": _text(card.get("project_name")) or _text(card.get("name")) or "Untitled option",
            "score": score,
            "dimensions": card.get("dimensions"),
        })
    if not scored:
        return None

    scored.sort(key=lambda c: -c["score"])
    leader = scored[0]
    leader_profile = evidence_profile(leader["dimensions"], weights, score=leader["score"])

    challengers = []
    for card in scored[1:]:
        profile = evidence_profile(
            card["dimensions"], weights, score=card["score"], leader_score=leader["score"],
        )
        if not profile:
            continue
        reversers = [e for e in profile["criteria"] if e["severity"] == SEVERITY_REVERSING]
        if reversers:
            challengers.append({
                "name": card["name"],
                "score": card["score"],
                "gap": leader["score"] - card["score"],
                "assumptions": reversers,
            })

    return {
        "leader": {"name": leader["name"], "score": leader["score"], "profile": leader_profile},
        "options": len(scored),
        "challengers": challengers,
        "could_change_leader": bool(challengers),
    }
