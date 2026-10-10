import React, { useMemo, useState } from 'react';

import SharedArtifactView from './SharedArtifactView';
import { REPORT_SECTIONS, applyPresentation, buildReportModel } from './reportModel';
import './OnePagerReport.css';

const EVIDENCE_LABELS = { none: 'No evidence', weak: 'Weak evidence', strong: 'Strong evidence' };

function List({ items, empty }) {
  if (!items.length) return <p className="op-muted">{empty}</p>;
  return (
    <ul className="op-list">
      {items.map((item) => <li key={item}>{item}</li>)}
    </ul>
  );
}

function Standings({ model }) {
  if (model.standings.length < 2) return null;
  return (
    <section className="op-section" aria-labelledby="op-standings">
      <h2 id="op-standings" className="op-h2">Where each option stands</h2>
      <div className="op-rule" />
      {model.standings.map((row) => (
        <div className="op-standing" key={row.name}>
          <div className="op-standing__main">
            <div className="op-standing__name">{row.name}</div>
            {row.failedGates.length > 0 && (
              <div className="op-standing__why">Misses a must-have: {row.failedGates.join(', ')}.</div>
            )}
            {row.why && <div className="op-standing__why">{row.why}</div>}
          </div>
          <div className="op-standing__side">
            <span className="op-verdict">{row.verdict}</span>
            {row.score !== null && <span className="op-muted">Case strength <strong>{row.score}</strong></span>}
          </div>
        </div>
      ))}
    </section>
  );
}

function Featured({ model, text, compact }) {
  const f = model.featured;
  if (!f) return null;
  const assumptions = compact ? f.assumptions.slice(0, 2) : f.assumptions;
  const verify = compact ? f.verify.slice(0, 2) : f.verify;
  return (
    <section className="op-section op-featured" aria-labelledby="op-featured">
      <div className="op-featured__top">
        <div className="op-kicker">{model.cardCount > 1 ? 'The strongest case' : 'The case'}</div>
        <span className="op-verdict-pill">{f.verdict}{f.score !== null ? ` · ${f.score}/100` : ''}</span>
      </div>
      <h2 id="op-featured" className="op-h2 op-h2--quote">“{text.featured_question}”</h2>

      {f.keyFacts.length > 0 && (
        <div className="op-facts" aria-label="What we know">
          {f.keyFacts.map((fact) => (
            <div key={fact.label} className="op-fact">
              <div className="op-fact__label">{fact.label}</div>
              <div className="op-fact__value">{fact.value}</div>
            </div>
          ))}
        </div>
      )}
      {f.mustHavesMet.length > 0 && (
        <p className="op-body op-musts"><strong>Must-haves met:</strong> {f.mustHavesMet.join(' · ')}</p>
      )}

      {assumptions.length > 0 && (
        <div className="op-featured__row">
          <div className="op-col-label">What we’re assuming</div>
          <ul className="op-list">{assumptions.map((item) => <li key={item}>{item}</li>)}</ul>
        </div>
      )}
      {verify.length > 0 && (
        <div className="op-featured__row">
          <div className="op-col-label">Check before committing</div>
          <ul className="op-list">{verify.map((item) => <li key={item}>{item}</li>)}</ul>
        </div>
      )}

      {f.metrics.length > 0 && (
        <div className="op-metrics">
          {f.metrics.map((m) => <span key={m.key}>{m.label} <strong>{m.value}</strong></span>)}
          <span className="op-muted">Calculated by Jaspen from your figures</span>
        </div>
      )}
    </section>
  );
}

