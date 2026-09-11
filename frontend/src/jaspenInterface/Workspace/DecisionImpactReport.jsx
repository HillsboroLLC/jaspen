// The Decision Impact Report — what changed about a decision between the
// moment it was submitted and the moment the analysis closed.
//
// Specification: docs/DECISION_IMPACT_REPORT_SPEC.md. The executive result is
// presented first; the complete Before / challenge / After comparison and the
// published methodology remain available as an audit drill-down.
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
// WHAT DID NOT MOVE IS NOT DISCARDED. A report listing only improvements is a
// highlight reel. `unmoved`, `not_applicable` and `excluded_unconfirmed` carry
// most of what makes this credible to a skeptical reader, and remain intact in
// the audit drill-down rather than competing with the executive answer.

import React, { useEffect, useRef, useState } from 'react';
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

const ACTIVITY_LABELS = {
  evidence_requested: ['request for supporting evidence', 'requests for supporting evidence'],
  assumption_resolved: ['assumption resolved', 'assumptions resolved'],
  assumption_left_open: ['assumption left open', 'assumptions left open'],
  exposure_quantified: ['exposure quantified', 'exposures quantified'],
  dependency_surfaced: ['dependency surfaced', 'dependencies surfaced'],
};

function activityLabel(type, count) {
  const labels = ACTIVITY_LABELS[type];
  if (!labels) return type.replace(/_/g, ' ');
  return Number(count) === 1 ? labels[0] : labels[1];
}

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

export default function DecisionImpactReport({ threadId, onMeasure }) {
  const [state, setState] = useState({ status: 'idle', report: null, error: null });
  const rootRef = useRef(null);

  // The card self-fetches, so the canvas cannot estimate its height from props
  // the way it does for the risk register. It reports its own instead: the
  // report's length varies a lot between a decision that changed and one that
  // did not, and a fixed height either clips the first or leaves a dead band
  // under the second.
  useEffect(() => {
    const el = rootRef.current;
    if (!el || typeof onMeasure !== 'function') return undefined;
    const report = () => onMeasure(el.scrollHeight);
    report();
    const ro = new ResizeObserver(report);
    ro.observe(el);
    return () => ro.disconnect();
  }, [onMeasure, state.status, state.report]);

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
  const hasActivity = Object.keys(activity?.counts_by_type || {}).length > 0;

  return (
    <section className="dir" ref={rootRef} aria-labelledby="dir-title">
      <header className="dir-head">
        <h3 className="dir-title" id="dir-title">
          {verified ? 'What changed about this decision' : 'Decision record — current state'}
        </h3>
        {/* The qualification comes FIRST for a reconstructed baseline, above
            anything a reader could mistake for a before state. */}
        {report.reconstruction_note && (
          <p className="dir-reconstructed">{report.reconstruction_note}</p>
        )}
      </header>

      <div className="dir-executive">
        <div className="dir-executive-head">
          <p className={`dir-verdict ${VERDICT_CLASS[impact.verdict]}`}>
            {VERDICT_LABELS[impact.verdict]}
          </p>
          <h4 className="dir-block-title">
            {verified ? 'The decision story so far' : 'What the current record shows'}
          </h4>
        </div>
        {impact.withheld_reason && (
          <p className="dir-block-note">{impact.withheld_reason}</p>
        )}
        {impact.attribution_cap_applied && (
          <p className="dir-block-note">
            Held at limited: no recorded challenge or validation activity, so the change
            is reported without attributing it to Jaspen.
          </p>
        )}
        <p className="dir-narrative">{narrative.what_changed}</p>
      </div>

      <details className="dir-audit">
        <summary>See the before, challenge, and after</summary>
        <div className="dir-audit-body">

      {verified ? (
        /* Read as a sequence, not a dashboard comparison. The report is a
           story about one decision moving through three states, and each step
           should be understandable before the reader reaches the next. */
        <div className="dir-story">
          <section className="dir-panel">
            <p className="dir-step-label">1 · Before analysis</p>
            <h4 className="dir-block-title">What you brought to the decision</h4>
            <p className="dir-block-note">
              Sealed {new Date(baseline.sealed_at).toLocaleDateString()}
              {baseline.sealed_by === 'user_confirmed' ? ', confirmed by you' : ', recorded at analysis'}
              {' · '}
              {baseline.submission_ref?.turn_count || 0} submitted{' '}
              {baseline.submission_ref?.turn_count === 1 ? 'message' : 'messages'}
              {baseline.submission_ref?.attachment_count
                ? ` · ${baseline.submission_ref.attachment_count} attached`
                : ''}
            </p>
            <StateList measures={baseline.measures} catalog={catalog} />
          </section>

          <section className="dir-panel">
            <p className="dir-step-label">2 · Jaspen's challenge</p>
            <h4 className="dir-block-title">What Jaspen challenged</h4>
            {interventions.length === 0 && !activity?.available && (
              <p className="dir-block-note">
                No challenge or validation activity is recorded for this decision
                ({activity?.reason}). Nothing below is attributed to Jaspen.
              </p>
            )}
            {/* Keyed off recorded ACTIVITY, not off the intervention measures.
                Evidence requests are the commonest challenge Jaspen makes and
                are not one of the intervention measures, so testing those alone
                printed "no challenge" directly above "3 evidence requested". */}
            {interventions.length === 0 && activity?.available && !hasActivity && (
              <p className="dir-block-note">
                Jaspen recorded no challenge to this decision.
              </p>
            )}
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
            {activity?.available && Object.keys(activity.counts_by_type || {}).length > 0 && (
              <ul className="dir-activity">
                {Object.entries(activity.counts_by_type).map(([type, count]) => (
                  <li key={type}>
                    <strong>{count}</strong> {activityLabel(type, count)}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="dir-panel">
            <p className="dir-step-label">3 · After analysis</p>
            <h4 className="dir-block-title">What the record shows now</h4>
            {current.leading_option && (
              <p className="dir-block-note">Leading option: {current.leading_option}</p>
            )}
            {impact.moved.length === 0 ? (
              <p className="dir-block-note">
                No measure moved beyond the thresholds below.
              </p>
            ) : (
              <ul className="dir-deltas">
                {impact.moved.map((movement) => (
                  <li key={movement.id} className="dir-delta dir-delta-stacked">
                    <span className="dir-delta-label">{movement.label}</span>
                    <span className="dir-delta-figures">
                      {formatValue(movement.from)} → {formatValue(movement.to)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      ) : (
        <div className="dir-block">
          <h4 className="dir-block-title">
            Recorded after analysis — not a record of what was submitted
          </h4>
          <p className="dir-block-note">
            Sealed {new Date(baseline.sealed_at).toLocaleDateString()} · {baseline.capture_reason}
          </p>
          <StateList measures={current.measures} catalog={catalog} />
        </div>
      )}

      <div className="dir-block">
        <h4 className="dir-block-title">Comparison details</h4>

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
            {/* Not "out of scope": these are measures with nothing to compare,
                and the reason says which kind. Calling an uncaptured measure
                out of scope tells the reader the facet did not apply. */}
            <h5 className="dir-sub">Not compared</h5>
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
      <p className="dir-provenance">{report.provenance_note}</p>
        </div>
      </details>
    </section>
  );
}
