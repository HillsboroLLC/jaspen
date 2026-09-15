import {
  FOUNDER_THINKING_POWER_SUMMARY,
  THINKING_POWER_PROJECT_ESTIMATES,
  THINKING_POWER_VARIABILITY_NOTE,
  projectEstimateForPlan,
} from './thinkingPowerEstimates';

describe('Thinking Power project estimates', () => {
  it('keeps usage-screen and upgrade copy consistent with each plan', () => {
    expect(projectEstimateForPlan('free')).toBe('~1–2 evaluations');
    expect(projectEstimateForPlan('starter')).toBe('~5–8 evaluations');
    expect(projectEstimateForPlan('essential')).toBe('~40–55 evaluations');
    expect(projectEstimateForPlan('team')).toBe('~165–230 evaluations');
    expect(projectEstimateForPlan('business')).toBe('~455–640 evaluations');
    expect(projectEstimateForPlan('essential', { project_evaluation_estimate: '~measured range' })).toBe('~measured range');
  });

  it('describes the Founder gift as persistent and approximate', () => {
    expect(FOUNDER_THINKING_POWER_SUMMARY).toContain('300,000 persistent credits, available until used');
    expect(FOUNDER_THINKING_POWER_SUMMARY).toContain(THINKING_POWER_PROJECT_ESTIMATES.founder);
    expect(THINKING_POWER_VARIABILITY_NOTE).toContain('evaluation complexity');
    expect(THINKING_POWER_VARIABILITY_NOTE).toContain('attachments');
  });

  it('does not describe customer credits as tokens', () => {
    const customerCopy = [
      ...Object.values(THINKING_POWER_PROJECT_ESTIMATES),
      FOUNDER_THINKING_POWER_SUMMARY,
      THINKING_POWER_VARIABILITY_NOTE,
    ].join(' ');
    expect(customerCopy.toLowerCase()).not.toContain('token');
  });
});
