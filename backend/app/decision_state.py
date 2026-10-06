"""Canonical decision-state identity shared by every scoring entry path.

Language is evidence presented to the extraction/judgment layer.  It is not a
decision identity.  Only validated facts, evidence classifications,
assumptions, human-approved rubric structure, objective, gates, and Decision
Kit configuration can change the identity used for scoring reuse.
"""

import hashlib
import json
import re


def _plain(value):
    """Return stable JSON data without timestamps or presentation-only fields."""
    if isinstance(value, dict):
        return {
            str(key): _plain(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if key not in {
                "created_at", "updated_at", "approved_by_user_at", "presented_at",
                "evidence", "rationale", "basis", "label", "description",
            }
        }
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def stable_option_identity(option_key=None, option_name=None):
    """Prefer the persisted option key; derive a stable key only at creation."""
    explicit = str(option_key or "").strip()
    if explicit:
        return explicit
    normalized = re.sub(r"[^a-z0-9]+", "-", str(option_name or "").lower()).strip("-")
    return normalized or "option"


def rubric_identity(rubric):
    criteria = []
    for item in ((rubric or {}).get("criteria") or []):
        if not isinstance(item, dict) or not item.get("key"):
            continue
        criteria.append({
            key: _plain(item.get(key))
            for key in (
                "key", "label", "description", "weight", "is_risk", "group", "gate", "gate_rule",
                "option_key", "scope", "fact_key", "pass_value",
            )
            if item.get(key) is not None
        })
    criteria.sort(key=lambda item: str(item.get("key") or ""))
    return {
        "status": "approved" if rubric_is_approved(rubric) else "proposed",
        "criteria": criteria,
    }


def rubric_is_approved(rubric):
    if not isinstance(rubric, dict):
        return False
    status = str(rubric.get("approval_status") or rubric.get("status") or "").strip().lower()
    if status:
        return status == "approved"
    # Read legacy records without allowing new code to infer approval from time.
    return bool(rubric.get("approved_by_user_at"))


def canonical_decision_state(
    *, option_key=None, option_name=None, attributes=None, rubric=None,
    objective="balanced", gates=None, decision_kit=None,
    decision_kit_version=None, canonical_evidence=None,
):
    facts = {}
    assumptions = []
    for key, raw in sorted((attributes or {}).items()):
        if not isinstance(raw, dict):
            raw = {"value": raw}
        entry = {
            "value": _plain(raw.get("value")),
            "source": str(raw.get("source") or "").lower() or None,
            "unit": raw.get("unit"),
            "source_id": raw.get("source_id"),
            "locator": raw.get("locator"),
        }
        if entry["source"] == "assumed":
            entry["assumption"] = _plain(raw.get("assumption") or {})
            assumptions.append({"field": str(key), **entry["assumption"]})
        facts[str(key)] = entry

    evidence = []
    for item in canonical_evidence or []:
        if not isinstance(item, dict):
            continue
        evidence.append(_plain(item))
    evidence.sort(key=lambda item: json.dumps(item, sort_keys=True, default=str))

    gate_defs = []
    for item in gates or []:
        if not isinstance(item, dict) or not item.get("key") or not item.get("gate"):
            continue
        gate_defs.append(_plain({
            key: item.get(key) for key in (
                "key", "gate_rule", "option_key", "scope", "fact_key", "pass_value"
            ) if item.get(key) is not None
        }))
    gate_defs.sort(key=lambda item: str(item.get("key") or ""))

    return {
        "schema_version": 1,
        "option_identity": stable_option_identity(option_key, option_name),
        "facts": facts,
        "evidence": evidence,
        "assumptions": assumptions,
        "rubric": rubric_identity(rubric),
        "objective": str(objective or "balanced"),
        "gates": gate_defs,
        "decision_kit": {
            "key": decision_kit,
            "version": decision_kit_version,
        },
    }


def decision_state_fingerprint(state):
    encoded = json.dumps(state, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()


def state_is_reusable(state):
    """Avoid caching judgments that still depend only on unnormalized prose."""
    base = bool(
        isinstance(state, dict)
        and rubric_is_approved(state.get("rubric"))
        and (state.get("facts") or state.get("evidence"))
    )
    if not base:
        return False
    facts = state.get("facts") or {}
    evidence = state.get("evidence") or []
    for gate in state.get("gates") or []:
        fact_key = str(gate.get("fact_key") or "")
        has_fact = bool(fact_key and isinstance(facts.get(fact_key), dict))
        has_claim = any(
            isinstance(item, dict) and str(item.get("gate_key") or "") == str(gate.get("key") or "")
            for item in evidence
        )
        if not has_fact and not has_claim:
            return False
    return True
