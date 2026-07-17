// =====================================================
// Mortgage calculator — deterministic engine (no React, no AI).
// Source of truth: Jaspen_Mortgage_Calculator_Methodology_v1.xlsx
//   (sheets 04 Calculation Model, 06 Sample Scenario).
//
// Distinguishes three payment tiers:
//   P&I  →  Required housing payment (PITI + HOA)  →  True carrying cost
//           (+ maintenance reserve + optional utilities).
// Equity is never treated as a cost; multi-year costs are flat at today's
// levels (a separate exposure view models growth).
// =====================================================

import { CALC_VERSION } from './version';

const num = (v, fallback = 0) => {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
};
const clampMin = (n, min = 0) => (n < min ? min : n);

export const HORIZONS = [1, 3, 5, 10];

export function monthlyPayment(loan, monthlyRate, n) {
  if (n <= 0) return 0;
  if (monthlyRate === 0) return loan / n;
  const f = Math.pow(1 + monthlyRate, n);
  return (loan * monthlyRate * f) / (f - 1);
}

function val(assumptions, key, fallback) {
  const a = assumptions[key];
  if (a == null) return fallback;
  return typeof a === 'object' ? num(a.value, fallback) : num(a, fallback);
}

// Month-by-month amortization with declining-balance PMI until the removal LTV.
function buildSchedule({ loan, monthlyRate, n, pi, homePrice, pmiApplies, pmiMonthlyRate, removalBalance, maxMonths }) {
  let balance = loan;
  const rows = [];
  for (let m = 1; m <= maxMonths; m += 1) {
    if (m > n || balance <= 0) {
      rows.push({ principal: 0, interest: 0, pmi: 0, balance: Math.max(0, balance) });
      continue;
    }
    const interest = balance * monthlyRate;
    let principal = pi - interest;
    if (principal > balance) principal = balance;
    const pmi = pmiApplies && balance > removalBalance ? balance * pmiMonthlyRate : 0;
    balance -= principal;
    rows.push({ principal, interest, pmi, balance });
  }
  return rows;
}

