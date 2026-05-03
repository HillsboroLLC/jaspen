from copy import deepcopy


CONNECTOR_ORDER = [
    "jira_sync",
    "workfront_sync",
    "smartsheet_sync",
    "salesforce_insights",
    "snowflake_insights",
    "oracle_fusion_insights",
    "servicenow_insights",
    "netsuite_insights",
]


CONNECTOR_REGISTRY = {
    "jira_sync": {
        "id": "jira_sync",
        "label": "Jira",
        "group": "execution",
        "description": "Sync epics, stories, assignees, and sprint status with Jaspen WBS plans.",
        "supports_pm_sync": True,
        "implementation_status": "implemented",
    },
    "workfront_sync": {
        "id": "workfront_sync",
        "label": "Workfront",
        "group": "execution",
        "description": "Sync milestones, owners, and schedule changes between Workfront and Jaspen.",
        "supports_pm_sync": True,
        "implementation_status": "implemented",
    },
    "smartsheet_sync": {
        "id": "smartsheet_sync",
        "label": "Smartsheet",
        "group": "execution",
        "description": "Sync task rows, dates, and delivery statuses with Jaspen execution plans.",
        "supports_pm_sync": True,
        "implementation_status": "implemented",
    },
    "salesforce_insights": {
        "id": "salesforce_insights",
        "label": "Salesforce",
        "group": "data",
        "description": "Analyze customer and pipeline patterns for delivery and prioritization insights.",
        "supports_pm_sync": False,
        "implementation_status": "implemented",
    },
    "snowflake_insights": {
        "id": "snowflake_insights",
        "label": "Snowflake",
        "group": "data",
        "description": "Read governed KPI and financial trend tables to enrich Jaspen recommendations.",
        "supports_pm_sync": False,
        "implementation_status": "implemented",
    },
    "oracle_fusion_insights": {
        "id": "oracle_fusion_insights",
        "label": "Oracle Fusion",
        "group": "data",
        "description": "Coming soon: Oracle Fusion ERP operational and finance insights.",
        "supports_pm_sync": False,
        "implementation_status": "coming_soon",
    },
    "servicenow_insights": {
        "id": "servicenow_insights",
        "label": "ServiceNow",
        "group": "data",
        "description": "Coming soon: ServiceNow service and change metrics for execution risk insights.",
        "supports_pm_sync": False,
        "implementation_status": "coming_soon",
    },
    "netsuite_insights": {
        "id": "netsuite_insights",
        "label": "NetSuite",
        "group": "data",
        "description": "Coming soon: NetSuite operating and finance trend insights.",
        "supports_pm_sync": False,
        "implementation_status": "coming_soon",
    },
}


def get_connector_ids():
    return list(CONNECTOR_ORDER)


def get_execution_connector_ids():
    return [
        connector_id
        for connector_id in CONNECTOR_ORDER
        if (CONNECTOR_REGISTRY.get(connector_id) or {}).get("supports_pm_sync")
    ]


def get_connector_definition(connector_id):
    key = str(connector_id or "").strip().lower()
    connector = CONNECTOR_REGISTRY.get(key)
    return deepcopy(connector) if connector else None


def connector_is_implemented(connector_id):
    connector = get_connector_definition(connector_id)
    if not connector:
        return False
    status = str(connector.get("implementation_status") or "implemented").strip().lower()
    return status == "implemented"


def get_connector_catalog():
    return [
        deepcopy(CONNECTOR_REGISTRY[connector_id])
        for connector_id in CONNECTOR_ORDER
        if connector_id in CONNECTOR_REGISTRY
    ]
