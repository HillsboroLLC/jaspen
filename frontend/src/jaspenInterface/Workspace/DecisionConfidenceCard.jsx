// The Decision Confidence report.
//
// Two layers, both visible. A summary that answers the decision at a glance,
// then the full evidence and assumption detail for every weighted criterion.
//
//   Summary        a briefing composed server-side from computed values:
//                  the verdict, standing, the evidence split, where exposure
//                  sits, what could change the answer, and what to do next.
//                  Prose, because it is meant to be quoted into a room, and
//                  deliberately not the first rows of the detail below.
//   Detail         per criterion: weight, grade, exposure, what Jaspen based
//                  the judgment on, what remains unsupported, what evidence
//                  would resolve it, and whether resolving it could change
//                  the score or the ranking
//
// NOTHING IMPORTANT IS COLLAPSED. An earlier version hid most criteria behind
// "Show 5 criteria", which buried the evidence story, and the evidence story
// is the product. A reader scrolls the report; they do not hunt for it.
//
// PROVENANCE LIMIT, the constraint that shapes this whole file. Scoring
// records only two things about why a criterion scored as it did:
//
//   source     the CHANNEL an input arrived on: conversation, connector,
//              inferred, or assumed. It does not identify which input.
//   rationale  the model's own account of its reasoning. Reasoning, not a
//              record of evidence.
//
// Nothing retains which document, message, connector field, or figure a score
// rested on. So this report says "Jaspen's assessment" and shows the model's
// reasoning plus a hedged characterisation of the channel. It must never
// render a list of evidence held, attribute a figure to a source, or imply an
// audit trail.
// Manufacturing that would produce precisely the confident, unsupported
// content the product exists to expose. See app/decision_confidence.py.
//
// Everything numeric comes from the server. Nothing here derives a figure or
// composes a claim; claims arrive rendered from exposure_claims() so the
// workspace, exports and email cannot drift into three vocabularies.
//
// TWO DISTINCTIONS THAT MUST NOT COLLAPSE
//
// Weak evidence is not score exposure. A criterion can rest on thin evidence
// while moving the score by nothing, because the judgment already sat at or
// below its cap. Those are reported as not materially affecting the score,
// never as evidence being fine.
//
// Reversal is upside only. The arithmetic supports "resolving this could lift
// another option above the leader". It does not support "if this assumption is
// wrong the plan fails", because nothing models a downside floor.

import React from 'react';
import './DecisionConfidenceCard.css';

const GRADE_LABELS = {
  high: 'Strong evidence',
  medium: 'Moderate evidence',
  low: 'Thin evidence',
  assumed: 'Assumed',
};

// How Jaspen characterises the input it used. Every one of these is hedged on
// purpose, because `source` is the model's own claim about where something came
// from and nothing verifies it.
//
// "From connected data" used to sit here and it was actively misleading: it
// reads as "Jaspen retrieved this from a system you connected", which is a
// factual assertion about system state that this field cannot support. Even on
// a real scoring run the value is the model saying so, not a retrieval record.
// Hedged wording stays until evidence references are actually captured, at
// which point the specific source can be named and these can be retired.
const ASSESSMENT_BASIS = {
  conversation: 'Based on what you described',
  connector: 'Jaspen reports drawing on connected data',
  inferred: 'Inferred rather than stated',
  assumed: 'No supporting input identified',
};

// What is still unsupported at each grade, stated as a consequence of the cap
// rather than as a judgment about the decision.
const UNSUPPORTED_BY_GRADE = {
  high: null,
  medium: 'Self-reported rather than verified, so this contributes at most 75.',
  low: 'Only partially supported, so this contributes at most 60.',
  assumed: 'Nothing verifiable behind this yet, so it contributes at most 45.',
};

const SEVERITY_CONSEQUENCE = {
  reversing: 'Resolving this could change which option leads.',
  material: 'Resolving this could materially change the score.',
  other: 'Resolving this would move the score slightly.',
  none: 'Resolving this would not move the score today.',
};

function pointsLabel(swing) {
  const rounded = Math.round(swing * 10) / 10;
  return `${rounded} ${rounded === 1 ? 'point' : 'points'}`;
}

