// =====================================================
// Cost of Turnover — Analytics / funnel tracking
// A single, testable event surface for the utility. It is transport-agnostic:
// every event is pushed to window.dataLayer (the standard GTM/GA4 queue) and
// re-dispatched as a DOM CustomEvent so any existing or future analytics
// listener can pick it up without this module knowing the vendor. In
// development it also logs to the console.
//
// Lead attribution is unified under a single source identifier so one contact
// can carry this activity alongside any Decision Profile / Toolkit activity.
// =====================================================

export const UTILITY_SOURCE = 'cost_of_turnover_utility';

// Canonical event names (workbook sheet 07 + the build brief).
export const EVENTS = {
  UTILITY_VIEWED: 'utility_view',
  CALCULATOR_STARTED: 'calculator_started',
  STEP_COMPLETED: 'step_completed',
  BENCHMARK_OVERRIDDEN: 'benchmark_overridden',
  BENCHMARK_RESTORED: 'benchmark_restored',
  CALCULATOR_COMPLETED: 'calculator_completed',
  RESULTS_VIEWED: 'results_viewed',
  METHODOLOGY_VIEWED: 'methodology_viewed',
  COMPOSITION_VIEWED: 'composition_viewed',
  SAVE_CTA_CLICKED: 'save_estimate_cta_clicked',
  SIGNUP_COMPLETED: 'signup_completed_from_utility',
  ESTIMATE_SAVED: 'estimate_saved',
  BENCHMARK_CONTRIBUTION_CONSENT: 'benchmark_contribution_consent',
  JASPEN_CTA_CLICKED: 'jaspen_product_cta_clicked',
  STEP_ABANDONED: 'step_abandoned',
  ERROR: 'utility_error',
};

function safeWindow() {
  return typeof window !== 'undefined' ? window : null;
}

/**
 * Emit a funnel event. `payload` is merged with the source + timestamp.
 */
export function track(event, payload = {}) {
  const w = safeWindow();
  const detail = {
    event,
    source: UTILITY_SOURCE,
    ts: Date.now(),
    ...payload,
  };
  if (!w) return detail;
  try {
    w.dataLayer = w.dataLayer || [];
    w.dataLayer.push(detail);
    w.dispatchEvent(new CustomEvent('jaspen:analytics', { detail }));
  } catch {
    /* analytics must never break the utility */
  }
  if (process.env.NODE_ENV !== 'production') {
    // eslint-disable-next-line no-console
    console.debug('[cost_of_turnover]', event, detail);
  }
  return detail;
}

export const analytics = {
  utilityViewed: () => track(EVENTS.UTILITY_VIEWED),
  calculatorStarted: () => track(EVENTS.CALCULATOR_STARTED),
  stepCompleted: (stepId, index) => track(EVENTS.STEP_COMPLETED, { stepId, index }),
  benchmarkOverridden: (key, benchmarkId) =>
    track(EVENTS.BENCHMARK_OVERRIDDEN, { key, benchmarkId }),
  benchmarkRestored: (key) => track(EVENTS.BENCHMARK_RESTORED, { key }),
  calculatorCompleted: (summary) => track(EVENTS.CALCULATOR_COMPLETED, summary),
  resultsViewed: (summary) => track(EVENTS.RESULTS_VIEWED, summary),
  methodologyViewed: () => track(EVENTS.METHODOLOGY_VIEWED),
  compositionViewed: () => track(EVENTS.COMPOSITION_VIEWED),
  saveCtaClicked: () => track(EVENTS.SAVE_CTA_CLICKED),
  signupCompleted: () => track(EVENTS.SIGNUP_COMPLETED),
  estimateSaved: (mode) => track(EVENTS.ESTIMATE_SAVED, { mode }),
  benchmarkContributionConsent: (accepted) =>
    track(EVENTS.BENCHMARK_CONTRIBUTION_CONSENT, { accepted: Boolean(accepted) }),
  jaspenCtaClicked: (target) => track(EVENTS.JASPEN_CTA_CLICKED, { target }),
  stepAbandoned: (stepId, index) => track(EVENTS.STEP_ABANDONED, { stepId, index }),
  error: (context, message) => track(EVENTS.ERROR, { context, message: String(message || '') }),
};
