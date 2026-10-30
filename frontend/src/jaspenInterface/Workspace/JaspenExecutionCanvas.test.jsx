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

  const error = await screen.findByText('Save failed — will retry');
  expect(error).toHaveAttribute('title', REVISION_CONFLICT_MESSAGE);
});