function CriterionRow({ entry }) {
  const unsupported = UNSUPPORTED_BY_GRADE[entry.confidence];
  return (
    <li className={`dcc-criterion dcc-criterion-${entry.severity}`}>
      <div className="dcc-criterion-head">
        <span className="dcc-criterion-name">{entry.label}</span>
        <span className={`dcc-grade dcc-grade-${entry.confidence}`}>
          {GRADE_LABELS[entry.confidence] || entry.confidence}
        </span>
      </div>

      <div className="dcc-criterion-meta">
        <span>{Math.round(entry.weight * 100)}% of the decision</span>
        <span aria-hidden="true">·</span>
        <span>contributes {entry.score}</span>
        {entry.swing > 0 && (
          <>
            <span aria-hidden="true">·</span>
            <span className="dcc-criterion-swing">
              {pointsLabel(entry.swing)} of exposure
            </span>
          </>
        )}
      </div>

      {/* Jaspen's assessment, not evidence.
          The heading was "What Jaspen based this on", which sounded like a
          provenance record and is more authority than the underlying data
          carries: what follows is the model's own reasoning plus its own claim
          about the channel. Calling it an assessment is accurate now and stays
          accurate later, when a real Evidence block can sit beside it. */}
      <div className="dcc-basis-block">
        <p className="dcc-block-label dcc-block-basis">Jaspen&apos;s assessment</p>
        {entry.rationale ? (
          <p className="dcc-basis-text">{entry.rationale}</p>
        ) : (
          <p className="dcc-basis-text is-empty">
            No assessment was recorded for this criterion.
          </p>
        )}
        {entry.source && (
          <p className="dcc-basis-source">{ASSESSMENT_BASIS[entry.source] || entry.source}</p>
        )}
      </div>

      {unsupported && (
        <div className="dcc-unsupported-block">
          <p className="dcc-block-label dcc-block-unsupported">Still unsupported</p>
          <p className="dcc-block-text">{unsupported}</p>
        </div>
      )}

      {entry.resolution && (
        <div className="dcc-needed-block">
          <p className="dcc-block-label dcc-block-needed">Evidence needed</p>
          <p className="dcc-block-text">{entry.resolution}</p>
        </div>
      )}

      <p className="dcc-criterion-consequence">
        {SEVERITY_CONSEQUENCE[entry.severity]}
      </p>
    </li>
  );
}

export default function DecisionConfidenceCard({
  profile, exposure, optionName, score, scoreCategory, summary,
}) {
  if (!profile) return null;

  const backed = profile.evidence_backed_pct;
  const assumed = profile.assumption_dependent_pct;
  const claims = Array.isArray(profile.claims) ? profile.claims : [];
  const criteria = profile.criteria || [];
  const primaryClaim = claims[0] || null;
  const secondaryClaims = claims.slice(1);
  const isClear = primaryClaim?.kind === 'clear';

  return (
    <section className="dcc" aria-label="Decision confidence report">
      {/* ── Layer 1: the summary ─────────────────────────────────────────── */}
      <header className="dcc-head">
        <p className="dcc-eyebrow">Decision Confidence</p>

        {Number.isFinite(score) && (
          <p className="dcc-score-line">
            <strong>{score}</strong>
            {scoreCategory && <span className="dcc-score-cat">{scoreCategory}</span>}
          </p>
        )}

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
        <p className="dcc-basis">Evidence-backed share of the weighted decision</p>
      </header>

      {/* A briefing, not the first rows of the detail. It reads as continuous
          prose because it is meant to be quoted into a room, and every
          sentence is composed server-side from computed values, so it cannot
          drift from the arithmetic below or smuggle in a claim the detail does
          not support. See decision_confidence.decision_summary. */}
      {summary && (
        <div className="dcc-briefing">
          <p className="dcc-briefing-label">Summary</p>
          <p className="dcc-briefing-lead">
            {summary.verdict} {summary.standing}
          </p>
          <p className="dcc-briefing-body">
            {summary.confidence} {summary.concentration}
          </p>
          <p className={`dcc-briefing-sensitivity${isClear ? ' is-clear' : ''}`}>
            {summary.sensitivity}
          </p>
          {summary.next_step && (
            <p className="dcc-briefing-action">
              <span className="dcc-briefing-action-label">Do this next</span>
              {summary.next_step}
            </p>
          )}
          {secondaryClaims.length > 0 && (
            <p className="dcc-briefing-also">
              {secondaryClaims.map((c) => c.text).join('. ')}.
            </p>
          )}
        </div>
      )}

      {/* ── Layer 2: the detail, every criterion, nothing hidden ─────────── */}
      {criteria.length > 0 && (
        <div className="dcc-detail">
          <h4 className="dcc-detail-head">Evidence and assumption detail</h4>
          <ul className="dcc-criteria">
            {criteria.map((entry) => (
              <CriterionRow entry={entry} key={entry.key} />
            ))}
          </ul>
          <p className="dcc-provenance-note">
            Jaspen&apos;s assessment is its own reasoning about the inputs it was
            given. Jaspen cannot yet identify the specific document, message, or
            record behind a judgment, so nothing here should be read as a source
            citation or an audit trail.
          </p>
        </div>
      )}
    </section>
  );
}
