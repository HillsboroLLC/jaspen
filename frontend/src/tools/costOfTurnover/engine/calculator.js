// =====================================================
// Cost of Turnover — Calculation Engine (pure, no React)
// Source of truth: workbook sheets "04 Calculation Model" and "06 Sample
// Scenario". Every additive component has a defensible formula; subtotals are
// never re-added into the total (double-count safeguard).
//
// Low / mid / high use the sensitivity factors documented in sheet 04, not
// arbitrary percentages.
//
// This module knows nothing about the UI. It takes resolved inputs + assumptions
// and returns a structured result including per-component provenance metadata.
// =====================================================

import { CALC_VERSION } from './version';
import {
  costPerHireBenchmarkFor,
  timeToFillBenchmarkFor,
} from '../data/roles';
import { BENCHMARKS, PROVENANCE } from '../data/benchmarks';
import { MODEL_CONSTANTS } from '../data/benchmarks';

const { workingDaysPerYear, hoursPerYear, monthsPerYear, workingDayConversion } = MODEL_CONSTANTS;

const clamp01 = (n) => Math.max(0, Math.min(1, n));
const num = (v, fallback = 0) => {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
};

// ---------------------------------------------------------------------------
// Component catalog. `provenanceInputs` gives, per component, the share of the
// component's cost attributable to a specific benchmark-driven assumption and
// its provenance bucket. The remainder (1 - sum of shares) is the organization's
// own inputs (salary-driven rates, headcount, project count). Shares are the
// decomposition from workbook sheet 06 (cols "Benchmark share" / "Direct share
// of benchmark"). The form-wide composition itself is handled in builtUsing.js.
// ---------------------------------------------------------------------------
export const CATEGORY = { TRADITIONAL: 'traditional', KNOWLEDGE: 'knowledge' };

export const COMPONENTS = [
  {
    key: 'recruiting',
    label: 'Recruiting and sourcing',
    category: CATEGORY.TRADITIONAL,
    explanation: 'Estimated cost to source and recruit a replacement.',
    driverNote: 'Cost per hire × number of departures.',
    provenanceInputs: [{ key: 'costPerHire', bucket: PROVENANCE.PUBLISHED, share: 1.0 }],
  },
  {
    key: 'vacancy',
    label: 'Vacancy capacity loss',
    category: CATEGORY.TRADITIONAL,
    explanation: 'Estimated value of work not covered while the role is vacant.',
    driverNote: 'Vacancy working days × loaded daily cost × uncovered-work share.',
    provenanceInputs: [
      { key: 'timeToFill', bucket: PROVENANCE.PUBLISHED, share: 0.25 },
      { key: 'uncoveredWork', bucket: PROVENANCE.RESEARCH, share: 0.25 },
    ],
  },
  {
    key: 'onboarding',
    label: 'Onboarding and training',
    category: CATEGORY.TRADITIONAL,
    explanation: 'Direct training and the internal time required to onboard the replacement.',
    driverNote: 'Direct training cost + onboarding hours × blended support rate.',
    provenanceInputs: [
      { key: 'directTrainingCost', bucket: PROVENANCE.RESEARCH, share: 0.42 },
      { key: 'onboardingHours', bucket: PROVENANCE.RESEARCH, share: 0.28 },
    ],
  },
  {
    key: 'rampUp',
    label: 'Ramp-up productivity loss',
    category: CATEGORY.TRADITIONAL,
    explanation:
      'Incremental productivity lost while the replacement ramps to full output. The model multiplies by the productivity gap, so the full ramp period is not treated as lost.',
    driverNote: 'Loaded monthly cost × ramp months × productivity gap (1 − average productivity).',
    provenanceInputs: [
      { key: 'rampMonths', bucket: PROVENANCE.PUBLISHED, share: 0.25 },
      { key: 'rampProductivity', bucket: PROVENANCE.RESEARCH, share: 0.25 },
    ],
  },
  {
    key: 'knowledgeTransfer',
    label: 'Knowledge transfer',
    category: CATEGORY.KNOWLEDGE,
    explanation:
      'Employee time used to transfer knowledge through overlap, handoffs, mentoring, or documentation. Only applies when a departure is planned.',
    driverNote: 'Transfer hours × blended support rate.',
    jaspenRelevance: 'Jaspen can supplement knowledge capture, not replace human handoff.',
    provenanceInputs: [{ key: 'knowledgeTransferHours', bucket: PROVENANCE.RESEARCH, share: 0.5 }],
  },
  {
    key: 'contextRediscovery',
    label: 'Time to rebuild context',
    category: CATEGORY.KNOWLEDGE,
    explanation:
      'Replacement time spent rebuilding historical context and rationale that was not transferred — counted only where it is not already captured by the ramp-up productivity gap.',
    driverNote: 'Rediscovery hours × replacement loaded hourly cost.',
    jaspenRelevance: 'Jaspen can preserve context so it does not have to be rediscovered from scratch.',
    provenanceInputs: [{ key: 'contextRediscoveryHours', bucket: PROVENANCE.RESEARCH, share: 0.5 }],
  },
  {
    key: 'institutionalMemory',
    label: 'Institutional-memory reconstruction',
    category: CATEGORY.KNOWLEDGE,
    explanation:
      'Coworker and leadership time spent recreating missing records, lessons, history, and explanations.',
    driverNote: 'Reconstruction hours × blended support rate.',
    jaspenRelevance: 'Core Jaspen connection: knowledge that would otherwise be paid for twice.',
    provenanceInputs: [{ key: 'instMemoryHours', bucket: PROVENANCE.RESEARCH, share: 0.5 }],
  },
  {
    key: 'projectDisruption',
    label: 'Project disruption',
    category: CATEGORY.KNOWLEDGE,
    explanation:
      'Additional labor required on active projects because critical context or expertise is missing. Labor-only; excludes speculative project-value loss.',
    driverNote: 'Affected projects × added team hours × blended support rate.',
    jaspenRelevance: 'Connected project history can reduce the context gap.',
    provenanceInputs: [{ key: 'projectDisruptionHours', bucket: PROVENANCE.RESEARCH, share: 0.35 }],
  },
];

