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
import TradeoffView from './TradeoffView';
import JaspenExecutionCanvas from './JaspenExecutionCanvas';

// Sentinel scorecardId values that route the canvas to a non-scorecard
// artifact view. Keep these in sync with the entry-point links in
// JaspenChat's Session Artifacts dropdown.
const SENTINEL_TRADEOFF = '__tradeoff__';
const SENTINEL_EXECUTION = '__execution__';

// Color palette matched against the chat scorecard's renderScorecardCard.
const COLOR_NAVY = '#0f172a';
const COLOR_ROSE = '#a0036c';
const COLOR_RISK_ORANGE = '#f59e0b';

// Generic placeholders that should never surface as an idea name.
const _GENERIC_TITLES = new Set([
  'baseline analysis', 'baseline', 'jaspen project', 'jaspen analysis',
  'strategy analysis', 'initiative', 'untitled', 'untitled idea',
  'untitled scorecard', 'project',
]);
const _GENERIC_TITLE_PATTERNS = [/^version\s+\d+$/i, /^v\d+$/i, /^scenario\s+[a-z]$/i];

// Default section config for the scorecard canvas section-grid. Defined as a
// module-level const (not state) so it is stable across renders.
const DEFAULT_SCORECARD_SECTIONS = [
  { key: 'score',      label: 'Score',                cols: 2, locked: true },
  { key: 'executive',  label: 'Executive Summary',    cols: 2, locked: false },
  { key: 'dimensions', label: 'Dimensions',           cols: 2, locked: true },
  { key: 'risks',      label: 'Top Risks',            cols: 1, locked: true },
  { key: 'scenario',   label: 'Recommended Scenario', cols: 1, locked: true },
];

function _pickMeaningful(...candidates) {
  for (const c of candidates) {
    const v = String(c || '').trim();
    if (!v) continue;
    if (_GENERIC_TITLES.has(v.toLowerCase())) continue;
    if (_GENERIC_TITLE_PATTERNS.some((re) => re.test(v))) continue;
    return v;
  }
  return null;
}

