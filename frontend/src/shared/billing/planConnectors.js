export const PLAN_CONNECTORS = {
  free: [],
  essential: ['Jira'],
  team: ['Jira', 'Workfront', 'Smartsheet'],
  enterprise: ['Jira', 'Workfront', 'Smartsheet', 'Salesforce', 'Snowflake', 'Oracle Fusion', 'ServiceNow', 'NetSuite'],
};

function normalizePlanKey(planKey) {
  return String(planKey || '').trim().toLowerCase();
}

export function getPlanConnectors(planKey) {
  const key = normalizePlanKey(planKey);
  return PLAN_CONNECTORS[key] || [];
}

export function getPlanConnectorSentence(planKey) {
  const connectors = getPlanConnectors(planKey);
  if (!connectors.length) return 'No connectors included';
  return connectors.join(', ');
}
