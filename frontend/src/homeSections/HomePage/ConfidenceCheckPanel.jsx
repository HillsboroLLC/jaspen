// The first-run Confidence Check, as a finding rather than a checklist.
//
// The panel this replaces listed every readiness category with a tick or an
// empty circle. That reads as a form reporting what the visitor failed to
// supply, which is the cold-start problem this work exists to fix: Jaspen's
// own mechanic means a first-time visitor with thin context gets the least
// impressive result, exactly when they are deciding whether to stay.
//
// So the order here is the product decision, and it is deliberate:
//
//   1. What Jaspen can already see        something gained, from one sentence
//   2. The biggest gaps, and what closes them
//   3. Why those gaps matter              the cap mechanic, the actual "aha"
//   4. Context coverage                   supporting, and last
//
// Every number and sentence comes from the server's confidence_check payload.
// Nothing here composes a new claim: claims arrive rendered from
// app/confidence_check.py::check_claims so the homepage, the workspace and
// any export cannot drift into three different vocabularies for one
// computation.
//
// CONTEXT COVERAGE IS NOT DECISION CONFIDENCE. Nothing is scored before
// signup, so no evidence-backed percentage exists. Coverage is styled
// deliberately as a quiet footer metric, never as a headline score or a
// progress ring, so it cannot be mistaken for one. Read
// app/confidence_check.py before changing anything in this file.

import React from 'react';
import './ConfidenceCheckPanel.css';

// Friendlier homepage wording for the server's category labels. A
// presentation-only overlay: any key not listed falls back to the server's
// own label, so a change to the active readiness spec cannot break this.
const FRIENDLY_GAP_LABELS = {
  goal_definition: 'A clear goal with a target',
  evidence_baseline: 'Evidence behind the numbers',
  sme_drivers: 'Who is involved, and why',
  system_mapping: 'How it works end to end',
  constraint_unlock: 'The constraint in the way',
  execution_sequence: 'A rough sequence of work',
  replication_plan: 'How this repeats elsewhere',
  problem_clarity: 'A clear problem to solve',
  market_context: 'Who this is for',
  business_model: 'How this creates value',
  execution_plan: 'A timeline and the resources',
};

const CLAIM_KIND_ORDER = ['evidence_baseline', 'cap_consequence', 'blocking'];

function gapLabel(gap) {
  return FRIENDLY_GAP_LABELS[gap.key] || gap.label;
}

export default function ConfidenceCheckPanel({ check }) {
  if (!check) return null;

  const { covered = [], gaps = [], evidence_baseline: baseline } = check;
  const claims = Array.isArray(check.claims) ? check.claims : [];
  const byKind = Object.fromEntries(claims.map((c) => [c.kind, c]));

  // Blocking gates first, then the heaviest remaining gaps. The server has
  // already ranked them; this only limits how many are shown at once.
  const shownGaps = gaps.slice(0, 4);
  const present = baseline?.present || [];
  const missing = baseline?.missing || [];

  const findings = CLAIM_KIND_ORDER
    .map((kind) => byKind[kind])
    .filter(Boolean);

  return (
    <section className="ccp" aria-label="Confidence check">
      <header className="ccp-head">
        <p className="ccp-eyebrow">Confidence check</p>
        <h3 className="ccp-title">What Jaspen can already see</h3>
      </header>

      {/* 1. Something gained. Present before absent, always. */}
      {(present.length > 0 || covered.length > 0) && (
        <div className="ccp-block">
          <ul className="ccp-list ccp-list-present">
            {present.map((item) => (
              <li key={item.key}>
                <i className="fa-solid fa-check" aria-hidden="true" />
                <span>{item.label}</span>
              </li>
            ))}
            {covered.map((item) => (
              <li key={item.key}>
                <i className="fa-solid fa-check" aria-hidden="true" />
                <span>{FRIENDLY_GAP_LABELS[item.key] || item.label}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* 2. The gaps, and what would close them. */}
      {shownGaps.length > 0 && (
        <div className="ccp-block">
          <h4 className="ccp-subhead">What would strengthen this</h4>
          <ul className="ccp-list ccp-list-gaps">
            {shownGaps.map((gap) => (
              <li key={gap.key} className={gap.required ? 'is-blocking' : ''}>
                <span className="ccp-gap-label">{gapLabel(gap)}</span>
                {gap.required && <span className="ccp-tag">Needed first</span>}
              </li>
            ))}
          </ul>
          {missing.length > 0 && (
            <p className="ccp-note">
              Your evidence baseline is missing {missing.length} of{' '}
              {present.length + missing.length} parts:{' '}
              {missing.map((m) => m.label.toLowerCase()).join(', ')}.
            </p>
          )}
        </div>
      )}

      {/* 3. Why it matters. The mechanic, quoted from the server. */}
      {findings
        .filter((claim) => claim.kind === 'cap_consequence')
        .map((claim) => (
          <div className="ccp-mechanic" key={claim.kind}>
            <p>{claim.text}</p>
          </div>
        ))}

      {/* 4. Coverage. Supporting information, deliberately last and quiet.
          Never a ring, a big number, or anything that reads as a score. */}
      {byKind.coverage && (
        <footer className="ccp-coverage">
          <span className="ccp-coverage-text">{byKind.coverage.text}</span>
        </footer>
      )}
    </section>
  );
}
