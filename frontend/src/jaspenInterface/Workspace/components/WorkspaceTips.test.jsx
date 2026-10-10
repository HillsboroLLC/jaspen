import { fireEvent, render, screen } from '@testing-library/react';
import WorkspaceTips from './WorkspaceTips';

const tips = [
  { id: 'one', title: 'First tip', body: 'First detail' },
  { id: 'two', title: 'Second tip', body: 'Second detail' },
  { id: 'three', title: 'Third tip', body: 'Third detail' },
];

beforeEach(() => {
  localStorage.clear();
});

test('shows one tip at a time and steps through them only when asked', () => {
  render(<WorkspaceTips tips={tips} />);

  expect(screen.getByText('First tip')).toBeInTheDocument();
  expect(screen.queryByText('Second tip')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Previous tip' })).toBeDisabled();

  fireEvent.click(screen.getByRole('button', { name: 'Next tip' }));
  expect(screen.getByText('Second tip')).toBeInTheDocument();
  expect(screen.getByText('Tip 2 of 3')).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: 'Show tip 3' }));
  expect(screen.getByText('Third tip')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Next tip' })).toBeDisabled();

  fireEvent.click(screen.getByRole('button', { name: 'Previous tip' }));
  expect(screen.getByText('Second tip')).toBeInTheDocument();
  // Stepping never dismisses the carousel.
  expect(localStorage.getItem('jaspen_tips_dismissed')).toBeNull();
});

test.each([0, 1, 2])('the close button dismisses the whole carousel from tip %i', (steps) => {
  render(<WorkspaceTips tips={tips} />);
  for (let i = 0; i < steps; i += 1) {
    fireEvent.click(screen.getByRole('button', { name: 'Next tip' }));
  }

  fireEvent.click(screen.getByRole('button', { name: 'Close tips' }));

  expect(screen.queryByRole('complementary', { name: 'Workspace tips' })).not.toBeInTheDocument();
  expect(localStorage.getItem('jaspen_tips_dismissed')).toBe('true');
  expect(localStorage.getItem('jaspen_tip_idx')).toBe(String(tips.length));
});

test('keeps a previously closed carousel dismissed', () => {
  localStorage.setItem('jaspen_tips_dismissed', 'true');

  render(<WorkspaceTips tips={tips} />);

  expect(screen.queryByRole('complementary', { name: 'Workspace tips' })).not.toBeInTheDocument();
});
