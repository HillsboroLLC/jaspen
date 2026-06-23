import React, { useMemo, useState } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faCheck } from '@fortawesome/free-solid-svg-icons';
import ChooseFocusStep from './ChooseFocusStep';
import CaptureContextStep from './CaptureContextStep';
import RefineInputsStep from './RefineInputsStep';
import ReviewStep from './ReviewStep';
import {
  emptyDraft,
  flowHasRefineStep,
  buildStructuredPrompt,
} from './guidedDecisionState';

const STEP_LABELS = ['Focus', 'Context', 'Refine', 'Review'];

// Logical step keys. The Refine step is conditionally present, so we resolve
// the visible sequence from the current draft rather than a fixed index.
const FULL_SEQUENCE = ['focus', 'context', 'refine', 'review'];

export default function GuidedDecisionWizard({ onUse, onClose }) {
  const [draft, setDraft] = useState(emptyDraft);
  const [stepKey, setStepKey] = useState('focus');
  const [reviewText, setReviewText] = useState('');
  const [editing, setEditing] = useState(false);

  const update = (patch) => setDraft((prev) => ({ ...prev, ...patch }));

  // Visible step sequence adapts to the chosen method.
  const sequence = useMemo(
    () => FULL_SEQUENCE.filter((k) => k !== 'refine' || flowHasRefineStep(draft)),
    [draft],
  );
  const currentIndex = sequence.indexOf(stepKey);

  // Map each logical step to its label index for the progress indicator.
  const labelIndexFor = (key) => FULL_SEQUENCE.indexOf(key);
  const activeLabelIndex = labelIndexFor(stepKey);

  const canAdvance = useMemo(() => {
    if (stepKey === 'focus') return Boolean(draft.focus) || draft.focusCustom.trim().length > 0;
    if (stepKey === 'context') {
      if (!draft.method) return false;
      // speak / type need at least some context captured; guided moves on freely
      if (draft.method === 'guided') return true;
      return draft.contextText.trim().length > 0;
    }
    return true;
  }, [stepKey, draft]);

  const goNext = () => {
    const next = sequence[currentIndex + 1];
    if (!next) return;
    if (next === 'review') {
      setReviewText(buildStructuredPrompt(draft));
      setEditing(false);
    }
    setStepKey(next);
  };

  const goBack = () => {
    const prev = sequence[currentIndex - 1];
    if (prev) setStepKey(prev);
  };

  const isReview = stepKey === 'review';

  return (
    <div className="gd-wizard">
      {/* Progress indicator */}
      <ol className="gd-progress" aria-label="Progress">
        {STEP_LABELS.map((label, i) => {
          const inFlow = i !== labelIndexFor('refine') || flowHasRefineStep(draft);
          const state =
            i < activeLabelIndex ? 'done' : i === activeLabelIndex ? 'active' : 'upcoming';
          return (
            <li
              key={label}
              className={`gd-progress-item gd-progress-item--${state}${inFlow ? '' : ' gd-progress-item--skipped'}`}
            >
              <span className="gd-progress-dot">
                {state === 'done' ? <FontAwesomeIcon icon={faCheck} /> : i + 1}
              </span>
              <span className="gd-progress-label">{label}</span>
            </li>
          );
        })}
      </ol>

      <div className="gd-wizard-body">
        {stepKey === 'focus' && <ChooseFocusStep draft={draft} update={update} />}
        {stepKey === 'context' && <CaptureContextStep draft={draft} update={update} />}
        {stepKey === 'refine' && <RefineInputsStep draft={draft} update={update} />}
        {stepKey === 'review' && (
          <ReviewStep value={reviewText} editing={editing} onChange={setReviewText} />
        )}
      </div>

      {/* Footer actions */}
      <div className="gd-wizard-footer">
        <div className="gd-footer-left">
          {currentIndex > 0 && (
            <button type="button" className="gd-btn gd-btn--ghost" onClick={goBack}>
              Back
            </button>
          )}
        </div>
        <div className="gd-footer-right">
          {isReview ? (
            <>
              <button
                type="button"
                className="gd-btn gd-btn--ghost"
                onClick={() => setEditing((v) => !v)}
              >
                {editing ? 'Done editing' : 'Edit'}
              </button>
              <button
                type="button"
                className="gd-btn gd-btn--primary"
                onClick={() => onUse(reviewText)}
              >
                Use This
              </button>
            </>
          ) : (
            <button
              type="button"
              className="gd-btn gd-btn--primary"
              onClick={goNext}
              disabled={!canAdvance}
            >
              {canAdvance ? 'Continue →' : 'Continue'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
