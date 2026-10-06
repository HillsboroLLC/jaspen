"""Canonical, deterministic fact normalization for every decision path.

The model may identify candidate facts, but this module owns field validation,
types, units, provenance, and null handling.  Decision Kits only describe the
fields; they do not get a separate fact engine.
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation
import re


_ALIASES = {
    "margin": "margin_pct",
    "expected_margin": "margin_pct",
    "margin_percent": "margin_pct",
    "win_chance": "win_probability",
    "win_rate": "win_probability",
    "deadline": "submission_due",
    "due_date": "submission_due",
    "submission_deadline": "submission_due",
    "requirements": "mandatory_requirements",
    "bonding": "capacity_draw",
    "bonding_requirement": "capacity_draw",
    "capacity": "capacity_draw",
    "contract_amount": "contract_value",
    "price": "proposal_price",
}

_MONTHS = {
    name.lower(): number for number, name in enumerate(
        ("", "January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December")
    ) if name
}
_MONTHS.update({name[:3].lower(): number for name, number in list(_MONTHS.items())})


def _decimal(value):
    if isinstance(value, bool) or value is None:
        return None
    text = str(value).strip().replace(",", "").replace("$", "")
    if not text:
        return None
    multiplier = Decimal(1)
    if text[-1:].lower() in {"k", "m", "b"}:
        multiplier = {"k": Decimal(1000), "m": Decimal(1000000), "b": Decimal(1000000000)}[text[-1].lower()]
        text = text[:-1]
    text = text.rstrip("%").strip()
    try:
        parsed = Decimal(text) * multiplier
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _number(value):
    parsed = _decimal(value)
    if parsed is None:
        return None
    return int(parsed) if parsed == parsed.to_integral_value() else float(parsed.normalize())


def _date(value):
    if value is None:
        return None
    text = str(value).strip().rstrip(".,")
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        pass
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%B %d %Y", "%b %d %Y", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(text.replace(",", ""), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _list(value):
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        result = [str(item).strip() for item in value if str(item).strip()]
    else:
        result = [item.strip(" -\t") for item in re.split(r"[;\n]|,(?=\s*\w)|\s+and\s+", str(value), flags=re.I) if item.strip(" -\t")]
    return result or None


def _team(value):
    if value is None:
        return None
    if isinstance(value, list) and all(isinstance(item, dict) for item in value):
        return [dict(item) for item in value]
    return [{"name": item} for item in (_list(value) or [])]


def field_definitions(kit):
    return {
        str(field.get("key")): field
        for field in ((kit or {}).get("fields") or [])
        if isinstance(field, dict) and field.get("key")
    }


def canonical_field_key(key, kit=None):
    normalized = re.sub(r"[^a-z0-9]+", "_", str(key or "").strip().lower()).strip("_")
    normalized = _ALIASES.get(normalized, normalized)
    definitions = field_definitions(kit)
    if definitions and normalized not in definitions:
        return None
    return normalized or None


def normalize_value(value, field):
    if value in (None, ""):
        return None
    kind = str((field or {}).get("type") or "text").lower()
    if kind in {"money", "number", "percentage"}:
        parsed = _number(value)
        if parsed is None:
            return None
        if kind == "percentage" and not 0 <= float(parsed) <= 100:
            return None
        return parsed
    if kind == "date":
        return _date(value)
    if kind == "list":
        return _list(value)
    if kind == "team":
        return _team(value)
    if kind == "object":
        return dict(value) if isinstance(value, dict) else None
    return str(value).strip() or None


def normalize_fact_entry(key, raw, *, kit=None, default_source="user", default_evidence=""):
    definitions = field_definitions(kit)
    canonical = canonical_field_key(key, kit)
    if canonical is None:
        raise ValueError(f"Unknown decision field: {key}")
    entry = dict(raw) if isinstance(raw, dict) else {"value": raw}
    source = str(entry.get("source") or default_source).strip().lower()
    if source not in {"user", "document", "connector", "calculated", "assumed"}:
        raise ValueError(f"Invalid source for {canonical}")
    value = normalize_value(entry.get("value"), definitions.get(canonical, {}))
    if entry.get("value") not in (None, "") and value is None:
        raise ValueError(f"Invalid value for {canonical}")
    evidence = str(entry.get("evidence") or default_evidence or "").strip()
    result = {"value": value, "source": source, "evidence": evidence}
    if source == "assumed":
        result["assumption"] = {
            "basis": str(entry.get("basis") or entry.get("assumption_basis") or "").strip() or None,
            "bounds": entry.get("bounds"),
        }
    if definitions.get(canonical, {}).get("unit"):
        result["unit"] = definitions[canonical]["unit"]
    return canonical, result


def _candidate(pattern, text, key, *, flags=re.I, group=1):
    match = re.search(pattern, text, flags)
    if not match:
        return None
    return key, match.group(group), match.group(0).strip()


def extract_candidate_facts(text, kit):
    """Extract only explicit, high-precision facts from user language.

    Ambiguous prose remains prose.  This deliberately small grammar handles
    common intake facts without guessing and can be extended by field config.
    """
    if not kit or not str(text or "").strip():
        return []
    text = str(text)
    candidates = []
    patterns = [
        (r"(?:expected\s+)?margin(?:\s+(?:is|of|=|at))?\s*\$?([0-9]+(?:\.[0-9]+)?)\s*%", "margin_pct"),
        (r"(?:win\s+(?:probability|chance)|probability\s+of\s+winning)(?:\s+(?:is|of|=|at))?\s*([0-9]+(?:\.[0-9]+)?)\s*%", "win_probability"),
        (r"(?:contract\s+(?:value|amount)|value\s+of\s+the\s+contract)(?:\s+(?:is|of|=|at))?\s*\$?([0-9][0-9,]*(?:\.[0-9]+)?\s*[kmb]?)", "contract_value"),
        (r"(?:pursuit|proposal|bid)\s+cost(?:\s+(?:is|of|=|at))?\s*\$?([0-9][0-9,]*(?:\.[0-9]+)?\s*[kmb]?)", "pursuit_cost"),
        (r"(?:bonding|bond|capacity)(?:\s+(?:requirement|draw|needed|limit))?(?:\s+(?:is|of|=|at))?\s*\$?([0-9][0-9,]*(?:\.[0-9]+)?\s*[kmb]?)", "capacity_draw"),
        (r"(?:proposal\s+price|bid\s+price)(?:\s+(?:is|of|=|at))?\s*\$?([0-9][0-9,]*(?:\.[0-9]+)?\s*[kmb]?)", "proposal_price"),
        (r"(?:total\s+cost\s+of\s+ownership|tco)(?:\s+(?:is|of|=|at))?\s*\$?([0-9][0-9,]*(?:\.[0-9]+)?\s*[kmb]?)", "tco"),
        (r"(?:submission\s+)?(?:deadline|due\s+date|due)(?:\s+(?:is|=|on))?\s+([A-Za-z]{3,9}\s+\d{1,2}(?:,?\s+\d{4})?|\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})", "submission_due"),
        (r"(?:pursuit|response|selection)\s+team(?:\s+(?:is|includes|:))\s*([^.;\n]+)", "team"),
        (r"mandatory\s+requirements?(?:\s+(?:are|include|:))\s*([^.;\n]+(?:[;][^\n]+)?)", "mandatory_requirements"),
    ]
    definitions = field_definitions(kit)
    for pattern, key in patterns:
        if key not in definitions:
            continue
        found = _candidate(pattern, text, key)
        if found:
            candidates.append(found)
    return candidates


def option_fact_text(source_text, option_name=None):
    """Return the user-authored clauses that name one option.

    This prevents a batch fact stated for Aurora from being attached to Commerce
    City.  A single unnamed option may use the complete user corpus.
    """
    source = str(source_text or "").strip()
    name = str(option_name or "").strip()
    if not source or not name:
        return source
    clauses = [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", source) if part.strip()]
    matches = [part for part in clauses if name.lower() in part.lower()]
    return "\n".join(matches)


def normalize_option_facts(attributes, *, kit=None, source_text="", extract=True, option_name=None):
    normalized = {}
    for key, raw in (attributes or {}).items():
        canonical, entry = normalize_fact_entry(key, raw, kit=kit)
        normalized[canonical] = entry
    if extract:
        for key, value, evidence in extract_candidate_facts(source_text, kit):
            canonical, entry = normalize_fact_entry(
                key, {"value": value, "source": "user", "evidence": evidence}, kit=kit
            )
            normalized[canonical] = entry
    return normalized


def apply_assumption_confidence_caps(scorecard, attributes, kit=None):
    """Demote dimensions affected by explicit assumptions, then expose them."""
    output = dict(scorecard or {})
    dimensions = {key: dict(value) for key, value in (output.get("dimensions") or {}).items() if isinstance(value, dict)}
    definitions = field_definitions(kit)
    assumptions = []
    affected = set()
    for key, entry in (attributes or {}).items():
        if not isinstance(entry, dict) or entry.get("source") != "assumed":
            continue
        definition = definitions.get(key, {})
        impacts = definition.get("affects") or []
        affected.update(str(item) for item in impacts)
        assumptions.append({
            "field": key,
            "value": entry.get("value"),
            "basis": (entry.get("assumption") or {}).get("basis"),
            "bounds": (entry.get("assumption") or {}).get("bounds"),
            "affects": list(impacts),
        })
    for key in affected:
        if key in dimensions:
            dimensions[key]["confidence"] = "assumed"
            dimensions[key]["confidence_cap_reason"] = "depends on an assumed fact"
    output["dimensions"] = dimensions
    gates = []
    for gate in output.get("gates") or []:
        if not isinstance(gate, dict):
            continue
        normalized_gate = dict(gate)
        if str(normalized_gate.get("key") or "") in affected:
            normalized_gate.update({
                "status": "unknown",
                "confidence": "assumed",
                "source": "assumed",
                "basis": "depends on an assumed fact",
            })
        gates.append(normalized_gate)
    output["gates"] = gates
    if assumptions:
        existing = output.get("assumptions") if isinstance(output.get("assumptions"), list) else []
        output["assumptions"] = [*existing, *assumptions]
    output["assumption_register"] = assumptions
    return output
