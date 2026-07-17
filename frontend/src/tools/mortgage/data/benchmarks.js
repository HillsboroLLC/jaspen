// =====================================================
// Mortgage calculator — Benchmark Library
// Source of truth: docs/utilities/Jaspen_Mortgage_Calculator_Methodology_v1.xlsx
//   (sheets 05 Benchmark Library, 09 Sources). Methodology v1.
//
// The core loan facts (price, down payment, rate, term) are user inputs. These
// benchmarks provide the assumptions a user typically won't have on hand, plus
// the current mortgage-rate reference. Every value is editable.
// =====================================================

import { PROVENANCE, RELIABILITY } from '../../shared/provenance';

export const BENCHMARK_VERSION = '1.0.0';
export const METHODOLOGY_VERSION = '1.0';

// Freddie Mac PMMS national averages, embedded as a dated constant (deterministic
// — no live API). Prefilled as a Published Benchmark; the user overrides with a
// lender quote.
export const PMMS = {
  asOf: '2026-07-16',
  rate30: 0.0655,
  rate15: 0.0593,
  sourceUrl: 'https://www.freddiemac.com/pmms',
};

function bench(record) {
  return { status: 'Adopted', effectiveDate: '2026-07-16', lastReviewed: '2026-07', ...record };
}

export const BENCHMARKS = {
  M001: bench({
    id: 'M001',
    variable: 'Mortgage interest rate',
    segment: '30-year fixed (Freddie Mac PMMS)',
    value: PMMS.rate30,
    unit: 'annual %',
    type: PROVENANCE.PUBLISHED,
    reliability: RELIABILITY.A_PRIMARY,
    source: 'Freddie Mac PMMS',
    sourceUrl: PMMS.sourceUrl,
    year: `as of ${PMMS.asOf}`,
    methodology:
      'The current weekly national average 30-year fixed rate, prefilled as a transparent reference. Your actual rate depends on credit, points, LTV, loan product, and lender — always confirm with a lender quote.',
    limitation: 'A national weekly average, not a borrower-specific quote.',
  }),
  M004: bench({
    id: 'M004',
    variable: 'Closing costs',
    segment: 'US purchase (% of purchase price)',
    value: 0.03,
    unit: '% of price',
    type: PROVENANCE.RESEARCH,
    reliability: RELIABILITY.B_PROXY,
    status: 'Under Review',
    source: 'CFPB Loan Estimate + industry planning practice',
    sourceUrl: 'https://www.consumerfinance.gov/owning-a-home/loan-estimate/',
    year: 'Current',
    methodology:
      'A research-based planning midpoint (low/mid/high 2%/3%/5% of purchase price). Your actual Loan Estimate from a lender controls the real figure.',
    limitation: 'Not a universal benchmark; lender, title, location, and loan structure vary.',
  }),
  M005: bench({
    id: 'M005',
    variable: 'Property tax rate',
    segment: 'National planning fallback',
    value: 0.011,
    unit: '% of home value/yr',
    type: PROVENANCE.RESEARCH,
    reliability: RELIABILITY.B_PROXY,
    status: 'Under Review',
    source: 'National planning estimate (local rate preferred)',
    sourceUrl: 'https://www.consumerfinance.gov/owning-a-home/loan-estimate/',
    year: 'TBD',
    methodology:
      'An editable national placeholder (~1.10% of value/yr) until local/assessed data is available. Enter your county rate or bill for accuracy.',
    limitation: 'Property tax is highly local and assessment-based.',
  }),
  M006: bench({
    id: 'M006',
    variable: 'Homeowners insurance',
    segment: 'National planning fallback',
    value: 0.005,
    unit: '% of home value/yr',
    type: PROVENANCE.RESEARCH,
    reliability: RELIABILITY.B_PROXY,
    status: 'Under Review',
    source: 'Model fallback (insurance quote preferred)',
    sourceUrl: 'https://myhome.freddiemac.com/owning/homeownership-costs',
    year: 'TBD',
    methodology:
      'A proxy of ~0.50% of home value per year. Insurers price replacement cost and risk, not market value — a real quote is more accurate.',
    limitation: 'Home-value percentage is only a proxy for a replacement-cost premium.',
  }),
  M003: bench({
    id: 'M003',
    variable: 'PMI rate',
    segment: 'Conventional loan, down payment < 20%',
    value: 0.006,
    unit: '% of loan/yr',
    type: PROVENANCE.RESEARCH,
    reliability: RELIABILITY.B_PROXY,
    status: 'Under Review',
    source: 'CFPB PMI guidance + typical PMI pricing',
    sourceUrl: 'https://www.consumerfinance.gov/ask-cfpb/what-is-private-mortgage-insurance-en-122/',
    year: 'Current',
    methodology:
      'PMI typically applies when the down payment is under 20% on a conventional loan. Rate here is a planning proxy; the lender quote controls the real rate and duration.',
    limitation: 'Loan type and cancellation rules vary by lender and program.',
  }),
  M003b: bench({
    id: 'M003b',
    variable: 'PMI removal point',
    segment: 'Conventional loan',
    value: 0.8,
    unit: 'LTV of original price',
    type: PROVENANCE.RESEARCH,
    reliability: RELIABILITY.B_PROXY,
    source: 'Industry benchmark (borrower-requested cancellation)',
    sourceUrl: 'https://www.consumerfinance.gov/ask-cfpb/what-is-private-mortgage-insurance-en-122/',
    year: 'Current',
    methodology:
      'PMI is modeled to stop when the amortizing balance reaches 80% LTV of the original purchase price — the level at which borrowers can typically request cancellation. Editable, since actual removal depends on loan type and lender terms.',
    limitation: 'Actual removal depends on loan program, on-time payments, and lender policy.',
  }),
  M007: bench({
    id: 'M007',
    variable: 'Maintenance reserve',
    segment: 'General homeownership',
    value: 0.01,
    unit: '% of home value/yr',
    type: PROVENANCE.RESEARCH,
    reliability: RELIABILITY.B_PROXY,
    status: 'Under Review',
    source: 'Freddie Mac spending research + planning convention',
    sourceUrl: 'https://www.freddiemac.com/research/insight/homeowner-vs-renter-spending',
    year: '2024',
    methodology:
      'A planning reserve for repairs and upkeep (low/mid/high 0.5%/1.0%/1.5% of home value per year). Not a required bill; edit for property age and condition.',
    limitation: 'A planning reserve, not a required payment; varies sharply by property.',
  }),
  M010: bench({
    id: 'M010',
    variable: 'Property-tax growth',
    segment: 'Future-cost scenario',
    value: 0.025,
    unit: 'annual growth',
    type: PROVENANCE.RESEARCH,
    reliability: RELIABILITY.B_PROXY,
    status: 'Under Review',
    source: 'Scenario assumption',
    sourceUrl: '',
    year: 'TBD',
    methodology: 'An editable future-cost scenario, not a forecast. Local policy and reassessments vary.',
    limitation: 'Scenario only; local assessment policy varies.',
  }),
  M011: bench({
    id: 'M011',
    variable: 'Insurance growth',
    segment: 'Future-cost scenario',
    value: 0.04,
    unit: 'annual growth',
    type: PROVENANCE.RESEARCH,
    reliability: RELIABILITY.B_PROXY,
    status: 'Under Review',
    source: 'Scenario assumption',
    sourceUrl: '',
    year: 'TBD',
    methodology: 'An editable future-cost scenario, not a forecast. Insurance markets are volatile and location-specific.',
    limitation: 'Scenario only; insurance pricing is volatile.',
  }),
  M012: bench({
    id: 'M012',
    variable: 'HOA growth',
    segment: 'Future-cost scenario',
    value: 0.03,
    unit: 'annual growth',
    type: PROVENANCE.RESEARCH,
    reliability: RELIABILITY.B_PROXY,
    source: 'Scenario assumption',
    sourceUrl: '',
    year: 'TBD',
    methodology: 'An editable future-cost scenario for association dues.',
    limitation: 'Special assessments are unpredictable and excluded.',
  }),
  M013: bench({
    id: 'M013',
    variable: 'Maintenance growth',
    segment: 'Future-cost scenario',
    value: 0.025,
    unit: 'annual growth',
    type: PROVENANCE.RESEARCH,
    reliability: RELIABILITY.B_PROXY,
    source: 'Inflation-style scenario',
    sourceUrl: '',
    year: 'TBD',
    methodology: 'An editable inflation-style growth assumption for upkeep costs.',
    limitation: 'Scenario only.',
  }),
  // Context-only definitions/thresholds (not dollar defaults, shown in methodology).
  M008: bench({
    id: 'M008',
    variable: 'Housing cost-burden threshold',
    segment: 'HUD context',
    value: 0.3,
    unit: 'of gross income',
    type: PROVENANCE.PUBLISHED,
    reliability: RELIABILITY.A_PRIMARY,
    source: 'HUD / Freddie Mac',
    sourceUrl: 'https://www.huduser.gov/portal/datasets/cp/CHAS/bg_chas.html',
    year: 'Current',
    methodology: 'Housing cost above 30% of gross income is considered a cost burden. Shown as context, never an approval rule.',
    limitation: 'Not individualized financial advice or underwriting.',
  }),
};

