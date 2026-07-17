import React from 'react';

// Accessible multi-step progress indicator. `steps` is [{id, short, title}].
export default function Stepper({ steps, current, onStepClick }) {
  const total = steps.length;
  return (
    <nav aria-label="Progress">
      <p className="tool-sr-only" role="status" aria-live="polite">
        Step {current + 1} of {total}: {steps[current].title}
      </p>
      <ol className="tool-stepper">
        {steps.map((s, index) => {
          const state = index < current ? 'complete' : index === current ? 'current' : 'upcoming';
          const clickable = typeof onStepClick === 'function' && index <= current;
          return (
            <li key={s.id} className="tool-step-pill" data-state={state}>
              <button
                type="button"
                className="tool-step-btn"
                onClick={clickable ? () => onStepClick(index) : undefined}
                aria-current={state === 'current' ? 'step' : undefined}
                disabled={!clickable}
                style={{ cursor: clickable ? 'pointer' : 'default' }}
              >
                <span className="tool-step-track" aria-hidden="true">
                  <span className="tool-step-fill" style={{ width: state === 'upcoming' ? '0%' : '100%' }} />
                </span>
                <span className="tool-step-meta">
                  <span className="tool-step-num">Step {index + 1}</span>
                  <span className="tool-step-label">{s.short}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
