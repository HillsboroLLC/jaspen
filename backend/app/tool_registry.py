from copy import deepcopy

from app.billing_config import normalize_plan_key


PLAN_ORDER = ["free", "essential", "team", "enterprise"]
PLAN_RANK = {key: idx for idx, key in enumerate(PLAN_ORDER)}


CONTEXT_BUDGET_BY_TIER = {
    "free": {
        "recent_turns": 16,
        "include_rolling_summary": True,
    },
    "essential": {
        "recent_turns": 24,
        "include_rolling_summary": True,
    },
    "team": {
        "recent_turns": 40,
        "include_rolling_summary": True,
        "include_active_scenario_and_wbs_snapshot": True,
    },
    "enterprise": {
        "recent_turns": 64,
        "include_rolling_summary": True,
        "include_active_scenario_and_wbs_snapshot": True,
        "include_connector_insight_snapshot": True,
    },
}


TOOL_REGISTRY = [
    {
        "id": "get_readiness_snapshot",
        "type": "internal",
        "access": "read",
        "purpose": "Return readiness percent, missing checklist items, and next best question.",
        "tiers": ["free", "essential", "team", "enterprise"],
        "limits": "Standard request rate limits.",
        "preconditions": ["active_thread"],
    },
    {
        "id": "get_data_contract",
        "type": "internal",
        "access": "read",
        "purpose": "Return required KPI/financial baseline fields for structured intake.",
        "tiers": ["free", "essential", "team", "enterprise"],
        "limits": "Standard request rate limits.",
        "preconditions": ["active_thread"],
    },
    {
        "id": "scenario_create",
        "type": "internal",
        "access": "write",
        "purpose": "Create scenario deltas from baseline scorecard.",
        "tiers": ["essential", "team", "enterprise"],
        "limits": {
            "essential": {"max_scenarios_per_thread": 10},
            "team": {"max_scenarios_per_thread": 50},
            "enterprise": {"max_scenarios_per_thread": None},
        },
        "preconditions": ["baseline_exists"],
    },
    {
        "id": "scenario_apply",
        "type": "internal",
        "access": "write",
        "purpose": "Compute deterministic scenario scorecard from baseline + deltas.",
        "tiers": ["essential", "team", "enterprise"],
        "preconditions": ["scenario_exists", "baseline_exists"],
    },
    {
        "id": "scenario_adopt",
        "type": "internal",
        "access": "write",
        "purpose": "Set adopted scenario pointer as current continuation context.",
        "tiers": ["essential", "team", "enterprise"],
        "behavior": "Non-destructive pointer switch. Baseline and scenarios are retained.",
        "preconditions": ["scenario_exists_in_thread"],
    },
    {
        "id": "scenario_delete",
        "type": "internal",
        "access": "write",
        "purpose": "Delete a scenario only when explicitly requested by user.",
        "tiers": ["essential", "team", "enterprise"],
        "guardrails": [
            "Requires explicit user intent.",
            "Deleting adopted scenario resets adopted pointer to baseline.",
        ],
    },
    {
        "id": "wbs_read",
        "type": "internal",
        "access": "read",
        "purpose": "Read WBS tasks, owners, milestones, and dependencies for execution tracking.",
        "tiers": ["essential", "team", "enterprise"],
        "preconditions": ["thread_exists"],
    },
    {
        "id": "wbs_write",
        "type": "internal",
        "access": "write",
        "purpose": "Create or update WBS tasks, owners, statuses, and dependencies.",
        "tiers": ["essential", "team", "enterprise"],
        "limits": {
            "essential": {
                "max_active_wbs_per_thread": 1,
                "max_tasks_per_wbs": 75,
                "max_dependencies_per_wbs": 150,
            },
            "team": {
                "max_active_wbs_per_thread": 3,
                "max_tasks_per_wbs": 300,
                "max_dependencies_per_wbs": 1000,
            },
            "enterprise": {
                "max_active_wbs_per_thread": None,
                "max_tasks_per_wbs": None,
                "max_dependencies_per_wbs": None,
            },
        },
        "preconditions": ["thread_exists"],
    },
    {
        "id": "jira_sync",
        "type": "connector",
        "access": "read_write",
        "purpose": "Sync epics/stories/status/owners/sprints with Jira.",
        "tiers": ["team", "enterprise"],
        "preconditions": ["connector_configured", "workspace_mapping_configured"],
    },
    {
        "id": "workfront_sync",
        "type": "connector",
        "access": "read_write",
        "purpose": "Sync portfolio/project milestones, owners, and statuses with Workfront.",
        "tiers": ["team", "enterprise"],
        "preconditions": ["connector_configured", "workspace_mapping_configured"],
    },
    {
        "id": "smartsheet_sync",
        "type": "connector",
        "access": "read_write",
        "purpose": "Sync sheet rows, task statuses, and timeline updates with Smartsheet.",
        "tiers": ["team", "enterprise"],
        "preconditions": ["connector_configured", "sheet_mapping_configured"],
    },
    {
        "id": "salesforce_insights",
        "type": "connector",
        "access": "read_write",
        "purpose": "Analyze customer and pipeline trends from Salesforce for strategic insights.",
        "tiers": ["enterprise"],
        "preconditions": ["connector_configured", "object_mapping_configured"],
    },
    {
        "id": "snowflake_insights",
        "type": "connector",
        "access": "read",
        "purpose": "Query governed KPI and financial trend views from Snowflake.",
        "tiers": ["enterprise"],
        "preconditions": ["connector_configured", "query_allowlist_configured"],
    },
    {
        "id": "oracle_fusion_insights",
        "type": "connector",
        "access": "read_write",
        "purpose": "Use Oracle Fusion operational and financial signals for execution insights.",
        "tiers": ["enterprise"],
        "preconditions": ["connector_configured"],
    },
    {
        "id": "servicenow_insights",
        "type": "connector",
        "access": "read_write",
        "purpose": "Track service and change trends impacting delivery confidence.",
        "tiers": ["enterprise"],
        "preconditions": ["connector_configured"],
    },
    {
        "id": "netsuite_insights",
        "type": "connector",
        "access": "read_write",
        "purpose": "Monitor NetSuite finance and operations trends for decision support.",
        "tiers": ["enterprise"],
        "preconditions": ["connector_configured"],
    },
]


