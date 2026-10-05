"""Apply Decision Kit mechanics to canonical scorecard payloads."""

import hashlib
import json

from .decision_kits import get_decision_kit
from .decision_metrics import calculate_metrics
from .decision_recommendation import recommend


def _quote_in_corpus(quote, corpus):
    quote = " ".join(str(quote or "").split()).lower()
    corpus = " ".join(str(corpus or "").split()).lower()
    return bool(quote and quote in corpus)


def normalize_gates(raw_gates, rubric, evidence_corpus=""):
    criteria = (rubric or {}).get("criteria") if isinstance((rubric or {}).get("criteria"), list) else []
    approved = bool((rubric or {}).get("approved_by_user_at"))
    definitions = {str(item.get("key")): item for item in criteria if isinstance(item, dict) and item.get("gate") and item.get("key")}
    if not approved:
        return []
    supplied = {str(item.get("key")): item for item in (raw_gates or []) if isinstance(item, dict) and item.get("key")}
    normalized = []
    for key, definition in definitions.items():
        item = supplied.get(key) or {}
        evidence = [str(value) for value in (item.get("evidence") or []) if _quote_in_corpus(value, evidence_corpus)]
        source = str(item.get("source") or "assumed").lower()
        confidence = str(item.get("confidence") or "assumed").lower()
        requested = str(item.get("status") or "unknown").lower()
        if requested == "pass" and evidence and source != "assumed" and confidence in {"medium", "high"}:
            status = "pass"
        elif requested == "fail" and evidence:
            status = "fail"
        else:
            status = "unknown"
        normalized.append({
            "key": key,
            "label": definition.get("label") or key,
            "rule": definition.get("gate_rule") or definition.get("description") or "",
            "status": status,
            "evidence": evidence,
            "basis": item.get("basis") or item.get("rationale") or None,
            "confidence": confidence,
            "source": source,
        })
    return normalized


def recommendation_inputs_fingerprint(scorecard, kit):
    payload = {
        "score": scorecard.get("jaspen_score"),
        "confidence": scorecard.get("data_confidence"),
        "dimensions": {key: {"score": value.get("score"), "confidence": value.get("confidence"), "what_would_improve": value.get("what_would_improve")} for key, value in (scorecard.get("dimensions") or {}).items() if isinstance(value, dict)},
        "gates": scorecard.get("gates") or [],
        "kit": kit["key"],
        "version": kit["version"],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def apply_decision_kit(scorecard, *, decision_kit=None, decision_kit_version=None, kit_context=None, evidence_corpus="", force_recommendation=False):
    output = dict(scorecard or {})
    if not decision_kit:
        return output
    kit = get_decision_kit(decision_kit, version=decision_kit_version or None)
    output["decision_kit"] = kit["key"]
    output["decision_kit_version"] = int(decision_kit_version or kit["version"])
    output["attributes"] = dict(output.get("attributes") or {})
    output["metrics"] = calculate_metrics(output["attributes"], kit.get("metrics"), context=kit_context)
    output["gates"] = normalize_gates(output.get("gates"), output.get("scoring_rubric") or output.get("rubric"), evidence_corpus)
    inputs_hash = recommendation_inputs_fingerprint(output, kit)
    existing = output.get("recommendation") if isinstance(output.get("recommendation"), dict) else None
    existing_version = ((existing or {}).get("thresholds_used") or {}).get("version")
    same_inputs = (existing or {}).get("inputs_fingerprint") == inputs_hash
    # A newer kit never rewrites an open recommendation silently. Explicit
    # recompute or a new scoring pass supplies force_recommendation=True.
    if existing and existing_version and int(existing_version) != kit["version"] and not force_recommendation:
        return output
    if existing and same_inputs and not force_recommendation:
        return output
    deadline_key = (kit.get("plan_bindings") or {}).get("deadline")
    due_by = None
    if deadline_key and not str(deadline_key).startswith("context:"):
        entry = output["attributes"].get(deadline_key)
        due_by = entry.get("value") if isinstance(entry, dict) else entry
    elif str(deadline_key).startswith("context:"):
        entry = (kit_context or {}).get(str(deadline_key).split(":", 1)[1])
        due_by = entry.get("value") if isinstance(entry, dict) else entry
    recommendation = recommend(output, kit, due_by=due_by)
    recommendation["inputs_fingerprint"] = inputs_hash
    output["recommendation"] = recommendation
    return output
