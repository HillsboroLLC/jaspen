"""Stable decision-input fingerprints for stored-result reuse."""

import hashlib
import json


def scoring_fingerprint(*, option_key, attributes, rubric, objective, decision_kit, decision_kit_version, evidence_corpus, facts_text=None):
    criteria = []
    for item in ((rubric or {}).get("criteria") or []):
        if not isinstance(item, dict):
            continue
        criteria.append({key: item.get(key) for key in ("key", "label", "weight", "is_risk", "group", "description", "gate", "gate_rule")})
    canonical = {
        "option_key": str(option_key or ""),
        "attributes": attributes if isinstance(attributes, dict) else {},
        "facts_text": None if decision_kit else str(facts_text or ""),
        "rubric": {"criteria": criteria, "approved_by_user_at": (rubric or {}).get("approved_by_user_at")},
        "objective": str(objective or "balanced"),
        "decision_kit": decision_kit,
        "decision_kit_version": decision_kit_version,
        "evidence_corpus": str(evidence_corpus or ""),
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()
