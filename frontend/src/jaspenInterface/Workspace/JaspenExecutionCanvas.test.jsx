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
  const fetchMock = jest.spyOn(global, 'fetch')
    .mockImplementationOnce(() => json(200, { bindings: [] }))
    .mockImplementationOnce(() => json(409, {
      code: 'revision_conflict', error: REVISION_CONFLICT_MESSAGE,
    }))
    .mockImplementationOnce(() => json(200, {
      project_wbs: {
        ...initialPlan,
        updated_at: 'D2',
        tasks: [{ ...initialPlan.tasks[0], title: 'Saved in the other tab' }],
      },
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
  expect(screen.getByText('Saved in the other tab')).toBeInTheDocument();
  expect(screen.queryByText('Conflicting edit')).not.toBeInTheDocument();
  expect(screen.getByTitle('Undo (⌘Z)')).toBeDisabled();
  expect(fetchMock.mock.calls.filter(([, init]) => Boolean(init?.body))).toHaveLength(1);
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
    }))
    .mockImplementationOnce(() => json(200, {
      project_wbs: { ...initialPlan, start_date: '2027-01-18', updated_at: 'S2' },
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
  expect(document.querySelector('input[type="date"]')).toHaveValue('2027-01-18');
  expect(screen.queryByText('Save failed — will retry')).not.toBeInTheDocument();
});

it('never clears the plan start date from an empty picker', async () => {
  jest.useFakeTimers();
  const initialPlan = {
    scorecard_id: 'start-date-clear-card',
    start_date: '2027-01-04',
    updated_at: 'S1',
    tasks: [{ id: 'task-1', title: 'Original', phase: 'Delivery', status: 'todo' }],
  };
  const fetchMock = jest.spyOn(global, 'fetch')
    .mockImplementation(() => json(200, { bindings: [] }));

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

  const writes = fetchMock.mock.calls.filter(([, init]) => init && init.method && init.method !== 'GET');
  expect(writes).toHaveLength(0);
  expect(document.querySelector('input[type="date"]').value).toBe('2027-01-04');
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
    }))
    .mockImplementationOnce(() => json(200, { project_wbs: initialPlan }));

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

  expect(await screen.findByText("That task date is invalid. Your change wasn't saved.")).toBeInTheDocument();
  expect(screen.getByText('Original')).toBeInTheDocument();
  expect(screen.queryByText('Changed')).not.toBeInTheDocument();
  expect(screen.getByTitle('Undo (⌘Z)')).toBeDisabled();
});

it('keeps a canvas edit visible after a temporary network failure', async () => {
  jest.useFakeTimers();
  jest.spyOn(console, 'error').mockImplementation(() => {});
  const initialPlan = {
    scorecard_id: 'network-card',
    updated_at: 'N1',
    tasks: [{ id: 'task-1', title: 'Original', phase: 'Delivery', status: 'todo' }],
  };
  jest.spyOn(global, 'fetch')
    .mockImplementationOnce(() => json(200, { bindings: [] }))
    .mockRejectedValueOnce(new TypeError('Failed to fetch'));

  render(<JaspenExecutionCanvas threadId="network-thread" scorecardId="network-card" wbs={initialPlan} />);
  fireEvent.click(screen.getByText('Original'));
  fireEvent.change(screen.getByDisplayValue('Original'), { target: { value: 'Unsaved edit' } });
  fireEvent.blur(screen.getByDisplayValue('Unsaved edit'));
  await act(async () => {
    jest.advanceTimersByTime(600);
    await Promise.resolve();
    await Promise.resolve();
  });

  expect(screen.getByText('Unsaved edit')).toBeInTheDocument();
  expect(screen.getByText('Save failed — will retry')).toBeInTheDocument();
});

it('still saves the next edit when a rejected start-date change cannot reload the latest plan', async () => {
  jest.spyOn(console, 'error').mockImplementation(() => {});
  const initialPlan = {
    scorecard_id: 'reload-fail-card',
    start_date: '2027-01-04',
    updated_at: 'R1',
    tasks: [{ id: 'task-1', title: 'Original', phase: 'Delivery', status: 'todo' }],
  };
  let startDateAttempts = 0;
  const fetchMock = jest.spyOn(global, 'fetch').mockImplementation((url, init = {}) => {
    const method = String(init.method || 'GET').toUpperCase();
    if (String(url).includes('bindings')) return json(200, { bindings: [] });
    if (method === 'GET') return Promise.reject(new TypeError('Failed to fetch'));
    if (String(init.body || '').includes('2027-01-11') && startDateAttempts === 0) {
      startDateAttempts += 1;
      return json(409, { code: 'revision_conflict', error: REVISION_CONFLICT_MESSAGE });
    }
    return json(200, { project_wbs: { ...initialPlan, updated_at: 'R2' } });
  });

  render(<JaspenExecutionCanvas threadId="reload-fail-thread" scorecardId="reload-fail-card" wbs={initialPlan} />);
  fireEvent.change(document.querySelector('input[type="date"]'), { target: { value: '2027-01-11' } });
  await screen.findByText(
    "This project has newer changes. Your change wasn't saved, and the latest saved version couldn't be loaded.",
    {}, { timeout: 12000 },
  );

  jest.useFakeTimers();
  fireEvent.click(screen.getByText('Original'));
  fireEvent.change(screen.getByDisplayValue('Original'), { target: { value: 'Edited after rejection' } });
  fireEvent.blur(screen.getByDisplayValue('Edited after rejection'));
  await act(async () => {
    jest.advanceTimersByTime(600);
    await Promise.resolve();
    await Promise.resolve();
  });

  const saved = fetchMock.mock.calls.some(([, init]) => String(init?.body || '').includes('Edited after rejection'));
  expect(saved).toBe(true);
}, 20000); // the failed reload uses the client's 1s/2s/4s GET retries
