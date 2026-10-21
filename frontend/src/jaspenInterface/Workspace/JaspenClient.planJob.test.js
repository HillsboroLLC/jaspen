import { Jaspen } from './JaspenClient';

const json = (status, body) => Promise.resolve({
  ok: status < 400, status, headers: { get: () => 'application/json' },
  json: () => Promise.resolve(body), text: () => Promise.resolve(JSON.stringify(body)),
});

afterEach(() => { jest.useRealTimers(); jest.restoreAllMocks(); });

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
    .mockImplementationOnce(() => json(200, { job_id: 'job-1', status: 'done', result_status: 200, result: { success: true, project_wbs: { tasks: [1] } } }));

  const pending = Jaspen.generateAiWbs('thread-1', { commit: true });
  await flushPolls(6);
  const result = await pending;

  expect(result).toEqual({ success: true, project_wbs: { tasks: [1] } });
  expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toMatchObject({ commit: true, background: true });
  expect(fetchMock.mock.calls[2][0]).toContain('/ai-wbs/jobs/job-1');
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
