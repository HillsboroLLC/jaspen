// ============================================================================
// File: frontend/src/jaspenInterface/Workspace/JaspenWorkspace.jsx
// Purpose: Canvas-style editor for a single artifact (scorecard or trade-off).
//          Opens in its own browser tab via /workspace/:threadId/:scorecardId.
//          Layout: left sidebar = Jaspen chat (scoped to this artifact);
//          center = canvas with renderScorecardCard + inline editable text;
//          footer = Download PDF / Share / Reset to original.
//
//          v1 / BETA scope: cosmetic edits only (title, headings, narrative,
//          accent color). Analytical fields (scores, risks, recommendations)
//          stay read-only — a rescore is a separate conversation.
// ============================================================================

import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faArrowLeft, faDownload, faShare, faRotateLeft, faPaperPlane } from '@fortawesome/free-solid-svg-icons';

import { Jaspen } from './JaspenClient';

/**
 * Apply display_overrides on top of a raw scorecard payload. Overrides are
 * purely cosmetic — anything missing falls through to the original value.
 */
function applyOverrides(scorecard, overrides) {
  if (!scorecard) return null;
  const ov = overrides && typeof overrides === 'object' ? overrides : {};
  return {
    ...scorecard,
    project_name: ov.title ?? scorecard.project_name,
    executive_summary: ov.executive_summary ?? scorecard.executive_summary,
    _accent_color: ov.accent_color ?? scorecard._accent_color ?? null,
    _display_overrides: ov,
  };
}

