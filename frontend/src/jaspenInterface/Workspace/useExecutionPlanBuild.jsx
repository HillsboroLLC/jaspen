import React, { useCallback, useRef, useState } from 'react';

import { Jaspen } from './JaspenClient';

export const PLAN_DECISION_REQUIRED = 'recorded_advancing_decision_required';
export const EXECUTION_PLAN_FAILURE_MESSAGE = "Jaspen couldn't finish building this plan — try again. Your existing plan was not changed.";

// "Try again" is only honest when the build itself failed. A request the
// server refused carries its own reason, and out-of-Thinking-Power already
// raises the account-wide notice.
const failureMessageFor = (error) => {
  if (error?.name === 'AbortError' || error?.status === 402) return null;
  if (typeof error?.status === 'number' && error.status < 500) {
    return error.message || EXECUTION_PLAN_FAILURE_MESSAGE;
  }
  return EXECUTION_PLAN_FAILURE_MESSAGE;
};

const isDecisionRequired = (error) => (
  error?.status === 409
  && (error?.data?.code === PLAN_DECISION_REQUIRED || error?.data?.action === 'record_decision')
);

export function ExecutionPlanBuildFailure({ message, onRetry, busy = false, style = {} }) {
  if (!message) return null;
  return (
    <div
      role="alert"
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 12,
        boxSizing: 'border-box',
        width: '100%',
        padding: '8px 12px',
        border: '1px solid #f3d0d0',
        borderRadius: 8,
        background: '#fff5f5',
        color: '#b42318',
        fontSize: 12.5,
        lineHeight: 1.4,
        ...style,
      }}
    >
      <span style={{ flex: 1, minWidth: 0 }}>{message}</span>
      <button
        type="button"
        onClick={onRetry}
        disabled={busy}
        style={{
          flex: '0 0 auto',
          padding: '5px 12px',
          border: '1px solid #b42318',
          borderRadius: 6,
          background: '#fff',
          color: '#b42318',
          cursor: busy ? 'wait' : 'pointer',
          fontSize: 12,
          fontWeight: 600,
        }}
      >
        {busy ? 'Building plan…' : 'Retry'}
      </button>
    </div>
  );
}

/**
 * The only frontend entry point for committed execution-plan generation.
 * It lets the server decide whether this option already has a recorded
 * decision. A 409 opens one shared confirmation dialog, then the exact same
 * request is repeated with an option-scoped acknowledgement.
 */
export function useExecutionPlanBuild() {
  const [confirmation, setConfirmation] = useState(null);
  const [executionPlanFailure, setExecutionPlanFailure] = useState(null);
  const resolverRef = useRef(null);

  const finishConfirmation = useCallback((result) => {
    const resolve = resolverRef.current;
    resolverRef.current = null;
    setConfirmation(null);
    if (resolve) resolve(result);
  }, []);

  const askForDecision = useCallback((details = {}) => new Promise((resolve) => {
    resolverRef.current = resolve;
    setConfirmation({
      optionKey: details.option_key || null,
      optionName: details.option_name || 'this option',
      failedCheckLabels: Array.isArray(details.failed_check_labels) ? details.failed_check_labels : [],
    });
  }), []);

  const publishDecision = useCallback((response, threadId) => {
    if (!response?.decision) return response;
    window.dispatchEvent(new CustomEvent('jaspen:decision-recorded', {
      detail: { threadId, ...response.decision },
    }));
    return response;
  }, []);

  const generateExecutionPlan = useCallback(async (threadId, payload = {}, options = {}) => {
    const committedPayload = { ...payload };

    try {
      const response = await Jaspen.generateAiWbs(threadId, committedPayload, options);
      setExecutionPlanFailure(null);
      return publishDecision(response, threadId);
    } catch (error) {
      if (!isDecisionRequired(error) || committedPayload.commit === false) {
        if (committedPayload.commit !== false) setExecutionPlanFailure(failureMessageFor(error));
        throw error;
      }
      const accepted = await askForDecision(error.data || {});
      if (!accepted?.acknowledged) return { cancelled: true };
      try {
        const response = await Jaspen.generateAiWbs(threadId, {
          ...committedPayload,
          record_decision: {
            acknowledged: true,
            option_key: accepted.optionKey || error?.data?.option_key || null,
          },
        }, options);
        setExecutionPlanFailure(null);
        return publishDecision(response, threadId);
      } catch (buildError) {
        setExecutionPlanFailure(failureMessageFor(buildError));
        throw buildError;
      }
    }
  }, [askForDecision, publishDecision]);

  const executionPlanDecisionDialog = confirmation ? (
    <div className="jas-modal-backdrop" role="presentation" onClick={() => finishConfirmation({ acknowledged: false })}>
      <div className="jas-account-modal" role="dialog" aria-modal="true" aria-label="Build a plan anyway?" onClick={(event) => event.stopPropagation()}>
        <div className="jas-account-modal-header">
          <h3>Build a plan anyway?</h3>
          <button type="button" className="jas-account-modal-close" onClick={() => finishConfirmation({ acknowledged: false })} aria-label="Close">×</button>
        </div>
        <p style={{ margin: '0 0 16px', color: 'var(--color-text-secondary)' }}>
          Jaspen recommended No-Bid because {confirmation.failedCheckLabels.length > 0
            ? `${confirmation.failedCheckLabels.join(', ')} failed`
            : 'the score is below the decline threshold'}. Building a plan records that you&apos;re overriding that recommendation.
        </p>
        <div className="jas-account-modal-actions">
          <button type="button" className="jas-account-secondary-btn" onClick={() => finishConfirmation({ acknowledged: false })}>Cancel</button>
          <button
            type="button"
            className="jas-account-portal-btn"
            onClick={() => finishConfirmation({
              acknowledged: true,
              optionKey: confirmation.optionKey,
            })}
          >
            Build plan anyway
          </button>
        </div>
      </div>
    </div>
  ) : null;

  return { generateExecutionPlan, executionPlanDecisionDialog, executionPlanFailure };
}
