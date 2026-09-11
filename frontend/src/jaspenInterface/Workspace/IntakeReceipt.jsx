// "Here's what Jaspen received" — the intake correction window.
//
// Shown before analysis, while the baseline is still editable. It states what
// the submission contained and invites the user to correct it.
//
// THIS PANEL CUTS AGAINST US, ON PURPOSE.
//
// Every correction a user makes here makes the eventual Decision Impact Report
// claim LESS. That is the point. A baseline the user was invited to fatten,
// and accepted, is one we cannot later be accused of having thinned to
// manufacture a delta. See docs/DECISION_IMPACT_REPORT_SPEC.md §3.3.
//
// It also has to be honest about the trade the user is making. Confirming is
// what turns these counts from `proposed_unconfirmed` into `user_confirmed`,
// and only confirmed measures can move the impact report. Skipping does not
// block anything — analysis runs, a report is still produced — it just narrows
// what the report is able to say. That asymmetry is stated in the panel rather
// than hidden, and the panel never blocks the conversation.
//
// TONE. Before and After are two states of a decision, not a bad one and a
// good one. Nothing here may read as a deficiency notice: it is a receipt.
// No "missing", no "gaps", no "incomplete".

import React, { useCallback, useEffect, useState } from 'react';
import { jasApi } from '../../services/jaspenApi';
import './IntakeReceipt.css';

const EMPTY = {
  alternatives: [],
  criteria: [],
  assumptions: [],
  risks: [],
  dependencies: [],
  sources: [],
};

// Free text in, list out. One item per line is the only rule a person has to
// hold, and it survives paste from a document.
const toList = (text) =>
  String(text || '')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean);

const fromList = (list) => (Array.isArray(list) ? list : []).join('\n');

const LIST_FIELDS = [
  { key: 'alternatives', label: 'Options under consideration', hint: 'One per line' },
  { key: 'assumptions', label: 'Assumptions you are working from', hint: 'One per line' },
  { key: 'risks', label: 'Risks already identified', hint: 'One per line' },
  { key: 'dependencies', label: 'Execution dependencies', hint: 'One per line' },
  { key: 'sources', label: 'Supporting evidence supplied', hint: 'Documents, exports, systems' },
];

