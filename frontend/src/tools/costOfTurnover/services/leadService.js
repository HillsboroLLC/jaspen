// Lead attribution for the Cost of Turnover utility. Thin wrapper over the
// shared lead client so this utility's activity flows into the same
// /api/v1/public/leads pipeline (and the same contact record) as the other
// lead magnets, tagged with a unique source.

import { submitLead } from '../../../shared/lead/leadClient';
import { UTILITY_SOURCE } from './analytics';

/**
 * Email the estimate report / register the lead.
 * @param {{ email:string, marketingOptIn?:boolean, estimateSummary?:object }} args
 */
export async function submitUtilityLead({ email, marketingOptIn = false, estimateSummary }) {
  return submitLead({
    email,
    source: UTILITY_SOURCE,
    marketingOptIn,
    // Reuses the existing assessment_answers channel to carry a compact,
    // non-confidential estimate summary for attribution.
    assessmentAnswers: estimateSummary,
  });
}

export { UTILITY_SOURCE };
