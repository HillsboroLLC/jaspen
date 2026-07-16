// =====================================================
// Cost of Turnover — Question configuration + conditional logic
// Source of truth: workbook sheet "03 User Questions".
//
// This is DATA, not UI. Steps declare their fields; conditional visibility is
// expressed as pure predicate functions of the current input state. The step
// components read this config so questions can be added, reordered, or gated
// without touching rendering code.
// =====================================================

export const STEPS = [
  { id: 'role', index: 0, title: 'About the role', short: 'Role' },
  { id: 'assumptions', index: 1, title: 'Review the assumptions', short: 'Assumptions' },
  { id: 'knowledge', index: 2, title: 'Knowledge and context', short: 'Knowledge' },
  { id: 'results', index: 3, title: 'Your estimate', short: 'Results' },
];

// Step 1 — minimal role setup. Salary is optional (benchmark fills it).
export const ROLE_FIELDS = {
  departures: { required: true, min: 1, default: 1 },
  roleCategory: { required: true, default: 'corporate_knowledge' },
  roleLevel: { required: true, default: 'manager' },
  salary: { required: false, default: null },
  industry: { required: false, default: '' },
  country: { required: false, default: 'US' },
};

// Step 2 — the editable benchmark assumptions shown for review. `key` maps to an
// assumption key in the engine's getDefaultAssumptions().
export const REVIEW_ASSUMPTIONS = [
  { key: 'timeToFill', label: 'Time to fill', unit: 'calendar days', kind: 'number', step: 1 },
  {
    key: 'fullyLoadedMultiplier',
    label: 'Fully loaded compensation multiplier',
    unit: '× salary',
    kind: 'number',
    step: 0.001,
    help: 'Converts salary to fully loaded cost (wages are ~69.9% of total employer cost).',
  },
  { key: 'costPerHire', label: 'Recruiting cost per replacement', unit: 'USD', kind: 'currency' },
  {
    key: 'uncoveredWork',
    label: "Share of the vacant role's work not absorbed by others",
    unit: '%',
    kind: 'percent',
  },
  { key: 'rampMonths', label: 'Time to expected productivity', unit: 'months', kind: 'number', step: 1 },
  {
    key: 'rampProductivity',
    label: 'Average productivity during ramp-up',
    unit: '%',
    kind: 'percent',
  },
  { key: 'directTrainingCost', label: 'Direct onboarding and training cost', unit: 'USD', kind: 'currency' },
  { key: 'onboardingHours', label: 'Internal onboarding labor', unit: 'hours', kind: 'number', step: 1 },
];

// Step 3 — knowledge and context. Conditional fields keep the path short.
export const KNOWLEDGE_FIELDS = [
  {
    key: 'knowledgeTransferPlanned',
    label: 'Was there planned overlap or formal knowledge transfer?',
    kind: 'choice',
    options: [
      { id: 'yes', label: 'Yes' },
      { id: 'partial', label: 'Partial' },
      { id: 'no', label: 'No' },
    ],
    default: 'partial',
    required: true,
  },
  {
    key: 'knowledgeTransferHours',
    label: 'Total employee hours spent transferring this role’s knowledge',
    unit: 'hours',
    kind: 'assumption',
    // Only relevant when some transfer happened.
    visibleWhen: (state) => state.knowledgeTransferPlanned !== 'no',
  },
  {
    key: 'contextRediscoveryHours',
    label: 'Time for a replacement to rebuild the historical context this role needs',
    unit: 'hours',
    kind: 'assumption',
  },
  {
    key: 'instMemoryHours',
    label: 'Coworker or leader time needed to reconstruct missing context, records, or lessons',
    unit: 'hours',
    kind: 'assumption',
  },
  {
    key: 'affectedProjects',
    label: 'How many active projects or initiatives rely materially on this role?',
    unit: 'projects',
    kind: 'number',
    step: 1,
    min: 0,
    default: 0,
    required: false,
  },
  {
    key: 'projectDisruptionHours',
    label: 'Added team hours typically required per affected project',
    unit: 'hours',
    kind: 'assumption',
    // Only ask when at least one project is affected.
    visibleWhen: (state) => Number(state.affectedProjects) > 0,
  },
];

// Predicate helper used by the step components.
export function isFieldVisible(field, state) {
  if (typeof field.visibleWhen !== 'function') return true;
  return field.visibleWhen(state);
}
