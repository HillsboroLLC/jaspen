import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

import ScorecardExecutionPlanAction from './ScorecardExecutionPlanAction';
import { EXECUTION_PLAN_FAILURE_MESSAGE } from './useExecutionPlanBuild';

const failedRequest = {
  threadBundleId: 'thread-1',
  scorecardId: 'scorecard-1',
  force: false,
};

function renderAction(overrides = {}) {
  const props = {
    scorecardId: 'scorecard-1',
    buildingExecutionPlanFor: null,
    failedExecutionPlanRequest: failedRequest,
    executionPlanFailure: EXECUTION_PLAN_FAILURE_MESSAGE,
    onBuildExecutionPlan: jest.fn(),
    onRetryExecutionPlan: jest.fn(),
    ...overrides,
  };
  return { props, ...render(<ScorecardExecutionPlanAction {...props} />) };
}

test('chat scorecard shows the persistent failure and retries the same request', () => {
  const { props } = renderAction();

  expect(screen.getByRole('alert')).toHaveTextContent(EXECUTION_PLAN_FAILURE_MESSAGE);
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }));

  expect(props.onRetryExecutionPlan).toHaveBeenCalledTimes(1);
  expect(props.onRetryExecutionPlan).toHaveBeenCalledWith(failedRequest);
});

test('chat scorecard clears the failure after success', () => {
  const { rerender, props } = renderAction();
  expect(screen.getByRole('alert')).toBeInTheDocument();

  rerender(<ScorecardExecutionPlanAction
    {...props}
    failedExecutionPlanRequest={null}
    executionPlanFailure={null}
  />);

  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

test('chat scorecard disables the build button and labels it while building', () => {
  renderAction({
    buildingExecutionPlanFor: 'scorecard-1',
    failedExecutionPlanRequest: null,
    executionPlanFailure: null,
  });

  expect(screen.getByRole('button', { name: 'Building plan…' })).toBeDisabled();
});
