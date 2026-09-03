// The Decision Impact Report — what changed about a decision between the
// moment it was submitted and the moment the analysis closed.
//
// Specification: docs/DECISION_IMPACT_REPORT_SPEC.md. Five sections, in the
// order the spec fixes: Before, what Jaspen examined, After, the impact
// verdict, and the narrative.
//
// WHAT THIS PANEL MAY AND MAY NOT SAY
//
// It describes the state of the DECISION RECORD. It never claims the decision
// improved, that the recommendation is more likely to be right, or that value
// was created. Before and After are two states of one decision, not a bad
// state and a good one, and no label here may read as a deficiency notice.
//
// EVERYTHING NUMERIC ARRIVES COMPUTED. Nothing in this file derives a figure,
// compares two numbers, or decides what counts as movement. The server's
// predicate did all of it and published its thresholds; this renders the
// result. A panel that did its own arithmetic could disagree with the report
// a customer forwards, which is the whole failure the assembler exists to
// prevent.
//
// WHAT DID NOT MOVE IS NOT OPTIONAL CHROME. A report listing only improvements
// is a highlight reel. `unmoved`, `not_applicable` and `excluded_unconfirmed`
// carry most of what makes this credible to a skeptical reader, and they
// render at the same weight as the movements.

import React, { useEffect, useState } from 'react';
import { jasApi } from '../../services/jaspenApi';
import './DecisionImpactReport.css';

const VERDICT_LABELS = {
  material: 'Material change',
  limited: 'Limited change',
  no_material_change: 'No material change',
  // Not a degree of the other three. The comparison could not be made, which
  // is a different statement from "it was made and found little".
  unverified_baseline: 'Baseline unavailable for verified impact comparison',
};

// "No material change" renders in the same visual weight as the others. It is
// a correct result, not a disappointment to soften (spec §7.3).
const VERDICT_CLASS = {
  material: 'dir-verdict-material',
  limited: 'dir-verdict-limited',
  no_material_change: 'dir-verdict-none',
  unverified_baseline: 'dir-verdict-unverified',
};

const GRADE_ORDER = ['high', 'medium', 'low', 'assumed'];

function formatValue(value) {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'object') {
    return GRADE_ORDER.filter((grade) => value[grade])
      .map((grade) => `${value[grade]} ${grade}`)
      .join(' · ') || '—';
  }
  return String(value);
}

// Only decision-state measures belong in Before/After. An intervention is
// something Jaspen DID; it has no Before, and rendering it beside measures
// that do would invite the reader to treat it as a delta (spec §2.5).
function StateList({ measures, catalog }) {
  const rows = Object.entries(measures || {}).filter(
    ([id, entry]) =>
      entry &&
      entry.value !== null &&
      entry.value !== undefined &&
      (catalog?.[id]?.class ?? 'state') === 'state'
  );
  if (!rows.length) {
    return <p className="dir-empty">Nothing was established at this point.</p>;
  }
  return (
    <ul className="dir-state">
      {rows.map(([id, entry]) => (
        <li key={id} className="dir-state-row">
          <span className="dir-state-label">{catalog?.[id]?.label || id}</span>
          <span className="dir-state-value">{formatValue(entry.value)}</span>
          {entry.basis === 'proposed_unconfirmed' && (
            <span className="dir-state-basis">not confirmed</span>
          )}
        </li>
      ))}
    </ul>
  );
}

