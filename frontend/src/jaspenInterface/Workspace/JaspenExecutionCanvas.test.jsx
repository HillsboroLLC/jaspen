import React from 'react';
import { render, screen } from '@testing-library/react';
import { TaskRow } from './JaspenExecutionCanvas';

it('keeps the task title readable when the execution sidebar narrows the list', () => {
  render(<TaskRow
    task={{ id: 'task-1', title: 'Prepare and finalize the complete submission package', status: 'todo' }}
    phaseName="Submission"
  />);
  const row = screen.getByText('Prepare and finalize the complete submission package').closest('[draggable="true"]');
  expect(row).toHaveStyle({ minWidth: '980px' });
  expect(row.style.gridTemplateColumns).toContain('minmax(300px, 1fr)');
});
