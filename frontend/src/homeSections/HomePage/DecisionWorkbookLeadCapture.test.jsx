import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import DecisionWorkbookLeadCapture from './DecisionWorkbookLeadCapture';

// In the test env REACT_APP_LEADS_MOCK is unset, so submitLead() hits fetch,
// which we spy on. We also stub anchor.click so the jsdom "navigation not
// implemented" download attempt is captured instead of firing.
let clickSpy;
beforeEach(() => {
  clickSpy = jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
});
afterEach(() => {
  jest.restoreAllMocks();
});

describe('DecisionWorkbookLeadCapture', () => {
  it('renders the distinct workbook framing and CTA', () => {
    render(<DecisionWorkbookLeadCapture />);
    expect(
      screen.getByRole('heading', { name: /have an important decision to make/i })
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /email me the decision workbook/i })
    ).toBeInTheDocument();
  });

  it('submits with the decision-workbook source and starts the download', async () => {
    const user = userEvent.setup();
    const fetchSpy = jest
      .spyOn(global, 'fetch')
      .mockResolvedValue({ ok: true, status: 201, json: async () => ({ ok: true }) });

    render(<DecisionWorkbookLeadCapture />);
    await user.type(screen.getByLabelText(/your email/i), 'lydia@jaspen.ai');
    await user.click(screen.getByRole('button', { name: /email me the decision workbook/i }));

    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1));
    const body = JSON.parse(fetchSpy.mock.calls[0][1].body);
    expect(body).toEqual({ email: 'lydia@jaspen.ai', source: 'decision-workbook' });

    // Download happened and the success state shows.
    expect(clickSpy).toHaveBeenCalled();
    expect(await screen.findByText(/your workbook is downloading/i)).toBeInTheDocument();
  });

  it('still downloads the workbook even if lead capture fails', async () => {
    const user = userEvent.setup();
    jest.spyOn(global, 'fetch').mockRejectedValue(new Error('network down'));

    render(<DecisionWorkbookLeadCapture />);
    await user.type(screen.getByLabelText(/your email/i), 'lydia@jaspen.ai');
    await user.click(screen.getByRole('button', { name: /email me the decision workbook/i }));

    await waitFor(() => expect(clickSpy).toHaveBeenCalled());
    expect(await screen.findByText(/your workbook is downloading/i)).toBeInTheDocument();
  });

  it('rejects an invalid email without submitting or downloading', async () => {
    const user = userEvent.setup();
    const fetchSpy = jest.spyOn(global, 'fetch');

    render(<DecisionWorkbookLeadCapture />);
    await user.type(screen.getByLabelText(/your email/i), 'nope');
    await user.click(screen.getByRole('button', { name: /email me the decision workbook/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/valid email/i);
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(clickSpy).not.toHaveBeenCalled();
  });
});
