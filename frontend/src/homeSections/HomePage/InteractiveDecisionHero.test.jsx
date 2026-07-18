import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import InteractiveDecisionHero from './InteractiveDecisionHero';

jest.mock('./StarterDecisionChips', () => function StarterDecisionChipsMock() { return null; });

describe('InteractiveDecisionHero anonymous handoff gate', () => {
  beforeEach(() => {
    window.localStorage.clear();
    global.fetch = jest.fn()
      .mockResolvedValueOnce({ ok: false, body: null })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ready: false,
          band: 'building',
          overall_percent: 45,
          known: [],
          missing: [{ key: 'goal_definition', label: 'Goal', required: true }],
          next_question: 'What outcome matters most?',
          characters_remaining: 2000,
          user_turns: 6,
          turn_limit: 6,
          turn_limit_reached: true,
        }),
      });
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('locks anonymous chat and requires workspace handoff at the turn ceiling', async () => {
    const openModal = jest.fn();
    render(<InteractiveDecisionHero onOpenModal={openModal} />);

    fireEvent.change(screen.getByLabelText('What decision are you working through?'), {
      target: { value: 'I need help making a decision.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Send to Jaspen' }));

    await waitFor(() => expect(screen.getByRole('button', { name: /Create my workspace/i })).toBeInTheDocument());
    expect(screen.getByRole('textbox')).toBeDisabled();
    expect(screen.getAllByText(/continue the intake inside your workspace/i)).toHaveLength(2);

    fireEvent.click(screen.getByRole('button', { name: /Create my workspace/i }));
    expect(openModal).toHaveBeenCalledWith('signup');
  });

  it('also locks anonymous chat as soon as the decision is ready', async () => {
    global.fetch = jest.fn()
      .mockResolvedValueOnce({ ok: false, body: null })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ready: true,
          band: 'ready',
          overall_percent: 85,
          known: [],
          missing: [],
          next_question: null,
          characters_remaining: 2000,
          user_turns: 2,
          turn_limit: 6,
          turn_limit_reached: false,
        }),
      });

    render(<InteractiveDecisionHero />);
    fireEvent.change(screen.getByLabelText('What decision are you working through?'), {
      target: { value: 'A well-defined decision with evidence.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Send to Jaspen' }));

    await waitFor(() => expect(screen.getByRole('button', { name: /Create my workspace/i })).toBeInTheDocument());
    expect(screen.getByRole('textbox')).toBeDisabled();
    expect(screen.getByText(/begin building your scorecard/i)).toBeInTheDocument();
  });
});
