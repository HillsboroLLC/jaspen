import React from 'react';
import { render, screen } from '@testing-library/react';
import GuidedDecisionButton from './GuidedDecisionButton';

test('Guided Decision keeps its label and shows a solid lightbulb icon', () => {
  render(<GuidedDecisionButton onClick={jest.fn()} />);
  const button = screen.getByRole('button', { name: 'Open Guided Decision' });
  expect(button).toHaveClass('gd-nav-icon');
  const svg = button.querySelector('svg');
  expect(svg).toHaveAttribute('fill', 'currentColor');
  expect(button.innerHTML).not.toMatch(/Gradient/);
  expect(svg.querySelectorAll('rect')).toHaveLength(2);
});
