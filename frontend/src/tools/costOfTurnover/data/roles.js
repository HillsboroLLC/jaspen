// =====================================================
// Cost of Turnover — Role taxonomy + salary defaults
// Role categories and levels are the finalized definitions from the workbook
//   sheet "03 User Questions".
//
// SALARY DEFAULTS — FLAGGED FOR REVIEW:
// The workbook (benchmark B014) specifies a *dynamic* BLS OEWS lookup keyed on
// role category/level, but does not ship fixed per-role salary values. Until an
// OEWS lookup service is integrated, the salary defaults below are Jaspen
// Research-Based Estimates (placeholders), not published benchmarks. The
// corporate/knowledge Manager anchor is $120,000 to match the workbook's sample
// scenario exactly. All other cells are directional placeholders. They are
// labeled as Research-Based Estimates in the UI and must be validated before any
// public salary claim. See DELIVERABLE notes.
// =====================================================

import { BENCHMARKS, PROVENANCE, RELIABILITY } from './benchmarks';

export const ROLE_CATEGORIES = [
  { id: 'corporate_knowledge', label: 'Corporate / knowledge' },
  { id: 'operations_field', label: 'Operations / field' },
  { id: 'technical_engineering', label: 'Technical / engineering' },
  { id: 'sales_customer', label: 'Sales / customer' },
  { id: 'executive_leadership', label: 'Executive leadership' },
  { id: 'other', label: 'Other' },
];

export const ROLE_LEVELS = [
  { id: 'frontline', label: 'Frontline / field' },
  { id: 'ic', label: 'Individual contributor' },
  { id: 'supervisor', label: 'Supervisor' },
  { id: 'manager', label: 'Manager' },
  { id: 'senior_manager', label: 'Senior manager' },
  { id: 'director', label: 'Director' },
  { id: 'vp', label: 'VP' },
  { id: 'c_suite', label: 'C-suite / executive' },
];

// Executive classification drives which SHRM cost-per-hire (B001 vs B002) and
// time-to-fill (B003 vs B004) benchmark applies.
// FLAGGED: SHRM does not publish the exact level cut-off. We treat VP and above,
// or the Executive leadership category, as "executive". Adjustable for review.
const EXECUTIVE_LEVELS = new Set(['vp', 'c_suite']);

export function isExecutiveRole({ roleCategory, roleLevel } = {}) {
  if (roleCategory === 'executive_leadership') return true;
  return EXECUTIVE_LEVELS.has(roleLevel);
}

// Directional salary placeholders (USD annual). Manager × corporate = 120000
// anchors the workbook sample. Level multipliers are documented placeholders.
const LEVEL_SALARY_ANCHOR = {
  frontline: 48000,
  ic: 78000,
  supervisor: 92000,
  manager: 120000,
  senior_manager: 150000,
  director: 185000,
  vp: 245000,
  c_suite: 340000,
};

// Category adjustment factor relative to corporate/knowledge (= 1.00).
const CATEGORY_SALARY_FACTOR = {
  corporate_knowledge: 1.0,
  operations_field: 0.82,
  technical_engineering: 1.18,
  sales_customer: 0.95,
  executive_leadership: 1.15,
  other: 0.9,
};

export function defaultSalaryFor({ roleCategory = 'corporate_knowledge', roleLevel = 'manager' } = {}) {
  const anchor = LEVEL_SALARY_ANCHOR[roleLevel] ?? LEVEL_SALARY_ANCHOR.manager;
  const factor = CATEGORY_SALARY_FACTOR[roleCategory] ?? 1.0;
  // Round to the nearest $500 for a clean, reviewable default.
  return Math.round((anchor * factor) / 500) * 500;
}

// A synthetic benchmark record describing the salary default's provenance, so
// the Benchmark Review step can show it with an honest label.
export function salaryBenchmarkFor(inputs) {
  return {
    id: 'B014',
    variable: 'Annual salary',
    segment: 'Selected role category / level',
    value: defaultSalaryFor(inputs),
    unit: 'USD',
    type: PROVENANCE.RESEARCH,
    reliability: RELIABILITY.C_SECONDARY,
    status: 'Future Research',
    source: 'BLS OEWS (lookup pending) — directional placeholder',
    sourceUrl: 'https://www.bls.gov/oes/tables.htm',
    year: 'May 2025',
    methodology:
      'The methodology specifies a dynamic BLS OEWS lookup by role category/level. Until that lookup is integrated, this is a directional Research-Based placeholder anchored to the workbook sample ($120k corporate/knowledge manager). Enter your organization’s actual salary for an accurate estimate.',
    limitation:
      'Placeholder pending OEWS lookup integration; not a published salary benchmark. Replace with your organization’s salary.',
  };
}

// Cost-per-hire / time-to-fill benchmark selection by executive status.
export function costPerHireBenchmarkFor(inputs) {
  return isExecutiveRole(inputs) ? BENCHMARKS.B002 : BENCHMARKS.B001;
}
export function timeToFillBenchmarkFor(inputs) {
  return isExecutiveRole(inputs) ? BENCHMARKS.B004 : BENCHMARKS.B003;
}

// Optional industry list (BLS/JOLTS groups) — used only for optional refinement
// and context; does not change the additive cost total in v1.
export const INDUSTRIES = [
  { id: '', label: 'Not specified' },
  { id: 'professional_business', label: 'Professional & business services', quitsRate: 0.023 },
  { id: 'finance_insurance', label: 'Finance & insurance', quitsRate: 0.013 },
  { id: 'health_care', label: 'Health care & social assistance', quitsRate: 0.02 },
  { id: 'manufacturing', label: 'Manufacturing', quitsRate: 0.014 },
  { id: 'retail_trade', label: 'Retail trade', quitsRate: 0.026 },
  { id: 'accommodation_food', label: 'Accommodation & food services', quitsRate: 0.042 },
  { id: 'other_private', label: 'Other / total private', quitsRate: 0.022 },
];

export const COUNTRIES = [{ id: 'US', label: 'United States' }];
