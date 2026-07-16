// Engine tests — reconcile to the workbook "06 Sample Scenario" and enforce the
// double-counting + provenance safeguards.
//
// Golden targets are computed directly from the refined workbook's frozen v1.0
// defaults (ramp 8 months, rediscovery 130h) and stated formulas. Documented
// rounding tolerance: $1 per component, $2 on the total.

import { calculate, getDefaultAssumptions, COMPONENTS } from '../engine/calculator';
import { PROVENANCE } from '../data/benchmarks';

// Reproduces the workbook sample: 1 departure, $120k corporate/knowledge
// manager, $110k blended support salary, 2 affected projects.
const sampleInputs = {
  roleCategory: 'corporate_knowledge',
  roleLevel: 'manager',
};
const sampleEngineInputs = {
  departures: 1,
  salary: 120000,
  blendedSupportSalary: 110000,
  affectedProjects: 2,
  knowledgeTransferPlanned: 'partial',
};

function runSample() {
  const assumptions = getDefaultAssumptions(sampleInputs);
  return calculate(sampleEngineInputs, assumptions);
}

const TOL = 1.0;

describe('calculation engine — sample scenario reconciliation', () => {
  const r = runSample();
  const byKey = r.components.reduce((a, c) => ({ ...a, [c.key]: c }), {});

  const expectedMid = {
    recruiting: 5475.0,
    vacancy: 9196.81,
    onboarding: 4315.78,
    rampUp: 45779.68,
    knowledgeTransfer: 3026.3,
    contextRediscovery: 10729.61,
    institutionalMemory: 4539.45,
    projectDisruption: 3631.56,
  };

  Object.entries(expectedMid).forEach(([key, mid]) => {
    it(`${key} midpoint reconciles within tolerance`, () => {
      expect(byKey[key].mid).toBeCloseTo(mid, 0);
      expect(Math.abs(byKey[key].mid - mid)).toBeLessThanOrEqual(TOL);
    });
  });

  it('traditional subtotal ≈ $64,767', () => {
    expect(Math.abs(r.subtotals.traditional.mid - 64767.27)).toBeLessThanOrEqual(2);
  });
  it('knowledge subtotal ≈ $21,927', () => {
    expect(Math.abs(r.subtotals.knowledge.mid - 21926.93)).toBeLessThanOrEqual(2);
  });
  it('total midpoint reconciles to $86,694 within $2', () => {
    expect(Math.abs(r.total.mid - 86694.2)).toBeLessThanOrEqual(2);
  });
  it('total low/high reconcile', () => {
    expect(Math.abs(r.total.low - 57328.18)).toBeLessThanOrEqual(2);
    expect(Math.abs(r.total.high - 121189.99)).toBeLessThanOrEqual(2);
  });
});

describe('double-counting safeguards', () => {
  const r = runSample();
  it('total equals the sum of additive components only (subtotals never re-added)', () => {
    const sum = r.components.reduce((s, c) => s + c.mid, 0);
    expect(r.total.mid).toBeCloseTo(sum, 6);
  });
  it('traditional + knowledge subtotals equal the total (no third bucket)', () => {
    expect(r.subtotals.traditional.mid + r.subtotals.knowledge.mid).toBeCloseTo(r.total.mid, 6);
  });
  it('low <= mid <= high for every component and the total', () => {
    r.components.forEach((c) => {
      expect(c.low).toBeLessThanOrEqual(c.mid + 1e-6);
      expect(c.mid).toBeLessThanOrEqual(c.high + 1e-6);
    });
    expect(r.total.low).toBeLessThanOrEqual(r.total.mid);
    expect(r.total.mid).toBeLessThanOrEqual(r.total.high);
  });
});

describe('conditional inputs', () => {
  it('unplanned departure zeroes knowledge transfer', () => {
    const r = calculate({ ...sampleEngineInputs, knowledgeTransferPlanned: 'no' }, getDefaultAssumptions(sampleInputs));
    const kt = r.components.find((c) => c.key === 'knowledgeTransfer');
    expect(kt.mid).toBe(0);
  });
  it('zero affected projects zeroes project disruption', () => {
    const r = calculate({ ...sampleEngineInputs, affectedProjects: 0 }, getDefaultAssumptions(sampleInputs));
    const pd = r.components.find((c) => c.key === 'projectDisruption');
    expect(pd.mid).toBe(0);
  });
  it('departures scales the total linearly', () => {
    const one = runSample().total.mid;
    const three = calculate({ ...sampleEngineInputs, departures: 3 }, getDefaultAssumptions(sampleInputs)).total.mid;
    expect(three).toBeCloseTo(one * 3, 4);
  });
});

describe('executive benchmark selection', () => {
  it('executive role uses the executive cost-per-hire benchmark (B002)', () => {
    const execDefaults = getDefaultAssumptions({ roleCategory: 'executive_leadership', roleLevel: 'vp' });
    expect(execDefaults.costPerHire.value).toBe(35879);
    expect(execDefaults.costPerHire.benchmarkId).toBe('B002');
  });
  it('non-executive role uses B001', () => {
    expect(getDefaultAssumptions(sampleInputs).costPerHire.value).toBe(5475);
  });
});

describe('provenance labels are preserved (published vs research-based)', () => {
  const d = getDefaultAssumptions(sampleInputs);
  it('cost per hire and multiplier are Published Benchmarks', () => {
    expect(d.costPerHire.type).toBe(PROVENANCE.PUBLISHED);
    expect(d.fullyLoadedMultiplier.type).toBe(PROVENANCE.PUBLISHED);
    expect(d.timeToFill.type).toBe(PROVENANCE.PUBLISHED);
  });
  it('knowledge/context defaults are Research-Based Estimates', () => {
    expect(d.contextRediscoveryHours.type).toBe(PROVENANCE.RESEARCH);
    expect(d.instMemoryHours.type).toBe(PROVENANCE.RESEARCH);
    expect(d.uncoveredWork.type).toBe(PROVENANCE.RESEARCH);
    expect(d.rampProductivity.type).toBe(PROVENANCE.RESEARCH);
  });
  it('every component declares a category', () => {
    COMPONENTS.forEach((c) => {
      expect(['traditional', 'knowledge']).toContain(c.category);
    });
  });
});