export default function DecisionImpactReport({ threadId }) {
  const [state, setState] = useState({ status: 'idle', report: null, error: null });

  useEffect(() => {
    let cancelled = false;
    if (!threadId) return undefined;

    setState({ status: 'loading', report: null, error: null });
    jasApi
      .getDecisionImpactReport(threadId)
      .then((data) => {
        if (!cancelled) setState({ status: 'ready', report: data?.report || null, error: null });
      })
      .catch((err) => {
        if (!cancelled) {
          setState({ status: 'error', report: null, error: err?.message || 'Unavailable.' });
        }
      });

    return () => {
      cancelled = true;
    };
  }, [threadId]);

  if (state.status === 'loading') {
    return <p className="dir-empty">Assembling the impact report…</p>;
  }
  if (state.status === 'error' || !state.report) {
    return <p className="dir-empty">{state.error || 'No impact report for this decision yet.'}</p>;
  }

  const { report } = state;
  const { baseline, current, impact, activity, narrative, measure_catalog: catalog } = report;

  // One flag decides every label on this page. A reconstructed baseline was
  // assembled after analysis ran, so it contains the after inside the before —
  // it may be shown, but never under a heading that claims it preceded
  // anything (spec §7.4).
  const verified = impact.verified_comparison;
  // Counts of work Jaspen did. Never movement, so never in the delta lists.
  const interventions = (impact.interventions || []).filter((entry) => entry.qualifying);

  return (
    <section className="dir" aria-labelledby="dir-title">
      <header className="dir-head">
        <p className="dir-eyebrow">Decision impact</p>
        <h3 className="dir-title" id="dir-title">
          {verified ? 'What changed about this decision' : 'Decision record — current state'}
        </h3>
        {/* The qualification comes FIRST for a reconstructed baseline, above
            anything a reader could mistake for a before state. */}
        {report.reconstruction_note && (
          <p className="dir-reconstructed">{report.reconstruction_note}</p>
        )}
        <p className="dir-provenance">{report.provenance_note}</p>
      </header>

      {/* ── Before ─────────────────────────────────────────────────────── */}
      <div className="dir-block">
        <h4 className="dir-block-title">
          {verified
            ? 'Before Jaspen'
            : 'Recorded after analysis — not a record of what was submitted'}
        </h4>
        <p className="dir-block-note">
          Sealed {new Date(baseline.sealed_at).toLocaleDateString()}
          {baseline.sealed_by === 'user_confirmed' ? ', confirmed by you' : ', recorded at analysis'}
          {verified ? '' : ` · ${baseline.capture_reason}`}
          {' · '}
          {baseline.submission_ref?.turn_count || 0} submitted{' '}
          {baseline.submission_ref?.turn_count === 1 ? 'message' : 'messages'}
          {baseline.submission_ref?.attachment_count
            ? ` · ${baseline.submission_ref.attachment_count} attached`
            : ''}
        </p>
        <StateList measures={baseline.measures} catalog={catalog} />
      </div>

      {/* ── What Jaspen examined ───────────────────────────────────────── */}
      <div className="dir-block">
        <h4 className="dir-block-title">What Jaspen examined, challenged, and validated</h4>

        {/* Interventions live here rather than in Before/After: this is the
            section that is actually about what Jaspen did. */}
        {interventions.length > 0 && (
          <ul className="dir-state">
            {interventions.map((entry) => (
              <li key={entry.id} className="dir-state-row">
                <span className="dir-state-label">{entry.label}</span>
                <span className="dir-state-value">{entry.count}</span>
                {entry.strong && <span className="dir-state-basis">substantive</span>}
              </li>
            ))}
          </ul>
        )}

        {activity?.available ? (
          <ul className="dir-activity">
            {Object.entries(activity.counts_by_type || {}).map(([type, count]) => (
              <li key={type}>
                <strong>{count}</strong> {type.replace(/_/g, ' ')}
              </li>
            ))}
          </ul>
        ) : (
          // Stated rather than omitted: this is a stage of the build, not a
          // finding that nothing happened.
          <p className="dir-block-note">
            Challenge and validation activity is not yet recorded for this decision
            ({activity?.reason}). Until it is, this report does not attribute any
            change to Jaspen.
          </p>
        )}
      </div>

      {/* ── After ──────────────────────────────────────────────────────── */}
      <div className="dir-block">
        <h4 className="dir-block-title">{verified ? 'After Jaspen' : 'Current state'}</h4>
        {current.leading_option && (
          <p className="dir-block-note">Leading option: {current.leading_option}</p>
        )}
        <StateList measures={current.measures} catalog={catalog} />
      </div>

      {/* ── The verdict ────────────────────────────────────────────────── */}
      <div className="dir-block">
        <h4 className="dir-block-title">Decision impact</h4>
        <p className={`dir-verdict ${VERDICT_CLASS[impact.verdict]}`}>
          {VERDICT_LABELS[impact.verdict]}
        </p>

        {impact.withheld_reason && (
          <p className="dir-block-note">{impact.withheld_reason}</p>
        )}

        {impact.attribution_cap_applied && (
          <p className="dir-block-note">
            Held at limited: no recorded challenge or validation activity, so the change
            below is reported without attributing it to Jaspen.
          </p>
        )}

        {impact.moved.length > 0 && (
          <>
            <h5 className="dir-sub">What moved</h5>
            <ul className="dir-deltas">
              {impact.moved.map((movement) => (
                <li key={movement.id} className="dir-delta">
                  <span className="dir-delta-label">{movement.label}</span>
                  <span className="dir-delta-figures">
                    {formatValue(movement.from)} → {formatValue(movement.to)}
                  </span>
                  <span className="dir-delta-threshold">{movement.threshold}</span>
                </li>
              ))}
            </ul>
          </>
        )}

        {impact.unmoved.length > 0 && (
          <>
            <h5 className="dir-sub">What did not move</h5>
            <ul className="dir-deltas">
              {impact.unmoved.map((entry) => (
                <li key={entry.id} className="dir-delta dir-delta-flat">
                  <span className="dir-delta-label">{entry.label}</span>
                  <span className="dir-delta-figures">
                    {formatValue(entry.from)} → {formatValue(entry.to)}
                  </span>
                </li>
              ))}
            </ul>
          </>
        )}

        {impact.excluded_unconfirmed.length > 0 && (
          <>
            <h5 className="dir-sub">Left out — intake never confirmed</h5>
            <ul className="dir-reasons">
              {impact.excluded_unconfirmed.map((entry) => (
                <li key={entry.id}>{entry.label}</li>
              ))}
            </ul>
          </>
        )}

        {impact.not_applicable.length > 0 && (
          <>
            <h5 className="dir-sub">Out of scope for this decision</h5>
            <ul className="dir-reasons">
              {impact.not_applicable.map((entry) => (
                <li key={entry.id}>
                  {entry.label} <span className="dir-reason">— {entry.reason}</span>
                </li>
              ))}
            </ul>
          </>
        )}

        {/* Thresholds are published so a reader can recompute the verdict.
            There is no verdict to recompute when the comparison was withheld,
            and printing them anyway would imply one was applied. */}
        {verified && (
        <p className="dir-thresholds">
          Thresholds applied:{' '}
          {Object.entries(impact.thresholds)
            .map(([name, value]) => `${name} ${value}`)
            .join(' · ')}
          {' · '}
          {impact.methodology_version}
        </p>
        )}
      </div>

      {/* ── The narrative ──────────────────────────────────────────────── */}
      <div className="dir-block">
        <h4 className="dir-block-title">What changed</h4>
        <p className="dir-narrative">{narrative.what_changed}</p>
      </div>
    </section>
  );
}
