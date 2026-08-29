// The risk register.
//
// Scoring already captures a real register per risk: probability, impact in
// dollars, impact category, mitigation, mitigation cost, and residual risk.
// Until now the workspace rendered `risk` alone, joined by newlines into a
// textarea, so six of the seven fields were discarded at the point of display.
// Jaspen collected a register and showed a bulleted list of sentences.
//
// WHAT THE SHAPE IS FOR
//
// A risk is not a sentence, it is a position: how likely, how bad, what we
// would do about it, what that costs, and what is left after we do it. The
// last of those is the one a decision actually turns on, so residual sits
// beside the raw exposure rather than at the end of a paragraph.
//
// SYSTEM TRUTH VERSUS PRESENTATION, the same split the criteria use.
// Probability, impact, costs and residual are computed inputs and are not
// editable here. The description and the mitigation are narrative, so they can
// be rewritten, they are marked when they have been, and Jaspen's original is
// preserved and restorable. Editing wording never moves a number.

import React, { useState } from 'react';
import './RiskRegister.css';

const LEVEL_ORDER = { High: 3, Medium: 2, Low: 1 };

const IMPACT_CATEGORY_LABELS = {
  financial_health: 'Financial',
  operational_efficiency: 'Operational',
  market_position: 'Market',
  execution_readiness: 'Execution',
};

// Money is shown at the precision a decision uses. Nobody allocates against
// $2,100,000.00, and the extra digits cost scanning speed.
function money(value) {
  const amount = Number(String(value ?? '').replace(/[^0-9.-]/g, ''));
  if (!Number.isFinite(amount)) return null;
  if (amount === 0) return 'No cost';
  if (Math.abs(amount) >= 1_000_000) return `$${(amount / 1_000_000).toFixed(1)}M`;
  if (Math.abs(amount) >= 1_000) return `$${Math.round(amount / 1_000)}K`;
  return `$${amount}`;
}

function Level({ value, label }) {
  if (!value) return null;
  return (
    <span className={`rr-level rr-level-${String(value).toLowerCase()}`}>
      <span className="rr-level-label">{label}</span>
      {value}
    </span>
  );
}

function RiskRow({ risk, editable, onEdit, onRestore }) {
  const [draft, setDraft] = useState(null);
  const impact = money(risk.impact_dollars ?? risk.impact);
  const mitigationCost = money(risk.mitigation_cost);

  const startEdit = () => setDraft({
    risk: risk.risk || '',
    mitigation: risk.mitigation || '',
  });

  return (
    <li className="rr-row">
      <div className="rr-head">
        {draft ? (
          <textarea
            className="rr-input"
            rows={2}
            autoFocus
            value={draft.risk}
            onChange={(e) => setDraft({ ...draft, risk: e.target.value })}
            aria-label="Risk description"
          />
        ) : (
          <p className="rr-risk">
            {risk.risk || 'Untitled risk'}
            {risk._edited && (
              <span className="rr-edited" title="Edited by a person. Jaspen's original wording is preserved.">
                Edited
              </span>
            )}
          </p>
        )}
      </div>

      {/* The position, before the narrative. These are computed and are not
          editable from here: a rewritten sentence must never move a number. */}
      <div className="rr-levels">
        <Level value={risk.probability} label="Likelihood" />
        {impact && (
          <span className="rr-metric">
            <span className="rr-metric-label">Impact</span>
            {impact}
            {risk.impact_category && (
              <span className="rr-cat">{IMPACT_CATEGORY_LABELS[risk.impact_category] || risk.impact_category}</span>
            )}
          </span>
        )}
        <Level value={risk.residual_risk} label="After mitigation" />
      </div>

      {(risk.mitigation || draft) && (
        <div className="rr-mitigation">
          <p className="rr-block-label">Mitigation</p>
          {draft ? (
            <textarea
              className="rr-input"
              rows={2}
              value={draft.mitigation}
              onChange={(e) => setDraft({ ...draft, mitigation: e.target.value })}
              aria-label="Mitigation"
            />
          ) : (
            <p className="rr-block-text">
              {risk.mitigation}
              {mitigationCost && <span className="rr-cost">{mitigationCost} to mitigate</span>}
            </p>
          )}
        </div>
      )}

      {draft ? (
        <div className="rr-actions">
          <button
            type="button"
            className="rr-save"
            onClick={() => { onEdit(risk.id, draft); setDraft(null); }}
          >
            Save wording
          </button>
          <button type="button" className="rr-cancel" onClick={() => setDraft(null)}>
            Cancel
          </button>
          <span className="rr-hint">
            Wording only. Likelihood, impact, cost and residual risk are unchanged.
          </span>
        </div>
      ) : (
        <div className="rr-actions">
          {editable && (
            <button type="button" className="rr-edit" onClick={startEdit}>Edit wording</button>
          )}
          {risk._edited && (
            <>
              {risk._original_risk && (
                <details className="rr-original">
                  <summary>Jaspen&apos;s original wording</summary>
                  <p>{risk._original_risk}</p>
                  {risk._original_mitigation && (
                    <p><strong>Mitigation:</strong> {risk._original_mitigation}</p>
                  )}
                </details>
              )}
              <button type="button" className="rr-restore" onClick={() => onRestore(risk.id)}>
                Restore original
              </button>
            </>
          )}
        </div>
      )}
    </li>
  );
}

export default function RiskRegister({ risks, editable = false, onEdit, onRestore }) {
  const items = Array.isArray(risks) ? risks.filter(Boolean) : [];
  if (!items.length) {
    return <p className="rr-empty">No risks recorded for this decision.</p>;
  }

  // Ordered by what survives mitigation, then by raw exposure. A register
  // sorted by how alarming a risk sounds before mitigation puts the ones
  // already handled at the top, which is the opposite of useful.
  const ordered = [...items].sort((a, b) => {
    const residual = (LEVEL_ORDER[b.residual_risk] || 0) - (LEVEL_ORDER[a.residual_risk] || 0);
    if (residual) return residual;
    const impact = (Number(b.impact_numeric) || 0) - (Number(a.impact_numeric) || 0);
    if (impact) return impact;
    return (LEVEL_ORDER[b.probability] || 0) - (LEVEL_ORDER[a.probability] || 0);
  });

  return (
    <ul className="rr">
      {ordered.map((risk, index) => (
        <RiskRow
          key={risk.id || index}
          risk={risk}
          editable={editable}
          onEdit={onEdit}
          onRestore={onRestore}
        />
      ))}
    </ul>
  );
}
