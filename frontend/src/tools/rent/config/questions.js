// Rent questionnaire configuration (data, not UI). Source: workbook sheet 03.

export const STEPS = [
  { id: 'lease', index: 0, title: 'Lease basics', short: 'Lease' },
  { id: 'recurring', index: 1, title: 'Recurring costs', short: 'Recurring' },
  { id: 'movein', index: 2, title: 'Move-in & future', short: 'Move-in' },
  { id: 'results', index: 3, title: 'Your true cost', short: 'Results' },
];

export const LEASE_TERMS = [
  { id: 6, label: '6 months' },
  { id: 12, label: '12 months' },
  { id: 18, label: '18 months' },
  { id: 24, label: '24 months' },
];

// Step 2 recurring cost inputs (all direct user inputs).
export const RECURRING_FIELDS = [
  { key: 'monthlyParking', label: 'Parking' },
  { key: 'monthlyPetRent', label: 'Pet rent' },
  { key: 'monthlyOtherFees', label: 'Amenity / tech / trash / package fees' },
  { key: 'monthlyInsurance', label: "Renter's insurance" },
  { key: 'monthlyUtilities', label: 'Tenant-paid utilities' },
];

// Step 3 move-in cash inputs.
export const MOVEIN_FIELDS = [
  { key: 'lastMonthPrepaid', label: "Last month's / prepaid rent", help: 'Counted as move-in cash timing, not extra rent.' },
  { key: 'nonrefundableFees', label: 'Application / admin / move-in fees' },
  { key: 'refundablePetDeposit', label: 'Refundable pet deposit' },
  { key: 'nonrefundablePetFee', label: 'Nonrefundable pet fee' },
  { key: 'movingSetup', label: 'Moving / utility setup / furniture' },
];

// Step 3 future-growth assumptions.
export const GROWTH_ASSUMPTIONS = [
  { key: 'annualRentIncrease', label: 'Annual rent increase', kind: 'rate', unit: '%/yr', decimals: 1, step: 0.1 },
  { key: 'annualFeeIncrease', label: 'Annual fee increase', kind: 'rate', unit: '%/yr', decimals: 1, step: 0.1 },
  { key: 'annualUtilityIncrease', label: 'Annual utility increase', kind: 'rate', unit: '%/yr', decimals: 1, step: 0.1 },
  { key: 'annualInsuranceIncrease', label: 'Annual insurance increase', kind: 'rate', unit: '%/yr', decimals: 1, step: 0.1 },
];

export const ASSUMPTION_LABELS = {
  securityDeposit: 'Security deposit',
  annualRentIncrease: 'Annual rent increase',
  annualFeeIncrease: 'Annual fee increase',
  annualUtilityIncrease: 'Annual utility increase',
  annualInsuranceIncrease: 'Annual insurance increase',
};
