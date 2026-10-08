"""Canonical decision-state identity shared by every scoring entry path.

Language is evidence presented to the extraction/judgment layer.  It is not a
decision identity.  Only validated facts, evidence classifications,
assumptions, human-approved rubric structure, objective, gates, and Decision
Kit configuration can change the identity used for scoring reuse.
"""

import hashlib
import json
import re
import uuid


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


def _option_alias(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold().replace("&", " and ")).strip()


def _option_registry(session):
    if not isinstance(session, dict):
        return {}, {}
    registry = session.get("option_registry") if isinstance(session.get("option_registry"), dict) else {}
    aliases = session.get("option_aliases") if isinstance(session.get("option_aliases"), dict) else {}
    session["option_registry"] = registry
    session["option_aliases"] = aliases
    return registry, aliases


def register_option(session, display_name, *, authoritative_key=None, status="pending"):
    """Create or update a code-owned option identity in one decision session."""
    registry, aliases = _option_registry(session)
    alias = _option_alias(display_name)
    key = str(authoritative_key or "").strip()
    if not key and alias:
        key = str(aliases.get(alias) or "").strip()
    if not key:
        key = f"opt_{uuid.uuid4().hex}"
    current = registry.get(key) if isinstance(registry.get(key), dict) else {}
    known_aliases = list(current.get("aliases") or [])
    if alias and alias not in known_aliases:
        known_aliases.append(alias)
    registry[key] = {
        **current,
        "option_key": key,
        "display_name": str(display_name or current.get("display_name") or "").strip(),
        "aliases": known_aliases,
        "status": "scored" if current.get("status") == "scored" else status,
    }
    for known in known_aliases:
        aliases[known] = key
    return key


def resolve_option_key(session, display_name, *, authoritative_key=None, allow_single_pending=False):
    """Resolve identity without trusting a model-generated name or key.

    ``authoritative_key`` may come only from a persisted scorecard/queue. For a
    first single-option score, one pending fact record may acquire an additional
    display alias; this covers harmless model title expansion without merging
    already-scored or multi-option decisions.
    """
    registry, aliases = _option_registry(session)
    if authoritative_key:
        return register_option(session, display_name, authoritative_key=authoritative_key)
    alias = _option_alias(display_name)
    if alias and aliases.get(alias) in registry:
        return register_option(session, display_name, authoritative_key=aliases[alias])
    if allow_single_pending:
        pending = [
            key for key, item in registry.items()
            if isinstance(item, dict) and item.get("status") != "scored"
        ]
        if len(pending) == 1:
            return register_option(session, display_name, authoritative_key=pending[0])
    return register_option(session, display_name)


def mark_option_scored(session, option_key, display_name=None):
    registry, _aliases = _option_registry(session)
    key = str(option_key or "").strip()
    if key:
        register_option(session, display_name or (registry.get(key) or {}).get("display_name"), authoritative_key=key)
        registry[key]["status"] = "scored"


def option_attributes(session, option_key, display_name=None):
    if not isinstance(session, dict):
        return {}
    by_key = session.get("option_attributes_by_key") if isinstance(session.get("option_attributes_by_key"), dict) else {}
    found = by_key.get(str(option_key or ""))
    if isinstance(found, dict):
        return found
    legacy = session.get("option_attributes") if isinstance(session.get("option_attributes"), dict) else {}
    if not display_name:
        return {}
    return (
        legacy.get(stable_option_identity(None, display_name))
        or legacy.get(_option_alias(display_name))
        or {}
    )