export function calculate(inputs = {}, assumptions = {}) {
  const homePrice = clampMin(num(inputs.homePrice, 0));
  const downPaymentPct = Math.min(1, clampMin(num(inputs.downPaymentPct, 0)));
  const loanTerm = clampMin(num(inputs.loanTerm, 30), 1);
  const hoaMonthly = clampMin(num(inputs.hoaMonthly, 0));
  const utilitiesMonthly = clampMin(num(inputs.utilitiesMonthly, 0));
  const pointsCreditsNet = num(inputs.pointsCreditsNet, 0);
  const grossMonthlyIncome = clampMin(num(inputs.grossMonthlyIncome, 0));

  const interestRate = clampMin(val(assumptions, 'interestRate', 0.0655));
  const propertyTaxRate = clampMin(val(assumptions, 'propertyTaxRate', 0.011));
  const insuranceRate = clampMin(val(assumptions, 'insuranceRate', 0.005));
  const pmiRate = clampMin(val(assumptions, 'pmiRate', 0.006));
  const maintenanceRate = clampMin(val(assumptions, 'maintenanceRate', 0.01));
  const closingCostPct = clampMin(val(assumptions, 'closingCostPct', 0.03));
  const pmiRemovalLtv = Math.min(1, clampMin(val(assumptions, 'pmiRemovalLtv', 0.8)));
  const taxGrowth = val(assumptions, 'taxGrowth', 0.025);
  const insuranceGrowth = val(assumptions, 'insuranceGrowth', 0.04);
  const hoaGrowth = val(assumptions, 'hoaGrowth', 0.03);
  const maintenanceGrowth = val(assumptions, 'maintenanceGrowth', 0.025);

  const downPayment = homePrice * downPaymentPct;
  const loanAmount = clampMin(homePrice - downPayment);
  const monthlyRate = interestRate / 12;
  const n = Math.round(loanTerm * 12);

  const pi = monthlyPayment(loanAmount, monthlyRate, n);
  const monthlyTax = (homePrice * propertyTaxRate) / 12;
  const monthlyInsurance = (homePrice * insuranceRate) / 12;
  const pmiApplies = downPaymentPct < 0.2 && loanAmount > 0;
  const monthlyPMI = pmiApplies ? (loanAmount * pmiRate) / 12 : 0;
  const monthlyMaintenance = (homePrice * maintenanceRate) / 12;

  const requiredPayment = pi + monthlyTax + monthlyInsurance + monthlyPMI + hoaMonthly;
  const trueCarrying = requiredPayment + monthlyMaintenance + utilitiesMonthly;

  const closingCosts = homePrice * closingCostPct;
  const cashToClose = downPayment + closingCosts + pointsCreditsNet;
  const cashToCloseLow = downPayment + homePrice * 0.02 + pointsCreditsNet;
  const cashToCloseHigh = downPayment + homePrice * 0.05 + pointsCreditsNet;

  // Low / mid / high band for the true monthly carrying cost (sheet 04 factors).
  const trueMonthlyLow =
    pi + monthlyTax * 0.85 + monthlyInsurance * 0.8 + monthlyPMI * 0.8 + hoaMonthly + monthlyMaintenance * 0.5 + utilitiesMonthly;
  const trueMonthlyHigh =
    pi + monthlyTax * 1.15 + monthlyInsurance * 1.25 + monthlyPMI * 1.25 + hoaMonthly + monthlyMaintenance * 1.5 + utilitiesMonthly;

  // Multi-year schedule (flat costs at today's levels).
  const maxMonths = Math.max(...HORIZONS) * 12;
  const schedule = buildSchedule({
    loan: loanAmount,
    monthlyRate,
    n,
    pi,
    homePrice,
    pmiApplies,
    pmiMonthlyRate: pmiRate / 12,
    removalBalance: pmiRemovalLtv * homePrice,
    maxMonths,
  });

  const horizons = HORIZONS.map((years) => {
    const months = years * 12;
    let principal = 0;
    let interest = 0;
    let pmiPaid = 0;
    for (let i = 0; i < months && i < schedule.length; i += 1) {
      principal += schedule[i].principal;
      interest += schedule[i].interest;
      pmiPaid += schedule[i].pmi;
    }
    const totalPI = principal + interest;
    const taxes = monthlyTax * months;
    const insurance = monthlyInsurance * months;
    const hoa = hoaMonthly * months;
    const maintenance = monthlyMaintenance * months;
    const utilities = utilitiesMonthly * months;
    const upfront = cashToClose;
    const totalOutflow = totalPI + taxes + insurance + pmiPaid + hoa + maintenance + utilities + upfront;
    const equity = downPayment + principal;
    return {
      years,
      months,
      totalPI,
      principalPaid: principal,
      interestPaid: interest,
      taxes,
      insurance,
      pmi: pmiPaid,
      hoa,
      maintenance,
      utilities,
      upfront,
      totalOutflow,
      equityBuilt: equity,
      netCostAfterEquity: totalOutflow - equity,
    };
  });

  // Payment-change exposure: non-P&I costs grown by their scenario rates.
  const exposure = [5, 10].map((years) => {
    const taxY = monthlyTax * Math.pow(1 + taxGrowth, years);
    const insY = monthlyInsurance * Math.pow(1 + insuranceGrowth, years);
    const hoaY = hoaMonthly * Math.pow(1 + hoaGrowth, years);
    const maintY = monthlyMaintenance * Math.pow(1 + maintenanceGrowth, years);
    const projected = pi + taxY + insY + monthlyPMI + hoaY + maintY + utilitiesMonthly;
    return { years, projectedTrueMonthly: projected, increaseVsToday: projected - trueCarrying };
  });

  // Top cost drivers within the true monthly carrying cost.
  const driverComponents = [
    { key: 'pi', label: 'Principal & interest', value: pi },
    { key: 'tax', label: 'Property tax', value: monthlyTax },
    { key: 'insurance', label: 'Homeowners insurance', value: monthlyInsurance },
    { key: 'pmi', label: 'PMI', value: monthlyPMI },
    { key: 'hoa', label: 'HOA', value: hoaMonthly },
    { key: 'maintenance', label: 'Maintenance reserve', value: monthlyMaintenance },
    { key: 'utilities', label: 'Utilities', value: utilitiesMonthly },
  ].filter((c) => c.value > 0);
  const topDrivers = [...driverComponents].sort((a, b) => b.value - a.value).slice(0, 3);

  const requiredRatio = grossMonthlyIncome > 0 ? requiredPayment / grossMonthlyIncome : null;
  const trueRatio = grossMonthlyIncome > 0 ? trueCarrying / grossMonthlyIncome : null;

  return {
    calcVersion: CALC_VERSION,
    inputs: { homePrice, downPaymentPct, loanTerm, hoaMonthly, utilitiesMonthly, pointsCreditsNet, grossMonthlyIncome },
    derived: {
      downPayment,
      loanAmount,
      monthlyRate,
      numberOfPayments: n,
      closingCosts,
      pmiApplies,
    },
    monthly: {
      pi,
      tax: monthlyTax,
      insurance: monthlyInsurance,
      pmi: monthlyPMI,
      hoa: hoaMonthly,
      maintenance: monthlyMaintenance,
      utilities: utilitiesMonthly,
    },
    tiers: {
      pi,
      requiredPayment,
      trueCarrying,
    },
    trueMonthly: { low: trueMonthlyLow, mid: trueCarrying, high: trueMonthlyHigh },
    cashToClose: { low: cashToCloseLow, mid: cashToClose, high: cashToCloseHigh },
    horizons,
    exposure,
    topDrivers,
    ratios: { required: requiredRatio, true: trueRatio },
  };
}
