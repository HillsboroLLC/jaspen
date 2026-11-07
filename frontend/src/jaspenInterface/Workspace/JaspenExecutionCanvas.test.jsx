import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import JaspenExecutionCanvas, { TaskRow } from './JaspenExecutionCanvas';
import { Jaspen, REVISION_CONFLICT_MESSAGE } from './JaspenClient';

const json = (status, body) => Promise.resolve({
  ok: status < 400,
  status,
  headers: { get: () => 'application/json' },
  json: () => Promise.resolve(body),
  text: () => Promise.resolve(JSON.stringify(body)),
});

afterEach(() => {
  jest.useRealTimers();
  jest.restoreAllMocks();
});

it('keeps the task title readable when the execution sidebar narrows the list', () => {
  render(<TaskRow
    task={{ id: 'task-1', title: 'Prepare and finalize the complete submission package', status: 'todo' }}
    phaseName="Submission"
  />);
  const row = screen.getByText('Prepare and finalize the complete submission package').closest('[draggable="true"]');
  expect(row).toHaveStyle({ minWidth: '980px' });
  expect(row.style.gridTemplateColumns).toContain('minmax(300px, 1fr)');
});

it('edits task dates with an ISO date input and never saves duration text', () => {
  const onUpdate = jest.fn();
  render(<TaskRow
    task={{
      id: 'task-1', title: 'Prepare package', status: 'todo', timeline_days: 3,
    }}
    phaseName="Submission"
    onUpdate={onUpdate}
  />);

  fireEvent.click(screen.getByText('3 days'));
  const input = screen.getByLabelText('Task due date');
  expect(input).toHaveAttribute('type', 'date');
  expect(input).toHaveValue('');
  fireEvent.blur(input);
  expect(onUpdate).not.toHaveBeenCalled();

  fireEvent.click(screen.getByText('3 days'));
  const reopened = screen.getByLabelText('Task due date');
  fireEvent.change(reopened, { target: { value: '2026-11-13' } });
  fireEvent.blur(reopened);
  expect(onUpdate).toHaveBeenCalledWith({ due_date: '2026-11-13' });
});

it('allows an existing task date to be cleared', () => {
  const onUpdate = jest.fn();
  render(<TaskRow
    task={{ id: 'task-1', title: 'Prepare package', status: 'todo', due_date: '2026-11-13' }}
    phaseName="Submission"
    onUpdate={onUpdate}
  />);

  fireEvent.click(screen.getByText('2026-11-13'));
  const input = screen.getByLabelText('Task due date');
  fireEvent.change(input, { target: { value: '' } });
  fireEvent.blur(input);
  expect(onUpdate).toHaveBeenCalledWith({ due_date: '' });
});

it('serializes consecutive canvas autosaves and advances their basis', async () => {
  jest.useFakeTimers();
  let releaseFirstSave;
  const initialPlan = {
    scorecard_id: 'canvas-queue-card',
    updated_at: 'C1',
    tasks: [{ id: 'task-1', title: 'Original', phase: 'Delivery', status: 'todo' }],
  };
  const fetchMock = jest.spyOn(global, 'fetch')
    .mockImplementationOnce(() => json(200, { bindings: [] }))
    .mockImplementationOnce(() => new Promise((resolve) => {
      releaseFirstSave = () => resolve(json(200, {
        project_wbs: { ...initialPlan, tasks: [{ ...initialPlan.tasks[0], title: 'First' }], updated_at: 'C2' },
      }));
    }))
    .mockImplementationOnce(() => json(200, {
      project_wbs: { ...initialPlan, tasks: [{ ...initialPlan.tasks[0], title: 'Second' }], updated_at: 'C3' },
    }));

  render(
    <JaspenExecutionCanvas
      threadId="canvas-queue-thread"
      scorecardId="canvas-queue-card"
      wbs={initialPlan}
    />,
  );

  fireEvent.click(screen.getByText('Original'));
  fireEvent.change(screen.getByDisplayValue('Original'), { target: { value: 'First' } });
  fireEvent.blur(screen.getByDisplayValue('First'));
  await act(async () => {
    jest.advanceTimersByTime(600);
    await Promise.resolve();
  });
  expect(fetchMock).toHaveBeenCalledTimes(2);

  fireEvent.click(screen.getByText('First'));
  fireEvent.change(screen.getByDisplayValue('First'), { target: { value: 'Second' } });
  fireEvent.blur(screen.getByDisplayValue('Second'));
  await act(async () => {
    jest.advanceTimersByTime(600);
    await Promise.resolve();
  });
  expect(fetchMock).toHaveBeenCalledTimes(2);

  await act(async () => {
    releaseFirstSave();
    await Promise.resolve();
    await Promise.resolve();
  });
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));

  expect(fetchMock.mock.calls.slice(1).map((call) => (
    JSON.parse(call[1].body).expected_updated_at
  ))).toEqual(['C1', 'C2']);
});

