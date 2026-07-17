// =====================================================
// Rent calculator — deterministic engine (no React, no AI).
// Source of truth: Jaspen_Rent_Calculator_Methodology_v1.xlsx
//   (sheets 04 Calculation Model, 06 Sample Scenario).
//
// Distinguishes advertised rent from the true monthly cost, separates refundable
// deposits (cash held) from real cost, and amortizes one-time nonrefundable
// costs into an "Effective Monthly Cost". Concessions are netted once.
// =====================================================

import { CALC_VERSION } from './version';

const num = (v, fallback = 0) => {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
};
const clampMin = (n, min = 0) => (n < min ? min : n);

export const HORIZONS = [1, 3, 5];

function val(assumptions, key, fallback) {
  const a = assumptions[key];
  if (a == null) return fallback;
  return typeof a === 'object' ? num(a.value, fallback) : num(a, fallback);
}

export function calculate(inputs = {}, assumptions = {}) {
  const advertisedRent = clampMin(num(inputs.advertisedRent, 0));
  const leaseTermMonths = clampMin(num(inputs.leaseTermMonths, 12), 1);
  const freeMonths = clampMin(num(inputs.freeMonths, 0));
  const parking = clampMin(num(inputs.monthlyParking, 0));
  const petRent = clampMin(num(inputs.monthlyPetRent, 0));
  const otherFees = clampMin(num(inputs.monthlyOtherFees, 0));
  const insurance = clampMin(num(inputs.monthlyInsurance, 0));
  const utilities = clampMin(num(inputs.monthlyUtilities, 0));
  const refundablePetDeposit = clampMin(num(inputs.refundablePetDeposit, 0));
  const nonrefundableFees = clampMin(num(inputs.nonrefundableFees, 0));
  const nonrefundablePetFee = clampMin(num(inputs.nonrefundablePetFee, 0));
  const movingSetup = clampMin(num(inputs.movingSetup, 0));
  const lastMonthPrepaid = clampMin(num(inputs.lastMonthPrepaid, 0));
  const grossMonthlyIncome = clampMin(num(inputs.grossMonthlyIncome, 0));

  const securityDeposit = clampMin(val(assumptions, 'securityDeposit', advertisedRent));
  const rentGrowth = val(assumptions, 'annualRentIncrease', 0.03);
  const feeGrowth = val(assumptions, 'annualFeeIncrease', 0.025);
  const utilGrowth = val(assumptions, 'annualUtilityIncrease', 0.025);
  const insGrowth = val(assumptions, 'annualInsuranceIncrease', 0.025);

  // Concession: free months valued at base rent, netted into effective rent.
  const concessionValue = freeMonths * advertisedRent;
  const effectiveFirstYearRent = (advertisedRent * leaseTermMonths - concessionValue) / leaseTermMonths;

  const recurringFees = parking + petRent + otherFees;
  const trueMonthlyRentCost = effectiveFirstYearRent + recurringFees + insurance + utilities;

  const refundableCashHeld = securityDeposit + refundablePetDeposit;
  const nonrefundableMoveInCost = nonrefundableFees + nonrefundablePetFee + movingSetup;

  // Move-in cash: first month is free if a concession covers it; refundable
  // deposits + prepaid + nonrefundable are all due up front.
  const firstMonthDue = freeMonths >= 1 ? 0 : advertisedRent;
  const moveInCashRequired = firstMonthDue + lastMonthPrepaid + refundableCashHeld + nonrefundableMoveInCost;

  // Effective Monthly Cost: all-in recurring + one-time nonrefundable amortized
  // over the lease term (equals the 1-year average net monthly cost).
  const effectiveMonthlyCost = trueMonthlyRentCost + nonrefundableMoveInCost / leaseTermMonths;

  // Month-by-month multi-year outflow. Growth applies per 12-month renewal block;
  // free months apply to the first months of the lease; concession only initial term.
  const maxMonths = Math.max(...HORIZONS) * 12;
  const g = (rate, monthIndex) => Math.pow(1 + rate, Math.floor(monthIndex / 12)); // monthIndex 0-based
  const monthly = [];
  for (let i = 0; i < maxMonths; i += 1) {
    const isFree = i < freeMonths;
    monthly.push({
      rent: isFree ? 0 : advertisedRent * g(rentGrowth, i),
      fees: recurringFees * g(feeGrowth, i),
      utilities: utilities * g(utilGrowth, i),
      insurance: insurance * g(insGrowth, i),
    });
  }

  const horizons = HORIZONS.map((years) => {
    const months = years * 12;
    let rent = 0;
    let fees = 0;
    let util = 0;
    let ins = 0;
    for (let i = 0; i < months && i < monthly.length; i += 1) {
      rent += monthly[i].rent;
      fees += monthly[i].fees;
      util += monthly[i].utilities;
      ins += monthly[i].insurance;
    }
    const totalCashPaid = rent + fees + util + ins + nonrefundableMoveInCost + refundableCashHeld;
    const netCostExclRefundable = totalCashPaid - refundableCashHeld;
    const endingMonthlyRent = advertisedRent * Math.pow(1 + rentGrowth, years - 1);
    return {
      years,
      months,
      rent,
      fees,
      utilities: util,
      insurance: ins,
      nonrefundable: nonrefundableMoveInCost,
      refundableCashHeld,
      totalCashPaid,
      netCostExclRefundable,
      avgMonthlyCost: netCostExclRefundable / months,
      endingMonthlyRent,
      housingRatio: grossMonthlyIncome > 0 ? trueMonthlyRentCost / grossMonthlyIncome : null,
    };
  });

  // Renewal exposure: projected true monthly cost at renewal under low/mid/high rent growth.
  const renewal = [2, 3].map((year) => {
    const project = (rate) => {
      const rentY = advertisedRent * Math.pow(1 + rate, year - 1);
      const feesY = recurringFees * Math.pow(1 + feeGrowth, year - 1);
      const utilY = utilities * Math.pow(1 + utilGrowth, year - 1);
      const insY = insurance * Math.pow(1 + insGrowth, year - 1);
      return rentY + feesY + utilY + insY;
    };
    return { year, low: project(0.02), mid: project(rentGrowth), high: project(0.05) };
  });

  // Largest hidden costs beyond the advertised rent.
  const hidden = [
    { key: 'utilities', label: 'Utilities', value: utilities },
    { key: 'fees', label: 'Recurring fees', value: recurringFees },
    { key: 'moveInAmortized', label: 'Move-in costs (amortized)', value: nonrefundableMoveInCost / leaseTermMonths },
    { key: 'insurance', label: "Renter's insurance", value: insurance },
  ].filter((c) => c.value > 0);
  const topHiddenCosts = [...hidden].sort((a, b) => b.value - a.value).slice(0, 3);

  const housingRatio = grossMonthlyIncome > 0 ? trueMonthlyRentCost / grossMonthlyIncome : null;

  return {
    calcVersion: CALC_VERSION,
    inputs: { advertisedRent, leaseTermMonths, freeMonths, grossMonthlyIncome },
    derived: { concessionValue, recurringFees, securityDeposit },
    advertisedRent,
    effectiveFirstYearRent,
    trueMonthlyRentCost,
    effectiveMonthlyCost,
    refundableCashHeld,
    nonrefundableMoveInCost,
    moveInCashRequired,
    horizons,
    renewal,
    topHiddenCosts,
    housingRatio,
    monthlyBreakdown: {
      effectiveRent: effectiveFirstYearRent,
      parking,
      petRent,
      otherFees,
      recurringFees,
      insurance,
      utilities,
    },
  };
}