function Strength({ model }) {
  const s = model.strength;
  if (!s || s.score === null) return null;
  const verdict = s.score >= 70 ? 'A strong case.' : s.score >= 50 ? 'Promising, with gaps to close.' : 'Not ready yet.';
  return (
    <section className="op-section op-strength" aria-labelledby="op-strength">
      <div className="op-ring" role="img" aria-label={`Case strength ${s.score} out of 100`}>
        <span className="op-ring__value">{s.score}</span>
        <span className="op-ring__of">of 100</span>
      </div>
      <div className="op-strength__body">
        <h2 id="op-strength" className="op-h2">How strong is the case?</h2>
        <p className="op-lead">
          {verdict}
          {s.verifiedShare !== null && ` About ${s.verifiedShare}% of the case rests on stated facts; the rest depends on assumptions you can check.`}
        </p>
        {s.verifiedShare !== null && (
          <>
            <div className="op-bar" aria-hidden="true">
              <div className="op-bar__facts" style={{ width: `${s.verifiedShare}%` }} />
              <div className="op-bar__assumed" style={{ width: `${100 - s.verifiedShare}%` }} />
            </div>
            <div className="op-legend">
              <span><i className="op-swatch op-swatch--facts" />Stated facts ({s.verifiedShare}%)</span>
              <span><i className="op-swatch op-swatch--assumed" />Assumptions ({100 - s.verifiedShare}%)</span>
            </div>
          </>
        )}
        {s.raiseConfidence.length > 0 && (
          <p className="op-body op-raise"><strong>To raise confidence, provide:</strong> {s.raiseConfidence.join(', ')}.</p>
        )}
      </div>
    </section>
  );
}

