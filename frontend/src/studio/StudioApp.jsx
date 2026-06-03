// frontend/src/studio/StudioApp.jsx
//
// "Studio" — the clean idea-vetting workspace (Phase 2 UI). Talks to the new
// /api/v1/studio backend: a thin per-session workspace holding the USER's rubric,
// and standalone scorecard artifacts (one row per idea — no baseline/scenario).
// Themed entirely off the locked brand tokens (colors.css / tokens.css).

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { authFetch } from '../shared/auth/http';
import './studio.css';

const TIER_STYLES = {
  'Strategic Necessity': { bg: 'var(--color-brand-navy)', fg: '#fff', label: 'Strategic Necessity' },
  'Leading Candidate': { bg: 'var(--color-brand-magenta)', fg: '#fff', label: 'Leading Candidate' },
  'Secondary Candidate': { bg: 'var(--color-brand-gold)', fg: '#161f3b', label: 'Secondary Candidate' },
  'Monitor / Niche': { bg: '#e5e9f0', fg: '#4b5563', label: 'Monitor / Niche' },
};

function tierStyle(tier) {
  return TIER_STYLES[tier] || { bg: '#e5e9f0', fg: '#4b5563', label: tier || '—' };
}

async function api(path, { method = 'GET', body } = {}) {
  const res = await authFetch(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch { /* ignore */ }
  if (!res.ok) throw new Error((data && (data.error || data.msg)) || `Request failed (${res.status})`);
  return data;
}

// ---- small presentational bits ------------------------------------------------

function ScorePuck({ value }) {
  const tenths = (Math.max(0, Math.min(100, Number(value) || 0)) / 10).toFixed(1);
  return (
    <div className="st-puck" title={`${Math.round(Number(value) || 0)}/100`}>
      <span className="st-puck-num">{tenths}</span>
      <span className="st-puck-denom">/10</span>
    </div>
  );
}

function TierPill({ tier, locked }) {
  const s = tierStyle(tier);
  return (
    <span className="st-pill" style={{ background: s.bg, color: s.fg }}>
      {locked ? '🔒 ' : ''}{s.label}
    </span>
  );
}

function DimBar({ dim }) {
  const score = Math.max(0, Math.min(100, Number(dim?.score) || 0));
  const tenths = (score / 10).toFixed(1);
  const low = score < 55;
  const color = (dim?.is_risk && score < 65) || low ? 'var(--color-brand-orange)' : 'var(--color-brand-navy)';
  const conf = String(dim?.confidence || 'medium').toLowerCase();
  const assumed = conf === 'assumed' || conf === 'low';
  return (
    <div className="st-dim" title={dim?.rationale || ''}>
      <div className="st-dim-head">
        <span className="st-dim-label">{dim?.label || dim?.key}</span>
        <span className="st-dim-score" style={{ color: low ? 'var(--color-brand-orange)' : undefined }}>
          {tenths}<span className="st-dim-denom">/10</span>
        </span>
      </div>
      <div className="st-dim-track"><div className="st-dim-fill" style={{ width: `${score}%`, background: color }} /></div>
      {dim?.rationale ? <div className="st-dim-rationale">{dim.rationale}</div> : null}
      {assumed ? <span className="st-dim-conf">{conf}</span> : null}
    </div>
  );
}

function ScorecardCard({ artifact }) {
  const d = artifact?.data || {};
  const dims = d.dimensions || {};
  const rubricCriteria = Array.isArray(d.rubric?.criteria) ? d.rubric.criteria : null;
  const groupScores = d.group_scores || null;

  // Order dims by the rubric; group them if the rubric has groups.
  const ordered = rubricCriteria
    ? rubricCriteria.map((c) => ({ key: c.key, ...dims[c.key], label: dims[c.key]?.label || c.label, group: c.group }))
    : Object.keys(dims).map((k) => ({ key: k, ...dims[k] }));

  const byGroup = useMemo(() => {
    const groups = {};
    ordered.forEach((dim) => {
      const g = dim.group || 'Criteria';
      (groups[g] = groups[g] || []).push(dim);
    });
    return groups;
  }, [ordered]);

  const considerations = Array.isArray(d.key_considerations) ? d.key_considerations
    : Array.isArray(d.top_risks) ? d.top_risks.map((r) => (typeof r === 'string' ? r : r.text || r.risk)).filter(Boolean)
    : [];
  const strengths = Array.isArray(d.key_insights) ? d.key_insights : [];

  return (
    <div className="st-card">
      <div className="st-card-top">
        <div className="st-card-id">
          <div className="st-card-name">{artifact.name}</div>
          {d.primary_role ? <div className="st-card-role">{d.primary_role}</div> : null}
          <TierPill tier={d.tier} locked={d.locked} />
        </div>
        <ScorePuck value={d.jaspen_score} />
      </div>

      {groupScores ? (
        <div className="st-groups">
          {Object.entries(groupScores).map(([g, v]) => (
            <div key={g} className="st-group-chip">
              <span className="st-group-name">{g}</span>
              <span className="st-group-val">{(Number(v) / 10).toFixed(1)}</span>
            </div>
          ))}
        </div>
      ) : null}

      {d.strategic_rationale || d.executive_summary ? (
        <p className="st-card-summary">{d.strategic_rationale || d.executive_summary}</p>
      ) : null}

      <div className="st-card-dims">
        {Object.entries(byGroup).map(([g, list]) => (
          <div key={g} className="st-dimgroup">
            {g !== 'Criteria' ? <div className="st-dimgroup-title">{g}</div> : null}
            {list.map((dim) => <DimBar key={dim.key} dim={dim} />)}
          </div>
        ))}
      </div>

      {(strengths.length || considerations.length) ? (
        <div className="st-card-notes">
          {strengths.length ? (
            <div className="st-note-col">
              <div className="st-note-h st-note-h--good">Strengths</div>
              <ul>{strengths.slice(0, 4).map((s, i) => <li key={i}>{s}</li>)}</ul>
            </div>
          ) : null}
          {considerations.length ? (
            <div className="st-note-col">
              <div className="st-note-h st-note-h--risk">Considerations</div>
              <ul>{considerations.slice(0, 4).map((s, i) => <li key={i}>{s}</li>)}</ul>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

// ---- main app ----------------------------------------------------------------

const EMPTY_CRITERION = () => ({ label: '', weight: '', group: '' });

export default function StudioApp() {
  const [workspace, setWorkspace] = useState(null);
  const [artifacts, setArtifacts] = useState([]);
  const [portfolio, setPortfolio] = useState(null);
  const [criteria, setCriteria] = useState([EMPTY_CRITERION(), EMPTY_CRITERION()]);
  const [rubricSaved, setRubricSaved] = useState(false);
  const [ideaInput, setIdeaInput] = useState('');
  const [ideas, setIdeas] = useState([]); // {name, locked}
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');

  // Create (or reuse) a workspace on mount.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await api('/api/v1/studio/workspaces', { method: 'POST', body: { title: 'New evaluation' } });
        if (!cancelled) setWorkspace(r.workspace);
      } catch (e) {
        if (!cancelled) setError(e.message || 'Could not start a workspace.');
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const totalWeight = useMemo(
    () => criteria.reduce((s, c) => s + (parseFloat(c.weight) || 0), 0),
    [criteria]
  );

  const updateCriterion = (i, patch) =>
    setCriteria((prev) => prev.map((c, idx) => (idx === i ? { ...c, ...patch } : c)));
  const addCriterion = () => setCriteria((prev) => [...prev, EMPTY_CRITERION()]);
  const removeCriterion = (i) => setCriteria((prev) => prev.filter((_, idx) => idx !== i));

  const saveRubric = useCallback(async () => {
    if (!workspace) return;
    const clean = criteria
      .map((c) => ({ label: c.label.trim(), weight: parseFloat(c.weight) || 0, group: c.group.trim() || undefined }))
      .filter((c) => c.label && c.weight > 0);
    if (clean.length < 2) { setError('Add at least 2 criteria with a label and a weight.'); return; }
    setBusy('rubric'); setError('');
    try {
      const r = await api(`/api/v1/studio/workspaces/${workspace.id}/rubric`, { method: 'PUT', body: { criteria: clean } });
      setWorkspace(r.workspace);
      setRubricSaved(true);
    } catch (e) { setError(e.message); } finally { setBusy(''); }
  }, [workspace, criteria]);

  const addIdea = () => {
    const name = ideaInput.trim();
    if (!name) return;
    setIdeas((prev) => prev.some((i) => i.name.toLowerCase() === name.toLowerCase()) ? prev : [...prev, { name, locked: false }]);
    setIdeaInput('');
  };
  const toggleLock = (i) => setIdeas((prev) => prev.map((x, idx) => idx === i ? { ...x, locked: !x.locked } : x));
  const removeIdea = (i) => setIdeas((prev) => prev.filter((_, idx) => idx !== i));

  const scoreAll = useCallback(async () => {
    if (!workspace || !ideas.length) return;
    setBusy('score'); setError('');
    try {
      const r = await api(`/api/v1/studio/workspaces/${workspace.id}/score`, { method: 'POST', body: { ideas } });
      // Reload the full workspace so the ranked list reflects all artifacts.
      const full = await api(`/api/v1/studio/workspaces/${workspace.id}`);
      const arts = (full.workspace?.artifacts || []).slice().sort(
        (a, b) => (Number(b.data?.jaspen_score) || 0) - (Number(a.data?.jaspen_score) || 0)
      );
      setArtifacts(arts);
      setPortfolio(r.portfolio_summary || null);
    } catch (e) { setError(e.message); } finally { setBusy(''); }
  }, [workspace, ideas]);

  return (
    <div className="st-root">
      <header className="st-header">
        <div className="st-brand">Jaspen <span className="st-brand-sub">Studio</span></div>
        <div className="st-header-meta">Deterministic idea scoring · your criteria, your weights</div>
      </header>

      <div className="st-body">
        {/* Setup rail */}
        <aside className="st-rail">
          <section className="st-panel">
            <div className="st-panel-h">1 · Your criteria</div>
            <p className="st-panel-sub">You define them — the app applies them deterministically. Group them (e.g. Impact / Fit) to get sub-scores.</p>
            <div className="st-crit-list">
              {criteria.map((c, i) => (
                <div className="st-crit-row" key={i}>
                  <input className="st-in st-in-label" placeholder="Criterion" value={c.label} onChange={(e) => updateCriterion(i, { label: e.target.value })} />
                  <input className="st-in st-in-wt" placeholder="%" inputMode="decimal" value={c.weight} onChange={(e) => updateCriterion(i, { weight: e.target.value })} />
                  <input className="st-in st-in-grp" placeholder="Group" value={c.group} onChange={(e) => updateCriterion(i, { group: e.target.value })} list="st-groups-suggest" />
                  <button className="st-x" onClick={() => removeCriterion(i)} title="Remove">×</button>
                </div>
              ))}
              <datalist id="st-groups-suggest"><option value="Impact" /><option value="Fit" /></datalist>
            </div>
            <div className="st-crit-foot">
              <button className="st-link" onClick={addCriterion}>+ Add criterion</button>
              <span className={`st-weight-total ${Math.abs(totalWeight - 100) < 0.5 ? 'ok' : ''}`}>Σ {Math.round(totalWeight)}%</span>
            </div>
            <button className="st-btn st-btn-primary" disabled={busy === 'rubric'} onClick={saveRubric}>
              {busy === 'rubric' ? 'Saving…' : rubricSaved ? 'Rubric saved ✓ · update' : 'Save rubric'}
            </button>
          </section>

          <section className="st-panel" style={{ opacity: rubricSaved ? 1 : 0.5, pointerEvents: rubricSaved ? 'auto' : 'none' }}>
            <div className="st-panel-h">2 · Ideas to score</div>
            <p className="st-panel-sub">Any kind of option. Lock the ones that are required anchors.</p>
            <div className="st-idea-add">
              <input className="st-in" placeholder="Add an idea / option…" value={ideaInput}
                onChange={(e) => setIdeaInput(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && addIdea()} />
              <button className="st-btn" onClick={addIdea}>Add</button>
            </div>
            <div className="st-idea-list">
              {ideas.map((it, i) => (
                <div className="st-idea-chip" key={i}>
                  <button className={`st-lock ${it.locked ? 'on' : ''}`} onClick={() => toggleLock(i)} title="Required anchor">{it.locked ? '🔒' : '🔓'}</button>
                  <span className="st-idea-name">{it.name}</span>
                  <button className="st-x" onClick={() => removeIdea(i)}>×</button>
                </div>
              ))}
            </div>
            <button className="st-btn st-btn-primary" disabled={busy === 'score' || !ideas.length} onClick={scoreAll}>
              {busy === 'score' ? 'Scoring all in one pass…' : `Score ${ideas.length || ''} ${ideas.length === 1 ? 'idea' : 'ideas'}`}
            </button>
          </section>

          {error ? <div className="st-error">{error}</div> : null}
        </aside>

        {/* Results canvas */}
        <main className="st-canvas">
          {portfolio ? (
            <div className="st-portfolio">
              <div className="st-portfolio-h">Portfolio recommendation</div>
              {portfolio.structure ? <div className="st-portfolio-struct">{portfolio.structure}</div> : null}
              {portfolio.recommended_sequence ? <p className="st-portfolio-seq">{portfolio.recommended_sequence}</p> : null}
            </div>
          ) : null}

          {artifacts.length ? (
            <>
              <div className="st-rank-h">Ranked — {artifacts.length} option{artifacts.length === 1 ? '' : 's'}</div>
              <div className="st-grid">
                {artifacts.map((a) => <ScorecardCard key={a.id} artifact={a} />)}
              </div>
            </>
          ) : (
            <div className="st-empty">
              <div className="st-empty-art">◆</div>
              <div className="st-empty-h">Your scored options will appear here</div>
              <div className="st-empty-sub">Set your criteria, add a few ideas, and score them in one pass. Each becomes its own card — ranked, with the trade-offs.</div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
