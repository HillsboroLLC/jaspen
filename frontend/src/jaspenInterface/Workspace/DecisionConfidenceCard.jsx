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
// records model reasoning plus deterministically located source passages:
//
//   source     the CHANNEL an input arrived on: conversation, connector,
//              inferred, or assumed. It does not identify which input.
//   rationale  the model's own account of its reasoning. Reasoning, not a
//              record of evidence.
//
//   references verified excerpts from conversation, attachments, or connector
//              snapshots. They prove what Jaspen read, not that it is true.
//   role       deterministic support/gap classification. A sentence saying
//              "I have no data" remains visible but cannot support the case.
//
// The report may quote verified references and their locators. It may not
// promote model reasoning or a claimed source channel into evidence.
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

// The built-in scoring pass returns dimensions with no `label`, so
// criterion_entries falls back to the raw key and the whole report renders
// `financial_viability` at a customer. These are the names the rest of the
// product already uses for the same six keys (see _DIMENSION_LABELS in
// JaspenWorkspace and the fallback list in JaspenChat), so a reader sees one
// vocabulary wherever a criterion is named.
const BUILT_IN_CRITERION_LABELS = {
  strategic_alignment: 'Strategic fit',
  financial_viability: 'Cost efficiency',
  execution_readiness: 'Time-to-value',
  risk_profile: 'Execution risk',
  market_opportunity: 'Market opportunity',
  evidence_quality: 'Evidence quality',
};

/** The criterion's name as a person should read it. A custom rubric supplies
 *  its own label and always wins; the built-in six are named above; anything
 *  else is de-slugged rather than shown raw. */
function criterionLabel(entry) {
  if (!entry) return '';
  const own = String(entry.label || '').trim();
  const key = String(entry.key || '');
  if (own && own !== key) return own;
  return (
    BUILT_IN_CRITERION_LABELS[key]
    || key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
  );
}

// `evidence_quality` is a META dimension: it assesses how good the user's
// evidence IS, rather than being something the decision rests on. Its passages
// are the user talking ABOUT their evidence ("I have the quotes", "Honestly I
// have no data on this"), which is correct for what it measures and wrong
// beside Cost efficiency in a list of what the decision stands on. Held out of
// that split and reported on its own.
const META_CRITERIA = new Set(['evidence_quality']);

const GRADE_LABELS = {
  high: 'Strong evidence',
  medium: 'Moderate evidence',
  low: 'Thin evidence',
  assumed: 'Assumed',
};

function supportingReferenceCount(entry) {
  if (Array.isArray(entry?.supporting_evidence_references)) {
    return entry.supporting_evidence_references.length;
  }
  return (Array.isArray(entry?.evidence_references) ? entry.evidence_references : [])
    .filter((reference) => reference?.evidence_role !== 'gap').length;
}

// A confidence grade is the model's assessment of the criterion. It must not
// become an evidence claim when every located passage is actually a gap.
function evidenceGradeLabel(entry) {
  if (!entry?.evidenced && supportingReferenceCount(entry) === 0) {
    return 'No verified support';
  }
  return GRADE_LABELS[entry?.confidence] || entry?.confidence;
}

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

