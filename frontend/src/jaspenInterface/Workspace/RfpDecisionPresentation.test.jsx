import React from 'react';
import { render, screen } from '@testing-library/react';
import { deriveStatus } from './TradeoffView';
import RfpRecommendationTrace from './RfpRecommendationTrace';


test('RFP trade-off status uses the deterministic verdict label', () => {
  expect(deriveStatus(72, {
    decision_kit: 'rfp_bid',
    recommendation: { label: 'Bid with conditions' },
  })).toBe('Bid with conditions');
  expect(deriveStatus(72, {})).toBe('HOLD');
});


test('RFP scorecard artifact shows recommendation and trace', () => {
  render(
    <RfpRecommendationTrace
      decisionKitVersion={1}
      recommendation={{
      label: 'Bid with conditions',
      kit_version: 1,
      trace: [
        { step: 'score', value: 62, effect: 'advance range' },
        { step: 'confidence', value: 58, effect: 'conditions required' },
      ],
      }}
    />
  );

  expect(screen.getByText('Jaspen recommendation')).toBeInTheDocument();
  expect(screen.getByText('Bid with conditions')).toBeInTheDocument();
  expect(screen.getByText(/score: 62/)).toBeInTheDocument();
  expect(screen.getByText(/kit v1/)).toBeInTheDocument();
});
