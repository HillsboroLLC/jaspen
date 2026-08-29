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

import React, { useState } from 'react';
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

// A concise, human source for a verified reference. The exact locator stays on
// the element as a data attribute for inspection and audit, but raw offsets
// like "message 0 · chars 89-140" are implementation detail and do not belong
// in a report someone reads.
function evidenceSource(reference) {
  const locator = reference.locator || {};
  if (reference.kind === 'attachment') {
    const place = locator.location
      ? Object.values(locator.location).filter(Boolean).join(' · ')
      : '';
    return [locator.filename || 'Uploaded file', place].filter(Boolean).join(' · ');
  }
  if (reference.kind === 'connector') {
    const system = (locator.system || 'Connected system').toUpperCase();
    const when = locator.retrieved_at
      ? `retrieved ${String(locator.retrieved_at).slice(0, 10)}`
      : null;
    return [system, locator.field, when].filter(Boolean).join(' · ');
  }
  return 'From your input';
}

function CriterionRow({ entry, onEditNarrative, onRestoreNarrative, editable }) {
  const [draft, setDraft] = useState(null);
  const unsupported = UNSUPPORTED_BY_GRADE[entry.confidence];
  const references = Array.isArray(entry.evidence_references)
    ? entry.evidence_references
    : [];
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

      {/* Verified evidence, above the assessment on purpose. These excerpts
          were located in the input by deterministic code, so they outrank the
          model's reasoning about them and should be read first. A criterion
          with none simply omits the block: manufacturing an entry here would
          undo the entire point of verifying them. */}
      {references.length > 0 && (
        <div className="dcc-evidence-block">
          <p className="dcc-block-label dcc-block-evidence">Evidence used</p>
          <ul className="dcc-evidence-list">
            {references.map((reference) => (
              <li key={reference.id} data-evidence-locator={JSON.stringify(reference.locator)}>
                <span className="dcc-evidence-excerpt">{reference.excerpt}</span>
                <span className="dcc-evidence-source">{evidenceSource(reference)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Jaspen's assessment, not evidence.
          The heading was "What Jaspen based this on", which sounded like a
          provenance record and is more authority than the underlying data
          carries: what follows is the model's own reasoning plus its own claim
          about the channel. Calling it an assessment is accurate now and stays
          accurate later, when a real Evidence block can sit beside it. */}
      <div className="dcc-basis-block">
        <p className="dcc-block-label dcc-block-basis">
          Jaspen&apos;s assessment
          {/* Edited copy is marked, never passed off as the system finding.
              Jaspen's original wording is preserved underneath and is one
              click away, so a reader can always see what Jaspen actually
              said. */}
          {entry._edited && (
            <span className="dcc-edited-badge" title="Edited by a person. Jaspen's original wording is preserved.">
              Edited
            </span>
          )}
        </p>

        {draft !== null ? (
          <div className="dcc-edit">
            <textarea
              className="dcc-edit-input"
              value={draft}
              rows={3}
              autoFocus
              onChange={(event) => setDraft(event.target.value)}
              aria-label={`Assessment for ${entry.label}`}
            />
            <div className="dcc-edit-actions">
              <button
                type="button"
                className="dcc-edit-save"
                onClick={() => { onEditNarrative(entry.key, draft); setDraft(null); }}
              >
                Save wording
              </button>
              <button type="button" className="dcc-edit-cancel" onClick={() => setDraft(null)}>
                Cancel
              </button>
              <span className="dcc-edit-hint">
                Wording only. This does not change the score, grade, or exposure.
              </span>
            </div>
          </div>
        ) : (
          <>
            {entry.rationale ? (
              <p
                className={`dcc-basis-text${editable ? ' is-editable' : ''}`}
                onClick={editable ? () => setDraft(entry.rationale || '') : undefined}
                title={editable ? 'Click to edit the wording' : undefined}
              >
                {entry.rationale}
              </p>
            ) : (
              <p className="dcc-basis-text is-empty">
                No assessment was recorded for this criterion.
              </p>
            )}
            {entry._edited && (
              <div className="dcc-edited-meta">
                {entry._original_rationale && (
                  <details className="dcc-original">
                    <summary>Jaspen&apos;s original wording</summary>
                    <p>{entry._original_rationale}</p>
                  </details>
                )}
                <button
                  type="button"
                  className="dcc-restore"
                  onClick={() => onRestoreNarrative(entry.key)}
                >
                  Restore original
                </button>
              </div>
            )}
          </>
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
  onEditNarrative, onRestoreNarrative, editable = false,
  // Which half to render. The report is split across canvas sections so each
  // criterion can be resized and reordered on its own, which means this
  // component is mounted once for the briefing and once per criterion rather
  // than once for the whole thing.
  only = null, criterionKey = null,
}) {
  if (!profile) return null;

  const backed = profile.evidence_backed_pct;
  const assumed = profile.assumption_dependent_pct;
  const claims = Array.isArray(profile.claims) ? profile.claims : [];
  const criteria = profile.criteria || [];
  const primaryClaim = claims[0] || null;
  const secondaryClaims = claims.slice(1);
  const isClear = primaryClaim?.kind === 'clear';

  // One criterion, rendered into its own section.
  if (only === 'criterion') {
    const entry = criteria.find((c) => c.key === criterionKey);
    if (!entry) return null;
    return (
      <section className="dcc dcc-single" aria-label={`${entry.label} detail`}>
        <ul className="dcc-criteria">
          <CriterionRow
            entry={entry}
            editable={editable}
            onEditNarrative={onEditNarrative}
            onRestoreNarrative={onRestoreNarrative}
          />
        </ul>
      </section>
    );
  }

  const showDetail = only !== 'summary';

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
      {showDetail && criteria.length > 0 && (
        <div className="dcc-detail">
          <h4 className="dcc-detail-head">Evidence and assumption detail</h4>
          <ul className="dcc-criteria">
            {criteria.map((entry) => (
              <CriterionRow
                entry={entry}
                key={entry.key}
                editable={editable}
                onEditNarrative={onEditNarrative}
                onRestoreNarrative={onRestoreNarrative}
              />
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
