import { getDefaultAssumptions } from '../engine/calculator';
import { computeBuiltUsing, DIRECT_MODEL_INPUTS } from '../engine/builtUsing';

const defaults = getDefaultAssumptions({
  roleCategory: 'corporate_knowledge',
  roleLevel: 'manager',
});

describe('Estimate Composition', () => {
  it('always totals 100%', () => {
    const composition = computeBuiltUsing(defaults);
    expect(composition.published + composition.research + composition.org).toBe(100);
  });

  it('includes assumptions and direct inputs from the entire form', () => {
    const composition = computeBuiltUsing(defaults);
    expect(
      composition.raw.published + composition.raw.research + composition.raw.org
    ).toBe(Object.keys(defaults).length + DIRECT_MODEL_INPUTS.length);
  });

  it('moves exactly one field when salary is edited', () => {
    const before = computeBuiltUsing(defaults);
    const after = computeBuiltUsing(defaults, [], ['salary']);
    expect(before.raw.org).toBe(0);
    expect(after.raw.org).toBe(1);
    expect(after.raw.research).toBe(before.raw.research - 1);
    expect(after.org).toBeLessThan(10);
  });

  it('moves each overridden assumption to organization inputs', () => {
    const before = computeBuiltUsing(defaults);
    const after = computeBuiltUsing(defaults, ['costPerHire', 'contextRediscoveryHours']);
    expect(after.raw.org).toBe(2);
    expect(after.raw.published + after.raw.research).toBe(
      before.raw.published + before.raw.research - 2
    );
  });
});
