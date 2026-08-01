import {
  THINKING_POWER_PROJECT_ESTIMATES,
  THINKING_POWER_VARIABILITY_NOTE,
} from '../../shared/billing/thinkingPowerEstimates';

export const ADVANTAGE_PRICE = 999;
export const ADVANTAGE_CREDITS = '300,000';
export const ADVANTAGE_PROJECT_ESTIMATE = THINKING_POWER_PROJECT_ESTIMATES.advantage;
export const ADVANTAGE_VARIABILITY_NOTE = THINKING_POWER_VARIABILITY_NOTE;

export const ADVANTAGE_TECHNICAL_GUARANTEE =
  'If a technical issue prevents you from completing the advertised workflow and our team cannot resolve it, we’ll refund your purchase.';

export const ADVANTAGE_GUARANTEE_QUALIFIER =
  'This guarantee covers unresolved product failures. The quality and usefulness of the results depend on the information, evidence, assumptions, criteria, and decisions provided by the user.';

export const SHARED_WORKFLOW = [
  {
    title: 'Frame the decision',
    detail: 'Define the outcome, the options or initiatives in scope, and the decision the room needs to make.',
  },
  {
    title: 'Build and refine the rubric',
    detail: 'Use Jaspen to establish the right criteria and relative importance for this decision, not a generic template.',
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

export const SHARED_DECISION_RECORD = [
  'What was being decided',
  'What options were considered',
  'What mattered',
  'What evidence was available',
  'What assumptions were made',
  'What was selected',
  'Why it was selected',
  'What happened afterward',
  'What the company learned',
];

export const SHARED_OFFER_ITEMS = [
  {
    value: ADVANTAGE_CREDITS,
    label: 'non-expiring usage credits',
    detail: 'A personal balance that remains available until used.',
  },
  {
    value: `Approximately ${ADVANTAGE_PROJECT_ESTIMATE}`,
    label: 'over the life of the credit balance',
    detail: 'A planning estimate based on typical evaluations, not a guaranteed quantity.',
  },
  {
    value: '30 projects',
    label: 'per comparison session',
    detail: 'Compare up to 30 projects in one focused session. Continue evaluating and retaining additional projects across sessions.',
  },
  {
    value: `$${ADVANTAGE_PRICE} once`,
    label: 'with no subscription required',
    detail: 'No monthly renewal, automatic replenishment, or recurring charge.',
  },
];

export const SHARED_OFFER_DISCLOSURES = [
  'The Jaspen Advantage is for individual use and does not require an Essential subscription.',
  'The 300,000 usage credits do not expire, remain available until used, and do not renew or replenish each month.',
  'The purchase and credits are personal to the buyer. They cannot be transferred, assigned, pooled, or shared with another user or workspace.',
  'If you later join a Team, Business, or Enterprise workspace, this promotional balance remains personal to your account.',
  'When the credits are used, you can continue through Jaspen’s normal paid plans and credit options.',
  'You complete the work independently with Jaspen and its AI. No consulting service, facilitated workshop, or done-for-you analysis is included.',
];

export const SHARED_FAQ = [
  {
    q: 'What is The Jaspen Advantage?',
    a: 'It is a limited launch offer for an individual Jaspen account with 300,000 non-expiring usage credits for $999 once. It is not a subscription or a separate product.',
  },
  {
    q: 'What are usage credits?',
    a: 'Usage credits meter the AI-powered analysis Jaspen performs. Deeper analysis, larger inputs, attachments, and revisions generally use more credits.',
  },
  {
    q: 'How was the 750–1,200 estimate calculated?',
    a: 'It is based on reasonable estimates for a typical evaluation that includes framing the project, refining a rubric, reviewing evidence, generating a scorecard, reviewing the recommendation, and creating an initial execution plan. Actual usage varies.',
  },
  { q: 'Do the 300,000 credits expire?', a: 'No. They remain available to the purchaser until used, subject to the current Jaspen terms and account status.' },
  { q: 'Is a subscription required?', a: 'No. The Jaspen Advantage is a one-time purchase and does not enroll you in Essential or another recurring plan.' },
  { q: 'Do the credits renew every month?', a: 'No. The balance does not renew or replenish, and there is no automatic renewal.' },
  { q: 'Can the credits be shared with a team?', a: 'No. The purchase and promotional credits are personal to the buyer and cannot be transferred, pooled, or shared.' },
  { q: 'What happens if I later upgrade to Team, Business, or Enterprise?', a: 'Your promotional balance remains personal to your account. Team or organization allowances remain governed by that plan.' },
  { q: 'What happens when the credits are used?', a: 'You can continue through Jaspen’s normal paid plans and available credit options.' },
  { q: 'How many options can I compare at one time?', a: 'You can compare up to 30 projects or options in one focused session and retain more work across additional sessions.' },
  { q: 'Does Jaspen make the final decision?', a: 'No. Jaspen helps structure the comparison, surface tradeoffs, and explain the order. The decision remains yours.' },
  { q: 'What information should I provide for the strongest analysis?', a: 'Provide a clear objective, the options in scope, relevant constraints, evidence, assumptions, and the criteria that matter. Better context creates sharper guidance.' },
  { q: 'What outputs can I retain or download?', a: 'You can retain scorecards and decision work, review tradeoffs, create an initial execution plan, and use the downloadable decision assets currently supported in Jaspen.' },
];

const consultantCampaign = {
  id: 'advantage_consultants',
  key: 'consultants',
  path: '/thinking-power',
  theme: 'consultants',
  eyebrow: 'For independent consultants & fractional executives',
  heroTitle: 'Give clients more than a recommendation. Show them why.',
  heroBody:
    'Build the right rubric, compare the options against real evidence, and turn the result into clear decision assets and an initial execution plan.',
  heroCallout:
    'Walk into the client room ready to show what should move forward, what should wait, and why.',
  primaryCta: 'Strengthen your next recommendation',
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
    title: 'Evidence-Based Client Decision Tool for Consultants',
    description:
      'Help clients make decisions with more than a gut feeling using a tailored rubric, evidence-aware evaluation, clear rationale, and an initial execution plan.',
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
  id: 'advantage_pmo',
  key: 'portfolio',
  path: '/thinking-power/portfolio',
  theme: 'portfolio',
  eyebrow: 'For PMO, portfolio & transformation leaders',
  heroTitle: 'Rank the work before you resource it.',
  heroBody:
    'Compare up to 30 projects with consistent criteria, real evidence, and visible tradeoffs. Then turn the result into an initial execution plan.',
  heroCallout:
    'Show leadership what should move forward, what should wait, and why each project landed where it did.',
  primaryCta: 'Rank your project list',
  momentTitle: 'Every sponsor believes their project is important.',
  momentBody:
    'When more projects exist than the organization can execute, gut feeling and sponsor influence are not enough. You need a consistent view of what gets funded, deferred, combined, or stopped, plus a clear explanation leadership can follow.',
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
      a: 'No. Jaspen helps the team structure the evaluation, challenge evidence and assumptions, and document a clear recommendation grounded in evidence. Leaders still own the decision.',
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
  id: 'advantage_strategic_planning_aop',
  key: 'strategic-planning',
  path: '/thinking-power/strategic-planning',
  theme: 'strategy',
  eyebrow: 'For strategy and planning leaders',
  heroTitle: 'Turn the planning list into a clear order.',
  heroBody:
    'Use Jaspen for Strategic Planning and Annual Operating Planning (AOP) to compare initiatives against the criteria, evidence, assumptions, and tradeoffs that determine what actually makes the plan.',
  heroCallout:
    'Walk into the planning room ready to show what should move forward, what should wait, and why.',
  primaryCta: 'Rank your strategic priorities',
  momentTitle: 'The ambition is clear. The funded work is not.',
  momentBody:
    'Functions have submitted more initiatives than the business can fund or execute. Jaspen helps the planning team decide which work deserves capacity and executive attention before commitments are locked in.',
  outcomeTitle: 'Create a clear bridge from strategy to execution.',
  outcomeBody:
    'Expose unsupported assumptions, connect priorities to resource allocation, and document why initiatives were funded, deferred, combined, or declined. Jaspen does not claim to create the complete strategy, budget, financial plan, or annual operating plan.',
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
    title: 'Strategic Planning and Annual Operating Planning (AOP)',
    description:
      'Decide what deserves attention during Strategic Planning and Annual Operating Planning (AOP) by comparing initiatives, evidence, assumptions, and tradeoffs.',
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

// Backward-compatible export names while older imports are retired.
export const FOUNDER_PRICE = ADVANTAGE_PRICE;
export const FOUNDER_CREDITS = ADVANTAGE_CREDITS;
export const FOUNDER_PROJECT_ESTIMATE = ADVANTAGE_PROJECT_ESTIMATE;
export const FOUNDER_VARIABILITY_NOTE = ADVANTAGE_VARIABILITY_NOTE;
export const FOUNDER_TECHNICAL_GUARANTEE = ADVANTAGE_TECHNICAL_GUARANTEE;
export const FOUNDER_GUARANTEE_QUALIFIER = ADVANTAGE_GUARANTEE_QUALIFIER;
