"""Deterministic, decomposable recommendation rules."""

from datetime import datetime, timezone


def _confidence_pct(scorecard):
    for path in (
        ("decision_confidence", "confidence_pct"),
        ("decision_confidence", "evidence_confidence_pct"),
        ("evidence_profile", "confidence_pct"),
        ("evidence_profile", "weighted_confidence_pct"),
    ):
        node = scorecard
        for key in path:
            node = node.get(key) if isinstance(node, dict) else None
        if isinstance(node, (int, float)):
            return max(0, min(100, round(float(node), 2)))
    grades = {"high": 100, "medium": 75, "low": 60, "assumed": 45}
    dims = scorecard.get("dimensions") if isinstance(scorecard.get("dimensions"), dict) else {}
    samples = [grades.get(str(item.get("confidence") or "").lower()) for item in dims.values() if isinstance(item, dict)]
    samples = [value for value in samples if value is not None]
    return round(sum(samples) / len(samples), 2) if samples else 0


def _condition(identifier, text, origin, *, due_by=None, due_by_rule=None):
    item = {"id": identifier, "text": text, "origin": origin}
    if due_by:
        item["due_by"] = due_by
    if due_by_rule:
        item["due_by_rule"] = due_by_rule
    return item


def recommend(scorecard, kit, *, due_by=None):
    thresholds = dict(kit["verdict_thresholds"])
    score = float(scorecard.get("jaspen_score") or 0)
    confidence = _confidence_pct(scorecard)
    gates = [dict(item) for item in (scorecard.get("gates") or []) if isinstance(item, dict)]
    failed = [gate for gate in gates if gate.get("status") == "fail"]
    unknown = [gate for gate in gates if gate.get("status") not in {"pass", "fail"}]
    # A kit may legitimately define no mandatory gates.  In that case the
    # gate predicate is vacuously satisfied; score and confidence still decide
    # the recommendation.  Unknown gates remain blocking conditions.
    all_pass = not failed and not unknown
    trace, conditions = [], []
    for index, gate in enumerate(gates, 1):
        status = gate.get("status") if gate.get("status") in {"pass", "fail", "unknown"} else "unknown"
        effect = "decline" if status == "fail" else "conditional" if status == "unknown" else "clear"
        trace.append({"step": "gate", "key": gate.get("key"), "label": gate.get("label"), "status": status, "effect": effect, "evidence": gate.get("evidence") or []})
        if status == "unknown":
            conditions.append(_condition(f"cond_gate_{index}", f"Resolve mandatory gate: {gate.get('label') or gate.get('key')}", {"type": "gate", "key": gate.get("key")}, due_by=due_by, due_by_rule="decision deadline" if due_by else None))
    trace.append({"step": "score", "value": score, "threshold": thresholds["advance_min_score"], "decline_below": thresholds["decline_below_score"], "effect": "meets" if score >= thresholds["advance_min_score"] else "below advance"})
    trace.append({"step": "confidence", "value": confidence, "threshold": thresholds["min_confidence_pct"], "effect": "meets" if confidence >= thresholds["min_confidence_pct"] else "below minimum"})

    if failed or score < thresholds["decline_below_score"]:
        verdict = "decline"
    elif all_pass and score >= thresholds["advance_min_score"] and confidence >= thresholds["min_confidence_pct"]:
        verdict = "advance"
    else:
        verdict = "advance_with_conditions"
    if score < thresholds["advance_min_score"] and verdict != "decline":
        conditions.append(_condition("cond_score", f"Raise the decision score from {score:g} to at least {thresholds['advance_min_score']:g}.", {"type": "threshold", "key": "advance_min_score"}, due_by=due_by))
    if confidence < thresholds["min_confidence_pct"] and verdict != "decline":
        conditions.append(_condition("cond_confidence", f"Strengthen evidence confidence from {confidence:g}% to at least {thresholds['min_confidence_pct']:g}%.", {"type": "threshold", "key": "min_confidence_pct"}, due_by=due_by))
    if verdict == "advance_with_conditions":
        blocking = []
        dims = scorecard.get("dimensions") if isinstance(scorecard.get("dimensions"), dict) else {}
        for key, dim in dims.items():
            if not isinstance(dim, dict) or not dim.get("what_would_improve"):
                continue
            if float(dim.get("score") or 0) < 75:
                blocking.append((key, dim))
        for index, (key, dim) in enumerate(blocking, 1):
            conditions.append(_condition(f"cond_criterion_{index}", str(dim["what_would_improve"]), {"type": "weak_criterion", "key": key}, due_by=due_by))
    threshold_snapshot = {"kit": kit["key"], **thresholds}
    return {
        "verdict_key": verdict,
        "label": kit["verdict_vocabulary"][verdict],
        "trace": trace,
        "conditions": conditions,
        "thresholds_used": threshold_snapshot,
        "kit_version": kit["version"],
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