export default function JaspenWorkspace() {
  const { threadId, scorecardId } = useParams();
  const [bundle, setBundle] = useState(null);
  const [snapshot, setSnapshot] = useState(null);
  const [overrides, setOverrides] = useState({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(null);
  const [error, setError] = useState(null);
  const [chatInput, setChatInput] = useState('');
  const [chatHistory, setChatHistory] = useState([]);
  const saveTimerRef = useRef(null);
  const skipNextSaveRef = useRef(true); // first render = freshly loaded, don't save back

  // Fetch the artifact on mount. We use the dedicated lightweight workspace
  // endpoint that returns just the snapshot + overrides in one round-trip,
  // not the full bundle. Falls back to fetchBundle if the focused endpoint
  // fails for any reason.
  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);

      let target = null;
      let ov = {};

      // Path A: focused endpoint
      try {
        const data = await Jaspen.getScorecardForWorkspace(threadId, scorecardId);
        target = data?.scorecard || null;
        if (data?.display_overrides && typeof data.display_overrides === 'object') {
          ov = data.display_overrides;
        }
      } catch (e) {
        console.warn('[Workspace] focused scorecard fetch failed, will try bundle:', e);
      }
      if (cancelled) return;

      // Path B: bundle fallback (older deploys, or if the focused endpoint 404s)
      if (!target) {
        try {
          const b = await Jaspen.fetchBundle(threadId);
          setBundle(b);
          const snapshots = Array.isArray(b?.scorecard_snapshots) ? b.scorecard_snapshots : [];
          target = snapshots.find(
            (s) => String(s?.id || s?.analysis_id || '') === String(scorecardId)
          ) || b?.current_scorecard || b?.baseline_scorecard || null;
          if (target?.display_overrides && typeof target.display_overrides === 'object' && Object.keys(ov).length === 0) {
            ov = target.display_overrides;
          }
        } catch (e) {
          console.error('[Workspace] bundle fallback also failed:', e);
          if (!cancelled) {
            setError(`Couldn't load this scorecard (${e?.name || 'Error'}): ${e?.message || String(e)}`);
          }
        }
        if (cancelled) return;
      }

      setSnapshot(target);
      skipNextSaveRef.current = true;
      setOverrides(ov || {});

      if (target) setError(null);
      setLoading(false);
    }
    void load();
    return () => { cancelled = true; };
  }, [threadId, scorecardId]);

  // Debounced auto-save: any change to overrides is persisted ~500ms later.
  useEffect(() => {
    if (skipNextSaveRef.current) {
      skipNextSaveRef.current = false;
      return;
    }
    if (!threadId || !scorecardId) return;
    if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current);
    saveTimerRef.current = window.setTimeout(async () => {
      try {
        setSaving(true);
        setSaveError(null);
        await Jaspen.patchScorecardOverrides(threadId, scorecardId, overrides);
      } catch (e) {
        setSaveError(String(e?.message || e || 'Failed to save'));
      } finally {
        setSaving(false);
      }
    }, 500);
    return () => { if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current); };
  }, [overrides, threadId, scorecardId]);

  const rendered = useMemo(() => applyOverrides(snapshot, overrides), [snapshot, overrides]);

  const score = Number(rendered?.jaspen_score || 0);
  const ringColor = rendered?._accent_color || '#a0036c';
  const category = score >= 80 ? 'Excellent' : score >= 60 ? 'Good' : score >= 40 ? 'Fair' : 'At Risk';

  // Set or remove a single cosmetic override. Auto-save fires from the
  // useEffect above on the next tick (debounced).
  function setOverride(key, value) {
    setOverrides((prev) => {
      const next = { ...prev };
      if (value === null || value === undefined || value === '') {
        delete next[key];
      } else {
        next[key] = value;
      }
      return next;
    });
  }

  async function resetOverrides() {
    skipNextSaveRef.current = true; // we'll do the save ourselves to clear remote
    setOverrides({});
    try {
      setSaving(true);
      // Pass nulls for each known key so the backend removes them.
      await Jaspen.patchScorecardOverrides(threadId, scorecardId, {
        title: null, subtitle: null, executive_summary: null,
        accent_color: null, theme: null, narrative: null,
      });
    } catch (e) {
      setSaveError(String(e?.message || e || 'Failed to reset'));
    } finally {
      setSaving(false);
    }
  }

  function sendChat() {
    const text = chatInput.trim();
    if (!text) return;
    setChatHistory((prev) => [
      ...prev,
      { role: 'user', text },
      { role: 'ai', text: 'Workspace chat is in beta. Edits via chat will land in v1.1 — for now, click any heading on the canvas to edit it directly.' },
    ]);
    setChatInput('');
  }

  // --- Loading / error states ---
  if (loading) {
    return (
      <div style={{ display:'flex', alignItems:'center', justifyContent:'center', height:'100vh', color:'#475569', fontSize:14 }}>
        Loading workspace…
      </div>
    );
  }
  if (error || !snapshot) {
    return (
      <div style={{ display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center', height:'100vh', gap:12, color:'#475569' }}>
        <div style={{ fontSize:15, fontWeight:600, color:'#0f172a' }}>Couldn't open this artifact</div>
        <div style={{ fontSize:13 }}>{error || 'Scorecard not found in this thread.'}</div>
        <Link to="/new" style={{ marginTop:8, padding:'8px 14px', borderRadius:8, background:'#0f172a', color:'#fff', textDecoration:'none', fontSize:13 }}>
          Back to Jaspen
        </Link>
      </div>
    );
  }

  return (
    <div style={{ display:'flex', height:'100vh', background:'#f7f8fa', fontFamily:'Inter Tight, system-ui, sans-serif' }}>
      {/* === LEFT SIDEBAR: scoped chat === */}
      <aside
        style={{
          width:340, flexShrink:0, background:'#fff',
          borderRight:'1px solid #e6eaf2', display:'flex', flexDirection:'column',
        }}
      >
        <div style={{ padding:'14px 16px', borderBottom:'1px solid #e6eaf2', display:'flex', alignItems:'center', gap:10 }}>
          <Link to={`/new?sid=${encodeURIComponent(threadId)}`} style={{ color:'#475569', textDecoration:'none', fontSize:13 }}>
            <FontAwesomeIcon icon={faArrowLeft} style={{ marginRight:6 }} />
            Back to Jaspen
          </Link>
        </div>
        <div style={{ padding:'14px 16px', borderBottom:'1px solid #e6eaf2' }}>
          <div style={{ fontSize:12, color:'#64748b', textTransform:'uppercase', letterSpacing:'0.06em', fontWeight:600 }}>
            Workspace · Beta
          </div>
          <div style={{ fontSize:14, color:'#0f172a', marginTop:4, fontWeight:600 }}>
            {rendered?.project_name || 'Untitled scorecard'}
          </div>
          <div style={{ fontSize:12, color:'#64748b', marginTop:2 }}>
            Editing cosmetic fields. Scores stay read-only.
          </div>
        </div>

        {/* Chat thread */}
        <div style={{ flex:1, overflow:'auto', padding:'12px 16px', display:'flex', flexDirection:'column', gap:10 }}>
          {chatHistory.length === 0 && (
            <div style={{ fontSize:12, color:'#94a3b8', lineHeight:1.5 }}>
              Ask Jaspen to rewrite copy, adjust tone, or tweak styling — or click anything on the canvas to edit directly.
            </div>
          )}
          {chatHistory.map((m, i) => (
            <div
              key={i}
              style={{
                alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start',
                maxWidth:'85%', padding:'8px 12px', borderRadius:10,
                background: m.role === 'user' ? '#0f172a' : '#f1f5f9',
                color: m.role === 'user' ? '#fff' : '#0f172a',
                fontSize:13, lineHeight:1.45,
              }}
            >
              {m.text}
            </div>
          ))}
        </div>

        {/* Chat input */}
        <div style={{ padding:'10px 12px 14px', borderTop:'1px solid #e6eaf2' }}>
          <div style={{ display:'flex', alignItems:'center', gap:6, background:'#f7f8fa', borderRadius:10, padding:'8px 10px' }}>
            <input
              type="text"
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); } }}
              placeholder="Describe a change…"
              style={{ flex:1, border:'none', outline:'none', background:'transparent', fontSize:13, color:'#0f172a' }}
            />
            <button
              onClick={sendChat}
              disabled={!chatInput.trim()}
              style={{
                width:30, height:30, borderRadius:8, border:'none',
                background: chatInput.trim() ? '#0f172a' : '#cbd5e1',
                color:'#fff', cursor: chatInput.trim() ? 'pointer' : 'not-allowed',
                display:'flex', alignItems:'center', justifyContent:'center',
              }}
              aria-label="Send"
            >
              <FontAwesomeIcon icon={faPaperPlane} style={{ fontSize:11 }} />
            </button>
          </div>
        </div>
      </aside>

      {/* === CENTER: canvas === */}
      <main style={{ flex:1, display:'flex', flexDirection:'column', overflow:'hidden' }}>
        <div style={{ padding:'18px 28px', borderBottom:'1px solid #e6eaf2', background:'#fff', display:'flex', alignItems:'center', justifyContent:'space-between' }}>
          <div style={{ display:'flex', alignItems:'baseline', gap:10 }}>
            <h1 style={{ margin:0, fontSize:18, fontWeight:600, color:'#0f172a' }}>{rendered?.project_name || 'Untitled scorecard'}</h1>
            <span style={{ padding:'2px 8px', borderRadius:10, background:'#fef3c7', color:'#92400e', fontSize:10, fontWeight:600, letterSpacing:'0.04em' }}>
              BETA
            </span>
            {saving && (
              <span style={{ fontSize:11, color:'#94a3b8' }}>Saving…</span>
            )}
            {!saving && saveError && (
              <span style={{ fontSize:11, color:'#dc2626' }} title={saveError}>Save failed</span>
            )}
            {!saving && !saveError && Object.keys(overrides).length > 0 && (
              <span style={{ fontSize:11, color:'#94a3b8' }}>Saved</span>
            )}
          </div>
          <div style={{ display:'flex', gap:8 }}>
            <button
              type="button"
              onClick={resetOverrides}
              disabled={Object.keys(overrides).length === 0}
              style={{
                padding:'8px 12px', borderRadius:8, border:'1px solid #d6dce6',
                background:'#fff', color:'#0f172a', cursor: Object.keys(overrides).length === 0 ? 'not-allowed' : 'pointer',
                fontSize:13, opacity: Object.keys(overrides).length === 0 ? 0.5 : 1,
              }}
            >
              <FontAwesomeIcon icon={faRotateLeft} style={{ marginRight:6 }} />
              Reset
            </button>
            <button
              type="button"
              onClick={() => window.print()}
              style={{ padding:'8px 12px', borderRadius:8, border:'1px solid #d6dce6', background:'#fff', color:'#0f172a', cursor:'pointer', fontSize:13 }}
            >
              <FontAwesomeIcon icon={faDownload} style={{ marginRight:6 }} />
              Download PDF
            </button>
            <button
              type="button"
              onClick={() => navigator.clipboard?.writeText(window.location.href)}
              style={{ padding:'8px 12px', borderRadius:8, border:'none', background:'#0f172a', color:'#fff', cursor:'pointer', fontSize:13 }}
            >
              <FontAwesomeIcon icon={faShare} style={{ marginRight:6 }} />
              Share
            </button>
          </div>
        </div>

        {/* The canvas itself — a simplified scorecard view for now.
            We're rendering this inline (rather than pulling the chat's
            renderScorecardCard) so we have full control over which fields
            are inline-editable. */}
        <div style={{ flex:1, overflow:'auto', padding:'32px 48px' }}>
          <div
            style={{
              maxWidth:980, margin:'0 auto', background:'#fff', borderRadius:14,
              boxShadow:'0 1px 3px rgba(15,23,42,0.06), 0 8px 24px rgba(15,23,42,0.04)',
              padding:'36px 40px',
            }}
          >
            {/* Title — editable */}
            <EditableText
              value={rendered?.project_name || 'Untitled scorecard'}
              onCommit={(v) => setOverride('title', v)}
              style={{ fontSize:24, fontWeight:600, color:'#0f172a', letterSpacing:'-0.01em' }}
            />

            {/* Score ring + category */}
            <div style={{ display:'flex', alignItems:'center', gap:24, marginTop:24 }}>
              <div style={{ position:'relative', width:96, height:96 }}>
                <svg width="96" height="96" viewBox="0 0 96 96">
                  <circle cx="48" cy="48" r="36" fill="none" stroke="#e6eaf2" strokeWidth="8" />
                  <circle
                    cx="48" cy="48" r="36" fill="none" stroke={ringColor} strokeWidth="8"
                    strokeDasharray={2 * Math.PI * 36}
                    strokeDashoffset={(1 - score / 100) * 2 * Math.PI * 36}
                    strokeLinecap="round"
                    transform="rotate(-90 48 48)"
                  />
                </svg>
                <div style={{ position:'absolute', inset:0, display:'flex', alignItems:'center', justifyContent:'center', fontSize:26, fontWeight:600, color:'#0f172a' }}>
                  {score}
                </div>
              </div>
              <div>
                <div style={{ fontSize:11, fontWeight:600, color:ringColor, letterSpacing:'0.06em', textTransform:'uppercase' }}>{category}</div>
                <div style={{ fontSize:18, fontWeight:600, color:'#0f172a', marginTop:4 }}>Strategy scorecard</div>
                <div style={{ fontSize:12, color:'#64748b', marginTop:2 }}>Locked · scores reflect Jaspen's analysis. Open chat to rescore.</div>
              </div>
            </div>

            {/* Executive summary — editable */}
            {(rendered?.executive_summary || rendered?._display_overrides?.executive_summary !== undefined) && (
              <div style={{ marginTop:28 }}>
                <div style={{ fontSize:11, fontWeight:600, color:'#64748b', letterSpacing:'0.06em', textTransform:'uppercase', marginBottom:8 }}>
                  Executive summary
                </div>
                <EditableText
                  multiline
                  value={rendered?.executive_summary || ''}
                  onCommit={(v) => setOverride('executive_summary', v)}
                  style={{ fontSize:14, color:'#334155', lineHeight:1.6 }}
                />
              </div>
            )}

            {/* Dimension scores — read-only with lock badges */}
            <div style={{ marginTop:32 }}>
              <div style={{ fontSize:11, fontWeight:600, color:'#64748b', letterSpacing:'0.06em', textTransform:'uppercase', marginBottom:12 }}>
                Dimensions
                <span style={{ marginLeft:8, padding:'1px 6px', background:'#f1f5f9', borderRadius:6, fontSize:9, color:'#94a3b8' }}>locked</span>
              </div>
              <DimensionBars dims={rendered?.dimensions || {}} accent={ringColor} />
            </div>

            {/* Top risks — read-only */}
            {Array.isArray(rendered?.top_risks) && rendered.top_risks.length > 0 && (
              <div style={{ marginTop:28 }}>
                <div style={{ fontSize:11, fontWeight:600, color:'#64748b', letterSpacing:'0.06em', textTransform:'uppercase', marginBottom:8 }}>
                  Top risks
                  <span style={{ marginLeft:8, padding:'1px 6px', background:'#f1f5f9', borderRadius:6, fontSize:9, color:'#94a3b8' }}>locked</span>
                </div>
                <ul style={{ margin:0, paddingLeft:18, fontSize:13, color:'#334155', lineHeight:1.6 }}>
                  {rendered.top_risks.slice(0, 5).map((r, i) => (
                    <li key={i}>{typeof r === 'string' ? r : (r?.risk || r?.label || '—')}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}

// ── EditableText: click to inline-edit. onCommit fires on blur or Enter. ────
function EditableText({ value, onCommit, multiline = false, style }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value || '');

  useEffect(() => { setDraft(value || ''); }, [value]);

  const commit = () => {
    setEditing(false);
    if (draft !== value) onCommit?.(draft);
  };

  if (!editing) {
    return (
      <div
        onClick={() => setEditing(true)}
        title="Click to edit"
        style={{
          ...style,
          cursor:'text', borderRadius:6, padding:'2px 4px', margin:'-2px -4px',
          transition:'background 120ms',
        }}
        onMouseEnter={(e) => { e.currentTarget.style.background = '#f7f8fa'; }}
        onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
      >
        {value || <span style={{ color:'#94a3b8' }}>Click to add…</span>}
      </div>
    );
  }

  if (multiline) {
    return (
      <textarea
        autoFocus
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => { if (e.key === 'Escape') { setDraft(value || ''); setEditing(false); } }}
        style={{
          ...style,
          width:'100%', minHeight:90, border:'1px solid #c7d2da', borderRadius:6,
          padding:'8px 10px', resize:'vertical', fontFamily:'inherit',
        }}
      />
    );
  }

  return (
    <input
      autoFocus
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === 'Enter') { e.preventDefault(); commit(); }
        if (e.key === 'Escape') { setDraft(value || ''); setEditing(false); }
      }}
      style={{
        ...style,
        width:'100%', border:'1px solid #c7d2da', borderRadius:6, padding:'4px 8px',
        fontFamily:'inherit',
      }}
    />
  );
}

// ── DimensionBars: read-only score bars per dimension. ──────────────────────
function DimensionBars({ dims, accent }) {
  const entries = Object.entries(dims || {}).filter(([, v]) => v && typeof v === 'object');
  if (entries.length === 0) return null;
  return (
    <div style={{ display:'grid', gridTemplateColumns:'repeat(2, 1fr)', gap:'14px 32px' }}>
      {entries.map(([key, dim]) => {
        const score = Number(dim?.score || 0);
        const label = key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
        return (
          <div key={key}>
            <div style={{ display:'flex', justifyContent:'space-between', fontSize:13, color:'#0f172a', marginBottom:6 }}>
              <span>{label}</span>
              <span style={{ fontFamily:'JetBrains Mono, monospace', fontSize:12, color:'#475569' }}>
                {score.toFixed(1)}<span style={{ color:'#94a3b8' }}>/100</span>
              </span>
            </div>
            <div style={{ height:6, background:'#eef2f6', borderRadius:3, overflow:'hidden' }}>
              <div style={{ height:'100%', width:`${score}%`, background:accent, borderRadius:3 }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}
