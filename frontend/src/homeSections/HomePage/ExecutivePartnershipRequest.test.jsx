import React from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ExecutivePartnershipRequest from './ExecutivePartnershipRequest';

function ok(body = { ok: true, acknowledged: true }) {
  return Promise.resolve({ ok: true, json: () => Promise.resolve(body) });
}

async function fillRequired(user) {
  await user.type(screen.getByRole('textbox', { name: /full name/i }), 'Dana Reyes');
  await user.type(screen.getByRole('textbox', { name: /company/i }), 'Acme Industrial');
  await user.type(screen.getByRole('textbox', { name: /job title/i }), 'CFO');
  await user.type(screen.getByRole('textbox', { name: /work email/i }), 'cfo@acme.co');
  await user.type(screen.getByRole('textbox', { name: /briefly describe the decision/i }), 'Consolidate two plants or automate both.');
  await user.type(screen.getByRole('textbox', { name: /what outcome/i }), 'Decide where to allocate capital.');
  await user.click(screen.getByRole('radio', { name: '1–3 months' }));
  await user.click(screen.getByRole('checkbox', { name: 'CFO' }));
  await user.click(screen.getByRole('radio', { name: 'I share the decision' }));
}

describe('Executive Partnership Request', () => {
  beforeEach(() => {
    global.fetch = jest.fn(() => ok());
  });

  it('pre-selects the engagement it was opened with', () => {
    render(<ExecutivePartnershipRequest initialEngagement="strategic_advisor_partnership" onClose={jest.fn()} />);

    expect(screen.getByRole('radio', { name: /Strategic Advisor Partnership \(\$100,000\)/ })).toBeChecked();
    expect(screen.getByRole('radio', { name: /Executive Decision Intensive/ })).not.toBeChecked();
  });

  it('lets the requester say they are not sure yet', async () => {
    const user = userEvent.setup();
    render(<ExecutivePartnershipRequest initialEngagement="executive_decision_intensive" onClose={jest.fn()} />);

    await user.click(screen.getByRole('radio', { name: /not sure yet/i }));
    expect(screen.getByRole('radio', { name: /not sure yet/i })).toBeChecked();
  });

  it('submits every answer to the advisory endpoint', async () => {
    const user = userEvent.setup();
    render(<ExecutivePartnershipRequest initialEngagement="executive_decision_intensive" onClose={jest.fn()} />);

    await fillRequired(user);
    await user.click(screen.getByRole('radio', { name: '$5M–$25M' }));
    await user.click(screen.getByRole('checkbox', { name: 'CEO' }));
    await user.click(screen.getByRole('button', { name: /request consultation/i }));

    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    const [url, options] = global.fetch.mock.calls[0];
    expect(url).toContain('/api/v1/public/leads/advisory-inquiry');

    const sent = JSON.parse(options.body);
    expect(sent).toMatchObject({
      source: 'advisory-partnerships',
      first_name: 'Dana',
      last_name: 'Reyes',
      email: 'cfo@acme.co',
      company: 'Acme Industrial',
      title: 'CFO',
      engagement: 'executive_decision_intensive',
      decision_timeline: '1_3_months',
      financial_impact_band: '5m_25m',
      decision_authority: 'shared',
    });
    expect(sent.participants).toEqual(expect.arrayContaining(['cfo', 'ceo']));
  });

  it('confirms receipt without implying the engagement is accepted', async () => {
    const user = userEvent.setup();
    render(<ExecutivePartnershipRequest initialEngagement="undecided" onClose={jest.fn()} />);

    await fillRequired(user);
    await user.click(screen.getByRole('button', { name: /request consultation/i }));

    const confirmation = await screen.findByRole('status');
    expect(confirmation).toHaveTextContent(/your request has been received/i);
    expect(confirmation).toHaveTextContent(/thank you for your interest in jaspen executive partnerships/i);
    expect(confirmation).toHaveTextContent(/we review every request personally/i);
    // Conditional, and no promised response time.
    expect(confirmation).toHaveTextContent(/if your request aligns with our current capacity and expertise/i);
    expect(confirmation).not.toHaveTextContent(/business days/i);
    expect(confirmation).toHaveTextContent(/cfo@acme\.co/);
  });

  it('says the request still stands when the confirmation email could not be sent', async () => {
    const user = userEvent.setup();
    global.fetch = jest.fn(() => ok({ ok: true, acknowledged: false }));
    render(<ExecutivePartnershipRequest initialEngagement="undecided" onClose={jest.fn()} />);

    await fillRequired(user);
    await user.click(screen.getByRole('button', { name: /request consultation/i }));

    const confirmation = await screen.findByRole('status');
    expect(confirmation).toHaveTextContent(/we have your request/i);
  });

  it('surfaces a server rejection instead of silently failing', async () => {
    const user = userEvent.setup();
    global.fetch = jest.fn(() => Promise.resolve({
      ok: false,
      json: () => Promise.resolve({ error: 'Please use your work email address.' }),
    }));
    render(<ExecutivePartnershipRequest initialEngagement="undecided" onClose={jest.fn()} />);

    await fillRequired(user);
    await user.click(screen.getByRole('button', { name: /request consultation/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/work email address/i);
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('requires at least one participant', async () => {
    const user = userEvent.setup();
    render(<ExecutivePartnershipRequest initialEngagement="undecided" onClose={jest.fn()} />);

    await user.type(screen.getByRole('textbox', { name: /full name/i }), 'Dana Reyes');
    await user.type(screen.getByRole('textbox', { name: /company/i }), 'Acme');
    await user.type(screen.getByRole('textbox', { name: /job title/i }), 'CFO');
    await user.type(screen.getByRole('textbox', { name: /work email/i }), 'cfo@acme.co');
    await user.type(screen.getByRole('textbox', { name: /briefly describe the decision/i }), 'A decision.');
    await user.type(screen.getByRole('textbox', { name: /what outcome/i }), 'An outcome.');
    await user.click(screen.getByRole('radio', { name: '1–3 months' }));
    await user.click(screen.getByRole('radio', { name: 'I share the decision' }));

    await user.click(screen.getByRole('button', { name: /request consultation/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/at least one participant/i);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('closes on Escape and restores focus to the opener', async () => {
    const user = userEvent.setup();
    const onClose = jest.fn();
    const opener = document.createElement('button');
    document.body.appendChild(opener);
    opener.focus();

    render(<ExecutivePartnershipRequest initialEngagement="undecided" onClose={onClose} />);
    await user.keyboard('{Escape}');

    expect(onClose).toHaveBeenCalled();
    expect(document.activeElement).toBe(opener);
    opener.remove();
  });

  it('traps Tab inside the dialog', async () => {
    const user = userEvent.setup();
    render(<ExecutivePartnershipRequest initialEngagement="undecided" onClose={jest.fn()} />);

    const dialog = screen.getByRole('dialog');
    const focusable = dialog.querySelectorAll('a[href], button:not([disabled]), input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])');
    focusable[focusable.length - 1].focus();

    await user.tab();
    expect(dialog.contains(document.activeElement)).toBe(true);
  });

  it('carries the honeypot field for bots to fall into', () => {
    render(<ExecutivePartnershipRequest initialEngagement="undecided" onClose={jest.fn()} />);

    const honeypot = document.querySelector('.epr-honeypot input');
    expect(honeypot).toBeInTheDocument();
    expect(honeypot).toHaveAttribute('tabindex', '-1');
  });

  it('caps the free-text fields so a long answer cannot be rejected as too large', () => {
    render(<ExecutivePartnershipRequest initialEngagement="undecided" onClose={jest.fn()} />);

    expect(screen.getByRole('textbox', { name: /briefly describe the decision/i })).toHaveAttribute('maxlength', '2000');
    expect(screen.getByRole('textbox', { name: /what outcome/i })).toHaveAttribute('maxlength', '1000');
    expect(screen.getByRole('textbox', { name: /anything else/i })).toHaveAttribute('maxlength', '2000');
  });
});