def _plan_rank(plan_key):
    normalized = normalize_plan_key(plan_key)
    return PLAN_RANK.get(normalized, 0)


def _is_access_compatible(tool_access, requested_access):
    requested = str(requested_access or "read").strip().lower()
    granted = str(tool_access or "read").strip().lower()

    if requested == "read":
        return granted in ("read", "read_write", "write")
    if requested == "write":
        return granted in ("write", "read_write")
    return False


def get_context_budget(plan_key):
    normalized = normalize_plan_key(plan_key)
    return deepcopy(CONTEXT_BUDGET_BY_TIER.get(normalized) or CONTEXT_BUDGET_BY_TIER["free"])


def get_tool_catalog():
    return deepcopy(TOOL_REGISTRY)


def get_tool_definition(tool_id):
    needle = str(tool_id or "").strip().lower()
    for tool in TOOL_REGISTRY:
        if str(tool.get("id") or "").strip().lower() == needle:
            return deepcopy(tool)
    return None


def get_tool_min_tier(tool_id):
    tool = get_tool_definition(tool_id)
    if not tool:
        return None
    tiers = tool.get("tiers") or []
    if not tiers:
        return None
    ranked = sorted(tiers, key=lambda t: _plan_rank(t))
    return ranked[0] if ranked else None


def is_tool_allowed(plan_key, tool_id, access="read"):
    tool = get_tool_definition(tool_id)
    if not tool:
        return False

    normalized_plan = normalize_plan_key(plan_key)
    allowed_tiers = tool.get("tiers") or []
    if normalized_plan not in allowed_tiers:
        return False

    return _is_access_compatible(tool.get("access"), access)


def get_tool_entitlements(plan_key):
    normalized_plan = normalize_plan_key(plan_key)
    items = []
    for tool in TOOL_REGISTRY:
        tool_id = tool.get("id")
        entry = deepcopy(tool)
        entry["enabled"] = normalized_plan in (tool.get("tiers") or [])
        entry["allowed_read"] = is_tool_allowed(normalized_plan, tool_id, "read")
        entry["allowed_write"] = is_tool_allowed(normalized_plan, tool_id, "write")
        entry["required_min_tier"] = get_tool_min_tier(tool_id)
        items.append(entry)
    return items


def get_wbs_limits_for_plan(plan_key):
    tool = get_tool_definition("wbs_write") or {}
    limits = tool.get("limits") or {}
    normalized_plan = normalize_plan_key(plan_key)
    return deepcopy(limits.get(normalized_plan) or {})


def get_scenario_limits_for_plan(plan_key):
    tool = get_tool_definition("scenario_create") or {}
    limits = tool.get("limits") or {}
    normalized_plan = normalize_plan_key(plan_key)
    return deepcopy(limits.get(normalized_plan) or {})
