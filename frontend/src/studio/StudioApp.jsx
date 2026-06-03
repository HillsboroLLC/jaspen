// frontend/src/studio/StudioApp.jsx
//
// "Studio" — a CONVERSATIONAL agent (mirrors the /new interface) running on the
// clean studio backend (standalone artifacts, deterministic scoring). You talk
// naturally; the agent sets your rubric / scores ideas and renders the cards
// inline. Themed off the locked brand tokens. Leaves the old /new untouched.

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { authFetch } from '../shared/auth/http';
import './studio.css';

const TIER_STYLES = {
  'Strategic Necessity': { bg: 'var(--color-brand-navy)', fg: '#fff' },
  'Leading Candidate': { bg: 'var(--color-brand-magenta)', fg: '#fff' },
  'Secondary Candidate': { bg: 'var(--color-brand-gold)', fg: '#161f3b' },
  'Monitor / Niche': { bg: '#e5e9f0', fg: '#4b5563' },
};
const tierStyle = (t) => TIER_STYLES[t] || { bg: '#e5e9f0', fg: '#4b5563' };

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

// ---- presentational ----------------------------------------------------------

function ScorePuck({ value }) {
  const tenths = (Math.max(0, Math.min(100, Number(value) || 0)) / 10).toFixed(1);
  return (
    <div className="st-puck" title={`${Math.round(Number(value) || 0)}/100`}>
      <span className="st-puck-num">{tenths}</span><span className="st-puck-denom">/10</span>
    </div>
  );
}

function TierPill({ tier, locked }) {
  const s = tierStyle(tier);
  return <span className="st-pill" style={{ background: s.bg, color: s.fg }}>{locked ? '🔒 ' : ''}{tier || '—'}</span>;
}

function DimBar({ dim }) {
  const score = Math.max(0, Math.min(100, Number(dim?.score) || 0));
  const low = score < 55;
  const color = (dim?.is_risk && score < 65) || low ? 'var(--color-brand-orange)' : 'var(--color-brand-navy)';
  const conf = String(dim?.confidence || 'medium').toLowerCase();
  const assumed = conf === 'assumed' || conf === 'low';
  return (
    <div className="st-dim" title={dim?.rationale || ''}>
      <div className="st-dim-head">
        <span className="st-dim-label">{dim?.label || dim?.key}</span>
        <span className="st-dim-score" style={{ color: low ? 'var(--color-brand-orange)' : undefined }}>
          {(score / 10).toFixed(1)}<span className="st-dim-denom">/10</span>
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
  const ordered = rubricCriteria
    ? rubricCriteria.map((c) => ({ key: c.key, ...dims[c.key], label: dims[c.key]?.label || c.label, group: c.group }))
    : Object.keys(dims).map((k) => ({ key: k, ...dims[k] }));
  const byGroup = useMemo(() => {
    const g = {};
    ordered.forEach((dim) => { (g[dim.group || 'Criteria'] = g[dim.group || 'Criteria'] || []).push(dim); });
    return g;
  }, [ordered]);
  const considerations = Array.isArray(d.key_considerations) ? d.key_considerations
    : Array.isArray(d.top_risks) ? d.top_risks.map((r) => (typeof r === 'string' ? r : r.text || r.risk)).filter(Boolean) : [];
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
            <div key={g} className="st-group-chip"><span className="st-group-name">{g}</span><span className="st-group-val">{(Number(v) / 10).toFixed(1)}</span></div>
          ))}
        </div>
      ) : null}
      {d.strategic_rationale || d.executive_summary ? <p className="st-card-summary">{d.strategic_rationale || d.executive_summary}</p> : null}
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
          {strengths.length ? <div className="st-note-col"><div className="st-note-h st-note-h--good">Strengths</div><ul>{strengths.slice(0, 4).map((s, i) => <li key={i}>{s}</li>)}</ul></div> : null}
          {considerations.length ? <div className="st-note-col"><div className="st-note-h st-note-h--risk">Considerations</div><ul>{considerations.slice(0, 4).map((s, i) => <li key={i}>{s}</li>)}</ul></div> : null}
        </div>
      ) : null}
    </div>
  );
}

