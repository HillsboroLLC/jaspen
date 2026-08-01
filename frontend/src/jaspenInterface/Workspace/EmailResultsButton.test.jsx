import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import EmailResultsButton from './EmailResultsButton';
import { Jaspen } from './JaspenClient';

jest.mock('./JaspenClient', () => ({
  Jaspen: {
    getEmailAssetRecipient: jest.fn(),
    requestEmailAssets: jest.fn(),
    getEmailAssetStatus: jest.fn(),
  },
}));

describe('EmailResultsButton', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    Jaspen.getEmailAssetRecipient.mockResolvedValue({ recipient_masked: 't**t@example.com' });
    Jaspen.requestEmailAssets.mockResolvedValue({
      delivery_id: 'delivery-1',
      status: 'sent',
      recipient_masked: 't**t@example.com',
    });
  });

  test('confirms the masked account email and reports a successful send', async () => {
    const user = userEvent.setup();
    render(
      <EmailResultsButton
        threadId="thread-1"
        scorecardId="scorecard-1"
        outputTypes={['scorecards', 'why_this_order']}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Email this to me' }));
    expect(await screen.findByText(/Send these results to/)).toBeInTheDocument();
    expect(screen.getByText('t**t@example.com')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Send results' }));
    expect(await screen.findByText(/Sent to/)).toBeInTheDocument();
    expect(Jaspen.requestEmailAssets).toHaveBeenCalledWith('thread-1', expect.objectContaining({
      scorecardId: 'scorecard-1',
      outputTypes: ['scorecards', 'why_this_order'],
      idempotencyKey: expect.any(String),
    }));
  });

  test('keeps a stable idempotency key for a safe retry', async () => {
    const user = userEvent.setup();
    Jaspen.requestEmailAssets
      .mockRejectedValueOnce(new Error('Temporary provider failure'))
      .mockResolvedValueOnce({
        delivery_id: 'delivery-1',
        status: 'sent',
        recipient_masked: 't**t@example.com',
      });
    render(<EmailResultsButton threadId="thread-1" outputTypes={['tradeoff']} />);
    await user.click(screen.getByRole('button', { name: 'Email this to me' }));
    await user.click(await screen.findByRole('button', { name: 'Send results' }));
    expect(await screen.findByText('Temporary provider failure')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Retry safely' }));
    await waitFor(() => expect(Jaspen.requestEmailAssets).toHaveBeenCalledTimes(2));
    const firstKey = Jaspen.requestEmailAssets.mock.calls[0][1].idempotencyKey;
    const secondKey = Jaspen.requestEmailAssets.mock.calls[1][1].idempotencyKey;
    expect(secondKey).toBe(firstKey);
  });
});
