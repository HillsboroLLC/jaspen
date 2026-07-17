// =====================================================
// Shared "Estimate Composition" engine.
// Equal-weight per modeled field: the panel is a transparent summary of the
// whole form, so no single high-dollar field can dominate the mix just because
// it feeds several outputs. Each assumption (default type = published/research)
// and each direct input (researched default until edited) counts once.
// Overriding an assumption or editing a direct input moves that one field into
// "Your Inputs". Always totals 100%.
//
// This is a composition of what the estimate was built FROM — never a
// confidence, accuracy, precision, quality, or reliability score.
// =====================================================

import { PROVENANCE } from './provenance';

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
 * @param {object} args
 * @param {Record<string,{type:string}>} args.assumptions  benchmark defaults keyed by field
 * @param {Set<string>|string[]} args.overridden            overridden assumption keys → org
 * @param {string[]} args.directInputs                      direct user-input field keys
 * @param {Set<string>|string[]} args.editedInputs          edited direct-input keys → org
 * @returns {{published:number, research:number, org:number, raw:object}}
 */
export function computeComposition({
  assumptions = {},
  overridden = new Set(),
  directInputs = [],
  editedInputs = new Set(),
} = {}) {
  const overriddenKeys = overridden instanceof Set ? overridden : new Set(overridden);
  const editedKeys = editedInputs instanceof Set ? editedInputs : new Set(editedInputs);
  const counts = { published: 0, research: 0, org: 0 };

  Object.entries(assumptions).forEach(([key, assumption]) => {
    if (overriddenKeys.has(key)) counts.org += 1;
    else if (assumption?.type === PROVENANCE.PUBLISHED) counts.published += 1;
    else counts.research += 1;
  });

  directInputs.forEach((key) => {
    counts[editedKeys.has(key) ? 'org' : 'research'] += 1;
  });

  const total = counts.published + counts.research + counts.org;
  if (total === 0) return { published: 0, research: 0, org: 0, raw: counts };

  const [published, research, org] = roundTo100([
    (counts.published / total) * 100,
    (counts.research / total) * 100,
    (counts.org / total) * 100,
  ]);
  return { published, research, org, raw: counts };
}
