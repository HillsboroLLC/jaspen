import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import ExecutionPanel from './ExecutionPanel';
import { Jaspen } from '../JaspenClient';

const plan = {
  tasks: [{ id: 'task-1', title: 'Saved title', phase: 'Delivery', status: 'todo' }],
};

const renderPanel = (props = {}) => render(
  <ExecutionPanel
    threadId="thread-1"
    wbs={plan}
    authFetch={jest.fn().mockResolvedValue({ json: async () => ({ members: [] }) })}
    onRefresh={jest.fn()}
    onUpdateTask={jest.fn()}
    onRejectedSave={jest.fn()}
    canEditFields
    canEditStructure
    canEditDependencies
    isViewer={false}
    isLocked={false}
    {...props}
  />,
);

beforeEach(() => {
  jest.spyOn(Jaspen, 'getThreadPmSync').mockResolvedValue({});
});

afterEach(() => {
  jest.restoreAllMocks();
});

it('clears a rejected field draft and refreshes the saved plan', async () => {
  const rejection = Object.assign(new Error('That title is not valid'), { status: 400 });
  const onUpdateTask = jest.fn().mockRejectedValue(rejection);
  const onRejectedSave = jest.fn().mockResolvedValue(plan);
  renderPanel({ onUpdateTask, onRejectedSave });

  fireEvent.click(screen.getByText('Saved title'));
  const input = screen.getByText('Title').closest('label').querySelector('input');
  fireEvent.change(input, { target: { value: 'Rejected title' } });
  fireEvent.blur(input);

  await waitFor(() => expect(onRejectedSave).toHaveBeenCalledTimes(1));
  expect(input).toHaveValue('Saved title');
  expect(screen.getByText("That title is not valid. Your change wasn't saved.")).toBeInTheDocument();
});

it('keeps a field draft visible after a temporary failure', async () => {
  const onUpdateTask = jest.fn().mockRejectedValue(new TypeError('Failed to fetch'));
  const onRejectedSave = jest.fn();
  renderPanel({ onUpdateTask, onRejectedSave });

  fireEvent.click(screen.getByText('Saved title'));
  const input = screen.getByText('Title').closest('label').querySelector('input');
  fireEvent.change(input, { target: { value: 'Unsaved title' } });
  fireEvent.blur(input);

  expect(await screen.findByText('Failed to fetch')).toBeInTheDocument();
  expect(input).toHaveValue('Unsaved title');
  expect(onRejectedSave).not.toHaveBeenCalled();
});
