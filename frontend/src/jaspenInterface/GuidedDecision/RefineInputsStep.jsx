import React, { useState } from 'react';
import { GUIDED_QUESTIONS } from './guidedDecisionState';

// Accordion: one question open at a time so the step never feels overwhelming.
// A filled-but-collapsed question shows a checkmark and a preview of its answer.
export default function RefineInputsStep({ draft, update }) {
  const [openId, setOpenId] = useState(GUIDED_QUESTIONS[0].id);

  const setAnswer = (id, value) =>
    update({ answers: { ...draft.answers, [id]: value } });

  return (
    <div className="gd-step">
      <h2 className="gd-step-title">A few guided questions</h2>
      <p className="gd-step-sub">All optional — skip anything you&apos;re unsure about.</p>

      <div className="gd-accordion">
        {GUIDED_QUESTIONS.map((q, i) => {
          const open = openId === q.id;
          const answer = (draft.answers[q.id] || '').trim();
          return (
            <div className={`gd-acc-item${open ? ' gd-acc-item--open' : ''}`} key={q.id}>
              <button
                type="button"
                className="gd-acc-header"
                aria-expanded={open}
                onClick={() => setOpenId(open ? null : q.id)}
              >
                <span className={`gd-acc-num${answer ? ' gd-acc-num--done' : ''}`}>
                  {answer ? '✓' : i + 1}
                </span>
                <span className="gd-acc-label">
                  {q.short}
                  {!open && answer ? <span className="gd-acc-preview">{answer}</span> : null}
                </span>
                <span className="gd-acc-toggle" aria-hidden="true">{open ? '−' : '+'}</span>
              </button>
              {open && (
                <div className="gd-acc-body">
                  <p className="gd-acc-question">{q.label}</p>
                  <textarea
                    className="gd-textarea"
                    rows={3}
                    placeholder="Optional"
                    value={draft.answers[q.id]}
                    onChange={(e) => setAnswer(q.id, e.target.value)}
                    autoFocus
                  />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
