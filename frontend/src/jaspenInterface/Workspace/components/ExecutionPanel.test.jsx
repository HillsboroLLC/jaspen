import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import ExecutionPanel from './ExecutionPanel';
import { Jaspen } from '../JaspenClient';

afterEach(() => {
  jest.restoreAllMocks();
});

it('uses an empty ISO date input for a legacy invalid task date', async () => {
  jest.spyOn(Jaspen, 'getThreadPmSync').mockResolvedValue({});
  const onUpdateTask = jest.fn().mockResolvedValue({});
  render(
    <ExecutionPanel
      threadId="thread-1"
      wbs={{ tasks: [{
        id: 'task-1', title: 'Prepare package', phase: 'Delivery', status: 'todo',
        due_date: '2026-11-102026-11-13',
      }] }}
      onUpdateTask={onUpdateTask}
      canEditFields
      canEditStructure
      canEditDependencies
    />,
  );

  fireEvent.click(screen.getByText('Prepare package'));
  const input = screen.getByLabelText('Due date');
  expect(input).toHaveAttribute('type', 'date');
  expect(input).toHaveValue('');

  fireEvent.change(input, { target: { value: '2026-11-13' } });
  await waitFor(() => expect(onUpdateTask).toHaveBeenCalledWith(
    'task-1', { due_date: '2026-11-13' },
  ));
});
