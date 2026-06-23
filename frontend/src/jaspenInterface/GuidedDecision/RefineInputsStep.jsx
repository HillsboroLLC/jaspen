import React from 'react';
import { GUIDED_QUESTIONS } from './guidedDecisionState';

export default function RefineInputsStep({ draft, update }) {
  const setAnswer = (id, value) =>
    update({ answers: { ...draft.answers, [id]: value } });

  return (
    <div className="gd-step">
      <h2 className="gd-step-title">A few guided questions</h2>
      <p className="gd-step-sub">All optional — skip anything you&apos;re unsure about.</p>

      <div className="gd-questions">
        {GUIDED_QUESTIONS.map((q, i) => (
          <div className="gd-question" key={q.id}>
            <label htmlFor={`gd-q-${q.id}`} className="gd-question-label">
              <span className="gd-question-num">{i + 1}</span>
              {q.label}
            </label>
            <textarea
              id={`gd-q-${q.id}`}
              className="gd-textarea"
              rows={2}
              placeholder="Optional"
              value={draft.answers[q.id]}
              onChange={(e) => setAnswer(q.id, e.target.value)}
            />
          </div>
        ))}
      </div>
    </div>
  );
}
