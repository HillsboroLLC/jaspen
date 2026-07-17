// =====================================================
// Rent calculator — Benchmark Library
// Source of truth: docs/utilities/Jaspen_Rent_Calculator_Methodology_v1.xlsx
//   (sheets 05 Benchmark Library, 09 Sources). Methodology v1.
//
// Lease economics are property-specific, so user/lease inputs dominate. These
// benchmarks provide HUD affordability context, a deposit fallback, and editable
// future-growth scenarios. Everything is editable.
// =====================================================

import { PROVENANCE, RELIABILITY } from '../../shared/provenance';

export const BENCHMARK_VERSION = '1.0.0';
export const METHODOLOGY_VERSION = '1.0';

function bench(record) {
  return { status: 'Adopted', effectiveDate: '2026-07-16', lastReviewed: '2026-07', ...record };
}

export const BENCHMARKS = {
  R001: bench({
    id: 'R001',
    variable: 'Cost-burden threshold',
    segment: 'HUD context',
    value: 0.3,
    unit: 'of gross income',
    type: PROVENANCE.PUBLISHED,
    reliability: RELIABILITY.A_PRIMARY,
    source: 'HUD CHAS',
    sourceUrl: 'https://www.huduser.gov/portal/datasets/cp/CHAS/bg_chas.html',
    year: 'Current',
    methodology: 'Housing cost (including utilities) above 30% of gross income is a cost burden. Context only, never an approval rule.',
    limitation: 'Not a personalized affordability recommendation.',
  }),
  R002: bench({
    id: 'R002',
    variable: 'Severe cost-burden threshold',
    segment: 'HUD context',
    value: 0.5,
    unit: 'of gross income',
    type: PROVENANCE.PUBLISHED,
    reliability: RELIABILITY.A_PRIMARY,
    source: 'HUD CHAS',
    sourceUrl: 'https://www.huduser.gov/portal/datasets/cp/CHAS/bg_chas.html',
    year: 'Current',
    methodology: 'Housing cost above 50% of gross income is a severe cost burden, including utilities.',
    limitation: 'Not individualized advice.',
  }),
  R006: bench({
    id: 'R006',
    variable: 'Security deposit',
    segment: 'General fallback',
    value: 1, // months of rent
    unit: "month's rent",
    type: PROVENANCE.RESEARCH,
    reliability: RELIABILITY.B_PROXY,
    status: 'Under Review',
    source: 'Model fallback (lease value preferred)',
    sourceUrl: '',
    year: 'TBD',
    methodology: 'A placeholder of one month’s rent when the lease value is unknown. Enter your actual deposit for accuracy.',
    limitation: 'State/local law and landlord terms vary.',
  }),
  R005rent: bench({
    id: 'R005rent',
    variable: 'Annual rent growth',
    segment: 'Future-cost scenario',
    value: 0.03,
    unit: 'annual %',
    type: PROVENANCE.RESEARCH,
    reliability: RELIABILITY.B_PROXY,
    status: 'Under Review',
    source: 'Scenario default (low/mid/high 2/3/5%)',
    sourceUrl: 'https://www.zillow.com/research/data/',
    year: 'TBD',
    methodology: 'An editable renewal-increase assumption, not a forecast. Rent growth varies by market and cycle.',
    limitation: 'Local market and cycle dependent.',
  }),
  R005fee: bench({
    id: 'R005fee',
    variable: 'Annual fee growth',
    segment: 'Future-cost scenario',
    value: 0.025,
    unit: 'annual %',
    type: PROVENANCE.RESEARCH,
    reliability: RELIABILITY.B_PROXY,
    source: 'Scenario default',
    sourceUrl: '',
    year: 'TBD',
    methodology: 'An editable growth assumption for recurring fees.',
    limitation: 'Landlord-specific.',
  }),
  R005util: bench({
    id: 'R005util',
    variable: 'Annual utility growth',
    segment: 'Future-cost scenario',
    value: 0.025,
    unit: 'annual %',
    type: PROVENANCE.RESEARCH,
    reliability: RELIABILITY.B_PROXY,
    source: 'Scenario default',
    sourceUrl: '',
    year: 'TBD',
    methodology: 'An editable growth assumption for tenant-paid utilities.',
    limitation: 'Usage and rates vary.',
  }),
  R005ins: bench({
    id: 'R005ins',
    variable: 'Annual insurance growth',
    segment: 'Future-cost scenario',
    value: 0.025,
    unit: 'annual %',
    type: PROVENANCE.RESEARCH,
    reliability: RELIABILITY.B_PROXY,
    source: 'Scenario default',
    sourceUrl: '',
    year: 'TBD',
    methodology: 'An editable growth assumption for renter’s insurance.',
    limitation: 'Insurer pricing varies.',
  }),
  // Context / future market data (methodology only, not a v1 default).
  R004: bench({
    id: 'R004',
    variable: 'Local market rent',
    segment: 'ZIP/metro/unit type',
    value: null,
    unit: 'USD/month',
    displayValue: 'future',
    type: PROVENANCE.RESEARCH,
    reliability: RELIABILITY.C_SECONDARY,
    status: 'Future Research',
    source: 'Zillow ZORI / HUD FMR',
    sourceUrl: 'https://www.zillow.com/research/data/',
    year: 'Current',
    methodology: 'Comparing your entered rent to a local market index is a future enhancement, once unit type, bedroom count, and geography matching are defined.',
    limitation: 'Indexes may not match property type, concessions, or the current listing.',
  }),
};

// Assumption defaults. Security deposit defaults to one month of the entered rent.
export function getDefaultAssumptions(inputs = {}) {
  const B = BENCHMARKS;
  const oneMonthRent = Math.max(0, Number(inputs.advertisedRent) || 0);
  return {
    securityDeposit: { value: oneMonthRent, benchmarkId: 'R006', type: B.R006.type },
    annualRentIncrease: { value: B.R005rent.value, benchmarkId: 'R005rent', type: B.R005rent.type },
    annualFeeIncrease: { value: B.R005fee.value, benchmarkId: 'R005fee', type: B.R005fee.type },
    annualUtilityIncrease: { value: B.R005util.value, benchmarkId: 'R005util', type: B.R005util.type },
    annualInsuranceIncrease: { value: B.R005ins.value, benchmarkId: 'R005ins', type: B.R005ins.type },
  };
}

export function getBenchmark(id) {
  return BENCHMARKS[id] || null;
}

export const DIRECT_INPUTS = [
  'advertisedRent',
  'leaseTermMonths',
  'freeMonths',
  'monthlyParking',
  'monthlyPetRent',
  'monthlyOtherFees',
  'monthlyInsurance',
  'monthlyUtilities',
  'refundablePetDeposit',
  'nonrefundableFees',
  'nonrefundablePetFee',
  'movingSetup',
  'lastMonthPrepaid',
  'grossMonthlyIncome',
];