export const COMPONENT_BY_KEY = COMPONENTS.reduce((acc, c) => {
  acc[c.key] = c;
  return acc;
}, {});

// ---------------------------------------------------------------------------
// Default assumptions for a set of role inputs. Returns a map of
// assumptionKey -> { value, benchmarkId, type }. The UI layers user overrides
// on top of this; the engine only ever reads resolved numeric values.
// ---------------------------------------------------------------------------
export function getDefaultAssumptions(inputs = {}) {
  const cph = costPerHireBenchmarkFor(inputs);
  const ttf = timeToFillBenchmarkFor(inputs);
  const B = BENCHMARKS;
  return {
    fullyLoadedMultiplier: { value: B.B006.value, benchmarkId: 'B006', type: B.B006.type },
    costPerHire: { value: cph.value, benchmarkId: cph.id, type: cph.type },
    timeToFill: { value: ttf.value, benchmarkId: ttf.id, type: ttf.type },
    uncoveredWork: { value: B.B015.value, benchmarkId: 'B015', type: B.B015.type },
    directTrainingCost: { value: B.B018.value, benchmarkId: 'B018', type: B.B018.type },
    onboardingHours: { value: 24, benchmarkId: 'B018', type: PROVENANCE.RESEARCH },
    rampMonths: { value: B.B017.value, benchmarkId: 'B017', type: B.B017.type },
    rampProductivity: { value: B.B016.value, benchmarkId: 'B016', type: B.B016.type },
    knowledgeTransferHours: { value: B.B019.value, benchmarkId: 'B019', type: B.B019.type },
    contextRediscoveryHours: { value: B.B020.value, benchmarkId: 'B020', type: B.B020.type },
    instMemoryHours: { value: B.B021.value, benchmarkId: 'B021', type: B.B021.type },
    projectDisruptionHours: { value: B.B022.value, benchmarkId: 'B022', type: B.B022.type },
  };
}

// Reads a resolved numeric value for an assumption key from {assumptions} where
// each entry may be a raw number or a { value } object.
function val(assumptions, key, fallback) {
  const a = assumptions[key];
  if (a == null) return fallback;
  if (typeof a === 'object') return num(a.value, fallback);
  return num(a, fallback);
}

