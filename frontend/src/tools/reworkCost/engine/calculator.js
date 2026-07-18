export const REWORK_DEFAULTS = Object.freeze({
  industry: 'knowledge',
  people: 12,
  hoursPerWeek: 40,
  weeksPerYear: 48,
  hourlyCost: 65,
  reworkShare: 8,
  avoidableShare: 50,
  managerHours: 3,
  managerHourlyCost: 95,
  materialsCost: 12000,
  delayCost: 0,
  annualBudget: 1000000,
  annualRevenue: 0,
  confidence: 'medium',
});

export const CONFIDENCE_FACTORS = Object.freeze({ high: 0.1, medium: 0.25, low: 0.4 });
export const RECOVERY_RATES = Object.freeze([0.1, 0.25, 0.5]);

const number = (value) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.max(0, parsed) : 0;
};

export function calculateReworkCost(values = REWORK_DEFAULTS) {
  const people = number(values.people);
  const hoursPerWeek = number(values.hoursPerWeek);
  const weeksPerYear = number(values.weeksPerYear);
  const hourlyCost = number(values.hourlyCost);
  const reworkShare = Math.min(100, number(values.reworkShare)) / 100;
  const avoidableShare = Math.min(100, number(values.avoidableShare)) / 100;
  const managerHours = number(values.managerHours);
  const managerHourlyCost = number(values.managerHourlyCost);
  const materialsCost = number(values.materialsCost);
  const delayCost = number(values.delayCost);
  const annualBudget = number(values.annualBudget);
  const annualRevenue = number(values.annualRevenue);
  const confidenceFactor = CONFIDENCE_FACTORS[values.confidence] ?? CONFIDENCE_FACTORS.medium;

  const annualPaidHours = people * hoursPerWeek * weeksPerYear;
  const reworkHours = annualPaidHours * reworkShare;
  const directLaborCost = reworkHours * hourlyCost;
  const managerCost = managerHours * weeksPerYear * managerHourlyCost;
  const grossAnnualCost = directLaborCost + managerCost + materialsCost + delayCost;
  const addressableCost = grossAnnualCost * avoidableShare;
  const annualHoursPerPerson = hoursPerWeek * weeksPerYear;

  const categories = [
    { id: 'labor', label: 'Direct rework labor', value: directLaborCost },
    { id: 'manager', label: 'Manager coordination', value: managerCost },
    { id: 'materials', label: 'Materials and vendors', value: materialsCost },
    { id: 'delay', label: 'Documented delay cost', value: delayCost },
  ].map((category) => ({
    ...category,
    share: grossAnnualCost > 0 ? category.value / grossAnnualCost : 0,
  }));

  return {
    annualPaidHours,
    reworkHours,
    directLaborCost,
    managerCost,
    materialsCost,
    delayCost,
    grossAnnualCost,
    monthlyCost: grossAnnualCost / 12,
    costPerPerson: people > 0 ? grossAnnualCost / people : 0,
    equivalentFte: annualHoursPerPerson > 0 ? reworkHours / annualHoursPerPerson : 0,
    addressableCost,
    low: grossAnnualCost * (1 - confidenceFactor),
    high: grossAnnualCost * (1 + confidenceFactor),
    confidenceFactor,
    budgetShare: annualBudget > 0 ? grossAnnualCost / annualBudget : null,
    revenueShare: annualRevenue > 0 ? grossAnnualCost / annualRevenue : null,
    categories,
    recoveryScenarios: RECOVERY_RATES.map((rate) => ({
      rate,
      annualValue: addressableCost * rate,
      monthlyValue: (addressableCost * rate) / 12,
    })),
  };
}

