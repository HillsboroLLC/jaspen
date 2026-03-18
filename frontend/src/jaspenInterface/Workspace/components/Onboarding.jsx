import React, { useEffect, useMemo, useState } from 'react';

import './Onboarding.css';

const ROLE_OPTIONS = [
  { key: 'executive', label: 'Executive', description: 'I need quick tradeoff visibility, confidence, and decision-ready outputs.' },
  { key: 'pm', label: 'PM', description: 'I need sequencing, dependencies, ownership, and delivery risk surfaced clearly.' },
  { key: 'analyst', label: 'Analyst', description: 'I need structured evidence, assumptions, and a clean scoring rationale.' },
  { key: 'other', label: 'Other', description: 'I want Jaspen to adapt as we learn more about how I work.' },
];

const EVALUATION_OPTIONS = [
  { key: 'new_initiative', label: 'New initiative', description: 'Shape a fresh project or investment from first principles.' },
  { key: 'cost_optimization', label: 'Cost optimization', description: 'Find waste, tighten spend, and protect margin.' },
  { key: 'growth_strategy', label: 'Growth strategy', description: 'Prioritize expansion bets, upside, and leverage points.' },
  { key: 'operational_improvement', label: 'Operational improvement', description: 'Improve throughput, execution quality, and handoffs.' },
];

const START_OPTIONS = [
  { key: 'conversation', label: 'Start a conversation', description: 'Begin the normal intake flow in chat.' },
  { key: 'batch_ideas', label: 'Upload a list of ideas', description: 'Bring in a CSV or XLSX and rank ideas together.' },
  { key: 'data_upload', label: 'Upload data for analysis', description: 'Attach files first and let Jaspen pull insights from them.' },
];

export default function Onboarding({
  open,
  onComplete,
  onBack,
  onSkip,
  canGoBack = false,
  canSkip = false,
  busy = false,
  busyLabel = '',
  initialSelection = null,
  submitLabel = 'Start',
}) {
  const [stepIndex, setStepIndex] = useState(0);
  const [role, setRole] = useState('');
  const [evaluation, setEvaluation] = useState('');
  const [startMode, setStartMode] = useState('');

  useEffect(() => {
    if (!open) return;
    setStepIndex(0);
    setRole(String(initialSelection?.role || '').trim().toLowerCase());
    setEvaluation(String(initialSelection?.evaluation || '').trim().toLowerCase());
    setStartMode(String(initialSelection?.startMode || '').trim().toLowerCase());
  }, [open, initialSelection]);

  const steps = useMemo(
    () => [
      {
        title: "What's your role?",
        subtitle: 'This helps Jaspen shape the conversation for your point of view.',
        options: ROLE_OPTIONS,
        value: role,
        onSelect: setRole,
      },
      {
        title: 'What are you evaluating?',
        subtitle: 'We will use this to bias the readiness buckets and first questions.',
        options: EVALUATION_OPTIONS,
        value: evaluation,
        onSelect: setEvaluation,
      },
      {
        title: 'How would you like to start?',
        subtitle: 'Choose the entry point that matches how you want to work today.',
        options: START_OPTIONS,
        value: startMode,
        onSelect: setStartMode,
      },
    ],
    [role, evaluation, startMode]
  );

  if (!open) return null;

  const step = steps[stepIndex];
  const isLastStep = stepIndex === steps.length - 1;
  const isStepComplete = Boolean(step.value);
  const cardClassName = `jas-onboarding-card jas-onboarding-card-step-${stepIndex + 1}`;
  const secondaryLabel = stepIndex === 0
    ? (canGoBack ? 'Back' : canSkip ? 'Set up later' : 'Back')
    : 'Back';

  return (
    <div className="jas-onboarding-backdrop" role="presentation">
      <div className={cardClassName} role="dialog" aria-modal="true" aria-label="Jaspen onboarding">
        <div className="jas-onboarding-progress" aria-hidden="true">
          {steps.map((item, idx) => (
            <span
              key={item.title}
              className={`jas-onboarding-progress-dot ${idx === stepIndex ? 'active' : ''} ${idx < stepIndex ? 'complete' : ''}`}
            />
          ))}
        </div>

        <div className="jas-onboarding-header">
          <h3>{step.title}</h3>
          <p>{step.subtitle}</p>
        </div>

        <div className="jas-onboarding-options">
          {step.options.map((option) => (
            <button
              key={option.key}
              type="button"
              className={`jas-onboarding-option ${step.value === option.key ? 'selected' : ''}`}
              onClick={() => step.onSelect(option.key)}
              disabled={busy}
            >
              <span className="jas-onboarding-option-title-row">
                <span className="jas-onboarding-option-title">{option.label}</span>
                {step.value === option.key ? <span className="jas-onboarding-option-badge">Selected</span> : null}
              </span>
              {option.description ? (
                <span className="jas-onboarding-option-description">{option.description}</span>
              ) : null}
            </button>
          ))}
        </div>

        <div className="jas-onboarding-actions">
          <button
            type="button"
            className="jas-onboarding-secondary"
            onClick={() => {
              if (stepIndex === 0) {
                if (canGoBack) {
                  onBack?.();
                  return;
                }
                if (canSkip) {
                  onSkip?.();
                  return;
                }
                onBack?.();
                return;
              }
              setStepIndex((prev) => Math.max(0, prev - 1));
            }}
            disabled={(stepIndex === 0 && !canGoBack && !canSkip) || busy}
          >
            {secondaryLabel}
          </button>
          {!isLastStep ? (
            <button
              type="button"
              className="jas-onboarding-primary"
              onClick={() => setStepIndex((prev) => Math.min(steps.length - 1, prev + 1))}
              disabled={!isStepComplete || busy}
            >
              Continue
            </button>
          ) : (
            <button
              type="button"
              className="jas-onboarding-primary"
              onClick={() =>
                onComplete?.({
                  role,
                  evaluation,
                  startMode,
                })
              }
              disabled={!isStepComplete || busy}
            >
              {busy ? (busyLabel || 'Starting…') : submitLabel}
            </button>
          )}
        </div>
        {busy && busyLabel ? <p className="jas-onboarding-status">{busyLabel}</p> : null}
      </div>
    </div>
  );
}
