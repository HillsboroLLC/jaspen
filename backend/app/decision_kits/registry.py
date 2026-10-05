"""Decision Kit registry and schema boundary.

Kit modules are declarative. Protected methodology cannot be configured here.
"""

from copy import deepcopy

from .rfp_bid import KIT as RFP_BID
from .rfp_vendor_selection import KIT as RFP_VENDOR_SELECTION

GENERAL_KIT_KEY = None
_KITS = {RFP_BID["key"]: RFP_BID, RFP_VENDOR_SELECTION["key"]: RFP_VENDOR_SELECTION}
_PROTECTED_KEYS = {
    "confidence_caps", "rollup", "rollup_weights", "category_bands",
    "derivation_rules", "task_templates", "tasks", "phase_template",
}
_REQUIRED = {"key", "version", "label", "fields", "metrics", "verdict_vocabulary", "verdict_thresholds", "plan_bindings"}


def normalize_decision_kit(value):
    raw = str(value or "").strip().lower()
    if raw in {"", "general", "none", "null"}:
        return None
    if raw not in _KITS:
        raise ValueError("decision_kit must be general, rfp_bid, or rfp_vendor_selection")
    return raw


def validate_decision_kit(config, previous=None):
    if not isinstance(config, dict):
        raise ValueError("Decision Kit config must be an object")
    missing = sorted(_REQUIRED - set(config))
    if missing:
        raise ValueError(f"Decision Kit config missing: {', '.join(missing)}")
    forbidden = sorted(_PROTECTED_KEYS & set(config))
    if forbidden:
        raise ValueError(f"Decision Kit cannot configure protected methodology: {', '.join(forbidden)}")
    if not isinstance(config.get("version"), int) or config["version"] < 1:
        raise ValueError("Decision Kit version must be a positive integer")
    thresholds = config.get("verdict_thresholds")
    if not isinstance(thresholds, dict) or int(thresholds.get("version") or 0) != config["version"]:
        raise ValueError("verdict_thresholds.version must match the Decision Kit version")
    for key in ("advance_min_score", "decline_below_score", "min_confidence_pct", "close_call_margin"):
        if not isinstance(thresholds.get(key), (int, float)):
            raise ValueError(f"Missing numeric verdict threshold: {key}")
    if previous and config.get("verdict_thresholds") != previous.get("verdict_thresholds"):
        if int(config["version"]) <= int(previous.get("version") or 0):
            raise ValueError("Changing verdict thresholds requires a Decision Kit version bump")
    if not isinstance(config.get("fields"), list) or not isinstance(config.get("metrics"), list):
        raise ValueError("Decision Kit fields and metrics must be lists")
    return True


for _config in _KITS.values():
    validate_decision_kit(_config)


def get_decision_kit(key, version=None):
    normalized = normalize_decision_kit(key)
    if normalized is None:
        return None
    config = _KITS[normalized]
    if version is not None and int(version) != int(config["version"]):
        raise KeyError(f"Decision Kit {normalized} v{version} is unavailable")
    return deepcopy(config)


def list_decision_kits():
    return [
        {"key": None, "version": None, "label": "General", "description": "General decision analysis."},
        *[{"key": k, "version": v["version"], "label": v["label"], "description": v.get("description")} for k, v in _KITS.items()],
    ]