// ---------------------------------------------------------------------------
// Core calculation. `inputs` carries step-1/step-3 values; `assumptions` carries
// resolved (default + overridden) benchmark values.
// ---------------------------------------------------------------------------
export function calculate(inputs = {}, assumptions = {}) {
  const departures = Math.max(0, num(inputs.departures, 1));
  const salary = Math.max(0, num(inputs.salary, 0));
  const affectedProjects = Math.max(0, num(inputs.affectedProjects, 0));
  const transferPlanned = inputs.knowledgeTransferPlanned || 'partial'; // yes | partial | no

  const multiplier = val(assumptions, 'fullyLoadedMultiplier', BENCHMARKS.B006.value);
  const costPerHire = val(assumptions, 'costPerHire', 0);
  const timeToFill = val(assumptions, 'timeToFill', 0);
  const uncoveredWork = clamp01(val(assumptions, 'uncoveredWork', 0.5));
  const directTrainingCost = val(assumptions, 'directTrainingCost', 0);
  const onboardingHours = val(assumptions, 'onboardingHours', 0);
  const rampMonths = val(assumptions, 'rampMonths', 0);
  const rampProductivity = clamp01(val(assumptions, 'rampProductivity', 0.6));
  const knowledgeTransferHours = val(assumptions, 'knowledgeTransferHours', 0);
  const contextRediscoveryHours = val(assumptions, 'contextRediscoveryHours', 0);
  const instMemoryHours = val(assumptions, 'instMemoryHours', 0);
  const projectDisruptionHours = val(assumptions, 'projectDisruptionHours', 0);

  // Support/blended salary is an organization input; defaults to the role salary.
  const supportSalary = Math.max(0, num(inputs.blendedSupportSalary, salary));

  // Derived labor rates.
  const loadedAnnual = salary * multiplier;
  const loadedHourly = loadedAnnual / hoursPerYear;
  const loadedDaily = loadedAnnual / workingDaysPerYear;
  const loadedMonthly = loadedAnnual / monthsPerYear;
  const supportLoadedHourly = (supportSalary * multiplier) / hoursPerYear;
  const vacancyWorkingDays = timeToFill * workingDayConversion;

  // Planned-overlap gate: unplanned exits get zero transfer overlap.
  const transferFactor = transferPlanned === 'no' ? 0 : 1;

  // Sensitivity band helper.
  const band = (low, mid, high) => ({ low, mid, high });

  // ---- Traditional components ----
  const recruiting = band(
    departures * costPerHire * 0.85,
    departures * costPerHire,
    departures * costPerHire * 1.15
  );

  const vacancyMid = departures * vacancyWorkingDays * loadedDaily * uncoveredWork;
  const vacancy = band(
    departures * (vacancyWorkingDays * 0.85) * loadedDaily * clamp01(uncoveredWork - 0.1),
    vacancyMid,
    departures * (vacancyWorkingDays * 1.15) * loadedDaily * clamp01(uncoveredWork + 0.1)
  );

  const onboardingMid = departures * (directTrainingCost + onboardingHours * supportLoadedHourly);
  const onboarding = band(onboardingMid * 0.8, onboardingMid, onboardingMid * 1.2);

  const rampMid = departures * loadedMonthly * rampMonths * (1 - rampProductivity);
  const rampUp = band(
    departures * loadedMonthly * (rampMonths * 0.8) * (1 - clamp01(rampProductivity + 0.1)),
    rampMid,
    departures * loadedMonthly * (rampMonths * 1.2) * (1 - clamp01(rampProductivity - 0.1))
  );

  // ---- Knowledge & context components ----
  const ktMid = departures * knowledgeTransferHours * transferFactor * supportLoadedHourly;
  const knowledgeTransfer = band(ktMid * 0.75, ktMid, ktMid * 1.25);

  const crMid = departures * contextRediscoveryHours * loadedHourly;
  const contextRediscovery = band(crMid * 0.7, crMid, crMid * 1.3);

  const imMid = departures * instMemoryHours * supportLoadedHourly;
  const institutionalMemory = band(imMid * 0.7, imMid, imMid * 1.3);

  const pdMid = departures * affectedProjects * projectDisruptionHours * supportLoadedHourly;
  const projectDisruption = band(pdMid * 0.7, pdMid, pdMid * 1.3);

  const rawComponents = {
    recruiting,
    vacancy,
    onboarding,
    rampUp,
    knowledgeTransfer,
    contextRediscovery,
    institutionalMemory,
    projectDisruption,
  };

  // Assemble component objects with metadata + provenance shares.
  const components = COMPONENTS.map((meta) => {
    const b = rawComponents[meta.key];
    return {
      ...meta,
      low: b.low,
      mid: b.mid,
      high: b.high,
    };
  });

  const sumBy = (pred, field) =>
    components.filter(pred).reduce((s, c) => s + c[field], 0);

  const traditionalPred = (c) => c.category === CATEGORY.TRADITIONAL;
  const knowledgePred = (c) => c.category === CATEGORY.KNOWLEDGE;

  const traditional = {
    low: sumBy(traditionalPred, 'low'),
    mid: sumBy(traditionalPred, 'mid'),
    high: sumBy(traditionalPred, 'high'),
  };
  const knowledge = {
    low: sumBy(knowledgePred, 'low'),
    mid: sumBy(knowledgePred, 'mid'),
    high: sumBy(knowledgePred, 'high'),
  };
  // DOUBLE-COUNT SAFEGUARD: the total is the sum of the additive *components*
  // only. Subtotals are display groupings and are never re-added.
  const total = {
    low: components.reduce((s, c) => s + c.low, 0),
    mid: components.reduce((s, c) => s + c.mid, 0),
    high: components.reduce((s, c) => s + c.high, 0),
  };

  const totalMid = total.mid || 1;
  const withPct = components.map((c) => ({ ...c, pctOfTotal: (c.mid / totalMid) * 100 }));

  const topDrivers = [...withPct].sort((a, b) => b.mid - a.mid).slice(0, 3);

  return {
    calcVersion: CALC_VERSION,
    inputs: { departures, salary, affectedProjects, transferPlanned, supportSalary },
    derived: {
      loadedAnnual,
      loadedHourly,
      loadedDaily,
      loadedMonthly,
      supportLoadedHourly,
      vacancyWorkingDays,
      effectiveLostProductivityMonths: rampMonths * (1 - rampProductivity),
    },
    components: withPct,
    subtotals: { traditional, knowledge },
    total,
    topDrivers,
  };
}