def store_option_attributes(session, option_key, attributes, display_name=None):
    if not isinstance(session, dict) or not option_key:
        return
    by_key = session.get("option_attributes_by_key") if isinstance(session.get("option_attributes_by_key"), dict) else {}
    current = by_key.get(str(option_key)) if isinstance(by_key.get(str(option_key)), dict) else {}
    history_by_key = session.get("option_attribute_history_by_key") if isinstance(session.get("option_attribute_history_by_key"), dict) else {}
    option_history = history_by_key.get(str(option_key)) if isinstance(history_by_key.get(str(option_key)), list) else []
    for field, replacement in (attributes or {}).items():
        previous = current.get(field)
        if not isinstance(previous, dict) or previous == replacement:
            continue
        previous_material = {
            key: value for key, value in previous.items()
            if key not in {"created_at", "updated_at", "superseded_at"}
        }
        replacement_material = {
            key: value for key, value in (replacement if isinstance(replacement, dict) else {"value": replacement}).items()
            if key not in {"created_at", "updated_at", "superseded_at"}
        }
        if previous_material != replacement_material:
            option_history.append({"field": str(field), "previous": dict(previous)})
    if option_history:
        history_by_key[str(option_key)] = option_history
        session["option_attribute_history_by_key"] = history_by_key
    by_key[str(option_key)] = {**current, **(attributes or {})}
    session["option_attributes_by_key"] = by_key
    # Keep the old name index readable during migration, but canonical reads use
    # option_key. This can be removed after stored sessions have been backfilled.
    if display_name:
        legacy = session.get("option_attributes") if isinstance(session.get("option_attributes"), dict) else {}
        legacy[stable_option_identity(None, display_name)] = dict(by_key[str(option_key)])
        legacy[_option_alias(display_name)] = dict(by_key[str(option_key)])
        session["option_attributes"] = legacy


def migrate_attribute_mapping(attributes, *, kit=None):
    """Return a copy with only schema-proven aliases collapsed."""
    from .decision_facts import canonical_field_key

    current = dict(attributes or {})
    for field in list(current):
        canonical = canonical_field_key(field, kit)
        if not canonical or canonical == field:
            continue
        alias_entry = current.pop(field)
        current.setdefault(canonical, alias_entry)
    return current


def migrate_option_attribute_keys(session, option_key, *, kit=None, display_name=None):
    """Collapse schema-proven aliases without touching unrelated facts."""
    if not isinstance(session, dict) or not option_key:
        return {}
    from .decision_facts import canonical_field_key

    by_key = session.get("option_attributes_by_key") if isinstance(session.get("option_attributes_by_key"), dict) else {}
    current = dict(by_key.get(str(option_key)) or {})
    if not current:
        return current
    history_by_key = session.get("option_attribute_history_by_key") if isinstance(session.get("option_attribute_history_by_key"), dict) else {}
    option_history = list(history_by_key.get(str(option_key)) or [])
    changed = False
    for field in list(current):
        canonical = canonical_field_key(field, kit)
        if not canonical or canonical == field:
            continue
        alias_entry = current.pop(field)
        existing = current.get(canonical)
        if isinstance(existing, dict) and existing != alias_entry:
            option_history.append({"field": canonical, "previous": dict(alias_entry), "migrated_from": field})
        else:
            current[canonical] = alias_entry
        changed = True
    if not changed:
        return current
    by_key[str(option_key)] = current
    session["option_attributes_by_key"] = by_key
    if option_history:
        history_by_key[str(option_key)] = option_history
        session["option_attribute_history_by_key"] = history_by_key
    if display_name:
        legacy = session.get("option_attributes") if isinstance(session.get("option_attributes"), dict) else {}
        legacy[stable_option_identity(None, display_name)] = dict(current)
        legacy[_option_alias(display_name)] = dict(current)
        session["option_attributes"] = legacy
    return current


def rubric_identity(rubric):
    criteria = []
    for item in ((rubric or {}).get("criteria") or []):
        if not isinstance(item, dict) or not item.get("key"):
            continue
        criteria.append({
            key: _plain(item.get(key))
            for key in (
                "key", "label", "description", "weight", "is_risk", "group", "gate", "gate_rule",
                "option_key", "scope", "fact_key", "pass_value", "status_values", "evidence_fields",
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
                "key", "gate_rule", "option_key", "scope", "fact_key", "pass_value",
                "status_values", "evidence_fields",
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
