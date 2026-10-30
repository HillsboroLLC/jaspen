import {
  Jaspen,
  REVISION_CONFLICT_MESSAGE,
  forgetThreadRevision,
  getThreadRevision,
  rememberThreadRevision,
} from './JaspenClient';

const json = (status, body) => Promise.resolve({
  ok: status < 400, status, headers: { get: () => 'application/json' },
  json: () => Promise.resolve(body), text: () => Promise.resolve(JSON.stringify(body)),
});

afterEach(() => {
  forgetThreadRevision('thread-1');
  jest.useRealTimers();
  jest.restoreAllMocks();
});

async function flushPolls(times) {
  for (let i = 0; i < times; i += 1) {
    // eslint-disable-next-line no-await-in-loop
    await Promise.resolve();
    jest.advanceTimersByTime(2000);
    // eslint-disable-next-line no-await-in-loop
    await Promise.resolve();
  }
}

it('starts a background build and returns the finished plan', async () => {
  jest.useFakeTimers();
  const fetchMock = jest.spyOn(global, 'fetch')
    .mockImplementationOnce(() => json(202, { job_id: 'job-1', status: 'running' }))
    .mockImplementationOnce(() => json(200, { job_id: 'job-1', status: 'running' }))
    .mockImplementationOnce(() => json(200, { job_id: 'job-1', status: 'done', result_status: 200, result: { success: true, revision: 7, project_wbs: { tasks: [1] } } }));

  const pending = Jaspen.generateAiWbs('thread-1', { commit: true });
  await flushPolls(6);
  const result = await pending;

  expect(result).toEqual({ success: true, revision: 7, project_wbs: { tasks: [1] } });
  expect(getThreadRevision('thread-1')).toBe(7);
  expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toMatchObject({ commit: true, background: true });
  expect(fetchMock.mock.calls[2][0]).toContain('/ai-wbs/jobs/job-1');
});

it('surfaces the exact D4 message for a plan-job revision conflict', async () => {
  jest.useFakeTimers();
  jest.spyOn(global, 'fetch')
    .mockImplementationOnce(() => json(202, { job_id: 'job-conflict', status: 'running' }))
    .mockImplementationOnce(() => json(200, {
      job_id: 'job-conflict', status: 'failed', result_status: 409,
      result: { code: 'revision_conflict', error: REVISION_CONFLICT_MESSAGE },
    }));

  const pending = Jaspen.generateAiWbs('thread-1', { commit: true });
  const assertion = expect(pending).rejects.toMatchObject({
    status: 409,
    message: REVISION_CONFLICT_MESSAGE,
    data: { code: 'revision_conflict' },
  });
  await flushPolls(4);
  await assertion;
});

it('throws the job error with its status', async () => {
  jest.useFakeTimers();
  jest.spyOn(global, 'fetch')
    .mockImplementationOnce(() => json(202, { job_id: 'job-2', status: 'running' }))
    .mockImplementationOnce(() => json(200, { job_id: 'job-2', status: 'failed', result_status: 403, result: { error: 'Generated WBS exceeds task limit for current plan' } }));

  const pending = Jaspen.generateAiWbs('thread-1', { commit: true });
  const assertion = expect(pending).rejects.toMatchObject({ status: 403, message: 'Generated WBS exceeds task limit for current plan' });
  await flushPolls(4);
  await assertion;
});

it('keeps previews synchronous', async () => {
  const fetchMock = jest.spyOn(global, 'fetch').mockImplementationOnce(() => json(200, { success: true, committed: false }));
  await expect(Jaspen.generateAiWbs('thread-1', { commit: false })).resolves.toEqual({ success: true, committed: false });
  expect(JSON.parse(fetchMock.mock.calls[0][1].body).background).toBeUndefined();
});