function Change({ model }) {
  if (!model.change.length) return null;
  return (
    <section className="op-section" aria-labelledby="op-change">
      <h2 id="op-change" className="op-h2">
        Where it’s weak, and how to make it stronger
        {model.sharedChangeScore !== null && (
          <span className="op-h2__note"> · each scored {model.sharedChangeScore}/100</span>
        )}
      </h2>
      <div className="op-rule" />
      <div className="op-grid">
        {model.change.map((item) => (
          <div key={item.label}>
            <div className="op-grid__title">{item.label}</div>
            <div className="op-evidence-row">
              <span className={`op-evidence op-evidence--${item.evidence}`}>{EVIDENCE_LABELS[item.evidence]}</span>
              {model.sharedChangeScore === null && item.score !== null && (
                <span className="op-weak-score">Scored {item.score}/100</span>
              )}
            </div>
            <div className="op-muted">{item.detail}</div>
            {item.strengthen && (
              <div className="op-strengthen"><span className="op-strengthen__label">To strengthen:</span> {item.strengthen}</div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

function Exposure({ model }) {
  const { risks, moves } = model.exposure;
  if (!risks.length && !moves.length) return null;
  return (
    <section className="op-section" aria-labelledby="op-exposure">
      <h2 id="op-exposure" className="op-h2">Risks, mitigations and next moves</h2>
      <div className="op-rule" />
      <div className="op-grid">
        {risks.length > 0 && (
          <div>
            <div className="op-col-label">Risks and mitigations</div>
            <ul className="op-list op-risks">
              {risks.map((item) => (
                <li key={item.risk}>
                  {item.risk}
                  {item.mitigation && (
                    <div className="op-strengthen op-small"><span className="op-strengthen__label">Mitigation:</span> {item.mitigation}</div>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
        {moves.length > 0 && (
          <div>
            <div className="op-col-label op-col-label--accent">Recommended moves</div>
            <ol className="op-list op-list--numbered">
              {moves.map((move) => (
                <li key={move.text}>
                  {move.text}
                  {move.chips.length > 0 && (
                    <div className="op-chips">{move.chips.map((chip) => <span key={chip} className="op-chip">{chip}</span>)}</div>
                  )}
                </li>
              ))}
            </ol>
          </div>
        )}
      </div>
    </section>
  );
}

function SectionShell({ id, title, model, children }) {
  return (
    <section className="op-section" aria-labelledby={id}>
      <h2 id={id} className="op-h2">
        {title}
        {model.cardCount > 1 && model.featured && <span className="op-h2__note"> · {model.featured.name}</span>}
      </h2>
      <div className="op-rule" />
      {children}
    </section>
  );
}

function Executive({ model }) {
  if (!model.executive.length) return null;
  return (
    <SectionShell id="op-executive" title="Executive summary" model={model}>
      {model.executive.map((para) => <p key={para} className="op-body op-para">{para}</p>)}
    </SectionShell>
  );
}

function Drivers({ model }) {
  if (!model.drivers.length) return null;
  return (
    <SectionShell id="op-drivers" title="What drove this score" model={model}>
      <ul className="op-list">{model.drivers.map((item) => <li key={item}>{item}</li>)}</ul>
    </SectionShell>
  );
}

function Breakdown({ model }) {
  if (!model.breakdown.length && !model.mustHaveRows.length) return null;
  return (
    <SectionShell id="op-breakdown" title="How each criterion scored" model={model}>
      <div className="op-breakdown">
        {model.breakdown.map((row) => (
          <div key={row.label} className="op-breakdown__row">
            <div className="op-breakdown__head">
              <span className="op-breakdown__label">{row.label}</span>
              {row.weight !== null && <span className="op-muted op-small">{row.weight}% of the decision</span>}
              <span className={`op-evidence op-evidence--${row.evidence}`}>{EVIDENCE_LABELS[row.evidence]}</span>
              {row.score !== null && <span className="op-breakdown__score">{row.score}<span className="op-muted">/100</span></span>}
            </div>
            {row.rationale && <div className="op-muted op-small">{row.rationale}</div>}
            {row.help && (
              <div className="op-strengthen op-small"><span className="op-strengthen__label">What would help:</span> {row.help}</div>
            )}
            {!row.help && row.satisfied && (
              <div className="op-strengthen op-small"><span className="op-strengthen__label">Satisfied:</span> nothing more needed here.</div>
            )}
          </div>
        ))}
        {model.mustHaveRows.map((row) => (
          <div key={row.label} className="op-breakdown__row">
            <div className="op-breakdown__head">
              <span className="op-breakdown__label">{row.label}</span>
              <span className="op-muted op-small">Must-have</span>
              <span className={`op-evidence op-evidence--${row.tone}`}>{row.status}</span>
            </div>
          </div>
        ))}
      </div>
    </SectionShell>
  );
}

function Rows({ rows }) {
  return (
    <dl className="op-rows">
      {rows.map((row) => (
        <React.Fragment key={row.label}>
          <dt>{row.label}</dt>
          <dd>{row.value}</dd>
        </React.Fragment>
      ))}
    </dl>
  );
}

function Financials({ model }) {
  if (!model.financials.length) return null;
  return (
    <SectionShell id="op-financials" title="Financial picture" model={model}>
      <div className="op-grid">
        {model.financials.map((group) => (
          <div key={group.title}>
            <div className="op-col-label">{group.title}</div>
            <Rows rows={group.rows} />
          </div>
        ))}
      </div>
    </SectionShell>
  );
}

function Framework({ model }) {
  if (!model.framework.length) return null;
  return (
    <SectionShell id="op-framework" title="Decision framework" model={model}>
      <Rows rows={model.framework} />
    </SectionShell>
  );
}

function Insights({ model }) {
  if (!model.insights.length) return null;
  return (
    <SectionShell id="op-insights" title="Insights from your data" model={model}>
      <ul className="op-list">
        {model.insights.map((item) => (
          <li key={item.text}>{item.source && <strong>{item.source}: </strong>}{item.text}</li>
        ))}
      </ul>
    </SectionShell>
  );
}

function Sharpen({ model }) {
  if (!model.sharpen.length) return null;
  return (
    <SectionShell id="op-sharpen" title="What would sharpen this score" model={model}>
      <ul className="op-list">{model.sharpen.map((item) => <li key={item}>{item}</li>)}</ul>
    </SectionShell>
  );
}

function Takeaways({ model, text }) {
  return (
    <>
    <section className="op-section op-takeaways" aria-labelledby="op-takeaways">
      <h2 id="op-takeaways" className="op-h2">{text.takeaway_title}</h2>
      <div className="op-grid op-grid--tight">
        {model.takeaways.map((item) => (
          <div key={item.title}>
            <div className={`op-takeaway__title${item.accent ? ' op-accent-text' : ''}`}>{item.title}</div>
            <div className="op-muted op-small">{item.body}</div>
          </div>
        ))}
      </div>
    </section>
    <p className="op-disclaimer">{model.numbersNote}</p>
    </>
  );
}

function Criteria({ model }) {
  const { weighted, mustHaves } = model.criteria;
  if (!weighted.length && !mustHaves.length) return null;
  return (
    <section className="op-section" aria-labelledby="op-criteria">
      <h2 id="op-criteria" className="op-h2">{model.rubricApproved ? 'The criteria you approved' : 'The criteria Jaspen proposed'}</h2>
      <div className="op-rule" />
      <div className="op-pills">
        {weighted.map((c) => <span key={c.label} className="op-pill">{c.label} <strong>{c.weight}%</strong></span>)}
        {mustHaves.map((label) => <span key={label} className="op-pill op-pill--must">Must have: {label}</span>)}
      </div>
    </section>
  );
}

function NextStep({ text }) {
  return (
    <section className="op-section op-next" aria-labelledby="op-next">
      <div>
        <div id="op-next" className="op-next__title">{text.next_step_title}</div>
        <div className="op-next__body">{text.next_step_body}</div>
      </div>
    </section>
  );
}

function Editor({ draft, setDraft, onSave, onCancel, saving, error }) {
  const setColor = (slot, value) => setDraft((d) => ({ ...d, colors: { ...d.colors, [slot]: value } }));
  const setText = (slot, value) => setDraft((d) => ({ ...d, text: { ...d.text, [slot]: value } }));
  const move = (index, delta) => setDraft((d) => {
    const order = [...d.order];
    const target = index + delta;
    if (target < 0 || target >= order.length) return d;
    [order[index], order[target]] = [order[target], order[index]];
    return { ...d, order };
  });
  const toggle = (key) => setDraft((d) => {
    const hidden = new Set(d.hidden);
    if (hidden.has(key)) hidden.delete(key); else hidden.add(key);
    return { ...d, hidden };
  });
  const labels = Object.fromEntries(REPORT_SECTIONS.map((s) => [s.key, s.label]));
  const brandSlots = [
    ['brand_name', 'Brand or your name'],
    ['company_name', 'Company'],
    ['report_label', 'Report name'],
    ['tagline', 'Tagline'],
  ];
  const textSlots = [
    ['headline', 'Headline'],
    ['summary', 'Summary'],
    ['featured_question', 'Featured question'],
    ['takeaway_title', 'Takeaways title'],
    ['next_step_title', 'Next step title'],
    ['next_step_body', 'Next step detail'],
  ];
  return (
    <aside className="op-editor" aria-label="Edit report">
      <div className="op-editor__head">
        <strong>Edit report</strong>
        <span className="op-muted op-small">Scores and figures can’t be edited. Change the facts in Jaspen to change a number.</span>
      </div>
      <fieldset className="op-editor__group">
        <legend>Colors</legend>
        {[['accent', 'Accent'], ['ink', 'Text'], ['tint', 'Panel tint']].map(([slot, label]) => (
          <label key={slot} className="op-editor__color">
            <input type="color" value={draft.colors[slot]} onChange={(e) => setColor(slot, e.target.value)} />
            {label}
          </label>
        ))}
      </fieldset>
      <fieldset className="op-editor__group">
        <legend>Branding</legend>
        {brandSlots.map(([slot, label]) => (
          <label key={slot} className="op-editor__field">
            <span>{label}</span>
            <textarea rows={1} value={draft.text[slot] || ''} onChange={(e) => setText(slot, e.target.value)} />
          </label>
        ))}
      </fieldset>
      <fieldset className="op-editor__group">
        <legend>Wording</legend>
        {textSlots.map(([slot, label]) => (
          <label key={slot} className="op-editor__field">
            <span>{label}</span>
            <textarea rows={slot === 'summary' || slot === 'next_step_body' ? 3 : 1} value={draft.text[slot] || ''} onChange={(e) => setText(slot, e.target.value)} />
          </label>
        ))}
      </fieldset>
      <fieldset className="op-editor__group">
        <legend>Layout</legend>
        {draft.order.map((key, index) => (
          <div key={key} className="op-editor__row">
            <label>
              <input type="checkbox" checked={!draft.hidden.has(key)} onChange={() => toggle(key)} />
              {labels[key]}
            </label>
            <span>
              <button type="button" onClick={() => move(index, -1)} aria-label={`Move ${labels[key]} up`} disabled={index === 0}>↑</button>
              <button type="button" onClick={() => move(index, 1)} aria-label={`Move ${labels[key]} down`} disabled={index === draft.order.length - 1}>↓</button>
            </span>
          </div>
        ))}
        <label className="op-editor__field">
          <span>Evidence box</span>
          <select value={draft.evidenceVariant} onChange={(e) => setDraft((d) => ({ ...d, evidenceVariant: e.target.value }))}>
            <option value="detailed">Detailed</option>
            <option value="compact">Compact</option>
          </select>
        </label>
      </fieldset>
      {error && <p className="op-editor__error" role="alert">{error}</p>}
      <div className="op-editor__actions">
        <button type="button" className="op-btn" onClick={onCancel} disabled={saving}>Cancel</button>
        <button type="button" className="op-btn op-btn--primary" onClick={onSave} disabled={saving}>{saving ? 'Saving…' : 'Save'}</button>
      </div>
    </aside>
  );
}

// The shareable decision report. Same template on the share link and the
// PDF. The owner (sharing is paid-only) can edit colors, wording and layout.
export default function OnePagerReport({
  artifactType, snapshot, title, createdAt, actions = null, canEdit = false, onSavePresentation = null,
}) {
  const model = useMemo(
    () => buildReportModel({ artifactType, snapshot, title, createdAt }),
    [artifactType, snapshot, title, createdAt],
  );
  const saved = useMemo(() => applyPresentation(model, snapshot?.presentation), [model, snapshot]);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(saved);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [detailsOpen, setDetailsOpen] = useState(false);

  const view = editing ? draft : saved;
  const startEdit = () => { setDraft(saved); setError(''); setEditing(true); };

  const save = async () => {
    if (!onSavePresentation) return;
    setSaving(true);
    setError('');
    const changedText = Object.fromEntries(
      Object.entries(draft.text).filter(([slot, value]) => value !== model.defaults[slot]),
    );
    const defaultOrder = REPORT_SECTIONS.map((s) => s.key);
    const presentation = {
      colors: draft.colors,
      text: changedText,
      layout: {
        ...(draft.order.join() !== defaultOrder.join() ? { order: draft.order } : {}),
        hidden: [...draft.hidden],
        ...(draft.evidenceVariant !== 'detailed' ? { evidence_variant: draft.evidenceVariant } : {}),
      },
    };
    try {
      await onSavePresentation(presentation);
      setEditing(false);
    } catch (saveError) {
      setError(saveError?.message || 'Could not save these edits.');
    } finally {
      setSaving(false);
    }
  };

  const style = {
    '--op-accent': view.colors.accent,
    '--op-ink': view.colors.ink,
    '--op-tint': view.colors.tint,
  };
  const sections = {
    standings: <Standings model={model} />,
    featured: <Featured model={model} text={view.text} compact={view.evidenceVariant === 'compact'} />,
    strength: <Strength model={model} />,
    executive: <Executive model={model} />,
    drivers: <Drivers model={model} />,
    breakdown: <Breakdown model={model} />,
    change: <Change model={model} />,
    exposure: <Exposure model={model} />,
    financials: <Financials model={model} />,
    framework: <Framework model={model} />,
    insights: <Insights model={model} />,
    sharpen: <Sharpen model={model} />,
    takeaways: <Takeaways model={model} text={view.text} />,
    criteria: <Criteria model={model} />,
    next_step: <NextStep text={view.text} />,
  };

  const visibleOrder = view.order.filter((key) => !view.hidden.has(key));
  // Case strength leads the report, above the decision question, when it is
  // first in the layout (the default). Owners can move it down in Edit.
  const leadSection = visibleOrder[0] === 'strength' ? 'strength' : null;

  return (
    <div className={`op-shell${editing ? ' op-shell--editing' : ''}`}>
      <article className="op-report" style={style}>
        <header className="op-masthead">
          <div>
            <div className="op-masthead__bar" />
            <div className="op-masthead__brand">{view.text.brand_name || 'JASPEN'}</div>
            {view.text.company_name && <div className="op-masthead__company">{view.text.company_name}</div>}
          </div>
          <div className="op-masthead__side">
            <div className="op-masthead__kind">{view.text.report_label}</div>
            {view.text.tagline && <div className="op-muted">{view.text.tagline}</div>}
          </div>
        </header>

        <nav className="op-actions" aria-label="Report actions">
          {actions}
          {canEdit && !editing && (
            <button type="button" className="op-btn" onClick={startEdit}>Edit</button>
          )}
        </nav>

        {leadSection && <div className="op-lead-section">{sections[leadSection]}</div>}

        <section className="op-headline">
          <h1 className="op-h1">{view.text.headline}</h1>
          {view.text.summary && <p className="op-lead">{view.text.summary}</p>}
          <div className="op-meta">
            {model.preparedOn && <span>Prepared {model.preparedOn}</span>}
            <span>{model.rubricApproved ? 'Criteria approved by you' : 'Criteria proposed by Jaspen'}</span>
          </div>
          {model.tags.length > 0 && (
            <div className="op-tags" aria-label="Decision context">
              {model.tags.map((tag) => (
                <span key={`${tag.kind}-${tag.label}`} className="op-tag"><span className="op-tag__kind">{tag.kind}</span>{tag.label}</span>
              ))}
            </div>
          )}
        </section>

        {visibleOrder.filter((key) => key !== leadSection).map((key) => (
          <React.Fragment key={key}>{sections[key]}</React.Fragment>
        ))}

        <section className="op-section op-details">
          <button
            type="button"
            className="op-details__toggle"
            aria-expanded={detailsOpen}
            onClick={() => setDetailsOpen((open) => !open)}
          >
            <span>See how this was scored <span className="op-muted">· scores by criterion, sources and every assumption</span></span>
            <span aria-hidden="true">{detailsOpen ? '▴' : '▾'}</span>
          </button>
          {detailsOpen && (
            <div className="op-details__body">
              <SharedArtifactView artifactType={artifactType} snapshot={snapshot} />
            </div>
          )}
        </section>

        <footer className="op-footer">
          <span>
            Prepared with Jaspen. Totals, dollar figures and must-have checks are calculated from your inputs.
            Criterion scores are Jaspen’s assessment, which you can review under “See how this was scored.”
            Confidence does not mean correctness. Please review your data for accuracy.
          </span>
          <a href="https://jaspen.ai">jaspen.ai</a>
        </footer>
      </article>

      {editing && (
        <Editor
          draft={draft}
          setDraft={setDraft}
          onSave={save}
          onCancel={() => { setEditing(false); setError(''); }}
          saving={saving}
          error={error}
        />
      )}
    </div>
  );
}
