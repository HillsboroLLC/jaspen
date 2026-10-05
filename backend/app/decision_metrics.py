"""Pure, deterministic formulas for structured decision metrics."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def _decimal(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = Decimal(str(value).replace(",", "").replace("$", "").replace("%", "").strip())
    except (InvalidOperation, AttributeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _number(value):
    value = value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP).normalize()
    return int(value) if value == value.to_integral_value() else float(value)


def expected_value(value, probability, margin):
    values = [_decimal(value), _decimal(probability), _decimal(margin)]
    if any(item is None for item in values):
        return None
    return _number(values[0] * (values[1] / Decimal(100)) * (values[2] / Decimal(100)))


def ratio(a, b):
    numerator, denominator = _decimal(a), _decimal(b)
    if numerator is None or denominator in {None, Decimal(0)}:
        return None
    return _number(numerator / denominator)


def per_unit(a, quantity):
    return ratio(a, quantity)


def sum_values(values):
    parsed = [_decimal(value) for value in values]
    if any(value is None for value in parsed):
        return None
    return _number(sum(parsed, Decimal(0)))


def difference(a, b):
    left, right = _decimal(a), _decimal(b)
    if left is None or right is None:
        return None
    return _number(left - right)


FORMULAS = {"expected_value": expected_value, "ratio": ratio, "per_unit": per_unit, "sum": sum_values, "difference": difference}


def attribute_entry(attributes, key):
    entry = (attributes or {}).get(key)
    return entry if isinstance(entry, dict) else {"value": entry} if entry is not None else None


def calculate_metrics(attributes, metric_specs, *, context=None):
    attributes = attributes if isinstance(attributes, dict) else {}
    context = context if isinstance(context, dict) else {}
    results = {}
    for spec in metric_specs or []:
        if not isinstance(spec, dict) or spec.get("formula") not in FORMULAS:
            continue
        input_values, input_trace, assumed, missing = [], {}, [], []
        for input_key in spec.get("inputs") or []:
            if str(input_key).startswith("metric:"):
                ref = str(input_key).split(":", 1)[1]
                entry = results.get(ref)
                value = entry.get("value") if isinstance(entry, dict) else None
                trace = {"value": value, "source": "calculated", "metric": ref}
            elif str(input_key).startswith("context:"):
                ref = str(input_key).split(":", 1)[1]
                raw = context.get(ref)
                trace = raw if isinstance(raw, dict) else {"value": raw, "source": "context"}
                value = trace.get("value")
            else:
                trace = attribute_entry(attributes, input_key) or {"value": None, "source": None}
                value = trace.get("value")
            input_values.append(value)
            input_trace[str(input_key)] = {k: trace.get(k) for k in ("value", "source", "evidence") if trace.get(k) is not None}
            if value in (None, ""):
                missing.append(str(input_key).split(":", 1)[-1])
            if trace.get("source") == "assumed":
                assumed.append(str(input_key))
        value = None if missing else FORMULAS[spec["formula"]](*input_values)
        results[spec["key"]] = {
            "value": value,
            "label": spec.get("label") or spec["key"],
            "formula": spec["formula"],
            "inputs": input_trace,
            "inputs_assumed": assumed,
            "missing_inputs": missing,
            "message": f"Add {missing[0]} to calculate" if missing else None,
        }
    return results
