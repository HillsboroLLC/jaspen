import {
  THINKING_POWER_PROJECT_ESTIMATES,
  THINKING_POWER_VARIABILITY_NOTE,
} from '../../shared/billing/thinkingPowerEstimates';

export const FOUNDER_PRICE = 599;
export const FOUNDER_CREDITS = '300,000';
export const FOUNDER_PROJECT_ESTIMATE = THINKING_POWER_PROJECT_ESTIMATES.founder;
export const FOUNDER_VARIABILITY_NOTE = THINKING_POWER_VARIABILITY_NOTE;

export const FOUNDER_TECHNICAL_GUARANTEE =
  'If a technical issue prevents you from completing the advertised workflow and our team cannot resolve it, we’ll refund your purchase.';

export const FOUNDER_GUARANTEE_QUALIFIER =
  'This guarantee covers unresolved product failures. The quality and usefulness of the results depend on the information, evidence, assumptions, criteria, and decisions provided by the user.';

export const SHARED_WORKFLOW = [
  {
    title: 'Frame the decision',
    detail: 'Define the outcome, the options or initiatives in scope, and the decision the room needs to make.',
  },
  {
    title: 'Build and refine the rubric',
    detail: 'Use Jaspen to establish the right criteria and relative importance for this decision—not a generic template.',
  },
  {
    title: 'Evaluate the evidence',
    detail: 'Score the work while examining evidence quality, assumptions, uncertainty, dependencies, and tradeoffs.',
  },
  {
    title: 'Recommend and plan',
    detail: 'Document what should move forward, wait, combine, or stop, then create an initial execution plan and download the decision assets.',
  },
];

export const SHARED_OFFER_ITEMS = [
  {
    value: FOUNDER_CREDITS,
    label: 'Thinking Power credits',
    detail: 'A persistent Founder gift that remains available until used.',
  },
  {
    value: `Approximately ${FOUNDER_PROJECT_ESTIMATE}`,
    label: 'over the life of the gift',
    detail: 'An estimate of typical project evaluations, not a guaranteed quantity.',
  },
  {
    value: '30 projects',
    label: 'per comparison session',
    detail: 'Compare up to 30 projects in one focused session. Continue evaluating and retaining additional projects across sessions.',
  },
  {
    value: `$${FOUNDER_PRICE}`,
    label: 'one-time Founder price',
    detail: 'Your first month of Essential is included.',
  },
];

export const SHARED_OFFER_DISCLOSURES = [
  'The Founder purchase enrolls you in Essential. You choose and accept the recurring billing option at checkout, and Essential billing begins after the included month.',
  'The 300,000 Founder Thinking Power credits remain available until used.',
  'Canceling or changing the subscription does not delete scorecards or decision work you already created.',
  'You complete the work independently with Jaspen and its AI. No consulting service, facilitated workshop, done-for-you analysis, or Founder involvement is part of the purchase.',
];

