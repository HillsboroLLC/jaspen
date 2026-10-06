"""Apply Decision Kit mechanics to canonical scorecard payloads."""

import hashlib
import json
import re

from .decision_kits import get_decision_kit
from .decision_metrics import calculate_metrics
from .decision_recommendation import recommend


def _quote_in_corpus(quote, corpus):
    quote = " ".join(str(quote or "").split()).lower()
    corpus = " ".join(str(corpus or "").split()).lower()
    return bool(quote and quote in corpus)


_GATE_FAIL_RE = re.compile(
    r"\b(?:cannot|can't|unable\s+to|never|does\s+not|doesn't|do\s+not|don't|"
    r"not\s+(?:meet|met|satisfy|satisfied|comply|compliant|available|confirmed)|"
    r"fails?|failed|lacks?|missing|unavailable|infeasible)\b",
    re.I,
)
_GATE_PASS_RE = re.compile(
    r"\b(?:can|able\s+to|meets?|met|satisf(?:y|ies|ied)|complies?|compliant|"
    r"confirmed|feasible|has\s+(?:successfully\s+)?integrated|is\s+available|will\s+meet)\b",
    re.I,
)
_GATE_STOPWORDS = {"the", "and", "for", "with", "must", "gate", "requirement", "required", "only", "option"}


def _gate_terms(definition):
    text = " ".join(str((definition or {}).get(key) or "") for key in ("key", "label", "gate_rule", "description"))
    return {
        word for word in re.findall(r"[a-z0-9%]+", text.lower())
        if len(word) > 2 and word not in _GATE_STOPWORDS
    }


def _grounded_gate_evidence(item, definition, corpus):
    supplied = [
        str(value).strip() for value in ((item or {}).get("evidence") or [])
        if _quote_in_corpus(value, corpus)
    ]
    if supplied:
        return supplied
    terms = _gate_terms(definition)
    if not terms:
        return []
    candidates = [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", str(corpus or "")) if part.strip()]
    for sentence in candidates:
        sentence_terms = set(re.findall(r"[a-z0-9%]+", sentence.lower()))
        if terms & sentence_terms and (_GATE_FAIL_RE.search(sentence) or _GATE_PASS_RE.search(sentence)):
            return [sentence]
    return []


def _deterministic_gate_status(evidence):
    text = " ".join(str(value or "") for value in evidence)
    if _GATE_FAIL_RE.search(text):
        return "fail"
    if _GATE_PASS_RE.search(text):
        return "pass"
    return "unknown"


def _gate_applies(item, option_key=None, option_name=None):
    explicit = str((item or {}).get("option_key") or "").strip()
    if explicit:
        return explicit == str(option_key or "").strip()
    scope = str(
        (item or {}).get("option_scope")
        or (item or {}).get("scope")
        or (item or {}).get("applies_to")
        or (item or {}).get("option")
        or ""
    ).strip()
    if not scope:
        descriptive = " ".join(str((item or {}).get(key) or "") for key in ("label", "gate_rule", "description", "rule"))
        scoped_match = re.search(r"\b(option\s+[A-Za-z0-9_-]+\s+only)\b", descriptive, re.I)
        scope = scoped_match.group(1) if scoped_match else ""
    if not scope:
        return True
    normalize = lambda value: re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()
    target, scoped = normalize(option_name or option_key), normalize(scope)
    for prefix in ("option ", "opt "):
        if target.startswith(prefix): target = target[len(prefix):]
        if scoped.startswith(prefix): scoped = scoped[len(prefix):]
    scoped = re.sub(r"\s+only$", "", scoped).strip()
    target_words, scoped_words = target.split(), scoped.split()
    return bool(
        target_words and scoped_words
        and (target == scoped or target_words[0] == scoped_words[0])
    )


def normalize_gates(raw_gates, rubric, evidence_corpus="", option_key=None, option_name=None):
    criteria = (rubric or {}).get("criteria") if isinstance((rubric or {}).get("criteria"), list) else []
    approved = bool((rubric or {}).get("approved_by_user_at"))
    option_key = str(option_key or "").strip()
    definitions = {
        str(item.get("key")): item
        for item in criteria
        if isinstance(item, dict)
        and item.get("gate")
        and item.get("key")
        and _gate_applies(item, option_key, option_name)
    }
    if not approved:
        return []
    supplied = {
        str(item.get("key")): item
        for item in (raw_gates or [])
        if isinstance(item, dict)
        and item.get("key")
        and _gate_applies(item, option_key, option_name)
    }
    normalized = []
    for key, definition in definitions.items():
        item = supplied.get(key) or {}
        evidence = _grounded_gate_evidence(item, definition, evidence_corpus)
        source = str(item.get("source") or ("user" if evidence else "assumed")).lower()
        confidence = str(item.get("confidence") or ("medium" if evidence else "assumed")).lower()
        status = _deterministic_gate_status(evidence)
        if status != "unknown" and source == "assumed":
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
    output["gates"] = normalize_gates(
        output.get("gates"),
        output.get("scoring_rubric") or output.get("rubric"),
        evidence_corpus,
        option_key=output.get("option_key"),
        option_name=output.get("project_name") or output.get("initiative_name") or output.get("name"),
    )
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
