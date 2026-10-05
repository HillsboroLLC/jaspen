import { decisionKitForConversationStart, isRfpDecision, RFP_DECISION_INTENT } from './decisionTypeSelection';

test('the single RFP selection preserves an RFP intent for new-thread creation', () => {
  expect(decisionKitForConversationStart(RFP_DECISION_INTENT)).toBe('rfp');
  expect(isRfpDecision('rfp_bid')).toBe(true);
  expect(isRfpDecision('rfp_vendor_selection')).toBe(true);
});

test('general selection remains general', () => {
  expect(decisionKitForConversationStart(null)).toBeNull();
  expect(isRfpDecision(null)).toBe(false);
});
