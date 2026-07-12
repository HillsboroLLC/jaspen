import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import DecisionPlanningToolkitLeadCapture from './DecisionPlanningToolkitLeadCapture';

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

  it('submits with the decision-planning-toolkit source and starts the download', async () => {
    const user = userEvent.setup();
    const fetchSpy = jest
      .spyOn(global, 'fetch')
      .mockResolvedValue({ ok: true, status: 201, json: async () => ({ ok: true }) });

    render(<DecisionPlanningToolkitLeadCapture />);
    await user.type(screen.getByLabelText(/where should we send it/i), 'lydia@jaspen.ai');
    await user.click(screen.getByRole('button', { name: /email me the toolkit/i }));

    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1));
    const body = JSON.parse(fetchSpy.mock.calls[0][1].body);
    expect(body).toEqual({ email: 'lydia@jaspen.ai', source: 'decision-planning-toolkit' });

    // Download happened and the success state shows.
    expect(clickSpy).toHaveBeenCalled();
    expect(await screen.findByText(/your toolkit is downloading/i)).toBeInTheDocument();
  });

  it('still downloads the toolkit even if lead capture fails', async () => {
    const user = userEvent.setup();
    jest.spyOn(global, 'fetch').mockRejectedValue(new Error('network down'));

    render(<DecisionPlanningToolkitLeadCapture />);
    await user.type(screen.getByLabelText(/where should we send it/i), 'lydia@jaspen.ai');
    await user.click(screen.getByRole('button', { name: /email me the toolkit/i }));

    await waitFor(() => expect(clickSpy).toHaveBeenCalled());
    expect(await screen.findByText(/your toolkit is downloading/i)).toBeInTheDocument();
  });

  it('rejects an invalid email without submitting or downloading', async () => {
    const user = userEvent.setup();
    const fetchSpy = jest.spyOn(global, 'fetch');

    render(<DecisionPlanningToolkitLeadCapture />);
    await user.type(screen.getByLabelText(/where should we send it/i), 'nope');
    await user.click(screen.getByRole('button', { name: /email me the toolkit/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/valid email/i);
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(clickSpy).not.toHaveBeenCalled();
  });
});