const consultantCampaign = {
  id: 'founder_consultants',
  key: 'consultants',
  path: '/thinking-power',
  theme: 'consultants',
  eyebrow: 'For independent consultants & fractional executives',
  heroTitle: 'Turn client inputs into a recommendation you can defend.',
  heroBody:
    'Use Jaspen to build the rubric, evaluate competing options, test the evidence, and create downloadable decision assets with an initial execution plan.',
  heroCallout:
    'Walk into the client room ready to show what should move forward, what should wait, and why.',
  primaryCta: 'Build the client recommendation',
  momentTitle: 'The client meeting is set. The recommendation still has to hold up.',
  momentBody:
    'You have client inputs, competing options, and a deadline. Jaspen helps you turn that material into a clear recommendation whose logic, evidence, assumptions, and tradeoffs can withstand the questions in the room.',
  outcomeTitle: 'Strengthen the deliverable without building analysis infrastructure.',
  outcomeBody:
    'Structure and challenge the work with Jaspen while you retain professional judgment. Preserve the decision intelligence for follow-up work and leave with client-ready rationale, reconsideration triggers, and a practical starting plan.',
  useCases: [
    'Prioritizing transformation initiatives',
    'Recommending an operating-model option',
    'Comparing market-entry choices',
    'Selecting a vendor or technology',
    'Prioritizing improvement opportunities',
    'Evaluating cost-reduction or growth initiatives',
  ],
  leaveWith: [
    'A decision-specific rubric and documented evaluation',
    'Clear evidence gaps, assumptions, uncertainty, and tradeoffs',
    'A recommendation with rationale and reconsideration triggers',
    'An initial execution plan and downloadable decision assets',
    'Retained scorecards and decision work for follow-up',
  ],
  faq: [
    {
      q: 'Does Jaspen make the recommendation for me?',
      a: 'Jaspen structures, challenges, documents, and accelerates the analysis. You keep ownership of the professional judgment and the recommendation you present.',
    },
    {
      q: 'Can I reuse the work after the client meeting?',
      a: 'Yes. Scorecards and decision work are retained for future access, so you can revisit assumptions, update evidence, or continue the engagement without rebuilding the analysis.',
    },
    {
      q: 'What can I download?',
      a: 'You can download the resulting decision assets, including the recommendation and the initial execution plan produced through the workflow.',
    },
  ],
  seo: {
    title: 'Client Recommendation Tool for Consultants',
    description:
      'Build a defensible client recommendation with a tailored rubric, evidence-aware evaluation, clear rationale, and an initial execution plan.',
    keywords: [
      'consultant decision tool',
      'client recommendation tool',
      'consulting prioritization',
      'fractional executive decision support',
      'client-ready recommendation',
    ],
  },
};

const portfolioCampaign = {
  id: 'founder_pmo',
  key: 'portfolio',
  path: '/thinking-power/portfolio',
  theme: 'portfolio',
  eyebrow: 'For PMO, portfolio & transformation leaders',
  heroTitle: 'Portfolio review coming up? Walk into the room ready.',
  heroBody:
    'Build the rubric, evaluate up to 30 projects in one focused session, and create a defensible recommendation with an initial execution plan.',
  heroCallout:
    'Show leadership what should move forward, what should wait, and why each project landed where it did.',
  primaryCta: 'Evaluate your projects',
  momentTitle: 'Every sponsor believes their project is important.',
  momentBody:
    'When more projects exist than the organization can execute, you need a consistent, evidence-aware recommendation for what gets funded, deferred, combined, or stopped—and a transparent explanation that survives governance review.',
  outcomeTitle: 'Move from reporting the portfolio to improving it.',
  outcomeBody:
    'Jaspen helps you identify weak evidence before leadership does, separate strategic value from sponsor influence, document the rationale, and retain the intelligence behind every prioritization decision.',
  criteriaTitle: 'Establish the criteria your organization actually needs.',
  criteriaIntro:
    'Your rubric can consider these factors without forcing every project into an identical detailed model:',
  criteria: [
    'Strategic alignment',
    'Financial value',
    'Customer or operational impact',
    'Urgency and risk',
    'Feasibility and resource requirements',
    'Dependencies',
    'Evidence quality',
    'Confidence in underlying assumptions',
  ],
  useCases: [
    'Technology project prioritization',
    'Transformation roadmaps',
    'Stage Gate decisions',
    'Capital or resource allocation',
    'Cost-reduction initiatives',
    'Operational improvement portfolios',
    'Project intake and governance',
    'Competing cross-functional initiatives',
  ],
  leaveWith: [
    'A transparent, organization-specific prioritization rubric',
    'Evidence-aware evaluations and confidence signals',
    'A portfolio recommendation with documented rationale',
    'An initial execution plan and downloadable decision assets',
    'Retained scorecards for governance follow-up',
  ],
  faq: [
    {
      q: 'Is 30 the maximum size of our portfolio?',
      a: 'No. You can compare up to 30 projects in one focused session, then evaluate and retain additional projects across other sessions.',
    },
    {
      q: 'Do all projects need the same detailed rubric?',
      a: 'No. Jaspen supports contextually appropriate evaluations and an overall comparison. It helps you establish criteria suited to the decision and your organization.',
    },
    {
      q: 'Does Jaspen replace the governance decision?',
      a: 'No. Jaspen helps the team structure the evaluation, challenge evidence and assumptions, and document a defensible recommendation. Leaders still own the decision.',
    },
  ],
  seo: {
    title: 'Project Portfolio Prioritization for PMO Leaders',
    description:
      'Evaluate competing initiatives with transparent criteria, evidence-aware project scoring, clear rationale, and an initial execution plan for portfolio review.',
    keywords: [
      'project portfolio prioritization',
      'PMO prioritization',
      'initiative prioritization',
      'portfolio governance',
      'Stage Gate prioritization',
    ],
  },
};

