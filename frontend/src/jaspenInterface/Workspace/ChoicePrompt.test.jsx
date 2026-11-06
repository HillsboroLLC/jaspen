import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ChoicePrompt, { parseChoicePrompt } from './ChoicePrompt';

const multi = {
  question: 'Which bids are you pursuing?',
  allow_text: true,
  allow_multi: true,
  options: [
    { label: 'Adams County' },
    { label: 'Boulder Transit' },
    { label: 'Cherry Creek' },
    { label: 'Denver Water' },
    { label: 'Englewood Depot' },
    { label: 'None of them', exclusive: true },
    { label: 'Still evaluating', exclusive: true },
  ],
};

it('parses exclusive options and keeps more than four options', () => {
  const raw = `Where did you land?\n[[choice]]\n${JSON.stringify(multi)}\n[[/choice]]`;
  const { text, choice } = parseChoicePrompt(raw);
  expect(text).toBe('Where did you land?');
  expect(choice.options).toHaveLength(7);
  expect(choice.options.filter((o) => o.exclusive).map((o) => o.label)).toEqual(['None of them', 'Still evaluating']);
  expect(choice.options[0].exclusive).toBe(false);
});

it('an exclusive answer clears the others, and any other answer clears it', () => {
  const onChoose = jest.fn();
  render(<ChoicePrompt choice={multi} onChoose={onChoose} />);
  const adams = screen.getByRole('button', { name: 'Adams County' });
  const cherry = screen.getByRole('button', { name: 'Cherry Creek' });
  const none = screen.getByRole('button', { name: 'None of them' });

  fireEvent.click(cherry);
  fireEvent.click(adams);
  expect(adams).toHaveAttribute('aria-pressed', 'true');
  expect(cherry).toHaveAttribute('aria-pressed', 'true');

  fireEvent.click(none);
  expect(none).toHaveAttribute('aria-pressed', 'true');
  expect(adams).toHaveAttribute('aria-pressed', 'false');
  expect(cherry).toHaveAttribute('aria-pressed', 'false');

  fireEvent.click(adams);
  expect(none).toHaveAttribute('aria-pressed', 'false');
  fireEvent.click(cherry);
  fireEvent.click(screen.getByRole('button', { name: 'Send 2 selected' }));
  // Sent in the order the agent listed them, joined exactly as offered.
  expect(onChoose).toHaveBeenCalledWith('Adams County, Cherry Creek');
});

it('options are real keyboard-focusable buttons in a labelled group', () => {
  render(<ChoicePrompt choice={multi} onChoose={jest.fn()} />);
  expect(screen.getByRole('group', { name: 'Which bids are you pursuing?' })).toBeInTheDocument();
  const button = screen.getByRole('button', { name: 'Denver Water' });
  act(() => { button.focus(); });
  expect(button).toHaveFocus();
  expect(button.style.outline).toContain('2px solid');
});

it('Enter and Space toggle options from the keyboard', async () => {
  const user = userEvent.setup();
  render(<ChoicePrompt choice={multi} onChoose={jest.fn()} />);
  const adams = screen.getByRole('button', { name: 'Adams County' });
  const none = screen.getByRole('button', { name: 'None of them' });
  await user.tab();
  expect(adams).toHaveFocus();
  await user.keyboard('{Enter}');
  expect(adams).toHaveAttribute('aria-pressed', 'true');
  act(() => { none.focus(); });
  await user.keyboard(' ');
  expect(none).toHaveAttribute('aria-pressed', 'true');
  expect(adams).toHaveAttribute('aria-pressed', 'false');
});

it('single select still sends the clicked label immediately', () => {
  const onChoose = jest.fn();
  render(<ChoicePrompt choice={{ question: 'Horizon?', options: [{ label: '1 year' }, { label: '3 years' }], allow_text: false, allow_multi: false }} onChoose={onChoose} />);
  const option = screen.getByRole('button', { name: '3 years' });
  expect(option).not.toHaveAttribute('aria-pressed');
  fireEvent.click(option);
  expect(onChoose).toHaveBeenCalledWith('3 years');
});