export default function IntakeReceipt({ threadId, analysisStarted = false }) {
  const [state, setState] = useState({ status: 'idle', baseline: null, error: null });
  const [draft, setDraft] = useState(EMPTY);
  const [criteriaText, setCriteriaText] = useState('');
  const [criteriaFlags, setCriteriaFlags] = useState({});
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (!threadId || analysisStarted) return undefined;

    setState({ status: 'loading', baseline: null, error: null });
    jasApi
      .getDecisionBaseline(threadId)
      .then((data) => {
        if (cancelled) return;
        const baseline = data?.baseline || null;
        const structure = baseline?.submission_payload?.structure || {};
        setDraft({ ...EMPTY, ...structure });
        setCriteriaText(fromList((structure.criteria || []).map((c) => c.label)));
        setCriteriaFlags(
          Object.fromEntries(
            (structure.criteria || []).map((c) => [
              c.label,
              { backed: Boolean(c.backed_by_source), quantified: Boolean(c.quantified) },
            ])
          )
        );
        setState({ status: 'ready', baseline, error: null });
      })
      .catch((err) => {
        if (cancelled) return;
        // A thread with nothing in it yet has no baseline, which is not an
        // error worth showing anyone.
        setState({ status: 'unavailable', baseline: null, error: err?.message || null });
      });

    return () => {
      cancelled = true;
    };
  }, [threadId, analysisStarted]);

  const buildStructure = useCallback(
    (confirmed) => ({
      ...draft,
      criteria: toList(criteriaText).map((label, index) => ({
        key: `c${index + 1}`,
        label,
        backed_by_source: Boolean(criteriaFlags[label]?.backed),
        quantified: Boolean(criteriaFlags[label]?.quantified),
        weight: null,
      })),
      confirmed,
    }),
    [draft, criteriaText, criteriaFlags]
  );

  const save = useCallback(
    async (confirmed) => {
      setSaving(true);
      try {
        const structure = buildStructure(confirmed);
        const saved = await jasApi.saveDecisionBaseline(threadId, structure);
        if (confirmed) {
          const sealed = await jasApi.sealDecisionBaseline(threadId);
          setState({ status: 'ready', baseline: sealed?.baseline || saved?.baseline, error: null });
        } else {
          setState((prev) => ({ ...prev, baseline: saved?.baseline || prev.baseline }));
        }
      } catch (err) {
        setState((prev) => ({ ...prev, error: err?.message || 'Could not save.' }));
      } finally {
        setSaving(false);
      }
    },
    [buildStructure, threadId]
  );

  if (!threadId || analysisStarted) return null;
  if (state.status !== 'ready' || !state.baseline) return null;
  if (state.baseline.sealed) return null;

  const criteria = toList(criteriaText);
  const counted = [
    [draft.alternatives.length, 'option', 'options'],
    [criteria.length, 'decision criterion', 'decision criteria'],
    [draft.assumptions.length, 'stated assumption', 'stated assumptions'],
    [draft.sources.length, 'supporting source', 'supporting sources'],
    [draft.risks.length, 'identified risk', 'identified risks'],
    [draft.dependencies.length, 'execution dependency', 'execution dependencies'],
  ];

  return (
    <section className="ir" aria-labelledby="ir-title">
      <header className="ir-head">
        <p className="ir-eyebrow">Before analysis</p>
        <h3 className="ir-title" id="ir-title">Here&rsquo;s what Jaspen received</h3>
      </header>

      <ul className="ir-counts">
        {counted.map(([count, singular, plural]) => (
          <li key={singular} className={count ? 'ir-count' : 'ir-count ir-count-zero'}>
            <span className="ir-count-n">{count}</span>
            <span className="ir-count-label">{count === 1 ? singular : plural}</span>
          </li>
        ))}
      </ul>

      <p className="ir-note">
        This is the starting point Jaspen will compare against later. Anything you add now
        becomes part of it. You can skip this &mdash; analysis runs either way &mdash; but
        only a baseline you confirm can be measured against.
      </p>

      <button
        type="button"
        className="ir-toggle"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        {open ? 'Hide' : 'Correct or add to this'}
      </button>

      {open && (
        <div className="ir-form">
          <label className="ir-field">
            <span className="ir-field-label">Decision criteria</span>
            <span className="ir-field-hint">One per line. Tick what you already have a source for.</span>
            <textarea
              className="ir-textarea"
              rows={3}
              value={criteriaText}
              onChange={(event) => setCriteriaText(event.target.value)}
            />
          </label>

          {criteria.length > 0 && (
            <ul className="ir-criteria">
              {criteria.map((label) => (
                <li key={label} className="ir-criterion">
                  <span className="ir-criterion-label">{label}</span>
                  <label className="ir-check">
                    <input
                      type="checkbox"
                      checked={Boolean(criteriaFlags[label]?.backed)}
                      onChange={(event) =>
                        setCriteriaFlags((prev) => ({
                          ...prev,
                          [label]: { ...prev[label], backed: event.target.checked },
                        }))
                      }
                    />
                    I have a source for this
                  </label>
                  <label className="ir-check">
                    <input
                      type="checkbox"
                      checked={Boolean(criteriaFlags[label]?.quantified)}
                      onChange={(event) =>
                        setCriteriaFlags((prev) => ({
                          ...prev,
                          [label]: { ...prev[label], quantified: event.target.checked },
                        }))
                      }
                    />
                    Already quantified
                  </label>
                </li>
              ))}
            </ul>
          )}

          {LIST_FIELDS.map((field) => (
            <label className="ir-field" key={field.key}>
              <span className="ir-field-label">{field.label}</span>
              <span className="ir-field-hint">{field.hint}</span>
              <textarea
                className="ir-textarea"
                rows={2}
                value={fromList(draft[field.key])}
                onChange={(event) =>
                  setDraft((prev) => ({ ...prev, [field.key]: toList(event.target.value) }))
                }
              />
            </label>
          ))}

          {state.error && <p className="ir-error">{state.error}</p>}

          <div className="ir-actions">
            <button
              type="button"
              className="ir-save"
              disabled={saving}
              onClick={() => void save(false)}
            >
              {saving ? 'Saving…' : 'Save for now'}
            </button>
            <button
              type="button"
              className="ir-confirm"
              disabled={saving}
              onClick={() => void save(true)}
            >
              That&rsquo;s what I gave you
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
