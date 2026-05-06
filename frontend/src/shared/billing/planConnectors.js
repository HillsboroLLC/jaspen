export const PLAN_CONNECTORS = {
  free: [],
  essential: ['Salesforce', 'Snowflake'],
  team: ['Salesforce', 'Snowflake', 'Jira', 'Smartsheet'],
  enterprise: ['Salesforce', 'Snowflake', 'Jira', 'Smartsheet', 'Oracle Fusion', 'ServiceNow', 'NetSuite'],
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
