// Mortgage questionnaire configuration (data, not UI). Source: workbook sheet
// 03 User Questions. Conditional visibility is expressed as pure predicates.

export const STEPS = [
  { id: 'property', index: 0, title: 'Property & loan', short: 'Property' },
  { id: 'assumptions', index: 1, title: 'Review assumptions', short: 'Assumptions' },
  { id: 'cash', index: 2, title: 'Cash to close', short: 'Cash' },
  { id: 'results', index: 3, title: 'Your true cost', short: 'Results' },
];

export const LOAN_TERMS = [
  { id: 15, label: '15 years' },
  { id: 20, label: '20 years' },
  { id: 30, label: '30 years' },
];

// Step 2 — editable benchmark assumptions (the main-path ones).
export const REVIEW_ASSUMPTIONS = [
  { key: 'propertyTaxRate', label: 'Property tax rate', kind: 'rate', unit: '% of value/yr', decimals: 2 },
  { key: 'insuranceRate', label: 'Homeowners insurance', kind: 'rate', unit: '% of value/yr', decimals: 2 },
  { key: 'maintenanceRate', label: 'Maintenance reserve', kind: 'rate', unit: '% of value/yr', decimals: 2, help: 'A planning reserve for repairs and upkeep. Not a required bill.' },
];

// Step 2 — PMI assumptions live under Advanced options; only relevant < 20% down.
export const PMI_ASSUMPTIONS = [
  { key: 'pmiRate', label: 'PMI rate', kind: 'rate', unit: '% of loan/yr', decimals: 2 },
  { key: 'pmiRemovalLtv', label: 'PMI removal point', kind: 'rate', unit: '% LTV', decimals: 0, step: 1, help: 'PMI is modeled to stop when the balance reaches this share of the original price. Actual removal depends on loan type and lender.' },
];

// Step 4 — future-cost growth scenarios (all research-based, editable).
export const GROWTH_ASSUMPTIONS = [
  { key: 'taxGrowth', label: 'Annual property-tax growth', kind: 'rate', unit: '%/yr', decimals: 1, step: 0.1 },
  { key: 'insuranceGrowth', label: 'Annual insurance growth', kind: 'rate', unit: '%/yr', decimals: 1, step: 0.1 },
  { key: 'hoaGrowth', label: 'Annual HOA growth', kind: 'rate', unit: '%/yr', decimals: 1, step: 0.1 },
  { key: 'maintenanceGrowth', label: 'Annual maintenance growth', kind: 'rate', unit: '%/yr', decimals: 1, step: 0.1 },
];

// Human-facing labels for the "Why your estimate changed" explanations.
export const ASSUMPTION_LABELS = {
  interestRate: 'Interest rate',
  propertyTaxRate: 'Property tax rate',
  insuranceRate: 'Homeowners insurance',
  pmiRate: 'PMI rate',
  maintenanceRate: 'Maintenance reserve',
  closingCostPct: 'Closing costs',
  pmiRemovalLtv: 'PMI removal point',
  taxGrowth: 'Property-tax growth',
  insuranceGrowth: 'Insurance growth',
  hoaGrowth: 'HOA growth',
  maintenanceGrowth: 'Maintenance growth',
};
