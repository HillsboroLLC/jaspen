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

function ExposureRow({ entry, showResolution = true }) {
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
      {showResolution && entry.resolution && (
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

  // Claims arrive in descending severity from exposure_claims, so the first is
  // the most consequential finding and the rest are context.
  const primaryClaim = claims[0] || null;
  const secondaryClaims = claims.slice(1);

  // The assumption with the most power to change the answer, and something to
  // do about it. Criteria are already sorted by swing, so the first resolvable
  // one is the highest-leverage action available.
  const primaryAction = (profile.criteria || []).find(
    (c) => c.resolvable && c.resolution && c.swing > 0,
  ) || null;

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
        {/* Says what the number measures, right under it. Without this, 57%
            reads as "Jaspen is 57% sure", which is a generic model-confidence
            reading and the opposite of the claim. It is a property of the
            evidence behind the weighted criteria, not of Jaspen's certainty. */}
        <p className="dcc-basis">Evidence-backed share of the weighted decision</p>
      </header>

      {/* 2. The finding. One sentence, promoted above everything else.
          exposure_claims already returns claims in descending severity, so the
          first is the most consequential thing Jaspen found. The rest are
          demoted to a quiet line so the card reads as an executive finding
          rather than a diagnostic report with five equal-weight results. */}
      {primaryClaim && (
        <div className="dcc-finding">
          <p className="dcc-finding-text">{primaryClaim.text}</p>
          {/* Detail only, never the finding itself. Rendered solely from a
              server-computed challenger, since it depends on the peer set. */}
          {challengers.map((challenger) => {
            // Who it would overtake is the leader, never the card being
            // viewed. Passing the current option here named it against itself
            // whenever the reader was already looking at the challenger.
            const leaderName = exposure?.leader?.name;
            const isThisOption = optionName && challenger.name === optionName;
            const points = `${challenger.gap} ${challenger.gap === 1 ? 'point' : 'points'}`;
            return (
              <p className="dcc-finding-detail" key={challenger.name}>
                {isThisOption ? 'This option' : <strong>{challenger.name}</strong>}
                {' '}trails{leaderName ? ` ${leaderName}` : ''} by {points}.
              </p>
            );
          })}
        </div>
      )}

      {/* 3. What to do about it. The resolution for the single assumption with
          the most power to change the answer, lifted out of the register so
          the reader does not have to find it. */}
      {primaryAction && (
        <div className="dcc-action">
          <p className="dcc-action-eyebrow">What would resolve it</p>
          <p className="dcc-action-text">
            <span className="dcc-action-criterion">{primaryAction.label}</span>
            {primaryAction.resolution}
          </p>
        </div>
      )}

      {secondaryClaims.length > 0 && (
        <p className="dcc-secondary-claims">
          {secondaryClaims.map((claim) => claim.text).join('. ')}.
        </p>
      )}

      {grouped.length > 0 && (
        <div className="dcc-register">
          <h4 className="dcc-subhead">Assumption exposure</h4>
          {grouped.map((group) => (
            <div className="dcc-group" key={group.key}>
              <p className={`dcc-group-heading dcc-group-${group.key}`}>{group.heading}</p>
              <ul className="dcc-rows">
                {group.entries.map((entry) => (
                  <ExposureRow
                    entry={entry}
                    key={entry.key}
                    // Already stated in full under "What would resolve it".
                    // Repeating it here reads as two separate instructions.
                    showResolution={entry.key !== primaryAction?.key}
                  />
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
