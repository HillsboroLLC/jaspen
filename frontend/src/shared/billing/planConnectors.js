export const PLAN_CONNECTORS = {
  free: ['Salesforce', 'Snowflake', 'Jira', 'Smartsheet', 'Oracle Fusion', 'ServiceNow', 'NetSuite'],
  starter: ['Salesforce', 'Snowflake', 'Jira', 'Smartsheet', 'Oracle Fusion', 'ServiceNow', 'NetSuite'],
  essential: ['Salesforce', 'Snowflake', 'Jira', 'Smartsheet', 'Oracle Fusion', 'ServiceNow', 'NetSuite'],
  team: ['Salesforce', 'Snowflake', 'Jira', 'Smartsheet', 'Oracle Fusion', 'ServiceNow', 'NetSuite'],
  business: ['Salesforce', 'Snowflake', 'Jira', 'Smartsheet', 'Oracle Fusion', 'ServiceNow', 'NetSuite'],
  enterprise_custom: ['Salesforce', 'Snowflake', 'Jira', 'Smartsheet', 'Oracle Fusion', 'ServiceNow', 'NetSuite'],
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
  if (!connectors.length) return getPlanConnectors('free').join(', ');
  return connectors.join(', ');
}
