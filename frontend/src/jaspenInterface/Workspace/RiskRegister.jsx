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

// Money at the precision a decision uses. Nobody allocates against
// $2,100,000.00, and the extra digits cost scanning speed.
//
// Missing is NOT zero, and an earlier version rendered both as "No cost".
// Number('') is 0 in JavaScript, so an unrecorded mitigation cost claimed the
// mitigation was free. A cost nobody has estimated and a cost of nothing are
// different findings, and the free one is the rarer and more interesting.
function money(value) {
  if (value === null || value === undefined || String(value).trim() === '') return null;
  const amount = Number(String(value).replace(/[^0-9.-]/g, ''));
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
        <Level value={risk.residual_risk} label="If mitigated" />
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

  // Ordered by UNMITIGATED exposure: impact first, then likelihood.
  //
  // Residual was the primary sort and that was wrong. Nothing in the system
  // records whether a mitigation has actually been carried out: scoring asks
  // for a residual level and never defines it, and there is no mitigation
  // status field anywhere. So residual is at best the expected level IF the
  // plan is executed, and sorting by it silently demoted a $2.1M risk on the
  // strength of a plan nobody has confirmed was started.
  //
  // Impact and likelihood are what is actually known, so they order the
  // register. Residual is still shown, labelled as conditional.
  const ordered = [...items].sort((a, b) => {
    const impact = (Number(b.impact_numeric) || 0) - (Number(a.impact_numeric) || 0);
    if (impact) return impact;
    const likelihood = (LEVEL_ORDER[b.probability] || 0) - (LEVEL_ORDER[a.probability] || 0);
    if (likelihood) return likelihood;
    return (LEVEL_ORDER[b.residual_risk] || 0) - (LEVEL_ORDER[a.residual_risk] || 0);
  });

  return (
    <>
      {/* Says what the order means and what the residual level assumes.
          Without it a reader takes "If mitigated: Low" for "this is handled". */}
      <p className="rr-basis">
        Ordered by unmitigated exposure. Residual assumes the mitigation is
        carried out; Jaspen does not track whether it has been.
      </p>
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
    </>
  );
}