// Derive a short idea name (≤7 words, natural-break aware) from a chat message.
function _deriveFromMessage(text) {
  if (!text) return null;
  let raw = String(text).trim();
  if (!raw) return null;
  raw = raw.replace(
    /^(goal\s*[:–-]\s*|my goal\s+(is\s+)?[:–-]?\s*|i want to\s+|we want to\s+|we('re| are) (building|launching|creating)\s+|idea\s*[:–-]\s*|let'?s\s+(pivot\s+to\s+|add\s+|change\s+to\s+)|what\s+if\s+we\s+|please\s+score\s+(this|that)?\s*)/i,
    '',
  );
  const firstSentence = raw.split(/[.!?\n]/)[0].trim();
  const cleaned = firstSentence.length > 0 ? firstSentence : raw;
  const words = cleaned.split(/\s+/);
  if (words.length <= 7) return cleaned;
  const BREAKS = new Set(['for', 'to', 'that', 'which', 'and', 'or', 'with', 'in', 'on', 'at', 'by', 'from', 'via', 'using', 'through', 'across', 'into', 'of', 'about', 'between']);
  for (let i = Math.min(6, words.length - 1); i >= 3; i--) {
    if (BREAKS.has(words[i].toLowerCase().replace(/[^a-z]/g, ''))) {
      return words.slice(0, i).join(' ');
    }
  }
  return words.slice(0, 7).join(' ');
}

/**
 * Apply display_overrides on top of a raw scorecard payload. Overrides are
 * purely cosmetic — anything missing falls through to the original value.
 * Generic placeholder names (Baseline Analysis, etc.) are stripped so the
 * canvas always shows a real idea name.
 */
function applyOverrides(scorecard, overrides) {
  if (!scorecard) return null;
  const ov = overrides && typeof overrides === 'object' ? overrides : {};
  const meaningfulName = _pickMeaningful(
    ov.title,
    scorecard.name,
    scorecard.project_name,
    scorecard.title,
    scorecard.initiative_name,
  ) || 'Untitled idea';
  return {
    ...scorecard,
    project_name: meaningfulName,
    executive_summary: ov.executive_summary ?? scorecard.executive_summary,
    _accent_color: ov.accent_color ?? scorecard._accent_color ?? null,
    _display_overrides: ov,
  };
}

export default function JaspenWorkspace() {
  const { threadId, scorecardId } = useParams();
  const [bundle, setBundle] = useState(null);
  const [bundleError, setBundleError] = useState(null);
  const [snapshot, setSnapshot] = useState(null);
  const [overrides, setOverrides] = useState({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(null);
  const [error, setError] = useState(null);
  const [chatInput, setChatInput] = useState('');
  const [chatHistory, setChatHistory] = useState([]);
  const [chatBusy, setChatBusy] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const saveTimerRef = useRef(null);
  const skipNextSaveRef = useRef(true); // first render = freshly loaded, don't save back
  const [sectionLayout, setSectionLayout] = useState(() =>
    DEFAULT_SCORECARD_SECTIONS.map((s) => ({ ...s, collapsed: false }))
  );
  const dragSectionRef = useRef(null);

  const isTradeoff = scorecardId === SENTINEL_TRADEOFF;
  const isExecution = scorecardId === SENTINEL_EXECUTION;
  const isScorecard = !isTradeoff && !isExecution;
  const [wbs, setWbs] = useState(null);

  // Fetch the artifact on mount. ALWAYS pull the bundle in parallel — even
  // when the focused endpoint succeeds — because the bundle carries the
  // chat messages we need for sensible title fallback when the scorecard
  // payload has a generic 'Baseline Analysis' name.
  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);

      let target = null;
      let ov = {};

      // Always fetch the bundle in parallel (cheap-ish and gives us messages
      // for title fallback + the snapshot list for the tradeoff view).
      // Track bundle errors so the Trade-off view can surface them instead
      // of showing the misleading "Score an idea" empty state when the
      // real issue was a failed fetch.
      const bundlePromise = Jaspen.fetchBundle(threadId).catch((e) => {
        console.warn('[Workspace] bundle fetch failed:', e);
        setBundleError(String(e?.message || e || 'fetch failed'));
        return null;
      });

      // For scorecard artifacts, also fetch the focused endpoint for fast
      // first paint + authoritative overrides.
      let focusedPromise = Promise.resolve(null);
      if (isScorecard) {
        focusedPromise = Jaspen.getScorecardForWorkspace(threadId, scorecardId).catch((e) => {
          console.warn('[Workspace] focused scorecard fetch failed:', e);
          return null;
        });
      }

      // For execution artifacts, the WBS lives on a separate endpoint
      // (the bundle's project_wbs can lag for legacy threads). Hit
      // /threads/:tid/wbs directly so the canvas always sees the latest.
      let wbsPromise = Promise.resolve(null);
      if (isExecution) {
        wbsPromise = Jaspen.getThreadWbs(threadId).catch((e) => {
          console.warn('[Workspace] WBS fetch failed (non-fatal):', e);
          return null;
        });
      }

      const [b, focused, wbsResp] = await Promise.all([bundlePromise, focusedPromise, wbsPromise]);
      if (cancelled) return;

      if (b) setBundle(b);
      // Pick whichever source actually has tasks. Server-side getThreadWbs
      // wins because that's the same source the chat tab reads from.
      if (wbsResp && wbsResp?.project_wbs && Array.isArray(wbsResp.project_wbs.tasks) && wbsResp.project_wbs.tasks.length > 0) {
        setWbs(wbsResp.project_wbs);
      } else if (b?.project_wbs && Array.isArray(b.project_wbs.tasks) && b.project_wbs.tasks.length > 0) {
        setWbs(b.project_wbs);
      } else if (wbsResp?.project_wbs) {
        // Empty plan — still set so canvas knows we tried
        setWbs(wbsResp.project_wbs);
      }

      if (focused) {
        target = focused.scorecard || null;
        if (focused.display_overrides && typeof focused.display_overrides === 'object') {
          ov = focused.display_overrides;
        }
      }

      // For scorecards, fall back to the bundle's snapshot list if focused
      // endpoint didn't return a target.
      if (isScorecard && !target && b) {
        const snapshots = Array.isArray(b.scorecard_snapshots) ? b.scorecard_snapshots : [];
        target = snapshots.find(
          (s) => String(s?.id || s?.analysis_id || '') === String(scorecardId)
        ) || b.current_scorecard || b.baseline_scorecard || null;
        if (target?.display_overrides && typeof target.display_overrides === 'object' && Object.keys(ov).length === 0) {
          ov = target.display_overrides;
        }
      }

      setSnapshot(target);
      skipNextSaveRef.current = true;
      setOverrides(ov || {});

      if (isScorecard && !target) {
        setError(`Couldn't load this scorecard. Check that it exists in this thread.`);
      } else {
        setError(null);
      }
      setLoading(false);
    }
    void load();
    return () => { cancelled = true; };
  }, [threadId, scorecardId, isScorecard]);

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

  // Resolve the display title for THIS specific artifact. Priority:
  // override → meaningful scorecard fields → first user message in the
  // thread bundle. Never falls back to "Untitled idea" when the thread
  // has any user message to draw from.
  const displayTitle = useMemo(() => {
    // Sentinel artifact types: distinct top-bar titles
    if (scorecardId === SENTINEL_TRADEOFF) {
      const count = Array.isArray(bundle?.scorecard_snapshots) ? bundle.scorecard_snapshots.length : 0;
      return count > 0 ? `Trade-off · ${count} ideas` : 'Trade-off';
    }
    if (scorecardId === SENTINEL_EXECUTION) {
      return 'Execution Plan';
    }

    const ov = overrides && typeof overrides === 'object' ? overrides : {};
    const fromScorecard = _pickMeaningful(
      ov.title,
      snapshot?.name,
      snapshot?.project_name,
      snapshot?.title,
      snapshot?.initiative_name,
    );
    if (fromScorecard) return fromScorecard;

    const msgs = Array.isArray(bundle?.messages) ? bundle.messages : [];
    const firstUser = msgs.find(
      (m) => (m?.role === 'user' || m?.sender === 'user') &&
        String(m?.content || m?.text || '').trim().length > 0,
    );
    const fromMessage = _deriveFromMessage(firstUser?.content || firstUser?.text);
    if (fromMessage) return fromMessage;

    return 'Untitled idea';
  }, [snapshot, overrides, bundle, scorecardId]);

  const score = Number(rendered?.jaspen_score || 0);
  const ringColor = rendered?._accent_color || '#a0036c';
  const category = score >= 80 ? 'Excellent' : score >= 60 ? 'Good' : score >= 40 ? 'Fair' : 'At Risk';

  // Recommended scenario (first recommendation that has actionable text)
  const recs = Array.isArray(rendered?.recommendations) ? rendered.recommendations : [];
  const nextSteps = Array.isArray(rendered?.next_steps) ? rendered.next_steps : [];
  const recommendedScenario = (() => {
    if (recs[0]) {
      if (typeof recs[0] === 'string') return recs[0];
      if (recs[0]?.text) return recs[0].text;
      if (recs[0]?.action) return recs[0].action;
    }
    if (nextSteps[0] && typeof nextSteps[0] === 'string') return nextSteps[0];
    return null;
  })();

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

  async function sendChat() {
    const text = chatInput.trim();
    if (!text || chatBusy) return;
    // Optimistic user message
    const userTurn = { role: 'user', text };
    const nextHistory = [...chatHistory, userTurn];
    setChatHistory([...nextHistory, { role: 'ai', text: '…', pending: true }]);
    setChatInput('');
    setChatBusy(true);

    try {
      // Build a thin analysis_context so the agent grounds replies in this
      // artifact. We keep it compact — only the fields the agent needs to
      // reason about this canvas. Manual edits still flow through their own
      // patch endpoints; this chat is for Q&A + AI-assisted edits.
      const ctx = {
        thread_id: threadId,
        artifact_kind: isExecution ? 'execution_plan' : isTradeoff ? 'tradeoff' : 'scorecard',
        scorecard_id: isScorecard ? scorecardId : null,
        scorecard_name: isScorecard ? (snapshot?.name || displayTitle) : displayTitle,
        snapshot: isScorecard ? snapshot : null,
        wbs_summary: isExecution && Array.isArray(wbs?.tasks)
          ? { tasks: wbs.tasks.length }
          : null,
      };

      // Conversation history (Anthropic-friendly role+content shape).
      const history = nextHistory.map((m) => ({
        role: m.role === 'user' ? 'user' : 'assistant',
        content: String(m.text || ''),
      }));

      const resp = await Jaspen.chat({
        message: text,
        conversation_history: history,
        analysis_context: ctx,
        analysis_id: threadId,
      });
      const replyText = String(resp?.text || resp?.response || resp?.reply || '').trim()
        || 'Got it — I noted that. (No reply payload was returned.)';
      setChatHistory((prev) => {
        // Replace the trailing pending placeholder
        const arr = prev.slice(0, -1);
        return [...arr, { role: 'ai', text: replyText }];
      });
    } catch (e) {
      console.error('[workspace chat] failed:', e);
      setChatHistory((prev) => {
        const arr = prev.slice(0, -1);
        return [
          ...arr,
          { role: 'ai', text: `Jaspen couldn't reply: ${String(e?.message || e || 'unknown error')}. Try again in a moment.` },
        ];
      });
    } finally {
      setChatBusy(false);
    }
  }

  // --- Loading / error states ---
  if (loading) {
    return (
      <div style={{ display:'flex', alignItems:'center', justifyContent:'center', height:'100vh', color:'#475569', fontSize:14 }}>
        Loading workspace…
      </div>
    );
  }
  // For scorecard routes we need a snapshot; tradeoff/execution don't.
  if (error || (isScorecard && !snapshot)) {
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
    <div data-ws-root style={{ display:'flex', height:'100vh', background:'#f7f8fa', fontFamily:'Inter Tight, system-ui, sans-serif', position:'relative' }}>
      <style>{`
        @media print {
          * { -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; }
          [data-ws-sidebar] { display: none !important; }
          [data-ws-topbar] { display: none !important; }
          [data-ws-root] { display: block !important; height: auto !important; }
          [data-ws-main] { width: 100% !important; overflow: visible !important; }
          [data-ws-canvas] { overflow: visible !important; padding: 0 !important; }
        }
      `}</style>

      {/* === LEFT SIDEBAR: scoped chat === */}
      <aside
        data-ws-sidebar
        style={{
          width: sidebarOpen ? 340 : 0,
          flexShrink: 0,
          background: '#fff',
          borderRight: sidebarOpen ? '1px solid #e6eaf2' : 'none',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          transition: 'width 0.25s ease',
          position: 'relative',
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
            {displayTitle}
          </div>
          <div style={{ fontSize:12, color:'#64748b', marginTop:2 }}>
            {isExecution
              ? <>Editing execution plan. <span style={{ color:'#0f172a', fontWeight:500 }}>Manual edits are free</span>; AI edits cost credits.</>
              : isTradeoff
                ? <>Viewing trade-off comparison. <span style={{ color:'#0f172a', fontWeight:500 }}>Ask Jaspen anything</span> about the comparison.</>
                : <>Editing cosmetic fields. <span style={{ color:'#0f172a', fontWeight:500 }}>Manual edits are free</span>; AI edits cost credits.</>}
          </div>
        </div>

        {/* Chat thread */}
        <div style={{ flex:1, overflow:'auto', padding:'12px 16px', display:'flex', flexDirection:'column', gap:10 }}>
          {chatHistory.length === 0 && (
            <div style={{ fontSize:12, color:'#94a3b8', lineHeight:1.5 }}>
              {isExecution
                ? 'Ask Jaspen to reassign tasks, shift dates, or regenerate the plan — or click any cell on the canvas to edit directly.'
                : 'Ask Jaspen to rewrite copy, adjust tone, or tweak styling — or click anything on the canvas to edit directly.'}
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
              placeholder={chatBusy ? 'Jaspen is replying…' : 'Describe a change…'}
              disabled={chatBusy}
              style={{ flex:1, border:'none', outline:'none', background:'transparent', fontSize:13, color:'#0f172a' }}
            />
            <button
              onClick={sendChat}
              disabled={!chatInput.trim() || chatBusy}
              style={{
                width:30, height:30, borderRadius:8, border:'none',
                background: (chatInput.trim() && !chatBusy) ? '#0f172a' : '#cbd5e1',
                color:'#fff', cursor: (chatInput.trim() && !chatBusy) ? 'pointer' : 'not-allowed',
                display:'flex', alignItems:'center', justifyContent:'center',
              }}
              aria-label="Send"
            >
              <FontAwesomeIcon icon={faPaperPlane} style={{ fontSize:11 }} />
            </button>
          </div>
        </div>
      </aside>

      {/* Sidebar toggle tab */}
      <button
        data-ws-sidebar
        onClick={() => setSidebarOpen((o) => !o)}
        title={sidebarOpen ? 'Collapse chat' : 'Expand chat'}
        style={{
          position: 'absolute',
          left: sidebarOpen ? 332 : 0,
          top: '50%',
          transform: 'translateY(-50%)',
          zIndex: 10,
          width: 20,
          height: 48,
          borderRadius: sidebarOpen ? '0 6px 6px 0' : '0 6px 6px 0',
          border: '1px solid #e6eaf2',
          borderLeft: sidebarOpen ? 'none' : '1px solid #e6eaf2',
          background: '#fff',
          color: '#64748b',
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: 10,
          transition: 'left 0.25s ease',
          padding: 0,
        }}
        aria-label={sidebarOpen ? 'Collapse chat panel' : 'Expand chat panel'}
      >
        {sidebarOpen ? '‹' : '›'}
      </button>

      {/* === CENTER: canvas === */}
      <main data-ws-main style={{ flex:1, display:'flex', flexDirection:'column', overflow:'hidden' }}>
        <div data-ws-topbar style={{ padding:'18px 28px', borderBottom:'1px solid #e6eaf2', background:'#fff', display:'flex', alignItems:'center', justifyContent:'space-between' }}>
          <div style={{ display:'flex', alignItems:'baseline', gap:10 }}>
            <h1 style={{ margin:0, fontSize:18, fontWeight:600, color:'#0f172a' }}>{displayTitle}</h1>
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

        {/* Canvas */}
        <div data-ws-canvas style={{ flex:1, overflow:'auto', padding: isTradeoff ? 0 : '32px 48px' }}>
          {isTradeoff ? (
            // Trade-off canvas: full TradeoffView render. Cosmetic edits
            // (title overrides etc.) will land in v1.1 — this v1 shows the
            // full comparison surface inside the Workspace shell so the user
            // can already 'view large' and download.
            //
            // We merge baseline + current into the snapshots list because for
            // older threads `bundle.scorecard_snapshots` may be empty even
            // when a baseline exists — TradeoffView's empty state would then
            // hide a comparison that actually has data to show.
            <div style={{ height:'100%', display:'flex', flexDirection:'column' }}>
              {(() => {
                // Mirror what the chat-tab Trade-off view sees. Sources, in
                // order of preference: bundle.scorecard_snapshots (the
                // canonical merged list), then baseline_scorecard, then
                // current_scorecard, then every scenario in bundle.scenarios.
                // We de-dupe by id so the same scorecard doesn't appear twice.
                const list = [];
                const known = new Set();
                const seed = (s, label, isBaseline) => {
                  if (!s || typeof s !== 'object') return;
                  const id = String(
                    s.id || s.analysis_id || s.analysisId ||
                    (isBaseline ? 'baseline' : `card_${list.length}`)
                  );
                  if (known.has(id)) return;
                  known.add(id);
                  list.push({
                    ...s,
                    id,
                    analysis_id: s.analysis_id || id,
                    label: s.label || label,
                    isBaseline: Boolean(isBaseline || s.isBaseline),
                  });
                };
                // 1. The canonical merged list (covers historical snapshots).
                (Array.isArray(bundle?.scorecard_snapshots) ? bundle.scorecard_snapshots : [])
                  .forEach((s, i) => seed(s, s?.label || `Version ${i + 1}`, s?.isBaseline));
                // 2. Baseline + current — usually already in (1), but seed
                //    anyway in case the merged list is empty for legacy threads.
                seed(bundle?.baseline_scorecard, 'Baseline', true);
                seed(bundle?.current_scorecard, 'Current', false);
                // 3. Scenario-derived scorecards — `result` is the standard
                //    payload key, but we accept the alternates the chat tab
                //    accepts too.
                (Array.isArray(bundle?.scenarios) ? bundle.scenarios : []).forEach((entry, i) => {
                  const inner = entry?.result || entry?.scorecard || entry?.analysis_result;
                  if (!inner || typeof inner !== 'object') return;
                  seed(
                    { ...inner, label: inner.label || entry?.label || `Scenario ${i + 1}` },
                    entry?.label || `Scenario ${i + 1}`,
                    false,
                  );
                });

                // Diagnostic visibility — log every source the Trade-off view
                // pulled from so the user (and we) can see exactly where the
                // data came from / why it might be empty.
                if (typeof console !== 'undefined' && console.log) {
                  console.log('[Trade-off Workspace]', {
                    threadId,
                    bundleLoaded: Boolean(bundle),
                    bundleError,
                    snapshotsFromBundle: (bundle?.scorecard_snapshots || []).length,
                    hasBaseline: Boolean(bundle?.baseline_scorecard),
                    hasCurrent: Boolean(bundle?.current_scorecard),
                    scenariosFromBundle: (bundle?.scenarios || []).length,
                    listLength: list.length,
                  });
                }

                // Honest error path: when bundle didn't load at all, say so
                // instead of falling through to "Score an idea" — that
                // empty-state was misleading users into thinking they had
                // no scorecards when the real cause was a fetch failure.
                if (!bundle && bundleError) {
                  return (
                    <div style={{ flex:1, display:'flex', alignItems:'center', justifyContent:'center', padding:40, flexDirection:'column', gap:10 }}>
                      <div style={{ fontSize:14, fontWeight:600, color:'#0f172a' }}>Couldn't load trade-off data</div>
                      <div style={{ fontSize:12.5, color:'#5a6585', maxWidth:480, textAlign:'center' }}>
                        {bundleError}
                      </div>
                      <button
                        type="button"
                        onClick={() => window.location.reload()}
                        style={{ marginTop:8, padding:'8px 14px', borderRadius:8, background:'#0f172a', color:'#fff', border:'none', fontSize:13, cursor:'pointer' }}
                      >Refresh</button>
                    </div>
                  );
                }

                return (
                  <TradeoffView
                    scorecardSnapshots={list}
                    strategyObjective={bundle?.strategy_objective || 'balanced'}
                    portfolioAnalysis={null}
                    onAsk={() => { /* no-op for now */ }}
                    asking={false}
                    threadId={threadId}
                  />
                );
              })()}
            </div>
          ) : isExecution ? (
            <JaspenExecutionCanvas
              threadId={threadId}
              bundle={bundle}
              wbs={wbs}
              displayTitle={(() => {
                // Derive the canvas title: prefer the adopted scorecard's
                // name, fall back to the first user message.
                const baseline = bundle?.baseline_scorecard;
                const fromCard = _pickMeaningful(
                  baseline?.display_overrides?.title,
                  baseline?.name,
                  baseline?.project_name,
                  baseline?.title,
                );
                if (fromCard) return fromCard;
                const msgs = Array.isArray(bundle?.messages) ? bundle.messages : [];
                const firstUser = msgs.find(
                  (m) => (m?.role === 'user' || m?.sender === 'user') &&
                    String(m?.content || m?.text || '').trim().length > 0,
                );
                return _deriveFromMessage(firstUser?.content || firstUser?.text) || 'Execution plan';
              })()}
              score={Number(bundle?.baseline_scorecard?.jaspen_score || bundle?.current_scorecard?.jaspen_score || 0) || null}
              onAskJaspen={(text) => {
                setChatInput(text);
              }}
            />
          ) : (
          <div
            style={{
              maxWidth:980, margin:'0 auto', background:'#fff', borderRadius:14,
              boxShadow:'0 1px 3px rgba(15,23,42,0.06), 0 8px 24px rgba(15,23,42,0.04)',
              padding:'36px 40px',
            }}
          >
            {/* Title — editable */}
            <EditableText
              value={displayTitle}
              onCommit={(v) => setOverride('title', v)}
              style={{ fontSize:24, fontWeight:600, color:'#0f172a', letterSpacing:'-0.01em' }}
            />

            {/* Section grid */}
            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:20, marginTop:28 }}>
              {sectionLayout.map((section, idx) => {
                // Skip sections with no data
                if (section.key === 'executive' &&
                    !rendered?.executive_summary &&
                    rendered?._display_overrides?.executive_summary === undefined) return null;
                if (section.key === 'risks' &&
                    !(Array.isArray(rendered?.top_risks) && rendered.top_risks.length > 0)) return null;
                if (section.key === 'scenario' && !recommendedScenario) return null;

                const isCollapsed = section.collapsed;

                const toggleCollapse = () => {
                  setSectionLayout((prev) =>
                    prev.map((s, i) => i === idx ? { ...s, collapsed: !s.collapsed } : s)
                  );
                };

                const toggleSize = () => {
                  if (section.key === 'score') return; // score is always full-width
                  setSectionLayout((prev) =>
                    prev.map((s, i) => i === idx ? { ...s, cols: s.cols === 2 ? 1 : 2 } : s)
                  );
                };

                const handleDragStart = (e) => {
                  dragSectionRef.current = idx;
                  e.dataTransfer.effectAllowed = 'move';
                };

                const handleDragOver = (e) => {
                  e.preventDefault();
                  e.currentTarget.style.borderTop = '2px solid #a0036c';
                };

                const handleDragLeave = (e) => {
                  e.currentTarget.style.borderTop = '';
                };

                const handleDrop = (e) => {
                  e.preventDefault();
                  e.currentTarget.style.borderTop = '';
                  const fromIdx = dragSectionRef.current;
                  if (fromIdx === null || fromIdx === idx) return;
                  setSectionLayout((prev) => {
                    const next = [...prev];
                    const [moved] = next.splice(fromIdx, 1);
                    next.splice(idx, 0, moved);
                    return next;
                  });
                  dragSectionRef.current = null;
                };

                return (
                  <div
                    key={section.key}
                    draggable
                    onDragStart={handleDragStart}
                    onDragOver={handleDragOver}
                    onDragLeave={handleDragLeave}
                    onDrop={handleDrop}
                    style={{
                      gridColumn: `span ${section.cols}`,
                      background: isCollapsed ? '#fafbfc' : '#fff',
                      borderRadius: 8,
                      padding: isCollapsed ? 0 : '12px',
                      transition: 'all 0.15s',
                      boxSizing: 'border-box',
                    }}
                  >
                    {/* Section header bar */}
                    <div style={{
                      display:'flex', alignItems:'center', gap:8,
                      padding:'6px 0', marginBottom: isCollapsed ? 0 : 12,
                      cursor:'default', borderBottom:'1px solid #e6eaf2',
                    }}>
                      {/* Drag handle */}
                      <span style={{ fontSize:14, color:'#cbd5e1', cursor:'grab', userSelect:'none' }}>⠿</span>
                      {/* Label */}
                      <span style={{
                        fontSize:11, fontWeight:600, color:'#64748b',
                        letterSpacing:'0.06em', textTransform:'uppercase', flex:1,
                      }}>
                        {section.label}
                      </span>
                      {/* Lock badge */}
                      {section.locked && (
                        <span style={{
                          padding:'1px 6px', background:'#f1f5f9', borderRadius:6,
                          fontSize:9, color:'#94a3b8',
                        }}>LOCKED</span>
                      )}
                      {/* Size toggle — hidden for 'score' section */}
                      {section.key !== 'score' && (
                        <button
                          type="button"
                          onClick={toggleSize}
                          title={section.cols === 2 ? 'Half width' : 'Full width'}
                          style={{ fontSize:11, color:'#94a3b8', cursor:'pointer', background:'none', border:'none', padding:'2px 4px' }}
                        >
                          {section.cols === 2 ? '◫' : '▬'}
                        </button>
                      )}
                      {/* Collapse toggle */}
                      <button
                        type="button"
                        onClick={toggleCollapse}
                        title={isCollapsed ? 'Expand' : 'Collapse'}
                        style={{ fontSize:11, color:'#94a3b8', cursor:'pointer', background:'none', border:'none', padding:'2px 4px' }}
                      >
                        {isCollapsed ? '›' : '⌄'}
                      </button>
                    </div>

                    {/* Section content */}
                    <div style={{ display: isCollapsed ? 'none' : 'block' }}>
                      {section.key === 'score' && (
                        <div style={{ display:'flex', alignItems:'center', gap:24 }}>
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
                      )}

                      {section.key === 'executive' && (
                        <EditableText
                          multiline
                          value={rendered?.executive_summary || ''}
                          onCommit={(v) => setOverride('executive_summary', v)}
                          style={{ fontSize:14, color:'#334155', lineHeight:1.6 }}
                        />
                      )}

                      {section.key === 'dimensions' && (
                        <DimensionBars dims={rendered?.dimensions || {}} />
                      )}

                      {section.key === 'risks' && Array.isArray(rendered?.top_risks) && rendered.top_risks.length > 0 && (
                        <ul style={{ margin:0, paddingLeft:0, listStyle:'none', fontSize:13, color:'#334155', lineHeight:1.65 }}>
                          {rendered.top_risks.slice(0, 5).map((r, i) => (
                            <li key={i} style={{ marginBottom:6, paddingLeft:14, position:'relative' }}>
                              <span style={{ position:'absolute', left:0, color:'#94a3b8' }}>·</span>
                              {typeof r === 'string' ? r : (r?.risk || r?.label || '—')}
                            </li>
                          ))}
                        </ul>
                      )}

                      {section.key === 'scenario' && recommendedScenario && (
                        <div style={{ fontSize:13, color:ringColor, lineHeight:1.65, fontStyle:'italic' }}>
                          + {recommendedScenario}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Footer hint */}
            <div style={{
              marginTop:32, paddingTop:18, borderTop:'1px solid #e6eaf2',
              fontSize:12, color:'#64748b',
            }}>
              Click any heading or summary above to edit. Scores and risks stay locked — use the chat to rescore.
            </div>
          </div>
          )}
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
// Labels and colors match the chat scorecard's renderScorecardCard so the
// workspace canvas reads identically. Risk dimensions show in orange; all
// other dimensions show in navy.
const _DIMENSION_LABELS = {
  strategic_alignment: 'Strategic fit',
  financial_viability: 'Cost efficiency',
  execution_readiness: 'Time-to-value',
  risk_profile: 'Execution risk',
  market_opportunity: 'Market Opportunity',
  evidence_quality: 'Evidence Quality',
};
const _DIMENSION_ORDER = [
  'strategic_alignment',
  'financial_viability',
  'execution_readiness',
  'risk_profile',
  'market_opportunity',
  'evidence_quality',
];
const _RISK_DIMENSIONS = new Set(['risk_profile']);

function DimensionBars({ dims }) {
  if (!dims || typeof dims !== 'object') return null;
  const ordered = _DIMENSION_ORDER
    .map((key) => ({ key, dim: dims[key] }))
    .filter(({ dim }) => dim && typeof dim === 'object');
  for (const [key, dim] of Object.entries(dims)) {
    if (!_DIMENSION_LABELS[key] && dim && typeof dim === 'object') {
      ordered.push({ key, dim });
    }
  }
  if (ordered.length === 0) return null;
  return (
    <div style={{ display:'grid', gridTemplateColumns:'repeat(2, 1fr)', gap:'14px 32px' }}>
      {ordered.map(({ key, dim }) => {
        const score = Number(dim?.score || 0);
        const label = _DIMENSION_LABELS[key]
          || key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
        const barColor = _RISK_DIMENSIONS.has(key) ? COLOR_RISK_ORANGE : COLOR_NAVY;
        return (
          <div key={key}>
            <div style={{ display:'flex', justifyContent:'space-between', fontSize:13, color:'#0f172a', marginBottom:6 }}>
              <span>{label}</span>
              <span style={{ fontFamily:'JetBrains Mono, monospace', fontSize:12, color:'#475569' }}>
                {(score / 10).toFixed(1)}<span style={{ color:'#94a3b8' }}>/10</span>
              </span>
            </div>
            <div style={{ height:6, background:'#eef2f6', borderRadius:3, overflow:'hidden' }}>
              <div style={{ height:'100%', width:`${score}%`, background:barColor, borderRadius:3 }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}
