// =====================================================
// Cost of Turnover — "Estimate Built Using" composition
//
// Each modeled form field has equal weight. This keeps the panel a transparent
// summary of the ENTIRE form instead of allowing a high-dollar field (salary in
// particular) to dominate simply because it affects several cost components.
// =====================================================

import { PROVENANCE } from '../data/benchmarks';

// Direct inputs use researched defaults until the user changes them. Assumption
// fields get their provenance from getDefaultAssumptions(). Together these are
// every user-adjustable field that participates in the calculation.
export const DIRECT_MODEL_INPUTS = [
  'departures',
  'salary',
  'blendedSupportSalary',
  'knowledgeTransferPlanned',
  'affectedProjects',
];

// Largest-remainder rounding so three percentages always sum to exactly 100.
function roundTo100(rawPercents) {
  const floored = rawPercents.map((p) => Math.floor(p));
  let remainder = 100 - floored.reduce((sum, p) => sum + p, 0);
  const order = rawPercents
    .map((p, index) => ({ index, fraction: p - Math.floor(p) }))
    .sort((a, b) => b.fraction - a.fraction);
  const result = [...floored];
  for (let index = 0; index < order.length && remainder > 0; index += 1) {
    result[order[index].index] += 1;
    remainder -= 1;
  }
  return result;
}

/**
 * Calculate the provenance mix across all modeled fields in the form.
 * Assumption overrides and edited direct inputs move one field apiece to the
 * organization bucket.
 */
export function computeBuiltUsing(defaults, overridden = new Set(), editedInputs = new Set()) {
  const overriddenKeys = overridden instanceof Set ? overridden : new Set(overridden);
  const editedInputKeys = editedInputs instanceof Set ? editedInputs : new Set(editedInputs);
  const counts = { published: 0, research: 0, org: 0 };

  Object.entries(defaults || {}).forEach(([key, assumption]) => {
    if (overriddenKeys.has(key)) {
      counts.org += 1;
    } else if (assumption?.type === PROVENANCE.PUBLISHED) {
      counts.published += 1;
    } else {
      counts.research += 1;
    }
  });

  DIRECT_MODEL_INPUTS.forEach((key) => {
    counts[editedInputKeys.has(key) ? 'org' : 'research'] += 1;
  });

  const total = counts.published + counts.research + counts.org;
  if (total === 0) {
    return { published: 0, research: 0, org: 0, raw: counts };
  }

  const [published, research, org] = roundTo100([
    (counts.published / total) * 100,
    (counts.research / total) * 100,
    (counts.org / total) * 100,
  ]);
  return { published, research, org, raw: counts };
}
