import React from 'react';
import './StarterDecisionChips.css';

export const STARTER_DECISIONS = [
  {
    id: 'job-offer',
    label: 'Accept a Job Offer',
    prompt: `I need to decide whether to accept a job offer, stay in my current role, or keep looking for a better fit.

Please help me build an editable decision rubric for this choice. The natural tradeoffs include compensation, manager quality, role scope, growth path, company stability, work-life fit, location or flexibility, and long-term career direction.

Do not assume facts I have not provided. Start with a sensible starter rubric that I can edit, then ask me the single highest-value missing question that would most improve the scorecard.`,
  },
  {
    id: 'start-business',
    label: 'Start a Business',
    prompt: `I need to decide whether to start a business now, keep validating the idea before committing, or choose a different path.

Please help me build an editable decision rubric for this choice. The natural tradeoffs include customer demand, differentiation, startup cost, time commitment, financial risk, execution capacity, personal runway, and the evidence I have so far.

Do not invent market facts or financial assumptions. Start with a sensible starter rubric that I can edit, then ask me the single highest-value missing question that would most improve the scorecard.`,
  },
  {
    id: 'quarterly-investments',
    label: "Prioritize Next Quarter's Investments",
    prompt: `I need to decide which investments to prioritize next quarter across several competing options.

Please help me build an editable decision rubric for comparing the alternatives. The natural tradeoffs include strategic alignment, expected impact, cost, timeline, operational capacity, implementation risk, dependencies, and confidence in the available evidence.

Do not assume the options or numbers yet. Start with a sensible starter rubric that I can edit, then ask me the single highest-value missing question that would most improve the scorecard.`,
  },
];

export default function StarterDecisionChips({ onSelect }) {
  return (
    <div className="starter-decisions" aria-label="Example decisions">
      <p className="starter-decisions-label">Not sure where to begin? Try an example decision.</p>
      <div className="starter-decisions-list">
        {STARTER_DECISIONS.map((item) => (
          <button
            key={item.id}
            type="button"
            className="starter-decision-chip"
            onClick={() => onSelect(item)}
          >
            {item.label}
          </button>
        ))}
      </div>
    </div>
  );
}
