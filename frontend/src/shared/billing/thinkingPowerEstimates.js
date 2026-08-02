export const THINKING_POWER_VARIABILITY_NOTE =
  'Actual usage varies based on model selection, input completeness, attachments, analysis depth, revisions, and follow-up.';

export const THINKING_POWER_PROJECT_ESTIMATES = Object.freeze({
  free: '~1 focused evaluation with complete inputs',
  starter: '~3–4 typical project evaluations',
  essential: '~17–29 typical project evaluations',
  team: '~57–96 typical project evaluations across the shared allowance',
  business: '~133–222 typical project evaluations across the shared allowance',
  founder: '~750–1,200 typical project evaluations over the life of the gift',
  limited_time_300k: '~750–1,200 typical project evaluations over the life of the credit balance',
});

export const FOUNDER_THINKING_POWER_SUMMARY =
  '300,000 persistent credits, available until used · ~750–1,200 typical project evaluations over the life of the gift';

export const LIMITED_TIME_300K_THINKING_POWER_SUMMARY =
  '300,000 non-expiring credits, available until used · ~750–1,200 typical project evaluations over the life of the credit balance';

export function projectEstimateForPlan(planKey, plan = null) {
  return plan?.project_evaluation_estimate || THINKING_POWER_PROJECT_ESTIMATES[planKey] || '';
}
