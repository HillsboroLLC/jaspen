import React, { useCallback, useRef, useState } from 'react';

import { useAuth } from '../../shared/auth/AuthContext';
import { Jaspen } from './JaspenClient';

export const PLAN_DECISION_REQUIRED = 'recorded_advancing_decision_required';

const isDecisionRequired = (error) => (
  error?.status === 409
  && (error?.data?.code === PLAN_DECISION_REQUIRED || error?.data?.action === 'record_decision')
);

/**
 * The only frontend entry point for committed execution-plan generation.
 * It lets the server decide whether this option already has a recorded
 * decision. A 409 opens one shared confirmation dialog, then the exact same
 * request is repeated with an option-scoped acknowledgement.
 */
export function useExecutionPlanBuild() {
  const { user, updateUiPreferences } = useAuth();
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
      verdict: details.verdict_label || details.verdict || 'move forward',
      skipNextTime: false,
    });
  }), []);

  const generateExecutionPlan = useCallback(async (threadId, payload = {}, options = {}) => {
    setExecutionPlanFailure(null);
    const committedPayload = { ...payload };
    const skipConfirmation = Boolean(user?.ui_preferences?.skip_plan_decision_confirm);
    if (skipConfirmation && committedPayload.commit !== false) {
      committedPayload.record_decision = {
        acknowledged: true,
        option_key: committedPayload?.record_decision?.option_key || null,
      };
    }

    try {
      return await Jaspen.generateAiWbs(threadId, committedPayload, options);
    } catch (error) {
      if (!isDecisionRequired(error) || committedPayload.commit === false) {
        if (error?.status === 503 && error?.data?.code === 'execution_plan_generation_failed') {
          setExecutionPlanFailure(error.data.error || "Jaspen couldn't finish building this plan — try again. Your existing plan was not changed.");
        }
        throw error;
      }
      const accepted = await askForDecision(error.data || {});
      if (!accepted?.acknowledged) return { cancelled: true };
      if (accepted.skipNextTime && typeof updateUiPreferences === 'function') {
        try {
          await updateUiPreferences({ skip_plan_decision_confirm: true });
        } catch (_) {
          // Preference persistence must never block the confirmed plan build.
        }
      }
      try {
        return await Jaspen.generateAiWbs(threadId, {
          ...committedPayload,
          record_decision: {
            acknowledged: true,
            option_key: accepted.optionKey || error?.data?.option_key || null,
          },
        }, options);
      } catch (buildError) {
        if (buildError?.status === 503 && buildError?.data?.code === 'execution_plan_generation_failed') {
          setExecutionPlanFailure(buildError.data.error || "Jaspen couldn't finish building this plan — try again. Your existing plan was not changed.");
        }
        throw buildError;
      }
    }
  }, [askForDecision, updateUiPreferences, user?.ui_preferences?.skip_plan_decision_confirm]);

  const executionPlanDecisionDialog = confirmation ? (
    <div className="jas-modal-backdrop" role="presentation" onClick={() => finishConfirmation({ acknowledged: false })}>
      <div className="jas-account-modal" role="dialog" aria-modal="true" aria-label="Record decision and build plan" onClick={(event) => event.stopPropagation()}>
        <div className="jas-account-modal-header">
          <h3>Build execution plan?</h3>
          <button type="button" className="jas-account-modal-close" onClick={() => finishConfirmation({ acknowledged: false })} aria-label="Close">×</button>
        </div>
        <p style={{ margin: '0 0 16px', color: 'var(--color-text-secondary)' }}>
          {/\b(?:no[-\s]?bid|decline)\b/i.test(String(confirmation.verdict || '')) ? (
            <>Building this plan records that you&apos;re moving forward with <strong>{confirmation.optionName}</strong>, overriding Jaspen&apos;s No-Bid recommendation. This is saved to your decision history.</>
          ) : (
            <>Building this plan records that you&apos;re moving forward with <strong>{confirmation.optionName}</strong> ({confirmation.verdict}). This is saved to your decision history.</>
          )}
        </p>
        <label style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 16 }}>
          <input
            type="checkbox"
            checked={Boolean(confirmation.skipNextTime)}
            onChange={(event) => setConfirmation((current) => ({ ...current, skipNextTime: event.target.checked }))}
          />
          Don&apos;t show this again
        </label>
        <div className="jas-account-modal-actions">
          <button type="button" className="jas-account-secondary-btn" onClick={() => finishConfirmation({ acknowledged: false })}>Cancel</button>
          <button
            type="button"
            className="jas-account-portal-btn"
            onClick={() => finishConfirmation({
              acknowledged: true,
              optionKey: confirmation.optionKey,
              skipNextTime: confirmation.skipNextTime,
            })}
          >
            Build plan
          </button>
        </div>
      </div>
    </div>
  ) : null;

  return { generateExecutionPlan, executionPlanDecisionDialog, executionPlanFailure };
}
