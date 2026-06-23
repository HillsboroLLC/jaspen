import React, { useMemo, useState } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faCheck } from '@fortawesome/free-solid-svg-icons';
import ChooseFocusStep from './ChooseFocusStep';
import RefineInputsStep from './RefineInputsStep';
import ReviewStep from './ReviewStep';
import { emptyDraft, buildStructuredPrompt } from './guidedDecisionState';

const STEP_LABELS = ['Focus', 'Questions', 'Review'];

// Guided Decision is a secondary, optional aid for organizing thoughts: pick a
// focus, answer a few optional questions, review, and hand the result to chat.
const SEQUENCE = ['focus', 'questions', 'review'];

export default function GuidedDecisionWizard({ onUse, onClose }) {
  const [draft, setDraft] = useState(emptyDraft);
  const [stepKey, setStepKey] = useState('focus');
  const [reviewText, setReviewText] = useState('');
  const [editing, setEditing] = useState(false);

  // Accepts a plain patch object or a function of the previous draft (the
  // latter is needed for appends like live dictation, which must build on the
  // latest value rather than a stale snapshot).
  const update = (patch) =>
    setDraft((prev) => ({ ...prev, ...(typeof patch === 'function' ? patch(prev) : patch) }));

  const currentIndex = SEQUENCE.indexOf(stepKey);

  const canAdvance = useMemo(() => {
    if (stepKey === 'focus') return Boolean(draft.focus) || draft.focusCustom.trim().length > 0;
    return true; // questions are optional
  }, [stepKey, draft]);

  const goNext = () => {
    const next = SEQUENCE[currentIndex + 1];
    if (!next) return;
    if (next === 'review') {
      setReviewText(buildStructuredPrompt(draft));
      setEditing(false);
    }
    setStepKey(next);
  };

  const goBack = () => {
    const prev = SEQUENCE[currentIndex - 1];
    if (prev) setStepKey(prev);
  };

  const isReview = stepKey === 'review';

  return (
    <div className="gd-wizard">
      {/* Progress indicator */}
      <ol className="gd-progress" aria-label="Progress">
        {STEP_LABELS.map((label, i) => {
          const state =
            i < currentIndex ? 'done' : i === currentIndex ? 'active' : 'upcoming';
          return (
            <li key={label} className={`gd-progress-item gd-progress-item--${state}`}>
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
        {stepKey === 'questions' && <RefineInputsStep draft={draft} update={update} />}
        {stepKey === 'review' && (
          <ReviewStep value={reviewText} editing={editing} onChange={setReviewText} />
        )}
      </div>

      {/* Footer actions */}
      <div className="gd-wizard-footer">
        <div className="gd-footer-left">
          <button
            type="button"
            className="gd-back-link"
            onClick={currentIndex > 0 ? goBack : onClose}
          >
            Back
          </button>
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
              Continue
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
