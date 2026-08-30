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
# PROVENANCE LIMIT, read before building anything that shows "evidence":
# nothing in this system retains WHICH input supported a judgment. Scoring
# records a channel (`source`: conversation / connector / inferred / assumed)
# and the model's own reasoning (`rationale`). It does not record the document,
# the message, the connector field, or the figure that a score rested on.
#
# So a surface may say "Jaspen based this on connected data, and here is its
# stated reasoning". It may NOT present a list of evidence held, cite a figure
# to a source, or imply an audit trail exists. Doing so would manufacture
# exactly the confident, unsupported content this module exists to expose, and
# it would be indistinguishable from the failure the product is sold against.
# Closing this properly means capturing evidence references during scoring.
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
            # Passed through, not derived. Both are what the scoring pass
            # already recorded, and both are weaker than they may look:
            #
            #   source     the CHANNEL an input arrived on, one of
            #              conversation / connector / inferred / assumed. It
            #              does not identify which input.
            #   rationale  the model's own account of why it scored this way.
            #              It is reasoning, not a record of evidence.
            #
            # Neither is provenance. Nothing here retains which document,
            # message, or connector field supported a judgment, so no surface
            # may present these as an evidence trail. See PROVENANCE LIMIT at
            # the top of this module.
            "source": _text(dim.get("source")).lower() or None,
            "rationale": _text(dim.get("rationale")) or None,
            # Verified provenance, passed through untouched. Unlike `source`
            # and `rationale` these are not model claims: each was located in
            # the input by deterministic code before being stored, so they are
            # the only thing in this record a reader may treat as evidence.
            # See app/evidence_references.py.
            "evidence_references": dim.get("evidence_references") or [],
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
    profile = {
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
    # Claims travel with the profile so a consumer never has to assemble a
    # sentence from the counts itself. Every surface renders the same words for
    # the same computation, and a claim that is not in this list was not
    # computed and must not appear.
    profile["claims"] = exposure_claims(profile)
    return profile


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

    # The healthy case has to say so. When nothing is material and nothing can
    # change the ranking, every other claim below is correctly absent, and an
    # earlier version simply fell silent: a well-evidenced decision showed a
    # ratio and then nothing at all. Silence there reads as an incomplete
    # analysis rather than as good news, and it lands precisely on the user who
    # did the work Jaspen asked for. Resolving your assumptions should not be
    # rewarded with a blank card.
    #
    # Scoped carefully. This says no assumption carries enough WEIGHT to move
    # the score, which is what was computed. It does not say the decision is
    # sound, that the evidence is complete, or that nothing can go wrong, none
    # of which this module knows.
    if not counts["reversing"] and not counts["material"]:
        claims.append({
            "kind": "clear",
            "count": 0,
            "text": (
                "No assumption currently carries enough weight to materially "
                "change the score."
            ),
        })

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


def decision_summary(profile, *, exposure=None, option_name=None,
                     score=None, score_category=None):
    """The executive readout, composed from computed values only.

    Every sentence is assembled from numbers this module already produced. No
    model wrote any of it, which is what lets the summary be quoted into a
    room: it cannot drift from the arithmetic underneath it, and it cannot
    smuggle in a claim the detail does not support.

    Deliberately not a condensed copy of the detail. The detail answers "what
    is true of each criterion". This answers "what should I do about this
    decision", which is a different question and needs different sentences.

    Returns None when there is nothing to summarise. Absent fields are omitted
    rather than filled: a decision with one option has no standing, and a
    decision with no exposure has nothing concentrated anywhere.
    """
    if not profile:
        return None

    entries = profile.get("criteria") or []
    counts = profile.get("counts") or {}
    backed = profile.get("evidence_backed_pct")
    assumed = profile.get("assumption_dependent_pct")

    summary = {}

    if score is not None:
        rated = f", rated {score_category}" if score_category else ""
        summary["verdict"] = f"Scores {score} of 100{rated}."

    # Standing needs the peer set, so it only exists when peers were scored.
    leader = (exposure or {}).get("leader") or {}
    leader_name = _text(leader.get("name"))
    challengers = (exposure or {}).get("challengers") or []
    if leader_name and option_name:
        if option_name == leader_name:
            summary["standing"] = "Currently leads the options under consideration."
        else:
            trailing = next((c for c in challengers if c.get("name") == option_name), None)
            if trailing:
                gap = trailing.get("gap")
                unit = "point" if gap == 1 else "points"
                summary["standing"] = (
                    f"Trails {leader_name} by {gap} {unit}, a gap the assumptions "
                    "below could close."
                )
            else:
                summary["standing"] = f"Does not currently lead. {leader_name} scores higher."

    if backed is not None:
        summary["confidence"] = (
            f"{backed}% of the weighted decision rests on evidence. "
            f"The remaining {assumed}% depends on assumptions."
        )

    # Where the exposure actually sits. A decision with 45% assumption
    # dependence spread evenly is a different problem from one where it all
    # sits in a single heavy criterion, and only the second is quickly fixable.
    exposed = [e for e in entries if e.get("swing", 0) > 0]
    total_swing = sum(e["swing"] for e in exposed)
    if exposed and total_swing > 0:
        top = exposed[0]
        share = top["swing"] / total_swing
        weight_pct = int(round(top["weight"] * 100))
        if share >= 0.6:
            summary["concentration"] = (
                f"Most of that exposure sits in one criterion, {top['label']}, "
                f"which carries {weight_pct}% of the decision."
            )
        else:
            summary["concentration"] = (
                f"That exposure is spread across {len(exposed)} criteria, led by "
                f"{top['label']} at {weight_pct}% of the decision."
            )

    action = next(
        (e for e in entries if e.get("resolvable") and e.get("resolution") and e.get("swing", 0) > 0),
        None,
    )
    if action:
        summary["next_step"] = f"{action['label']}: {action['resolution']}"

    if counts.get("reversing"):
        n = counts["reversing"]
        summary["sensitivity"] = (
            f"{'One assumption' if n == 1 else f'{n} assumptions'} could change "
            "which option leads."
        )
    elif counts.get("material"):
        summary["sensitivity"] = (
            "Resolving the assumptions below could materially change the score, "
            "though not the ranking on current evidence."
        )
    else:
        summary["sensitivity"] = (
            "No assumption currently carries enough weight to change the score "
            "materially. Closing the remaining gaps would strengthen the record "
            "rather than move the answer."
        )

    return summary or None


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

    result = {
        "leader": {"name": leader["name"], "score": leader["score"], "profile": leader_profile},
        "options": len(scored),
        "challengers": challengers,
        "could_change_leader": bool(challengers),
    }
    # Each option's readout, keyed by name, assembled where the peer set is in
    # hand. Standing is part of the briefing and no single scorecard can state
    # it, so composing this per-card downstream would produce a summary that
    # silently omits the one sentence an executive reads first.
    result["summaries"] = {
        card["name"]: decision_summary(
            evidence_profile(
                card["dimensions"], weights,
                score=card["score"],
                leader_score=None if card["name"] == leader["name"] else leader["score"],
            ),
            exposure=result,
            option_name=card["name"],
            score=card["score"],
        )
        for card in scored
    }
    return result
