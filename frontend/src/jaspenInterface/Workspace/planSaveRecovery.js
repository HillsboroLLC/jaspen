import { useCallback, useRef } from 'react';
import {
  Jaspen,
  isInvalidTaskDate,
  isRevisionConflict,
  REVISION_CONFLICT_MESSAGE,
} from './JaspenClient';

export function isRejectedPlanSave(error) {
  if (isRevisionConflict(error) || isInvalidTaskDate(error)) return true;
  const status = Number(error?.status);
  return Number.isFinite(status) && status >= 400 && status < 500 && status !== 408 && status !== 429;
}

export function rejectedPlanSaveMessage(error, latestShown = true) {
  if (isRevisionConflict(error)) {
    return latestShown
      ? REVISION_CONFLICT_MESSAGE
      : "This project has newer changes. Your change wasn't saved, and the latest saved version couldn't be loaded.";
  }
  if (isInvalidTaskDate(error)) return "That task date is invalid. Your change wasn't saved.";
  if (error?.status === 401 || error?.status === 403) {
    return "You don't have permission to change this plan. Your change wasn't saved.";
  }
  const reason = String(error?.message || error?.data?.error || 'That change was rejected')
    .trim()
    .replace(/[.\s]+$/, '');
  return `${reason}. Your change wasn't saved.`;
}

// Tracks writes started by one mounted editor. A rejected edit can then wait
// for that editor's already-queued writes before reading the authoritative plan.
// This deliberately leaves JaspenClient's project-scoped B1 queue unchanged.
export function usePlanWriteRecovery() {
  const pendingWritesRef = useRef(new Set());
  const recoveryRef = useRef(null);

  const trackPlanWrite = useCallback((writePromise) => {
    const tracked = Promise.resolve(writePromise);
    pendingWritesRef.current.add(tracked);
    tracked.then(
      () => pendingWritesRef.current.delete(tracked),
      () => pendingWritesRef.current.delete(tracked),
    );
    return tracked;
  }, []);

  const loadLatestSavedPlan = useCallback((threadId, scorecardId = null) => {
    if (recoveryRef.current) return recoveryRef.current;
    const recovery = (async () => {
      let response = null;
      do {
        while (pendingWritesRef.current.size > 0) {
          await Promise.allSettled(Array.from(pendingWritesRef.current));
        }
        response = await Jaspen.getThreadWbs(threadId, scorecardId);
      } while (pendingWritesRef.current.size > 0);
      return response?.project_wbs || null;
    })();
    recoveryRef.current = recovery;
    recovery.then(
      () => { if (recoveryRef.current === recovery) recoveryRef.current = null; },
      () => { if (recoveryRef.current === recovery) recoveryRef.current = null; },
    );
    return recovery;
  }, []);

  return { trackPlanWrite, loadLatestSavedPlan };
}
