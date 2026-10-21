import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import StarterPlanNote from './StarterPlanNote';

it('labels a starter plan and offers refinement', () => {
  const onRefine = jest.fn();
  render(<StarterPlanNote
    plan={{ generation_status: 'starter_plan', starter_plan_note: 'Starter plan built from your decision; ask Jaspen to refine it.' }}
    onRefine={onRefine}
  />);
  expect(screen.getByRole('status')).toHaveTextContent('Starter plan built from your decision; ask Jaspen to refine it.');
  fireEvent.click(screen.getByRole('button', { name: 'Ask Jaspen to refine' }));
  expect(onRefine).toHaveBeenCalled();
});

it('shows nothing for an AI plan', () => {
  const { container } = render(<StarterPlanNote plan={{ generation_status: 'ai_generated' }} />);
  expect(container).toBeEmptyDOMElement();
});
