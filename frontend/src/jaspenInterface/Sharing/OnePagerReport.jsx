import React, { useMemo, useState } from 'react';

import SharedArtifactView from './SharedArtifactView';
import { REPORT_SECTIONS, applyPresentation, buildReportModel } from './reportModel';
import './OnePagerReport.css';

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
  const columns = [
    ['Supported by evidence', f.supported, 'No stated facts yet.'],
    ['Depends on assumptions', f.assumptions, 'No assumptions recorded.'],
    ['Verify before committing', f.verify, 'Nothing flagged to verify.'],
  ];
  return (
    <section className="op-section op-featured" aria-labelledby="op-featured">
      <div className="op-kicker">{model.cardCount > 1 ? 'The strongest case' : 'The case'}</div>
      <h2 id="op-featured" className="op-h2 op-h2--quote">“{text.featured_question}”</h2>
      <div className={`op-columns${compact ? ' op-columns--compact' : ''}`}>
        {columns.map(([label, items, empty]) => (
          <div key={label}>
            <div className="op-col-label">{label}</div>
            <List items={compact ? items.slice(0, 2) : items} empty={empty} />
          </div>
        ))}
        <div>
          <div className="op-col-label op-col-label--accent">For leadership to review</div>
          <p className="op-body">{f.verdict}{f.score !== null ? ` · case strength ${f.score} of 100` : ''}.</p>
        </div>
      </div>
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
      </div>
    </section>
  );
}

function Change({ model }) {
  if (!model.change.length) return null;
  return (
    <section className="op-section" aria-labelledby="op-change">
      <h2 id="op-change" className="op-h2">What could change the answer</h2>
      <div className="op-rule" />
      <div className="op-grid">
        {model.change.map((item) => (
          <div key={item.label}>
            <div className="op-grid__title">{item.label}</div>
            <div className="op-muted">{item.detail}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

function Takeaways({ model, text }) {
  return (
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
    change: <Change model={model} />,
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
            <div className="op-masthead__brand">JASPEN</div>
          </div>
          <div className="op-masthead__side">
            <div className="op-masthead__kind">{model.masthead}</div>
            <div className="op-muted">Evidence. Assumptions. Trade-offs.</div>
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
          <span>Prepared with Jaspen. Scores and figures are calculated by Jaspen, not estimated by AI.</span>
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
