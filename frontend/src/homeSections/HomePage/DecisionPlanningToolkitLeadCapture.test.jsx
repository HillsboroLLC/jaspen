import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import DecisionPlanningToolkitLeadCapture from './DecisionPlanningToolkitLeadCapture';

afterEach(() => {
  jest.restoreAllMocks();
});

describe('DecisionPlanningToolkitLeadCapture', () => {
  it('renders the distinct toolkit framing and CTA', () => {
    render(<DecisionPlanningToolkitLeadCapture />);
    expect(
      screen.getByRole('heading', { name: /have an important decision to work through/i })
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /email me the toolkit/i })
    ).toBeInTheDocument();
  });

  it('submits with the decision-planning-toolkit source and shows email delivery success', async () => {
    const user = userEvent.setup();
    const fetchSpy = jest
      .spyOn(global, 'fetch')
      .mockResolvedValue({ ok: true, status: 201, json: async () => ({ ok: true }) });

    render(<DecisionPlanningToolkitLeadCapture />);
    await user.type(screen.getByLabelText(/where should we send it/i), 'lydia@jaspen.ai');
    await user.click(screen.getByLabelText(/decision notes and occasional jaspen updates/i));
    await user.click(screen.getByRole('button', { name: /email me the toolkit/i }));

    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1));
    const body = JSON.parse(fetchSpy.mock.calls[0][1].body);
    expect(body).toEqual({
      email: 'lydia@jaspen.ai',
      source: 'decision-planning-toolkit',
      marketing_opt_in: true,
    });

    expect(await screen.findByText(/your toolkit is on its way/i)).toBeInTheDocument();
  });

  it('shows a retryable failure and preserves the email if delivery fails', async () => {
    const user = userEvent.setup();
    jest.spyOn(global, 'fetch').mockRejectedValue(new Error('network down'));

    render(<DecisionPlanningToolkitLeadCapture />);
    const emailInput = screen.getByLabelText(/where should we send it/i);
    await user.type(emailInput, 'lydia@jaspen.ai');
    await user.click(screen.getByRole('button', { name: /email me the toolkit/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/could not email the toolkit/i);
    expect(emailInput).toHaveValue('lydia@jaspen.ai');
  });

  it('rejects an invalid email without submitting or downloading', async () => {
    const user = userEvent.setup();
    const fetchSpy = jest.spyOn(global, 'fetch');

    render(<DecisionPlanningToolkitLeadCapture />);
    await user.type(screen.getByLabelText(/where should we send it/i), 'nope');
    await user.click(screen.getByRole('button', { name: /email me the toolkit/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/valid email/i);
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
