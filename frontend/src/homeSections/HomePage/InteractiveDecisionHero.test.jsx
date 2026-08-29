import React from 'react';
import { TextDecoder } from 'util';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import InteractiveDecisionHero from './InteractiveDecisionHero';

jest.mock('./StarterDecisionChips', () => function StarterDecisionChipsMock() { return null; });

global.TextDecoder = TextDecoder;

function sseResponse(events) {
  const chunks = events.map((event) => Buffer.from(`data: ${JSON.stringify(event)}\n\n`));
  let index = 0;
  return {
    ok: true,
    body: {
      getReader: () => ({
        read: async () => index < chunks.length
          ? { done: false, value: chunks[index++] }
          : { done: true, value: undefined },
      }),
    },
  };
}

describe('InteractiveDecisionHero anonymous handoff gate', () => {
  beforeEach(() => {
    window.localStorage.clear();
    global.fetch = jest.fn().mockResolvedValueOnce(sseResponse([
      {
        type: 'done',
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
          response_mode: 'handoff',
      },
    ]));
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('locks anonymous chat and requires workspace handoff at the turn ceiling', async () => {
    const openModal = jest.fn();
    render(<InteractiveDecisionHero onOpenModal={openModal} />);

    fireEvent.change(screen.getByLabelText('What are you weighing?'), {
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
    global.fetch = jest.fn().mockResolvedValueOnce(sseResponse([
      { type: 'delta', text: 'You have established a solid foundation.' },
      {
          type: 'done',
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
          response_mode: 'ai',
      },
    ]));

    render(<InteractiveDecisionHero />);
    fireEvent.change(screen.getByLabelText('What are you weighing?'), {
      target: { value: 'A well-defined decision with evidence.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Send to Jaspen' }));

    await waitFor(() => expect(screen.getByRole('button', { name: /Create my workspace/i })).toBeInTheDocument());
    expect(screen.getByRole('textbox')).toBeDisabled();
    expect(screen.getByText(/begin building your scorecard/i)).toBeInTheDocument();
  });

  it('shows a retry error instead of a deterministic reply when AI is unavailable', async () => {
    global.fetch = jest.fn().mockResolvedValueOnce(sseResponse([
      { type: 'unavailable', message: 'Jaspen is temporarily unavailable. Please try again.' },
      {
        type: 'done', ready: false, band: 'starting', overall_percent: 10,
        known: [], missing: [], next_question: 'A stale deterministic question',
        user_turns: 1, turn_limit: 6, turn_limit_reached: false,
        response_mode: 'unavailable',
      },
    ]));

    render(<InteractiveDecisionHero />);
    const input = screen.getByLabelText('What are you weighing?');
    fireEvent.change(input, { target: { value: 'Help me decide.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send to Jaspen' }));

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/temporarily unavailable/i));
    expect(screen.queryByText('A stale deterministic question')).not.toBeInTheDocument();
    expect(screen.getByRole('textbox')).toHaveValue('Help me decide.');
  });
});
