// Mortgage engine tests — reconcile to the workbook "06 Sample Scenario".
// Sample: $400,000 home, 20% down, 30-yr fixed @ 6.5%, tax 1.1%, insurance 0.5%,
// PMI 0.6% (n/a at 20% down), maintenance 1.0%, utilities $300, closing 3%,
// income $12,000/mo. Documented tolerance: $0.01 per figure.

import { calculate, monthlyPayment } from '../engine/calculator';

const sampleInputs = {
  homePrice: 400000,
  downPaymentPct: 0.2,
  loanTerm: 30,
  hoaMonthly: 0,
  utilitiesMonthly: 300,
  pointsCreditsNet: 0,
  grossMonthlyIncome: 12000,
};
const sampleAssumptions = {
  interestRate: 0.065,
  propertyTaxRate: 0.011,
  insuranceRate: 0.005,
  pmiRate: 0.006,
  maintenanceRate: 0.01,
  closingCostPct: 0.03,
  pmiRemovalLtv: 0.8,
  taxGrowth: 0.025,
  insuranceGrowth: 0.04,
  hoaGrowth: 0.03,
  maintenanceGrowth: 0.025,
};

const r = calculate(sampleInputs, sampleAssumptions);
const near = (a, b, tol = 0.01) => expect(Math.abs(a - b)).toBeLessThanOrEqual(tol);

describe('mortgage sample reconciliation', () => {
  it('derived loan facts', () => {
    expect(r.derived.downPayment).toBe(80000);
    expect(r.derived.loanAmount).toBe(320000);
    expect(r.derived.numberOfPayments).toBe(360);
    expect(r.derived.pmiApplies).toBe(false);
  });
  it('monthly P&I = 2022.6176751774913', () => near(r.monthly.pi, 2022.6176751774913));
  it('monthly tax / insurance / maintenance', () => {
    near(r.monthly.tax, 366.6666666666667);
    near(r.monthly.insurance, 166.66666666666666);
    near(r.monthly.maintenance, 333.3333333333333);
    expect(r.monthly.pmi).toBe(0);
  });
  it('three tiers', () => {
    near(r.tiers.pi, 2022.6176751774913);
    near(r.tiers.requiredPayment, 2555.9510085108245);
    near(r.tiers.trueCarrying, 3189.284341844158);
  });
  it('cash to close = 92000', () => near(r.cashToClose.mid, 92000));
  it('housing cost ratio (true) = 0.2657736951536798', () => near(r.ratios.true, 0.2657736951536798, 1e-9));
});

describe('mortgage multi-year schedule (flat costs)', () => {
  const byYear = r.horizons.reduce((a, h) => ({ ...a, [h.years]: h }), {});
  it('1-year figures', () => {
    near(byYear[1].totalPI, 24271.412102129896, 0.01);
    near(byYear[1].principalPaid, 3576.7215006719925, 0.01);
    near(byYear[1].interestPaid, 20694.690601457904, 0.01);
    near(byYear[1].taxes, 4400);
    near(byYear[1].insurance, 2000);
    near(byYear[1].maintenance, 4000);
    near(byYear[1].utilities, 3600);
    near(byYear[1].totalOutflow, 130271.41210212989, 0.02);
    near(byYear[1].equityBuilt, 83576.72150067199, 0.01);
    near(byYear[1].netCostAfterEquity, 46694.6906014579, 0.02);
  });
  it('10-year figures', () => {
    near(byYear[10].totalPI, 242714.12102129895, 0.02);
    near(byYear[10].principalPaid, 48716.395638355985, 0.02);
    near(byYear[10].interestPaid, 193997.72538294297, 0.02);
    near(byYear[10].totalOutflow, 474714.1210212989, 0.05);
    near(byYear[10].equityBuilt, 128716.39563835599, 0.02);
    near(byYear[10].netCostAfterEquity, 345997.72538294294, 0.05);
  });
});

describe('mortgage safeguards', () => {
  it('equity is not subtracted from monthly cost (tiers exclude equity)', () => {
    expect(r.tiers.trueCarrying).toBeGreaterThan(r.tiers.requiredPayment);
    expect(r.tiers.requiredPayment).toBeGreaterThan(r.tiers.pi);
  });
  it('low <= mid <= high for true monthly', () => {
    expect(r.trueMonthly.low).toBeLessThanOrEqual(r.trueMonthly.mid + 1e-6);
    expect(r.trueMonthly.mid).toBeLessThanOrEqual(r.trueMonthly.high + 1e-6);
  });
  it('PMI applies below 20% down and clears at the removal LTV', () => {
    const withPmi = calculate({ ...sampleInputs, downPaymentPct: 0.1 }, sampleAssumptions);
    expect(withPmi.derived.pmiApplies).toBe(true);
    expect(withPmi.monthly.pmi).toBeGreaterThan(0);
    // PMI should stop before the full 10-year window as the balance amortizes to 80% LTV.
    const tenYr = withPmi.horizons.find((h) => h.years === 10);
    const fullPmiIfNeverRemoved = withPmi.monthly.pmi * 120;
    expect(tenYr.pmi).toBeLessThan(fullPmiIfNeverRemoved);
  });
  it('top drivers ranked, top 3', () => {
    expect(r.topDrivers.map((d) => d.key)).toEqual(['pi', 'tax', 'maintenance']);
  });
  it('monthlyPayment matches standard amortization', () => {
    near(monthlyPayment(320000, 0.065 / 12, 360), 2022.6176751774913);
  });
});
