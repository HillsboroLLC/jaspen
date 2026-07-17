import { computeComposition } from '../../shared/composition';
import { getDefaultAssumptions, DIRECT_INPUTS } from '../data/benchmarks';

const defaults = getDefaultAssumptions();

describe('mortgage Estimate Composition', () => {
  it('always totals 100%', () => {
    const c = computeComposition({ assumptions: defaults, overridden: [], directInputs: DIRECT_INPUTS, editedInputs: new Set() });
    expect(c.published + c.research + c.org).toBe(100);
  });
  it('has a published share from the PMMS rate benchmark', () => {
    const c = computeComposition({ assumptions: defaults, overridden: [], directInputs: DIRECT_INPUTS, editedInputs: new Set() });
    expect(c.published).toBeGreaterThan(0);
  });
  it('editing inputs and overriding assumptions raises Your Inputs', () => {
    const base = computeComposition({ assumptions: defaults, overridden: [], directInputs: DIRECT_INPUTS, editedInputs: new Set() });
    const after = computeComposition({
      assumptions: defaults,
      overridden: ['propertyTaxRate', 'interestRate'],
      directInputs: DIRECT_INPUTS,
      editedInputs: new Set(['homePrice', 'downPaymentPct']),
    });
    expect(after.org).toBeGreaterThan(base.org);
    expect(after.published + after.research + after.org).toBe(100);
  });
});