function PortfolioBanner({ portfolio }) {
  if (!portfolio || (!portfolio.structure && !portfolio.recommended_sequence)) return null;
  return (
    <div className="st-portfolio">
      <div className="st-portfolio-h">Portfolio recommendation</div>
      {portfolio.structure ? <div className="st-portfolio-struct">{portfolio.structure}</div> : null}
      {portfolio.recommended_sequence ? <p className="st-portfolio-seq">{portfolio.recommended_sequence}</p> : null}
    </div>
  );
}

// ---- main: conversational agent ---------------------------------------------

let _mid = 0;
const mid = () => `m${++_mid}`;

export default function StudioApp() {
  const [workspace, setWorkspace] = useState(null);
  const [messages, setMessages] = useState([]); // {id, role, text, artifacts?, portfolio?}
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const scrollRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await api('/api/v1/studio/workspaces', { method: 'POST', body: { title: 'New evaluation' } });
        if (!cancelled) setWorkspace(r.workspace);
      } catch (e) { if (!cancelled) setError(e.message || 'Could not start a workspace.'); }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages, busy]);

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || !workspace || busy) return;
    setInput(''); setError('');
    const history = messages.map((m) => ({ role: m.role, content: m.text }));
    setMessages((prev) => [...prev, { id: mid(), role: 'user', text }]);
    setBusy(true);
    try {
      const r = await api(`/api/v1/studio/workspaces/${workspace.id}/chat`, { method: 'POST', body: { message: text, history } });
      setMessages((prev) => [...prev, {
        id: mid(), role: 'assistant', text: r.reply || 'Okay.',
        artifacts: (r.new_artifacts || []).slice().sort((a, b) => (Number(b.data?.jaspen_score) || 0) - (Number(a.data?.jaspen_score) || 0)),
        portfolio: r.portfolio_summary || null,
      }]);
    } catch (e) {
      setMessages((prev) => [...prev, { id: mid(), role: 'assistant', text: 'Sorry — I hit a snag. Try that again.' }]);
      setError(e.message);
    } finally { setBusy(false); }
  }, [input, workspace, busy, messages]);

  const onKey = (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } };

  return (
    <div className="st-root">
      <header className="st-header">
        <div className="st-brand">Jaspen <span className="st-brand-sub">Studio</span></div>
        <div className="st-header-meta">Vet ideas · score against your criteria · see the trade-offs</div>
      </header>

      <div className="st-chat" ref={scrollRef}>
        {messages.length === 0 ? (
          <div className="st-greeting">
            <div className="st-greeting-h">What do you want to evaluate?</div>
            <div className="st-greeting-sub">
              Tell me your options and the criteria that matter — e.g.<br />
              <em>“Score Dallas, Austin, and Charlotte on talent (40%), utility access (35%), and cost (25%).”</em><br />
              You set the criteria; I score them deterministically and rank them.
            </div>
          </div>
        ) : null}

        {messages.map((m) => (
          <div key={m.id} className={`st-msg st-msg--${m.role}`}>
            <div className="st-bubble">{m.text}</div>
            {m.portfolio ? <PortfolioBanner portfolio={m.portfolio} /> : null}
            {m.artifacts && m.artifacts.length ? (
              <div className="st-grid">{m.artifacts.map((a) => <ScorecardCard key={a.id} artifact={a} />)}</div>
            ) : null}
          </div>
        ))}

        {busy ? <div className="st-msg st-msg--assistant"><div className="st-bubble st-typing">Working…</div></div> : null}
      </div>

      {error ? <div className="st-error st-error--bar">{error}</div> : null}

      <div className="st-composer">
        <textarea
          className="st-composer-input"
          placeholder="Describe what you want to evaluate…"
          value={input}
          rows={1}
          disabled={!workspace}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKey}
        />
        <button className="st-send" disabled={!input.trim() || busy || !workspace} onClick={send} title="Send">↑</button>
      </div>
    </div>
  );
}
