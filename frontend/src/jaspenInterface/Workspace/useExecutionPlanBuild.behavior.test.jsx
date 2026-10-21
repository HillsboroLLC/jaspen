import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { Jaspen } from './JaspenClient';
import { useExecutionPlanBuild } from './useExecutionPlanBuild';

jest.mock('./JaspenClient', () => ({
  Jaspen: { generateAiWbs: jest.fn() },
}));

function Harness() {
  const { generateExecutionPlan, executionPlanDecisionDialog, executionPlanFailure } = useExecutionPlanBuild();
  return (
    <>
      <button type="button" onClick={() => { void generateExecutionPlan('thread-1', { commit: true }).catch(() => {}); }}>
        Build
      </button>
      {executionPlanFailure && <p role="alert">{executionPlanFailure}</p>}
      {executionPlanDecisionDialog}
    </>
  );
}

afterEach(() => jest.resetAllMocks());

it('builds the normal path immediately without a dialog', async () => {
  Jaspen.generateAiWbs.mockResolvedValue({ success: true, decision: { option_key: 'opt-1' } });
  render(<Harness />);

  fireEvent.click(screen.getByRole('button', { name: 'Build' }));

  await waitFor(() => expect(Jaspen.generateAiWbs).toHaveBeenCalledTimes(1));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});

it('shows one exact override confirmation and retries with acknowledgement', async () => {
  Jaspen.generateAiWbs
    .mockRejectedValueOnce({
      status: 409,
      data: {
        code: 'recorded_advancing_decision_required',
        override: true,
        option_key: 'opt-1',
        option_name: 'JeffCo RFP',
        failed_check_labels: ['Surety / bond confirmation'],
      },
    })
    .mockResolvedValueOnce({ success: true, decision: { option_key: 'opt-1', override: true } });
  render(<Harness />);

  fireEvent.click(screen.getByRole('button', { name: 'Build' }));

  expect(await screen.findByRole('heading', { name: 'Build a plan anyway?' })).toBeInTheDocument();
  expect(screen.getByText("Jaspen recommended No-Bid because Surety / bond confirmation failed. Building a plan records that you're overriding that recommendation.")).toBeInTheDocument();
  expect(screen.queryByText(/don't show this again/i)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Build plan anyway' }));

  await waitFor(() => expect(Jaspen.generateAiWbs).toHaveBeenCalledTimes(2));
  expect(Jaspen.generateAiWbs.mock.calls[1][1].record_decision).toEqual({
    acknowledged: true,
    option_key: 'opt-1',
  });
});

it('keeps the standard build failure visible until a later build succeeds', async () => {
  Jaspen.generateAiWbs
    .mockRejectedValueOnce({
      status: 503,
      data: { code: 'execution_plan_generation_failed' },
    })
    .mockResolvedValueOnce({ success: true });
  render(<Harness />);

  fireEvent.click(screen.getByRole('button', { name: 'Build' }));
  expect(await screen.findByRole('alert')).toHaveTextContent(
    "Jaspen couldn't finish building this plan — try again. Your existing plan was not changed."
  );

  fireEvent.click(screen.getByRole('button', { name: 'Build' }));
  await waitFor(() => expect(Jaspen.generateAiWbs).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
  expect(Jaspen.generateAiWbs.mock.calls[1].slice(0, 2)).toEqual([
    'thread-1',
    { commit: true },
  ]);
});