const strategyCampaign = {
  id: 'founder_strat_aop',
  key: 'strategic-planning',
  path: '/thinking-power/strategic-planning',
  theme: 'strategy',
  eyebrow: 'For STRAT & AOP planning leaders',
  heroTitle: 'STRAT submissions are in. Now decide what actually makes the plan.',
  heroBody:
    'Use Jaspen to evaluate strategic initiatives, test the evidence, clarify the tradeoffs, and create a defensible recommendation with an initial execution plan.',
  heroCallout:
    'Walk into the planning room ready to show what should move forward, what should wait, and why.',
  primaryCta: 'Prioritize the strategic initiatives',
  momentTitle: 'The ambition is clear. The funded work is not.',
  momentBody:
    'Functions have submitted more initiatives than the business can fund or execute. Jaspen helps the planning team decide which work deserves capacity and executive attention before commitments are locked in.',
  outcomeTitle: 'Create a defensible bridge from strategy to execution.',
  outcomeBody:
    'Expose unsupported assumptions, connect priorities to resource allocation, and document why initiatives were funded, deferred, combined, or declined—without claiming to create the complete strategy, budget, financial plan, or annual operating plan.',
  workflow: [
    'Define the decision and desired outcome.',
    'Establish the criteria and relative importance.',
    'Evaluate the initiatives and supporting evidence.',
    'Surface assumptions, uncertainty, and tradeoffs.',
    'Identify what should move forward, wait, combine, or stop.',
    'Create the recommendation and initial execution plan.',
    'Download and retain the resulting assets.',
  ],
  useCases: [
    'Strategic initiatives',
    'Growth opportunities',
    'Cost and productivity programs',
    'Technology or capital investments',
    'Transformation programs',
    'New markets or products',
    'Risk and compliance priorities',
    'Cross-functional resource requests',
    'Initiatives proposed for the annual operating plan',
  ],
  leaveWith: [
    'A rubric aligned to the planning decision',
    'Evaluated initiatives with evidence and assumption gaps exposed',
    'A recommendation for what moves, waits, combines, or stops',
    'An initial execution plan and downloadable decision assets',
    'Retained decision intelligence for the next planning cycle',
  ],
  faq: [
    {
      q: 'Does Jaspen create the complete annual operating plan?',
      a: 'No. Jaspen supports initiative evaluation and prioritization within planning. Your team still owns the strategy, financial plan, budget, and complete operating plan.',
    },
    {
      q: 'Can we challenge assumptions before funding decisions?',
      a: 'Yes. The workflow explicitly surfaces evidence quality, assumptions, uncertainty, tradeoffs, and confidence before the recommendation is finalized.',
    },
    {
      q: 'What happens after initiatives are selected?',
      a: 'Jaspen helps create an initial execution plan and retains the scorecards and decision work so planning rationale remains available after the meeting.',
    },
  ],
  seo: {
    title: 'Strategic Initiative Prioritization for AOP Planning',
    description:
      'Evaluate strategic initiatives, expose assumptions, clarify tradeoffs, and build a defensible funded-priority recommendation with an initial execution plan.',
    keywords: [
      'strategic initiative prioritization',
      'AOP initiative planning',
      'annual operating plan prioritization',
      'strategic planning tool',
      'strategy resource allocation',
    ],
  },
};

export const FOUNDER_CAMPAIGNS = Object.freeze({
  consultants: consultantCampaign,
  portfolio: portfolioCampaign,
  'strategic-planning': strategyCampaign,
});

export function getFounderCampaign(key) {
  return FOUNDER_CAMPAIGNS[key] || consultantCampaign;
}