// What a person can actually do about this criterion, when the scoring pass did
// not name something specific.
//
// Scoring is asked to populate `what_would_improve` for any criterion below
// "high", but it does not always do so, and a criterion that shows an exposure
// figure with no way to act on it is a dead end: the reader is told the score
// could move and not told how to move it.
//
// These are deliberately generic. A fallback that invented a specific ask
// ("upload the Q3 carrier contract") would read as though Jaspen knew such a
// document existed. Generic and true beats specific and fabricated.
const FALLBACK_ACTION_BY_GRADE = {
  high: null,
  medium: 'Share the source behind this, a document, export, or connected system, so it can be verified rather than taken as reported.',
  low: 'Provide the underlying figures or documents for this criterion so more of it rests on evidence.',
  assumed: 'Nothing verifiable supports this yet. Upload or connect the source that would establish it.',
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

function CriterionRow({
  entry, onEditNarrative, onRestoreNarrative, editable,
  acceptance, onAcceptExposure,
}) {
  const [draft, setDraft] = useState(null);
  const [acceptanceNote, setAcceptanceNote] = useState(null);
  const [acceptanceState, setAcceptanceState] = useState({ saving: false, error: '' });
  const unsupported = supportingReferenceCount(entry) === 0
    ? 'No affirmative verified input supports this criterion yet.'
    : UNSUPPORTED_BY_GRADE[entry.confidence];
  // Scoring's own suggestion when it made one, otherwise an honest generic.
  const action = entry.resolution || FALLBACK_ACTION_BY_GRADE[entry.confidence] || null;
  const references = Array.isArray(entry.evidence_references)
    ? entry.evidence_references
    : [];
  return (
    <li className={`dcc-criterion dcc-criterion-${entry.severity}`}>
      <div className="dcc-criterion-head">
        <span className="dcc-criterion-name">{criterionLabel(entry)}</span>
        <span className={`dcc-grade dcc-grade-${entry.confidence}`}>
          {evidenceGradeLabel(entry)}
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
          {/* NOT "Evidence used". evidence_references verifies PROVENANCE —
              that this passage demonstrably exists in the input and the scoring
              pass named it — never that the passage is evidence. On a thin
              criterion the passage is often the user saying they have none
              ("that's my gut"), and heading it "Evidence used" turns an
              anti-hallucination record into an evidentiary claim. The grade
              beside it carries the weight; this block only says what was read. */}
          <p className="dcc-block-label dcc-block-evidence">Verified input passages</p>
          <ul className="dcc-evidence-list">
            {references.map((reference) => (
              <li key={reference.id} data-evidence-locator={JSON.stringify(reference.locator)}>
                <span className="dcc-evidence-excerpt">{reference.excerpt}</span>
                <span className="dcc-evidence-source">
                  {evidenceSource(reference)}
                  {' · '}
                  {reference.evidence_role === 'gap' ? 'identifies a gap' : 'supports this dimension'}
                </span>
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
          {/* A real control, not a hover secret. Click-to-edit alone left the
              only editable text on the card indistinguishable from the
              computed text around it, so the affordance had to be found by
              accident. Everything else here is locked and must stay locked, so
              the one thing a person may change says so. */}
          {editable && draft === null && (
            <button
              type="button"
              className="dcc-edit-open"
              onClick={() => setDraft(entry.rationale || '')}
            >
              Edit wording
            </button>
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
              aria-label={`Assessment for ${criterionLabel(entry)}`}
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

      {/* The consequence, then what to do about it. The action sits directly
          under the line that states the exposure, so "this could move the
          score" is never left without an answer to "so what do I do?". */}
      <p className="dcc-criterion-consequence">
        {SEVERITY_CONSEQUENCE[entry.severity]}
      </p>

      {action && (
        <div className="dcc-needed-block">
          <p className="dcc-block-label dcc-block-needed">How to improve this</p>
          <p className="dcc-block-text">{action}</p>
        </div>
      )}

      {(entry.swing > 0 || entry.evidenced === false) && onAcceptExposure && (
        <div className="dcc-acceptance">
          <p className="dcc-block-label">Consciously accepted exposure</p>
          {acceptance && (
            <div className="dcc-acceptance-record" role="status">
              <strong>
                Accepted by {acceptance.accepted_by?.name || acceptance.accepted_by?.email || 'a user'}
              </strong>
              <span>{new Date(acceptance.accepted_at).toLocaleString()}</span>
              {acceptance.note && <p>{acceptance.note}</p>}
            </div>
          )}
          {acceptanceNote === null ? (
            <button
              type="button"
              className="dcc-accept-open"
              onClick={() => setAcceptanceNote('')}
            >
              {acceptance ? 'Accept the current exposure again' : 'Accept this exposure'}
            </button>
          ) : (
            <div className="dcc-accept-form">
              <p>
                This records that you understand this exposure remains unresolved and
                choose to proceed while consciously accepting it.
              </p>
              <label>
                Optional note
                <textarea
                  rows={2}
                  maxLength={1000}
                  value={acceptanceNote}
                  onChange={(event) => setAcceptanceNote(event.target.value)}
                />
              </label>
              <div className="dcc-edit-actions">
                <button
                  type="button"
                  className="dcc-edit-save"
                  disabled={acceptanceState.saving}
                  onClick={async () => {
                    setAcceptanceState({ saving: true, error: '' });
                    try {
                      await onAcceptExposure(entry, acceptanceNote);
                      setAcceptanceNote(null);
                      setAcceptanceState({ saving: false, error: '' });
                    } catch (error) {
                      setAcceptanceState({ saving: false, error: error?.message || 'Could not record acceptance.' });
                    }
                  }}
                >
                  {acceptanceState.saving ? 'Recording…' : 'Record accepted exposure'}
                </button>
                <button type="button" className="dcc-edit-cancel" onClick={() => setAcceptanceNote(null)}>
                  Cancel
                </button>
              </div>
              {acceptanceState.error && <p className="dcc-accept-error" role="alert">{acceptanceState.error}</p>}
            </div>
          )}
        </div>
      )}
    </li>
  );
}

export default function DecisionConfidenceCard({
  profile, exposure, optionName, summary,
  onEditNarrative, onRestoreNarrative, editable = false,
  acceptedExposures = [], onAcceptExposure,
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

  // What was actually located in the input, and what is carrying weight on
  // nothing. `evidence_references` is the only verified provenance the system
  // keeps — everything else on this card is Jaspen's own reasoning — so the
  // left column is built from those and nothing else.
  // Grouped by CRITERION, not pooled by passage. A verified passage is not the
  // same thing as evidence — evidence_references only proves Jaspen read the
  // text — so counting passages and calling the total "evidence you provided"
  // put "that's my gut" into an evidence list. What a criterion stands on is
  // decided by its grade, and that is what these two columns split on.
  const passagesFor = (entry, { supportOnly = false } = {}) =>
    (Array.isArray(
      supportOnly ? entry.supporting_evidence_references : entry.evidence_references
    ) ? (supportOnly ? entry.supporting_evidence_references : entry.evidence_references) : [])
      .map((ref) => String(ref?.excerpt || ref?.text || '').trim())
      .filter(Boolean);
  const decisionCriteria = criteria.filter((entry) => !META_CRITERIA.has(entry.key));
  const evidenced = decisionCriteria.filter((entry) => entry.evidenced);
  const assumedCriteria = decisionCriteria.filter((entry) => !entry.evidenced);
  const evidenceQuality = criteria.find((entry) => entry.key === 'evidence_quality') || null;
  const primaryClaim = claims[0] || null;
  const secondaryClaims = claims.slice(1);
  const isClear = primaryClaim?.kind === 'clear';
  const acceptanceFor = (entry) => [...acceptedExposures].reverse().find((item) => (
    item?.exposure?.kind === 'criterion'
    && item?.exposure?.target_key === entry.key
    && (!optionName || item?.exposure?.option_name === optionName || item?.exposure?.option_id === optionName)
  ));

  // One criterion, rendered into its own section.
  if (only === 'criterion') {
    const entry = criteria.find((c) => c.key === criterionKey);
    if (!entry) return null;
    return (
      <section className="dcc dcc-single" aria-label={`${criterionLabel(entry)} detail`}>
        <ul className="dcc-criteria">
          <CriterionRow
            entry={entry}
            editable={editable}
            onEditNarrative={onEditNarrative}
            onRestoreNarrative={onRestoreNarrative}
            acceptance={acceptanceFor(entry)}
            onAcceptExposure={onAcceptExposure}
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

        {/* NO OVERALL SCORE HERE, deliberately. The Jaspen score rates the
            OPTION — whether this is a good thing to do. This card rates the
            EVIDENCE — how much of that rating stands on anything. Leading the
            confidence report with the score made the two read as one number,
            so a thin 78 looked like a confident 78. The split below is the
            only headline this card gets. */}
        <p className="dcc-headline">
          <strong>{backed}%</strong> supported by verified input
          <span className="dcc-sep" aria-hidden="true">·</span>
          <strong>{assumed}%</strong> assumption-dependent
        </p>
        <div className="dcc-split" role="img"
          aria-label={`${backed} percent supported by verified input, ${assumed} percent assumption-dependent`}>
          <span className="dcc-split-backed" style={{ width: `${backed}%` }} />
          <span className="dcc-split-assumed" style={{ width: `${assumed}%` }} />
        </div>
        <p className="dcc-basis">Verified-support share of weighted decision criteria</p>

        {/* Reported on its own line, not in the split below: this is Jaspen's
            read on the QUALITY of what was brought, not one of the things the
            decision rests on. */}
        {evidenceQuality && (
          <p className="dcc-meta-line">
            <span className="dcc-meta-label">Evidence quality</span>
            <span className={`dcc-grade dcc-grade-${evidenceQuality.confidence}`}>
              {GRADE_LABELS[evidenceQuality.confidence] || evidenceQuality.confidence}
            </span>
            <span className="dcc-meta-note">Jaspen&rsquo;s read on what you brought</span>
          </p>
        )}

        {/* The two sides of that bar, named. A percentage on its own tells a
            reader how exposed they are without telling them to what, and the
            per-criterion detail below is too long to answer it at a glance.
            Split by verified affirmative support. Explicit gap statements
            remain visible on the assumption-dependent side. */}
        {(evidenced.length > 0 || assumedCriteria.length > 0) && (
          <div className="dcc-ledger">
            <div className="dcc-ledger-col">
              <p className="dcc-ledger-label dcc-ledger-label-evidence">
                Supported dimensions ({evidenced.length} of {decisionCriteria.length})
              </p>
              {evidenced.length === 0 ? (
                <p className="dcc-ledger-empty">
                  No decision dimension has verified affirmative support.
                </p>
              ) : (
                <ul className="dcc-ledger-list">
                  {evidenced.map((entry) => (
                    <li key={entry.key}>
                      <span className="dcc-ledger-excerpt">{criterionLabel(entry)}</span>
                      <span className="dcc-ledger-meta">
                        {evidenceGradeLabel(entry)}
                        {' · '}
                        {Math.round((entry.weight || 0) * 100)}% of the decision
                      </span>
                      {passagesFor(entry, { supportOnly: true }).slice(0, 2).map((excerpt) => (
                        <span className="dcc-ledger-quote" key={excerpt}>{excerpt}</span>
                      ))}
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="dcc-ledger-col">
              <p className="dcc-ledger-label dcc-ledger-label-assumed">
                Assumption-dependent dimensions ({assumedCriteria.length} of {decisionCriteria.length})
              </p>
              {assumedCriteria.length === 0 ? (
                <p className="dcc-ledger-empty">
                  Every decision dimension has verified affirmative support.
                </p>
              ) : (
                <ul className="dcc-ledger-list">
                  {assumedCriteria.map((entry) => (
                    <li key={entry.key}>
                      <span className="dcc-ledger-excerpt">{criterionLabel(entry)}</span>
                      <span className="dcc-ledger-meta">
                        {evidenceGradeLabel(entry)}
                        {' · '}
                        {Math.round((entry.weight || 0) * 100)}% of the decision
                      </span>
                      {/* Shown on purpose: seeing what you actually said is the
                          fastest way to understand why it is not evidence. */}
                      {passagesFor(entry).slice(0, 2).map((excerpt) => (
                        <span className="dcc-ledger-quote" key={excerpt}>{excerpt}</span>
                      ))}
                      {entry.resolution && (
                        <span className="dcc-ledger-meta">
                          <strong>What would strengthen it:</strong> {entry.resolution}
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )}
      </header>

      {/* A briefing, not the first rows of the detail. It reads as continuous
          prose because it is meant to be quoted into a room, and every
          sentence is composed server-side from computed values, so it cannot
          drift from the arithmetic below or smuggle in a claim the detail does
          not support. See decision_confidence.decision_summary. */}
      {summary && (
        <div className="dcc-briefing">
          <p className="dcc-briefing-label">Summary</p>
          {/* summary.verdict is dropped for the same reason: it opens
              "Scores 66 of 100", which is the option's rating, not this
              report's finding. Standing leads when there is a peer set;
              otherwise the evidence sentence does. */}
          {summary.standing && (
            <p className="dcc-briefing-lead">{summary.standing}</p>
          )}
          <p className={summary.standing ? 'dcc-briefing-body' : 'dcc-briefing-lead'}>
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
                acceptance={acceptanceFor(entry)}
                onAcceptExposure={onAcceptExposure}
              />
            ))}
          </ul>
          <p className="dcc-provenance-note">
            Verified passages show exactly what Jaspen read and where it came
            from. They do not independently prove that the source statement is
            true. Jaspen&apos;s assessment remains model reasoning, not evidence.
          </p>
        </div>
      )}
    </section>
  );
}