it('shows the D4 message when a canvas autosave gets a real conflict', async () => {
  jest.useFakeTimers();
  jest.spyOn(console, 'error').mockImplementation(() => {});
  const initialPlan = {
    scorecard_id: 'canvas-conflict-card',
    updated_at: 'D1',
    tasks: [{ id: 'task-1', title: 'Original', phase: 'Delivery', status: 'todo' }],
  };
  jest.spyOn(global, 'fetch')
    .mockImplementationOnce(() => json(200, { bindings: [] }))
    .mockImplementationOnce(() => json(409, {
      code: 'revision_conflict', error: REVISION_CONFLICT_MESSAGE,
    }));

  render(
    <JaspenExecutionCanvas
      threadId="canvas-conflict-thread"
      scorecardId="canvas-conflict-card"
      wbs={initialPlan}
    />,
  );
  fireEvent.click(screen.getByText('Original'));
  fireEvent.change(screen.getByDisplayValue('Original'), { target: { value: 'Conflicting edit' } });
  fireEvent.blur(screen.getByDisplayValue('Conflicting edit'));
  await act(async () => {
    jest.advanceTimersByTime(600);
    await Promise.resolve();
    await Promise.resolve();
  });

  const error = await screen.findByText(REVISION_CONFLICT_MESSAGE);
  expect(error).toHaveAttribute('title', REVISION_CONFLICT_MESSAGE);
  expect(screen.queryByText('Save failed — will retry')).not.toBeInTheDocument();
});

it('shows the D4 message when a start-date change gets a real conflict', async () => {
  jest.spyOn(console, 'error').mockImplementation(() => {});
  const initialPlan = {
    scorecard_id: 'start-date-conflict-card',
    start_date: '2027-01-04',
    updated_at: 'S1',
    tasks: [{ id: 'task-1', title: 'Original', phase: 'Delivery', status: 'todo' }],
  };
  jest.spyOn(global, 'fetch')
    .mockImplementationOnce(() => json(200, { bindings: [] }))
    .mockImplementationOnce(() => json(409, {
      code: 'revision_conflict', error: REVISION_CONFLICT_MESSAGE,
    }));

  render(
    <JaspenExecutionCanvas
      threadId="start-date-conflict-thread"
      scorecardId="start-date-conflict-card"
      wbs={initialPlan}
    />,
  );
  fireEvent.change(document.querySelector('input[type="date"]'), {
    target: { value: '2027-01-11' },
  });

  const error = await screen.findByText(REVISION_CONFLICT_MESSAGE);
  expect(error).toHaveAttribute('title', REVISION_CONFLICT_MESSAGE);
  expect(screen.queryByText('Save failed — will retry')).not.toBeInTheDocument();
});

it('allows the plan start date to be cleared without sending display text', async () => {
  jest.useFakeTimers();
  const initialPlan = {
    scorecard_id: 'start-date-clear-card',
    start_date: '2027-01-04',
    updated_at: 'S1',
    tasks: [{ id: 'task-1', title: 'Original', phase: 'Delivery', status: 'todo' }],
  };
  const fetchMock = jest.spyOn(global, 'fetch')
    .mockImplementationOnce(() => json(200, { bindings: [] }))
    .mockImplementationOnce(() => json(200, {
      project_wbs: { ...initialPlan, start_date: null, updated_at: 'S2' },
    }));

  render(
    <JaspenExecutionCanvas
      threadId="start-date-clear-thread"
      scorecardId="start-date-clear-card"
      wbs={initialPlan}
    />,
  );
  fireEvent.change(document.querySelector('input[type="date"]'), { target: { value: '' } });
  await act(async () => {
    jest.advanceTimersByTime(600);
    await Promise.resolve();
    await Promise.resolve();
  });

  const saved = JSON.parse(fetchMock.mock.calls[1][1].body);
  expect(saved.project_wbs.start_date).toBeNull();
});

it('shows the minimal invalid task date save message', async () => {
  jest.useFakeTimers();
  jest.spyOn(console, 'error').mockImplementation(() => {});
  const initialPlan = {
    scorecard_id: 'invalid-date-card',
    updated_at: 'I1',
    tasks: [{ id: 'task-1', title: 'Original', phase: 'Delivery', status: 'todo' }],
  };
  jest.spyOn(global, 'fetch')
    .mockImplementationOnce(() => json(200, { bindings: [] }))
    .mockImplementationOnce(() => json(400, {
      code: 'invalid_task_date', task_id: 'task-1', field: 'due_date',
      error: "Task 'task-1' has an invalid due_date; expected YYYY-MM-DD.",
    }));

  render(
    <JaspenExecutionCanvas
      threadId="invalid-date-thread"
      scorecardId="invalid-date-card"
      wbs={initialPlan}
    />,
  );
  fireEvent.click(screen.getByText('Original'));
  fireEvent.change(screen.getByDisplayValue('Original'), { target: { value: 'Changed' } });
  fireEvent.blur(screen.getByDisplayValue('Changed'));
  await act(async () => {
    jest.advanceTimersByTime(600);
    await Promise.resolve();
    await Promise.resolve();
  });

  expect(await screen.findByText('Invalid task date')).toBeInTheDocument();
});
