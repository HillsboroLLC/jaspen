import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import ScoreReuseNotice from './ScoreReuseNotice';

test('reused scorecard identifies provenance, free reuse, and offers fresh scoring', () => {
  const onSendText = jest.fn();
  render(<ScoreReuseNotice
    provenance={{
      source_user_name: 'Avery',
      source_created_at: '2026-10-16T12:00:00Z',
      root_scorecard_id: 'original-card',
    }}
    onScoreFresh={() => onSendText('Score this option fresh now. Do not reuse a stored judgment.')}
  />);

  expect(screen.getByText(/Reused Avery’s judgment/)).toBeInTheDocument();
  expect(screen.getByText(/No Thinking Power was charged/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Score fresh' }));
  expect(onSendText).toHaveBeenCalledWith(
    'Score this option fresh now. Do not reuse a stored judgment.'
  );
});
