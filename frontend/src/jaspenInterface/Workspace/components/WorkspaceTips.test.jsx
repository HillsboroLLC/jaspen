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

test('renders every tip in one scrollable surface', () => {
  render(<WorkspaceTips tips={tips} />);

  expect(screen.getByRole('complementary', { name: 'Workspace tips' })).toBeInTheDocument();
  expect(screen.getByText('First tip')).toBeInTheDocument();
  expect(screen.getByText('Second tip')).toBeInTheDocument();
  expect(screen.getByText('Third tip')).toBeInTheDocument();
  expect(screen.getByLabelText('All workspace tips')).toHaveClass('jas-floattip-list');
});

test('the close button dismisses the entire tips surface from any point', () => {
  render(<WorkspaceTips tips={tips} />);

  fireEvent.click(screen.getByRole('button', { name: 'Close tips' }));

  expect(screen.queryByRole('complementary', { name: 'Workspace tips' })).not.toBeInTheDocument();
  expect(screen.queryByText('Second tip')).not.toBeInTheDocument();
  expect(localStorage.getItem('jaspen_tips_dismissed')).toBe('true');
  expect(localStorage.getItem('jaspen_tip_idx')).toBe(String(tips.length));
});

test('keeps a previously closed tips surface dismissed', () => {
  localStorage.setItem('jaspen_tips_dismissed', 'true');

  render(<WorkspaceTips tips={tips} />);

  expect(screen.queryByRole('complementary', { name: 'Workspace tips' })).not.toBeInTheDocument();
});
