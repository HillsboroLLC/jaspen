import React from 'react';

import { ExecutionPlanBuildFailure } from './useExecutionPlanBuild';

export default function ScorecardExecutionPlanAction({
  scorecardId,
  buildingExecutionPlanFor,
  failedExecutionPlanRequest,
  executionPlanFailure,
  onBuildExecutionPlan,
  onRetryExecutionPlan,
}) {
  const isBuilding = Boolean(
    buildingExecutionPlanFor
    && String(buildingExecutionPlanFor) === String(scorecardId)
  );
  const failedTarget = failedExecutionPlanRequest?.scorecardId
    || failedExecutionPlanRequest?.threadBundleId;
  const didFail = Boolean(
    failedTarget
    && String(failedTarget) === String(scorecardId)
  );

  return (
    <>
      <button
        className="jas-scorecard-action-primary"
        type="button"
        onClick={() => onBuildExecutionPlan(scorecardId)}
        disabled={Boolean(buildingExecutionPlanFor)}
        title="Generate an AI-authored execution plan from this scorecard"
        style={{
          padding: '6px 12px',
          background: '#a0036c',
          color: '#fff',
          border: 'none',
          borderRadius: 6,
          fontSize: 12,
          fontWeight: 500,
          cursor: buildingExecutionPlanFor ? 'wait' : 'pointer',
          opacity: buildingExecutionPlanFor && !isBuilding ? 0.55 : 1,
          whiteSpace: 'nowrap',
        }}
      >
        {isBuilding ? 'Building plan…' : 'Build Execution Plan →'}
      </button>
      {didFail && (
        <ExecutionPlanBuildFailure
          message={executionPlanFailure}
          busy={isBuilding}
          onRetry={() => onRetryExecutionPlan(failedExecutionPlanRequest)}
          style={{ maxWidth: 520 }}
        />
      )}
    </>
  );
}