it('sends a plan object basis, not the project revision, and preserves D4 conflicts', async () => {
  rememberThreadRevision('thread-1', 11);
  const fetchMock = jest.spyOn(global, 'fetch').mockImplementationOnce(() => json(409, {
    code: 'revision_conflict', error: REVISION_CONFLICT_MESSAGE,
  }));

  await expect(Jaspen.upsertThreadWbs(
    'thread-1', { tasks: [], updated_at: '2026-10-29T12:00:00' }, 'card-1',
  )).rejects.toMatchObject({
    status: 409,
    message: REVISION_CONFLICT_MESSAGE,
  });
  expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toMatchObject({
    project_wbs: { updated_at: '2026-10-29T12:00:00' },
  });
  expect(JSON.parse(fetchMock.mock.calls[0][1].body)).not.toHaveProperty('base_revision');
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

it('echoes the scenario object basis on its next write', async () => {
  const fetchMock = jest.spyOn(global, 'fetch')
    .mockImplementationOnce(() => json(200, {
      scenarios: [{ scenario_id: 'scenario-1', updated_at: 'basis-1' }],
    }))
    .mockImplementationOnce(() => json(200, {
      scenario_id: 'scenario-1', updated_at: 'basis-2', label: 'Renamed',
    }));

  await Jaspen.listScenarios('thread-1');
  await Jaspen.updateScenario('scenario-1', { thread_id: 'thread-1', label: 'Renamed' });

  expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toMatchObject({
    expected_updated_at: 'basis-1', label: 'Renamed',
  });
  expect(JSON.parse(fetchMock.mock.calls[1][1].body)).not.toHaveProperty('base_revision');
});

it('adopts each returned plan basis across repeated edits and a start-date change', async () => {
  const fetchMock = jest.spyOn(global, 'fetch')
    .mockImplementationOnce(() => json(200, {
      scorecard_id: 'card-basis',
      project_wbs: { scorecard_id: 'card-basis', tasks: [], updated_at: 'plan-basis-1' },
    }))
    .mockImplementationOnce(() => json(200, {
      scorecard_id: 'card-basis',
      project_wbs: { scorecard_id: 'card-basis', tasks: [{ id: '1' }], updated_at: 'plan-basis-2' },
    }))
    .mockImplementationOnce(() => json(200, {
      scorecard_id: 'card-basis',
      project_wbs: { scorecard_id: 'card-basis', tasks: [{ id: '1' }, { id: '2' }], updated_at: 'plan-basis-3' },
    }))
    .mockImplementationOnce(() => json(200, {
      scorecard_id: 'card-basis',
      project_wbs: { scorecard_id: 'card-basis', tasks: [{ id: '1' }, { id: '2' }], updated_at: 'plan-basis-4' },
    }));

  await Jaspen.getThreadWbs('thread-basis', 'card-basis');
  await Jaspen.upsertThreadWbs('thread-basis', { scorecard_id: 'card-basis', tasks: [{ id: '1' }] }, 'card-basis');
  await Jaspen.upsertThreadWbs('thread-basis', { scorecard_id: 'card-basis', tasks: [{ id: '1' }, { id: '2' }] }, 'card-basis');
  await Jaspen.setThreadWbsStartDate('thread-basis', '2026-11-01', 'card-basis');

  expect(JSON.parse(fetchMock.mock.calls[1][1].body).expected_updated_at).toBe('plan-basis-1');
  expect(JSON.parse(fetchMock.mock.calls[2][1].body).expected_updated_at).toBe('plan-basis-2');
  expect(JSON.parse(fetchMock.mock.calls[3][1].body).expected_updated_at).toBe('plan-basis-3');
});

it('queues two quick inline edits until the first save returns its basis', async () => {
  let releaseFirst;
  const fetchMock = jest.spyOn(global, 'fetch')
    .mockImplementationOnce(() => json(200, {
      project_wbs: { scorecard_id: 'queue-card', tasks: [], updated_at: 'T1' },
    }))
    .mockImplementationOnce(() => new Promise((resolve) => {
      releaseFirst = () => resolve(json(200, {
        project_wbs: { scorecard_id: 'queue-card', tasks: [{ id: 1 }], updated_at: 'T2' },
      }));
    }))
    .mockImplementationOnce(() => json(200, {
      project_wbs: { scorecard_id: 'queue-card', tasks: [{ id: 1 }, { id: 2 }], updated_at: 'T3' },
    }));

  await Jaspen.getThreadWbs('queue-thread', 'queue-card');
  const first = Jaspen.upsertThreadWbs(
    'queue-thread', { scorecard_id: 'queue-card', tasks: [{ id: 1 }] }, 'queue-card',
  );
  const second = Jaspen.upsertThreadWbs(
    'queue-thread', { scorecard_id: 'queue-card', tasks: [{ id: 1 }, { id: 2 }] }, 'queue-card',
  );
  await Promise.resolve();
  await Promise.resolve();
  expect(fetchMock).toHaveBeenCalledTimes(2);
  releaseFirst();
  await first;
  await second;

  const sent = fetchMock.mock.calls.slice(1).map((call) => (
    JSON.parse(call[1].body).expected_updated_at
  ));
  expect(sent).toEqual(['T1', 'T2']);
});

it('runs the client plan lifecycle using each preceding response basis', async () => {
  const staleEditorPlan = {
    scorecard_id: 'lifecycle-card',
    tasks: [{ id: '1' }, { id: '2' }],
    updated_at: '2026-10-30T10:00:00Z',
  };
  const fetchMock = jest.spyOn(global, 'fetch')
    .mockImplementationOnce(() => json(200, { project_wbs: staleEditorPlan }))
    .mockImplementationOnce(() => json(200, {
      project_wbs: { ...staleEditorPlan, updated_at: '2026-10-30T10:00:01Z' },
    }))
    .mockImplementationOnce(() => json(200, {
      project_wbs: { ...staleEditorPlan, updated_at: '2026-10-30T10:00:02Z' },
    }))
    .mockImplementationOnce(() => json(200, {
      project_wbs: { ...staleEditorPlan, start_date: '2027-01-04', updated_at: '2026-10-30T10:00:03Z' },
    }))
    .mockImplementationOnce(() => json(200, {
      project_wbs: { ...staleEditorPlan, updated_at: '2026-10-30T10:00:04Z' },
    }));

  await Jaspen.getThreadWbs('lifecycle-thread', 'lifecycle-card');
  await Jaspen.upsertThreadWbs('lifecycle-thread', staleEditorPlan, 'lifecycle-card');
  await Jaspen.upsertThreadWbs('lifecycle-thread', staleEditorPlan, 'lifecycle-card');
  await Jaspen.setThreadWbsStartDate('lifecycle-thread', '2027-01-04', 'lifecycle-card');
  await Jaspen.upsertThreadWbs('lifecycle-thread', staleEditorPlan, 'lifecycle-card');

  expect(fetchMock.mock.calls.slice(1).map((call) => (
    JSON.parse(call[1].body).expected_updated_at
  ))).toEqual([
    '2026-10-30T10:00:00Z',
    '2026-10-30T10:00:01Z',
    '2026-10-30T10:00:02Z',
    '2026-10-30T10:00:03Z',
  ]);
});

it('uses an editor plan basis when it is newer than the remembered basis', async () => {
  const fetchMock = jest.spyOn(global, 'fetch')
    .mockImplementationOnce(() => json(200, {
      project_wbs: { scorecard_id: 'newer-card', tasks: [], updated_at: '2026-10-30T10:00:00Z' },
    }))
    .mockImplementationOnce(() => json(200, {
      project_wbs: { scorecard_id: 'newer-card', tasks: [], updated_at: '2026-10-30T10:00:02Z' },
    }));

  await Jaspen.getThreadWbs('newer-thread', 'newer-card');
  await Jaspen.upsertThreadWbs('newer-thread', {
    scorecard_id: 'newer-card', tasks: [], updated_at: '2026-10-30T10:00:01Z',
  }, 'newer-card');

  expect(JSON.parse(fetchMock.mock.calls[1][1].body).expected_updated_at)
    .toBe('2026-10-30T10:00:01Z');
});

it('queues scenario update, apply, adopt, and delete with the latest basis', async () => {
  let releaseUpdate;
  const fetchMock = jest.spyOn(global, 'fetch')
    .mockImplementationOnce(() => json(200, {
      scenarios: [{ scenario_id: 'queued-scenario', updated_at: 'S1' }],
    }))
    .mockImplementationOnce(() => new Promise((resolve) => {
      releaseUpdate = () => resolve(json(200, {
        scenario_id: 'queued-scenario', updated_at: 'S2',
      }));
    }))
    .mockImplementationOnce(() => json(200, { scenario_updated_at: 'S3' }))
    .mockImplementationOnce(() => json(200, { scenario_updated_at: 'S4' }))
    .mockImplementationOnce(() => json(200, { success: true }));

  await Jaspen.listScenarios('scenario-thread');
  const update = Jaspen.updateScenario('queued-scenario', {
    thread_id: 'scenario-thread', label: 'Updated',
  });
  const apply = Jaspen.applyScenario('queued-scenario', 'scenario-thread');
  await Promise.resolve();
  await Promise.resolve();
  expect(fetchMock).toHaveBeenCalledTimes(2);
  releaseUpdate();
  await update;
  await apply;
  await Jaspen.adoptScenario('queued-scenario', 'scenario-thread');
  await Jaspen.deleteScenario('queued-scenario', 'scenario-thread');

  expect(fetchMock.mock.calls.slice(1).map((call) => (
    JSON.parse(call[1].body).expected_updated_at
  ))).toEqual(['S1', 'S2', 'S3', 'S4']);
});

it('lets a failed inline save settle before retry and a later edit', async () => {
  const fetchMock = jest.spyOn(global, 'fetch')
    .mockImplementationOnce(() => json(200, {
      project_wbs: { scorecard_id: 'retry-card', tasks: [], updated_at: 'R1' },
    }))
    .mockImplementationOnce(() => json(500, { error: 'Temporary failure' }))
    .mockImplementationOnce(() => json(200, {
      project_wbs: { scorecard_id: 'retry-card', tasks: [{ id: 1 }], updated_at: 'R2' },
    }))
    .mockImplementationOnce(() => json(200, {
      project_wbs: { scorecard_id: 'retry-card', tasks: [{ id: 1 }, { id: 2 }], updated_at: 'R3' },
    }));

  await Jaspen.getThreadWbs('retry-thread', 'retry-card');
  await expect(Jaspen.upsertThreadWbs(
    'retry-thread', { scorecard_id: 'retry-card', tasks: [{ id: 1 }] }, 'retry-card',
  )).rejects.toMatchObject({ status: 500 });
  await Jaspen.upsertThreadWbs(
    'retry-thread', { scorecard_id: 'retry-card', tasks: [{ id: 1 }] }, 'retry-card',
  );
  await Jaspen.upsertThreadWbs(
    'retry-thread', { scorecard_id: 'retry-card', tasks: [{ id: 1 }, { id: 2 }] }, 'retry-card',
  );

  expect(fetchMock.mock.calls.slice(1).map((call) => (
    JSON.parse(call[1].body).expected_updated_at
  ))).toEqual(['R1', 'R1', 'R2']);
});
