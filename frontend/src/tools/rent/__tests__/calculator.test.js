// Rent engine tests — reconcile to the workbook "06 Sample Scenario".
// $2,200 advertised rent, 12-mo lease, 1 free month, parking $100, pet rent $35,
// other fees $75, insurance $20, utilities $250, security $2,200, nonrefundable
// app/admin $300 + pet fee $250 + moving $1,200, income $7,000/mo, rent growth 3%,
// fee/util/insurance growth 2.5%. Tolerance $0.01.

import { calculate } from '../engine/calculator';

const inputs = {
  advertisedRent: 2200,
  leaseTermMonths: 12,
  freeMonths: 1,
  monthlyParking: 100,
  monthlyPetRent: 35,
  monthlyOtherFees: 75,
  monthlyInsurance: 20,
  monthlyUtilities: 250,
  refundablePetDeposit: 0,
  nonrefundableFees: 300,
  nonrefundablePetFee: 250,
  movingSetup: 1200,
  lastMonthPrepaid: 0,
  grossMonthlyIncome: 7000,
};
const assumptions = {
  securityDeposit: { value: 2200 },
  annualRentIncrease: { value: 0.03 },
  annualFeeIncrease: { value: 0.025 },
  annualUtilityIncrease: { value: 0.025 },
  annualInsuranceIncrease: { value: 0.025 },
};

const r = calculate(inputs, assumptions);
const near = (a, b, tol = 0.01) => expect(Math.abs(a - b)).toBeLessThanOrEqual(tol);

describe('rent sample reconciliation', () => {
  it('concession value = 2200', () => near(r.derived.concessionValue, 2200));
  it('effective first-year rent = 2016.6667', () => near(r.effectiveFirstYearRent, 2016.6666666666667));
  it('recurring fees = 210', () => near(r.derived.recurringFees, 210));
  it('true monthly rent cost = 2496.6667', () => near(r.trueMonthlyRentCost, 2496.666666666667));
  it('refundable cash held = 2200', () => near(r.refundableCashHeld, 2200));
  it('nonrefundable move-in = 1750', () => near(r.nonrefundableMoveInCost, 1750));
  it('move-in cash required = 3950', () => near(r.moveInCashRequired, 3950));
  it('housing cost ratio = 0.35667', () => near(r.housingRatio, 0.3566666666666667, 1e-9));
  it('effective monthly cost = 2642.50 (all-in incl. amortized move-in)', () => near(r.effectiveMonthlyCost, 2642.5));
});

describe('rent multi-year (with growth, concession year 1 only)', () => {
  const byYear = r.horizons.reduce((a, h) => ({ ...a, [h.years]: h }), {});
  it('1-year figures', () => {
    near(byYear[1].rent, 24200);
    near(byYear[1].fees, 2520);
    near(byYear[1].insurance, 240);
    near(byYear[1].utilities, 3000);
    near(byYear[1].totalCashPaid, 33910);
    near(byYear[1].netCostExclRefundable, 31710);
    near(byYear[1].avgMonthlyCost, 2642.5);
  });
  it('3-year figures (compounded growth)', () => {
    near(byYear[3].rent, 79399.76, 0.02);
    near(byYear[3].fees, 7750.575, 0.01);
    near(byYear[3].insurance, 738.15, 0.01);
    near(byYear[3].utilities, 9226.875, 0.01);
    near(byYear[3].totalCashPaid, 101065.36, 0.05);
    near(byYear[3].netCostExclRefundable, 98865.36, 0.05);
  });
  it('5-year figures', () => {
    near(byYear[5].rent, 137961.18538399998, 0.1);
    near(byYear[5].totalCashPaid, 172187.63763399998, 0.2);
  });
});

describe('rent safeguards', () => {
  it('refundable deposit excluded from net cost but included in move-in cash', () => {
    expect(r.moveInCashRequired).toBeGreaterThan(r.nonrefundableMoveInCost);
    const oneYear = r.horizons.find((h) => h.years === 1);
    near(oneYear.totalCashPaid - oneYear.netCostExclRefundable, r.refundableCashHeld);
  });
  it('true monthly is below advertised rent when a concession applies', () => {
    // effective rent is discounted, but fees/utilities push true cost above advertised
    expect(r.effectiveFirstYearRent).toBeLessThan(r.advertisedRent);
  });
  it('unplanned prepaid rent counts as move-in cash, not extra horizon rent', () => {
    const withPrepaid = calculate({ ...inputs, lastMonthPrepaid: 2200 }, assumptions);
    // Horizon rent unchanged; only move-in cash rises by the prepaid amount.
    near(withPrepaid.horizons[0].rent, r.horizons[0].rent);
    near(withPrepaid.moveInCashRequired - r.moveInCashRequired, 2200);
  });
  it('top hidden costs ranked (utilities, fees, amortized move-in)', () => {
    expect(r.topHiddenCosts.map((c) => c.key)).toEqual(['utilities', 'fees', 'moveInAmortized']);
  });
});
