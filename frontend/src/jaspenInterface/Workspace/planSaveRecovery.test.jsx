import { act, renderHook } from '@testing-library/react';
import { Jaspen } from './JaspenClient';
import { usePlanWriteRecovery } from './planSaveRecovery';

afterEach(() => {
  jest.restoreAllMocks();
});

it('waits for already-issued plan writes before loading the latest saved plan', async () => {
  let finishWrite;
  const pendingWrite = new Promise((resolve) => { finishWrite = resolve; });
  const getPlan = jest.spyOn(Jaspen, 'getThreadWbs').mockResolvedValue({
    project_wbs: { scorecard_id: 'card-1', tasks: [{ id: '1', title: 'Latest saved' }] },
  });
  const { result } = renderHook(() => usePlanWriteRecovery());

  act(() => {
    result.current.trackPlanWrite(pendingWrite);
  });
  let recovery;
  act(() => {
    recovery = result.current.loadLatestSavedPlan('thread-1', 'card-1');
  });
  await act(async () => { await Promise.resolve(); });
  expect(getPlan).not.toHaveBeenCalled();

  await act(async () => {
    finishWrite();
    await recovery;
  });
  expect(getPlan).toHaveBeenCalledTimes(1);
});
