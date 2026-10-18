"""Canonical, deterministic fact normalization for every decision path.

The model may identify candidate facts, but this module owns field validation,
types, units, provenance, and null handling.  Decision Kits only describe the
fields; they do not get a separate fact engine.
"""

from datetime import date, datetime, timedelta
import calendar
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
    "proposal_due": "submission_due",
    "proposal_due_date": "submission_due",
    "requirements": "mandatory_requirements",
    "bonding": "capacity_draw",
    "bonding_requirement": "capacity_draw",
    "capacity": "capacity_draw",
    "contract_amount": "contract_value",
    "price": "proposal_price",
    "5yr_tco": "tco",
    "5_year_tco": "tco",
    "five_year_tco": "tco",
    "five_yr_tco": "tco",
}

# Shared schema-owned semantic identities. These are not a phrase extractor;
# they define which provider field keys represent the same canonical fact in
# every Decision Kit and general scoring path.
_COMMON_FIELD_DEFINITIONS = {
    "build_out_cost": {"aliases": ["buildout_cost"], "type": "money", "unit": "USD"},
    "monthly_lease": {"aliases": ["lease_monthly", "monthly_rent"], "type": "money", "unit": "USD"},
    "projected_first_year_revenue": {
        "aliases": ["projected_year1_revenue", "projected_year_one_revenue"],
        "type": "money",
        "unit": "USD",
    },
    # Governed connector metrics use the same canonical fact/provenance path as
    # user and document facts. Their values are computed before the model sees
    # them; the model may cite them but cannot redefine the arithmetic.
    "jira_active_project_count": {"type": "number", "unit": "projects"},
    "jira_completion_percent": {"type": "percentage", "unit": "percent_points"},
    "jira_throughput_per_week": {"type": "number", "unit": "issues_per_week"},
    "jira_overdue_share": {"type": "number", "unit": "ratio"},
    "jira_overdue_count": {"type": "number", "unit": "issues"},
    "jira_at_risk_project_count": {"type": "number", "unit": "projects"},
    "jira_blocked_count": {"type": "number", "unit": "issues"},
    "jira_overloaded_assignee_count": {"type": "number", "unit": "people"},
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


_RELATIVE_DATE_UNITS = {
    "day": "days", "days": "days",
    "week": "weeks", "weeks": "weeks",
    "month": "months", "months": "months",
    "business_day": "business_days", "business_days": "business_days",
    "business day": "business_days", "business days": "business_days",
}


def _relative_date(relative, reference_date):
    """Resolve provider-structured relative time using a fixed evidence date."""
    if not isinstance(relative, dict):
        return None, None
    try:
        amount = int(relative.get("amount"))
    except (TypeError, ValueError):
        return None, None
    unit = _RELATIVE_DATE_UNITS.get(str(relative.get("unit") or "").strip().lower())
    reference = _date(reference_date)
    if amount < 0 or amount > 10000 or not unit or not reference:
        return None, None
    start = date.fromisoformat(reference)
    if unit == "days":
        resolved = start + timedelta(days=amount)
    elif unit == "weeks":
        resolved = start + timedelta(weeks=amount)
    elif unit == "months":
        month_index = start.month - 1 + amount
        year = start.year + month_index // 12
        month = month_index % 12 + 1
        resolved = date(year, month, min(start.day, calendar.monthrange(year, month)[1]))
    else:
        resolved = start
        remaining = amount
        while remaining:
            resolved += timedelta(days=1)
            if resolved.weekday() < 5:
                remaining -= 1
    return resolved.isoformat(), {"amount": amount, "unit": unit}


def evidence_reference_date(session, evidence):
    """Return the date of the user message containing an exact evidence quote."""
    needle = str(evidence or "").strip().casefold()
    history = (session or {}).get("chat_history") if isinstance(session, dict) else None
    for message in reversed(history or []):
        if not isinstance(message, dict) or str(message.get("role") or "").lower() not in {"user", "human"}:
            continue
        content = str(message.get("content") or message.get("text") or "")
        if needle and needle not in content.casefold():
            continue
        stamp = message.get("timestamp") or message.get("created_at") or message.get("createdAt")
        parsed = _date(stamp)
        if parsed:
            return parsed
    return None


def attach_relative_reference(raw, session):
    """Add the immutable message date to a structured relative date candidate."""
    if not isinstance(raw, dict):
        return raw
    value = raw.get("value")
    relative = raw.get("relative") or (value.get("relative") if isinstance(value, dict) else None)
    if not isinstance(relative, dict) or raw.get("reference_date"):
        return raw
    reference = evidence_reference_date(session, raw.get("evidence"))
    return {**raw, "reference_date": reference} if reference else raw


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
    definitions = field_definitions(kit)
    # Decision Kit schemas own semantic field identity. This lets extraction
    # vocabulary evolve with a versioned field definition instead of growing a
    # global phrase list that can reinterpret unrelated decisions.
    for canonical, definition in definitions.items():
        aliases = [canonical, *(definition.get("aliases") or [])]
        if normalized in {
            re.sub(r"[^a-z0-9]+", "_", str(alias or "").strip().lower()).strip("_")
            for alias in aliases
        }:
            return canonical
    for canonical, definition in _COMMON_FIELD_DEFINITIONS.items():
        aliases = [canonical, *(definition.get("aliases") or [])]
        if normalized in {
            re.sub(r"[^a-z0-9]+", "_", str(alias or "").strip().lower()).strip("_")
            for alias in aliases
        }:
            normalized = canonical
            break
    normalized = _ALIASES.get(normalized, normalized)
    # Shared canonical fields remain valid when a Decision Kit is active. A
    # kit adds typed fields; it must not make the shared schema reject a fact
    # that the same capture layer already stored on an earlier turn.
    if definitions and normalized not in definitions and normalized not in _COMMON_FIELD_DEFINITIONS:
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
        if kind == "percentage":
            numeric = float(parsed)
            explicit_percent_points = isinstance(value, str) and "%" in value
            explicit_fraction = str((field or {}).get("input_unit") or "").lower() in {"fraction", "ratio"}
            # Canonical percentage representation is percent points (60, 8).
            # Provider JSON commonly emits fractions (0.60, 0.08); numeric
            # values in [0, 1] are therefore normalized once at this boundary.
            # A string containing '%' is already expressed in percent points.
            if not explicit_percent_points and (explicit_fraction or 0 < numeric <= 1):
                parsed = _number(Decimal(str(parsed)) * Decimal(100))
            if not 0 <= float(parsed) <= 100:
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
    normalized = str(value).strip() or None
    if kind == "enum" and normalized:
        value_aliases = (field or {}).get("value_aliases") or {}
        alias_key = re.sub(r"\s+", " ", normalized.casefold()).strip(" .")
        normalized = value_aliases.get(alias_key, normalized)
    return normalized


def _enum_value_from_user_excerpt(evidence, field_definition):
    aliases = dict(field_definition.get("value_aliases") or {})
    enum_phrases = {
        str(alias).strip(): str(canonical_value).strip()
        for alias, canonical_value in aliases.items()
        if str(alias).strip() and str(canonical_value).strip()
    }
    enum_phrases.update({value: value for value in enum_phrases.values()})
    derived_values = set()
    for phrase, canonical_value in enum_phrases.items():
        for match in re.finditer(
            rf"(?<![A-Za-z0-9]){re.escape(phrase)}(?![A-Za-z0-9])",
            str(evidence or ""),
            re.I,
        ):
            # A correction such as "has not declined; still pending" must
            # not preserve the explicitly negated prior state.
            if re.search(r"\bnot\s+$", str(evidence)[:match.start()], re.I):
                continue
            derived_values.add(canonical_value)
    return next(iter(derived_values)) if len(derived_values) == 1 else None


def normalize_fact_entry(key, raw, *, kit=None, default_source="user", default_evidence=""):
    definitions = field_definitions(kit)
    entry = dict(raw) if isinstance(raw, dict) else {"value": raw}
    normalized_key = re.sub(r"[^a-z0-9]+", "_", str(key or "").strip().lower()).strip("_")
    normalized_raw_value = re.sub(
        r"\s+", " ", str(entry.get("value") or "").casefold()
    ).strip(" .")
    canonical = None
    # Some provider field names are ambiguous without their value. A Decision
    # Kit may resolve those aliases only for an explicit, bounded enum value;
    # missing or numeric values continue through the ordinary canonical alias.
    for candidate, definition in definitions.items():
        for alias, accepted_values in (definition.get("conditional_aliases") or {}).items():
            normalized_alias = re.sub(
                r"[^a-z0-9]+", "_", str(alias or "").strip().lower()
            ).strip("_")
            accepted = {
                re.sub(r"\s+", " ", str(value or "").casefold()).strip(" .")
                for value in (accepted_values or [])
            }
            if normalized_key == normalized_alias and normalized_raw_value in accepted:
                canonical = candidate
                break
        if canonical:
            break
    canonical = canonical or canonical_field_key(key, kit)
    if canonical is None:
        raise ValueError(f"Unknown decision field: {key}")
    source = str(entry.get("source") or default_source).strip().lower()
    if source not in {"user", "document", "connector", "calculated", "assumed"}:
        raise ValueError(f"Invalid source for {canonical}")
    field_definition = definitions.get(canonical) or _COMMON_FIELD_DEFINITIONS.get(canonical, {})
    raw_value = entry.get("value")
    evidence = str(entry.get("evidence") or default_evidence or "").strip()
    field_type = str(field_definition.get("type") or "").lower()
    if source == "user" and evidence and field_type == "text":
        # The user's exact words are the fact. Provider paraphrases remain useful
        # for assigning a field, but must not replace user-stated text.
        raw_value = evidence
    elif source == "user" and evidence and field_type == "enum":
        derived_value = _enum_value_from_user_excerpt(evidence, field_definition)
        if derived_value is not None:
            raw_value = derived_value
        elif field_definition.get("value_aliases"):
            raise ValueError(f"User evidence does not determine one value for {canonical}")
    relative = entry.get("relative")
    reference_date = entry.get("reference_date")
    if isinstance(raw_value, dict):
        relative = relative or raw_value.get("relative")
        reference_date = reference_date or raw_value.get("reference_date")
    if field_type == "date" and relative:
        value, normalized_relative = _relative_date(relative, reference_date)
    else:
        value = normalize_value(raw_value, field_definition)
        normalized_relative = None
    if entry.get("value") not in (None, "") and value is None:
        raise ValueError(f"Invalid value for {canonical}")
    result = {"value": value, "source": source, "evidence": evidence}
    if normalized_relative:
        result["relative"] = normalized_relative
        result["reference_date"] = _date(reference_date)
    for provenance_key in ("source_id", "locator"):
        if entry.get(provenance_key) not in (None, ""):
            result[provenance_key] = entry.get(provenance_key)
    if source == "assumed":
        result["assumption"] = {
            "basis": str(entry.get("basis") or entry.get("assumption_basis") or "").strip() or None,
            "bounds": entry.get("bounds"),
            "affects": [str(item) for item in (entry.get("affects") or []) if str(item).strip()],
        }
    if field_definition.get("unit"):
        result["unit"] = field_definition["unit"]
    elif str(field_definition.get("type") or "").lower() == "percentage":
        result["unit"] = "percent_points"
    return canonical, result


_GENERIC_EVIDENCE_TERMS = {
    "amount", "date", "expected", "first", "requirement", "status", "value", "year",
}


def ground_user_evidence(key, value, claimed_evidence, source_text, *, kit=None, relative=None):
    """Return an exact user excerpt supporting a canonical field/value pair.

    A provider may paraphrase an excerpt, but stored provenance must remain the
    user's words. Text values come from that excerpt, enums resolve only through
    schema-owned values and aliases, and numeric/date values must still match
    exactly. No value is invented here.
    """
    corpus = str(source_text or "")
    claimed = str(claimed_evidence or "").strip()
    if not corpus:
        return None
    claimed_excerpt = None
    if claimed:
        start = corpus.casefold().find(claimed.casefold())
        if start >= 0:
            claimed_excerpt = corpus[start:start + len(claimed)]

    canonical = canonical_field_key(key, kit)
    if not canonical:
        return None
    definitions = field_definitions(kit)
    definition = definitions.get(canonical) or _COMMON_FIELD_DEFINITIONS.get(canonical, {})
    field_type = str(definition.get("type") or "").lower()
    if claimed_excerpt and field_type == "text":
        return claimed_excerpt
    if claimed_excerpt and field_type == "enum" and definition.get("value_aliases"):
        return claimed_excerpt if _enum_value_from_user_excerpt(claimed_excerpt, definition) is not None else None
    expected = normalize_value(value, definition)
    if expected is None:
        return None

    def schema_terms(field_key, field_definition):
        phrases = [field_key, field_definition.get("label"), *(field_definition.get("aliases") or [])]
        return {
            token
            for phrase in phrases if phrase
            for token in re.findall(r"[a-z0-9]+", str(phrase).casefold().replace("_", " "))
            if len(token) >= 3 and token not in _GENERIC_EVIDENCE_TERMS
        }

    field_terms = schema_terms(canonical, definition)
    all_definitions = {**_COMMON_FIELD_DEFINITIONS, **definitions}
    other_field_terms = set().union(*(
        schema_terms(field_key, field_definition)
        for field_key, field_definition in all_definitions.items()
        if field_key != canonical
    )) if len(all_definitions) > 1 else set()

    numeric_kind = field_type in {"money", "number", "percentage"}
    date_kind = field_type == "date"
    # Relative dates are accepted only from the provider's exact cited words;
    # code verifies amount/unit but never searches prose to infer the phrase.
    if date_kind and isinstance(relative, dict) and not claimed_excerpt:
        return None
    corpus_candidates = [
        part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", corpus) if part.strip()
    ]
    candidates = ([claimed_excerpt] if claimed_excerpt else []) + list(reversed(corpus_candidates))
    for sentence in candidates:
        is_claimed_fragment = bool(claimed_excerpt and sentence == claimed_excerpt and sentence != corpus)
        if numeric_kind:
            for clause in re.split(r";|,(?!\s*\d)", sentence):
                raw_numbers = re.findall(
                    r"\$?\s*[0-9][0-9,]*(?:\.[0-9]+)?\s*[kmb%]?",
                    clause,
                    flags=re.I,
                )
                if not any(normalize_value(raw_number, definition) == expected for raw_number in raw_numbers):
                    continue
                clause_terms = set(re.findall(r"[a-z0-9]+", clause.casefold().replace("-", " ")))
                if field_terms.intersection(clause_terms):
                    return sentence
                # The model owns the semantic assignment for an unlabeled
                # value. Code accepts it only when no competing schema field
                # label appears in the same clause as that exact value.
                if not other_field_terms.intersection(clause_terms) and not is_claimed_fragment:
                    return sentence
        elif date_kind and isinstance(relative, dict):
            try:
                amount = str(int(relative.get("amount")))
            except (TypeError, ValueError):
                continue
            unit = _RELATIVE_DATE_UNITS.get(str(relative.get("unit") or "").strip().lower())
            if not unit:
                continue
            unit_words = {
                "days": ("day", "days"), "weeks": ("week", "weeks"),
                "months": ("month", "months"),
                "business_days": ("business day", "business days"),
            }[unit]
            has_amount = re.search(rf"(?<![0-9]){re.escape(amount)}(?![0-9])", sentence)
            has_unit = any(re.search(rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])", sentence, re.I) for word in unit_words)
            if has_amount and has_unit:
                return sentence
        elif date_kind:
            for clause in re.split(r";|,(?!\s*\d)", sentence):
                raw_dates = re.findall(
                    r"[A-Za-z]{3,9}\s+\d{1,2}(?:,?\s+\d{4})?|\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2}",
                    clause,
                )
                if not any(normalize_value(raw_date, definition) == expected for raw_date in raw_dates):
                    continue
                clause_terms = set(re.findall(r"[a-z0-9]+", clause.casefold().replace("-", " ")))
                if field_terms.intersection(clause_terms) or not other_field_terms.intersection(clause_terms):
                    return sentence
        elif str(definition.get("type") or "").lower() == "enum":
            accepted_phrases = {str(expected)}
            for alias, canonical_value in (definition.get("value_aliases") or {}).items():
                if normalize_value(alias, definition) == expected and canonical_value == expected:
                    accepted_phrases.add(str(alias))
            if any(
                re.search(rf"(?<![A-Za-z0-9]){re.escape(phrase)}(?![A-Za-z0-9])", sentence, re.I)
                for phrase in accepted_phrases if phrase
            ):
                return sentence
        else:
            sentence_terms = set(re.findall(r"[a-z0-9]+", sentence.casefold().replace("-", " ")))
            if field_terms.intersection(sentence_terms) and str(expected).casefold() in sentence.casefold():
                return sentence
    return None


def option_evidence_identities(session, option_key=None, option_name=None, extra_names=None):
    """Return current and other known names for evidence containment checks."""
    session = session if isinstance(session, dict) else {}
    registry = session.get("option_registry") if isinstance(session.get("option_registry"), dict) else {}
    alias_index = session.get("option_aliases") if isinstance(session.get("option_aliases"), dict) else {}
    current_key = str(option_key or "").strip()
    current = {str(option_name or "").strip()}
    others = set()
    for key, item in registry.items():
        if not isinstance(item, dict):
            continue
        values = [item.get("display_name"), *(item.get("aliases") or [])]
        target = current if current_key and str(key) == current_key else others
        target.update(str(value or "").strip() for value in values if str(value or "").strip())
    normalized_current = {
        re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
        for value in current if value
    }
    for value in (extra_names or []):
        text = str(value or "").strip()
        normalized = re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()
        if not text:
            continue
        if normalized in normalized_current or (current_key and str(alias_index.get(normalized) or "") == current_key):
            current.add(text)
        else:
            others.add(text)
    current.discard("")
    others.difference_update(current)
    return sorted(current, key=len, reverse=True), sorted(others, key=len, reverse=True)


def ground_option_user_evidence(
    key,
    value,
    claimed_evidence,
    option_source_text,
    full_source_text,
    *,
    kit=None,
    current_option_names=None,
    other_option_names=None,
    relative=None,
):
    """Ground an AI-assigned option fact without expanding option semantics.

    The option section remains the first authority. A verbatim claimed excerpt
    may fall back to the full user corpus only when it names no known different
    option. This lets the model assign genuinely shared statements while code
    continues to enforce exact wording and option containment.
    """
    normalized_current = {
        re.sub(r"[^a-z0-9]+", " ", str(name or "").casefold()).strip()
        for name in (current_option_names or []) if str(name or "").strip()
    }
    normalized_others = {
        re.sub(r"[^a-z0-9]+", " ", str(name or "").casefold()).strip()
        for name in (other_option_names or []) if str(name or "").strip()
    } - normalized_current

    def names_different_option(text):
        normalized_text = re.sub(r"[^a-z0-9]+", " ", str(text or "").casefold()).strip()
        return any(
            re.search(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", normalized_text)
            for name in normalized_others if name
        )

    grounded = ground_user_evidence(
        key, value, claimed_evidence, option_source_text, kit=kit, relative=relative,
    )
    if grounded and not names_different_option(grounded):
        return grounded
    corpus = str(full_source_text or "")
    claimed = str(claimed_evidence or "").strip()
    if not corpus or not claimed:
        return None
    start = corpus.casefold().find(claimed.casefold())
    if start < 0:
        return None
    excerpt = corpus[start:start + len(claimed)]
    if names_different_option(excerpt):
        return None
    return ground_user_evidence(key, value, excerpt, excerpt, kit=kit, relative=relative)


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
    # Enumerated aliases are schema-owned values, so an exact phrase can fill
    # a missing enum without asking the model to restate it. Keep the complete
    # source sentence as provenance and prefer the longest matching alias.
    captured_keys = {key for key, _value, _evidence in candidates}
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", text) if part.strip()]
    for key, definition in definitions.items():
        if key in captured_keys or str(definition.get("type") or "").lower() != "enum":
            continue
        aliases = definition.get("value_aliases") if isinstance(definition.get("value_aliases"), dict) else {}
        matches = []
        for phrase, canonical_value in aliases.items():
            phrase = str(phrase or "").strip()
            if not phrase:
                continue
            for sentence in sentences:
                match = re.search(rf"(?<![A-Za-z0-9]){re.escape(phrase)}(?![A-Za-z0-9])", sentence, re.I)
                if match:
                    matches.append((len(phrase), match.start(), canonical_value, sentence))
        if matches:
            _length, _position, value, evidence = max(matches, key=lambda item: (item[0], -item[1]))
            candidates.append((key, value, evidence))
    return candidates


def option_fact_text(source_text, option_name=None, option_names=None):
    """Return one option's complete user-authored section.

    Headings may be semantic (``Option A``), ordinal (``Vendor 1``), or simply
    the option's name. The known option names determine both identity and
    boundaries; generic labels are accepted without making the parser RFP-only.
    """
    source = str(source_text or "").strip()
    name = str(option_name or "").strip()
    if not source or not name:
        return source
    names = [str(value or "").strip() for value in (option_names or [])]
    if name not in names:
        names.append(name)
    names = sorted({value for value in names if value}, key=len, reverse=True)
    heading = "|".join(re.escape(value) for value in names)
    if heading:
        marker = re.compile(
            rf"(?im)(?:^|(?<=[.!?])\s+|\n+)"
            rf"(?P<header>(?:"
            rf"(?:option|vendor|bid|proposal|alternative)\s+[A-Za-z0-9_-]+(?:\s+[^:\n.]{{1,100}})?\s*:"
            rf"|(?:\d+|[A-Z])[.)]\s*[^:\n.]{{1,100}}\s*:"
            rf"|(?:{heading})(?=\s*(?::|[-–—]|\.|\b(?:has|offers|requires|costs|is|can|cannot|will)\b))[^\n]{{0,100}}?(?::|\.)))",
        )
        matches = list(marker.finditer(source))
        for index, match in enumerate(matches):
            start = match.start("header")
            end = matches[index + 1].start("header") if index + 1 < len(matches) else len(source)
            section = source[start:end].strip()
            heading_context = re.split(r"(?<=[.!?])\s+|\n+", section, maxsplit=1)[0]
            if name.lower() not in heading_context.lower():
                continue
            # A lone prose sentence such as "Aurora has ..." is not enough to
            # establish a section boundary. Preserve the legacy clause-level
            # behavior unless another named section or an explicit heading is
            # present.
            explicit_heading = ":" in match.group("header")
            if len(matches) == 1 and not explicit_heading:
                continue
            return section
    clauses = [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", source) if part.strip()]
    matches = [part for part in clauses if name.lower() in part.lower()]
    return "\n".join(matches)


def normalize_option_facts(
    attributes,
    *,
    kit=None,
    source_text="",
    extract=False,
    extract_types=None,
    option_name=None,
    rejected_fields=None,
    session=None,
):
    """Normalize recognizable facts without letting one bad field abort.

    ``normalize_fact_entry`` remains the strict validator for one field. This
    collection boundary keeps rejected fields out of canonical facts and can
    report them separately to the caller for audit storage, while valid sibling
    fields continue through scoring.
    """
    normalized = {}
    for key, raw in (attributes or {}).items():
        try:
            canonical, entry = normalize_fact_entry(
                key, attach_relative_reference(raw, session), kit=kit,
            )
        except ValueError as exc:
            if isinstance(rejected_fields, list):
                raw_entry = dict(raw) if isinstance(raw, dict) else {"value": raw}
                rejected_fields.append({
                    "field": str(key or ""),
                    "value": raw_entry.get("value"),
                    "source": raw_entry.get("source"),
                    "evidence": raw_entry.get("evidence"),
                    "affects": raw_entry.get("affects") or [],
                    "reason": str(exc),
                })
            continue
        normalized[canonical] = entry
    # Legacy deterministic extraction is opt-in only. Production scoring gets
    # candidates from the governed AI/tool extraction boundary, then validates
    # them here. Phrase matching must never define canonical meaning.
    if extract:
        allowed_types = {
            str(value or "").strip().lower() for value in (extract_types or [])
            if str(value or "").strip()
        }
        definitions = field_definitions(kit)
        for key, value, evidence in extract_candidate_facts(source_text, kit):
            canonical, entry = normalize_fact_entry(
                key, {"value": value, "source": "user", "evidence": evidence}, kit=kit
            )
            if allowed_types and str((definitions.get(canonical) or {}).get("type") or "").lower() not in allowed_types:
                continue
            # The governed fact payload remains authoritative. Deterministic
            # extraction only fills an explicit typed fact the provider omitted.
            normalized.setdefault(canonical, entry)
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
        impacts = (entry.get("assumption") or {}).get("affects") or definition.get("affects") or []
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
