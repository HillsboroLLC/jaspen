import React from 'react';
import { STEPS } from '../config/questions';

// Accessible multi-step progress indicator. Announces current step to screen
// readers and shows a filled track for completed/current steps.
export default function Stepper({ current, onStepClick }) {
  const total = STEPS.length;
  return (
    <nav aria-label="Progress" className="cot-progress-wrap">
      <p className="cot-sr-only" role="status" aria-live="polite">
        Step {current + 1} of {total}: {STEPS[current].title}
      </p>
      <ol className="cot-stepper">
        {STEPS.map((s) => {
          const state = s.index < current ? 'complete' : s.index === current ? 'current' : 'upcoming';
          const clickable = typeof onStepClick === 'function' && s.index <= current;
          return (
            <li key={s.id} className="cot-step-pill" data-state={state}>
              <button
                type="button"
                className="cot-step-btn"
                onClick={clickable ? () => onStepClick(s.index) : undefined}
                aria-current={state === 'current' ? 'step' : undefined}
                disabled={!clickable}
                style={{ cursor: clickable ? 'pointer' : 'default' }}
              >
                <span className="cot-step-track" aria-hidden="true">
                  <span
                    className="cot-step-fill"
                    style={{ width: state === 'upcoming' ? '0%' : '100%' }}
                  />
                </span>
                <span className="cot-step-meta">
                  <span className="cot-step-num">Step {s.index + 1}</span>
                  <span className="cot-step-label">{s.short}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