// Default assumptions the engine reads. Rate defaults to the 30-year PMMS value.
export function getDefaultAssumptions() {
  const B = BENCHMARKS;
  return {
    interestRate: { value: B.M001.value, benchmarkId: 'M001', type: B.M001.type },
    propertyTaxRate: { value: B.M005.value, benchmarkId: 'M005', type: B.M005.type },
    insuranceRate: { value: B.M006.value, benchmarkId: 'M006', type: B.M006.type },
    pmiRate: { value: B.M003.value, benchmarkId: 'M003', type: B.M003.type },
    maintenanceRate: { value: B.M007.value, benchmarkId: 'M007', type: B.M007.type },
    closingCostPct: { value: B.M004.value, benchmarkId: 'M004', type: B.M004.type },
    pmiRemovalLtv: { value: B.M003b.value, benchmarkId: 'M003b', type: B.M003b.type },
    taxGrowth: { value: B.M010.value, benchmarkId: 'M010', type: B.M010.type },
    insuranceGrowth: { value: B.M011.value, benchmarkId: 'M011', type: B.M011.type },
    hoaGrowth: { value: B.M012.value, benchmarkId: 'M012', type: B.M012.type },
    maintenanceGrowth: { value: B.M013.value, benchmarkId: 'M013', type: B.M013.type },
  };
}

export function getBenchmark(id) {
  return BENCHMARKS[id] || null;
}

// Direct user-fact inputs (researched placeholder until edited, then Your Inputs).
export const DIRECT_INPUTS = [
  'homePrice',
  'downPaymentPct',
  'loanTerm',
  'hoaMonthly',
  'utilitiesMonthly',
  'pointsCreditsNet',
  'grossMonthlyIncome',
];
