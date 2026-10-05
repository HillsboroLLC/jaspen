"""Deterministic constrained option selection for Decision Kits."""

from itertools import combinations
import math


def _entry_value(option, key):
    if key == "jaspen_score":
        value = option.get("jaspen_score")
    else:
        container = option.get("metrics") if key in (option.get("metrics") or {}) else option.get("attributes")
        entry = (container or {}).get(key)
        value = entry.get("value") if isinstance(entry, dict) else entry
    if value is None or value == "":
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _entry(option, key):
    if key == "jaspen_score":
        return option.get("jaspen_score")
    container = option.get("metrics") if key in (option.get("metrics") or {}) else option.get("attributes")
    return (container or {}).get(key)


def _constraint_value(option, key):
    field = key.removeprefix("cap_").removeprefix("max_")
    return _entry_value(option, field)


def _field_label(key):
    return {
        "capacity_draw": "bonding requirement",
        "contract_value": "contract value",
        "win_probability": "win probability",
        "margin_pct": "expected margin",
        "pursuit_cost": "pursuit cost",
        "pursuit_effort_fte_weeks": "pursuit effort",
        "expected_value": "expected value",
        "jaspen_score": "Jaspen score",
    }.get(key, key.replace("_", " "))


def _missing_input_keys(option, key):
    entry = _entry(option, key)
    if isinstance(entry, dict) and isinstance(entry.get("missing_inputs"), list):
        missing = [str(item).removeprefix("metric:") for item in entry["missing_inputs"] if str(item).strip()]
        if missing:
            return missing
    return [key]


def _not_evaluable(option, missing_keys):
    unique_keys = list(dict.fromkeys(missing_keys))
    labels = [_field_label(key) for key in unique_keys]
    reason = f"missing {labels[0]}" if len(labels) == 1 else f"missing {', '.join(labels[:-1])} and {labels[-1]}"
    return {
        "option_key": option.get("option_key") or option.get("id"),
        "name": option.get("project_name") or option.get("name"),
        "reason": reason,
        "not_evaluable": True,
        "missing_values": {key: None for key in unique_keys},
    }


def select_options(options, constraints, *, objective_metric, max_options=12):
    options = [dict(item) for item in (options or []) if isinstance(item, dict)][:max_options]
    constraints = [dict(item) for item in (constraints or []) if isinstance(item, dict)]
    numeric_constraints = []
    invalid_constraints = []
    for constraint in constraints:
        key = str(constraint.get("key") or "")
        if key != "max_selected" and not key.startswith(("cap_", "max_")):
            continue
        value = constraint.get("value")
        try:
            limit = float(value) if value is not None and value != "" else None
        except (TypeError, ValueError):
            limit = None
        if limit is None or not math.isfinite(limit):
            invalid_constraints.append(key or "constraint")
        else:
            numeric_constraints.append((key, limit))

    eligible, excluded = [], []
    not_evaluable_count = 0
    for option in options:
        failed = [gate for gate in option.get("gates") or [] if isinstance(gate, dict) and gate.get("status") == "fail"]
        manually_excluded = option.get("selection_excluded") is True
        if failed or manually_excluded:
            excluded.append({"option_key": option.get("option_key") or option.get("id"), "name": option.get("project_name") or option.get("name"), "reason": "failed mandatory gate" if failed else "excluded by user"})
        else:
            missing_keys = []
            if _entry_value(option, objective_metric) is None:
                missing_keys.extend(_missing_input_keys(option, objective_metric))
            for key, _limit in numeric_constraints:
                if key != "max_selected" and _constraint_value(option, key) is None:
                    missing_keys.extend(_missing_input_keys(option, key.removeprefix("cap_").removeprefix("max_")))
            if missing_keys:
                excluded.append(_not_evaluable(option, missing_keys))
                not_evaluable_count += 1
            else:
                eligible.append(option)

    cannot_evaluate = {
        "best": None,
        "runner_up": None,
        "excluded": excluded,
        "feasible_count": 0,
        "can_evaluate": False,
        "status": "cannot_evaluate",
        "reason": "cannot evaluate with current inputs",
    }
    if invalid_constraints:
        cannot_evaluate["missing_constraint_values"] = {key: None for key in invalid_constraints}
        return cannot_evaluate
    if not eligible and not_evaluable_count:
        return cannot_evaluate

    locked = [item for item in eligible if item.get("locked") or item.get("tier") == "Strategic Necessity" or item.get("selection_pinned")]
    unlocked = [item for item in eligible if item not in locked]

    def feasible(group):
        for key, limit in numeric_constraints:
            if key == "max_selected" and len(group) > int(limit):
                return False
            if key.startswith(("cap_", "max_")) and key != "max_selected":
                if sum(_constraint_value(item, key) for item in group) > limit:
                    return False
        return True

    candidates = []
    for size in range(len(unlocked) + 1):
        for subset in combinations(unlocked, size):
            group = [*locked, *subset]
            if not feasible(group):
                continue
            objective = sum(_entry_value(item, objective_metric) for item in group)
            score_values = [_entry_value(item, "jaspen_score") for item in group]
            score = sum(score_values) if all(value is not None for value in score_values) else None
            signature = tuple(sorted(str(item.get("option_key") or item.get("id") or item.get("project_name")) for item in group))
            candidates.append((objective, score, signature, group))
    candidates.sort(key=lambda row: (-row[0], -(row[1] if row[1] is not None else float("-inf")), row[2]))

    def describe(row):
        if row is None:
            return None
        objective, score, _signature, group = row
        slack = {}
        for key, limit in numeric_constraints:
            used = len(group) if key == "max_selected" else sum(_constraint_value(item, key) for item in group)
            slack[key] = {"limit": limit, "used": used, "slack": limit - used}
        return {
            "options": [{"option_key": item.get("option_key") or item.get("id"), "name": item.get("project_name") or item.get("name"), "objective_value": _entry_value(item, objective_metric)} for item in group],
            "objective_metric": objective_metric,
            "objective_value": objective,
            "score_tiebreak": score,
            "constraints": slack,
        }
    return {
        "best": describe(candidates[0] if candidates else None),
        "runner_up": describe(candidates[1] if len(candidates) > 1 else None),
        "excluded": excluded,
        "feasible_count": len(candidates),
        "can_evaluate": bool(candidates),
        "status": "evaluated" if candidates else "no_feasible_selection",
    }
