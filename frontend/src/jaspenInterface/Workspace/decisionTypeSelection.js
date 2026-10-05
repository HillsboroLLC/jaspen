export const RFP_DECISION_INTENT = 'rfp';

export function isRfpDecision(decisionKit) {
  return decisionKit === RFP_DECISION_INTENT || String(decisionKit || '').startsWith('rfp_');
}

export function decisionKitForConversationStart(decisionKit) {
  return isRfpDecision(decisionKit) ? RFP_DECISION_INTENT : null;
}
