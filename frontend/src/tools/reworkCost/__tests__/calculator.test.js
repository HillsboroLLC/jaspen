import { calculateReworkCost, REWORK_DEFAULTS } from '../engine/calculator';

describe('rework cost calculator', () => {
  test('matches the methodology workbook default scenario', () => {
    const result = calculateReworkCost(REWORK_DEFAULTS);
    expect(result.grossAnnualCost).toBe(145488);
    expect(result.addressableCost).toBe(72744);
    expect(result.equivalentFte).toBeCloseTo(0.96);
    expect(result.low).toBe(109116);
    expect(result.high).toBe(181860);
  });

  test('supports a valid zero-rework result', () => {
    const result = calculateReworkCost({ ...REWORK_DEFAULTS, reworkShare: 0, managerHours: 0, materialsCost: 0 });
    expect(result.grossAnnualCost).toBe(0);
    expect(result.reworkHours).toBe(0);
    expect(result.equivalentFte).toBe(0);
  });

  test.each([['high', 0.1], ['medium', 0.25], ['low', 0.4]])('applies the %s confidence factor', (confidence, factor) => {
    const result = calculateReworkCost({ ...REWORK_DEFAULTS, confidence });
    expect(result.confidenceFactor).toBe(factor);
    expect(result.low).toBeCloseTo(result.grossAnnualCost * (1 - factor));
    expect(result.high).toBeCloseTo(result.grossAnnualCost * (1 + factor));
  });

  test('changing industry does not change the estimate', () => {
    const baseline = calculateReworkCost(REWORK_DEFAULTS).grossAnnualCost;
    expect(calculateReworkCost({ ...REWORK_DEFAULTS, industry: 'construction' }).grossAnnualCost).toBe(baseline);
  });
});

