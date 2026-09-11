// Decision Style Assessment — PROVISIONAL RESULT MAPPING (mock).
//
// ⚠️ PLACEHOLDER. This is intentionally simple and is NOT the Decision Profile
// framework. It exists only so the UX feels responsive during review. The next
// phase will replace `deriveProvisionalStyle` wholesale with the formal
// interpretation engine. Nothing else in the UI should need to change: the
// component depends only on this function's return shape:
//
//     { style: <STYLES entry>, isFallback: <boolean> }
//
// Deliberate constraints (kept faithful to the product philosophy):
//   - No numeric score is ever returned or shown. Internal affinity tallies are
//     a means of picking a label, never a grade of the user.
//   - No dense tree of hard-coded conditionals. The mapping is data-driven:
//     it simply sums the `signals` declared on each chosen option.
//   - Fully deterministic and side-effect free, so it is trivial to unit test.

// TODO (before the formal Decision Profile engine is built): THIS LOGIC MUST
// MOVE SERVER-SIDE.
//
// What ships to the browser today is the placeholder above: every option's
// affinity weight, the tally, the tie-break and the fallback. An audit
// confirmed all 38 options carry weights identical to OPTION_SIGNALS in
// backend/app/decision_profile.py, so the server-side copy currently protects
// nothing. That is acceptable only because this mapping is a stand-in and not
// the real framework.
//
// It stops being acceptable the moment the formal interpretation engine
// replaces deriveProvisionalStyle. Dropping that engine into this file would
// publish the actual Decision Profile methodology in a public bundle, where it
// is readable and reproducible by anyone.
//
// The client's job at that point is to SUBMIT ANSWERS AND RENDER THE RETURNED
// PROFILE. It should hold no weights, no thresholds, no classification rules.
// Move the call to the backend before the real engine is written, not after,
// so the sensitive version is never the one that has to be retrofitted.

import { QUESTIONS, STYLES, STYLE_ORDER } from './assessmentData';

// Neutral, balanced default when we cannot infer anything (e.g. every answer
// was "Not applicable"). Chosen because it makes the fewest assumptions about
// the user rather than because it is "best".
const FALLBACK_STYLE_KEY = 'practical_optimizer';

// Build a quick lookup of optionId -> signals from the question content so the
// mapping stays in sync with assessmentData automatically.
function buildSignalIndex() {
  const index = {};
  for (const question of QUESTIONS) {
    for (const option of question.options) {
      index[option.id] = option.signals || {};
    }
  }
  return index;
}

const SIGNAL_INDEX = buildSignalIndex();

/**
 * Tally provisional style affinity from the user's answers.
 * @param {Object<string,string>} answers map of questionId -> selected optionId
 * @returns {Object<string,number>} styleKey -> affinity total (internal only)
 */
export function tallyAffinity(answers) {
  const totals = {};
  for (const styleKey of STYLE_ORDER) totals[styleKey] = 0;

  for (const optionId of Object.values(answers || {})) {
    const signals = SIGNAL_INDEX[optionId];
    if (!signals) continue; // unknown / "Not applicable" contribute nothing
    for (const [styleKey, weight] of Object.entries(signals)) {
      if (styleKey in totals) totals[styleKey] += weight;
    }
  }
  return totals;
}

/**
 * Pick the provisional primary style from a set of answers.
 * @param {Object<string,string>} answers map of questionId -> selected optionId
 * @returns {{ style: object, isFallback: boolean }}
 */
export function deriveProvisionalStyle(answers) {
  const totals = tallyAffinity(answers);

  let bestKey = null;
  let bestScore = -1;
  // STYLE_ORDER gives a stable, intentional tie-break (first listed wins ties).
  for (const styleKey of STYLE_ORDER) {
    if (totals[styleKey] > bestScore) {
      bestScore = totals[styleKey];
      bestKey = styleKey;
    }
  }

  if (bestKey === null || bestScore <= 0) {
    return { style: STYLES[FALLBACK_STYLE_KEY], isFallback: true };
  }
  return { style: STYLES[bestKey], isFallback: false };
}
