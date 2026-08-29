// Decision Confidence and Assumption Exposure for a scored option.
//
// Replaces the "Data confidence" bar, which was a six pixel strip reporting a
// bare percentage with no explanation of what it measured or what to do about
// it. It read as a system health indicator. This reports a finding about the
// user's decision instead.
//
// Three sections, in the order the reader needs them:
//
//   1. Decision Confidence   the measurement, evidenced against assumed
//   2. Assumption Exposure   the actionable finding, ranked by what it moves
//   3. Evidence needed       the resolution path, per assumption
//
// EVERY NUMBER AND SENTENCE COMES FROM THE SERVER. The evidence split, the
// swing, the severity tier and the rendered claims are all computed in
// app/decision_confidence.py. Nothing here derives a figure, and nothing here
// composes a claim, because a second implementation would drift from the
// arithmetic it is supposed to describe. If a statement is needed that the
// payload does not carry, add it to exposure_claims() rather than writing it
// in JSX.
//
// TWO DISTINCTIONS THIS UI MUST NOT COLLAPSE
//
// Weak evidence is not the same as score exposure. A criterion can rest on
// thin evidence while moving the score by nothing at all, because the model's
// judgment already sat at or below its cap. Those criteria carry severity
// "none" and stay out of the exposure register, but they can still be worth
// resolving, so their evidence grade is still shown in the breakdown. Never
// render "no score exposure" as "the evidence is fine".
//
// Reversal is upside only. The arithmetic supports "resolving this could lift
// another option above the leader". It does not support "if this assumption is
// wrong the plan fails", because nothing models a downside floor. Do not add
// language implying the second.

import React, { useMemo, useState } from 'react';
import './DecisionConfidenceCard.css';

// Plain-language headings for the severity tiers. The taxonomy is engineering
// vocabulary and should not be read by a user: they see grouped sections, not
// tier names.
const EXPOSURE_GROUPS = [
  {
    key: 'reversing',
    tiers: ['reversing'],
    heading: 'Could change which option leads',
  },
  {
    key: 'material',
    tiers: ['material'],
    heading: 'Could materially change the score',
  },
  {
    key: 'other',
    tiers: ['other'],
    heading: 'Smaller exposure',
  },
];

const GRADE_LABELS = {
  high: 'Strong evidence',
  medium: 'Some evidence',
  low: 'Thin evidence',
  assumed: 'Assumed',
};

function pointsLabel(swing) {
  const rounded = Math.round(swing * 10) / 10;
  return `${rounded} ${rounded === 1 ? 'point' : 'points'}`;
}

function ExposureRow({ entry }) {
  return (
    <li className="dcc-row">
      <div className="dcc-row-head">
        <span className="dcc-row-label">{entry.label}</span>
        <span className="dcc-row-swing" title="How far the score could move if this evidence were obtained">
          {pointsLabel(entry.swing)}
        </span>
      </div>
      <div className="dcc-row-meta">
        <span className={`dcc-grade dcc-grade-${entry.confidence}`}>
          {GRADE_LABELS[entry.confidence] || entry.confidence}
        </span>
        <span className="dcc-row-weight">
          {Math.round(entry.weight * 100)}% of this decision
        </span>
      </div>
      {entry.resolution && (
        <p className="dcc-row-resolution">
          <span className="dcc-resolution-tag">Evidence needed</span>
          {entry.resolution}
        </p>
      )}
    </li>
  );
}

export default function DecisionConfidenceCard({ profile, exposure, optionName }) {
  const [showAll, setShowAll] = useState(false);

  const grouped = useMemo(() => {
    const criteria = profile?.criteria || [];
    return EXPOSURE_GROUPS
      .map((group) => ({
        ...group,
        entries: criteria.filter((c) => group.tiers.includes(c.severity)),
      }))
      .filter((group) => group.entries.length > 0);
  }, [profile]);

  // Criteria the evidence already supports, or whose judgment sits at its own
  // cap. Held back from the register because they are not assumptions the
  // decision depends on, but still reachable, because a thin grade here is
  // worth knowing even when it moves nothing today.
  const settled = useMemo(
    () => (profile?.criteria || []).filter((c) => c.severity === 'none'),
    [profile],
  );

  if (!profile) return null;

  const backed = profile.evidence_backed_pct;
  const assumed = profile.assumption_dependent_pct;
  const claims = Array.isArray(profile.claims) ? profile.claims : [];
  const challengers = exposure?.challengers || [];

  return (
    <section className="dcc card-shell" aria-label="Decision confidence">
      <header className="dcc-head">
        <p className="dcc-eyebrow">Decision Confidence</p>
        <p className="dcc-headline">
          <strong>{backed}%</strong> evidence-backed
          <span className="dcc-sep" aria-hidden="true">·</span>
          <strong>{assumed}%</strong> assumption-dependent
        </p>
        <div className="dcc-split" role="img"
          aria-label={`${backed} percent evidence-backed, ${assumed} percent assumption-dependent`}>
          <span className="dcc-split-backed" style={{ width: `${backed}%` }} />
          <span className="dcc-split-assumed" style={{ width: `${assumed}%` }} />
        </div>
      </header>

      {claims.length > 0 && (
        <ul className="dcc-claims">
          {claims.map((claim) => (
            <li key={claim.kind}>{claim.text}</li>
          ))}
        </ul>
      )}

      {/* Reversal. Only ever rendered from a server-computed challenger, since
          it depends on the peer set and no single scorecard can establish it. */}
      {challengers.length > 0 && (
        <div className="dcc-reversal">
          {challengers.map((challenger) => {
            // Who it would overtake is the leader, never the card being
            // viewed. Passing the current option here named it against itself
            // whenever the reader was already looking at the challenger.
            const leaderName = exposure?.leader?.name;
            const isThisOption = optionName && challenger.name === optionName;
            const points = `${challenger.gap} ${challenger.gap === 1 ? 'point' : 'points'}`;
            return (
              <p key={challenger.name}>
                {isThisOption ? 'This option' : <strong>{challenger.name}</strong>}
                {' '}trails{leaderName ? ` ${leaderName}` : ''} by {points}. Resolving{' '}
                {challenger.assumptions[0].label.toLowerCase()} could put it ahead.
              </p>
            );
          })}
        </div>
      )}

      {grouped.length > 0 && (
        <div className="dcc-register">
          <h4 className="dcc-subhead">Assumption exposure</h4>
          {grouped.map((group) => (
            <div className="dcc-group" key={group.key}>
              <p className={`dcc-group-heading dcc-group-${group.key}`}>{group.heading}</p>
              <ul className="dcc-rows">
                {group.entries.map((entry) => (
                  <ExposureRow entry={entry} key={entry.key} />
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}

      {settled.length > 0 && (
        <div className="dcc-settled">
          <button
            type="button"
            className="dcc-settled-toggle"
            onClick={() => setShowAll((v) => !v)}
            aria-expanded={showAll}
          >
            {showAll ? 'Hide' : 'Show'} {settled.length} criteria not moving the score
          </button>
          {showAll && (
            <ul className="dcc-settled-list">
              {settled.map((entry) => (
                <li key={entry.key}>
                  <span className="dcc-settled-label">{entry.label}</span>
                  <span className={`dcc-grade dcc-grade-${entry.confidence}`}>
                    {GRADE_LABELS[entry.confidence] || entry.confidence}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {showAll && (
            <p className="dcc-settled-note">
              Resolving these would not move the score today. Where the evidence
              is thin, it can still be worth strengthening.
            </p>
          )}
        </div>
      )}
    </section>
  );
}
