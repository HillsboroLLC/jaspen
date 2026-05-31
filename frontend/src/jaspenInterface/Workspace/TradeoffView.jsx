// TradeoffView.jsx — Portfolio trade-off engine
// Replaces the old ScenarioModeler / inline scenarios view.
// Receives scorecardSnapshots from the workspace and derives the portfolio data.

import React, { useState, useMemo, useRef, useCallback } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faEye, faEyeSlash, faDiagramProject, faSpinner } from '@fortawesome/free-solid-svg-icons';
import { Jaspen } from './JaspenClient';

const NAVY   = '#161f3b';
const ROSE   = '#a0036c';
const SLATE  = '#5a6585';
const MUTED  = '#8a93ad';
const LINE   = '#eef1f6';
const BG_ALT = '#f8fafc';

const DIM_KEYS = [
  { key: 'strategic_alignment', label: 'Strategic fit',   short: 'Strategic' },
  { key: 'financial_viability',  label: 'Cost efficiency', short: 'Cost'      },
  { key: 'execution_readiness',  label: 'Time-to-value',   short: 'Time'      },
  { key: 'market_opportunity',   label: 'Market ready',    short: 'Market'    },
  { key: 'risk_profile',         label: 'Execution risk',  short: 'Risk'      },
  { key: 'evidence_quality',     label: 'Data confidence', short: 'Data'      },
];

// Derive a 2-char ID from project name
function shortId(name) {
  const words = String(name || '').trim().split(/\s+/);
  if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase();
  return String(name || '??').slice(0, 2).toUpperCase();
}

// Assign status from score
function deriveStatus(score) {
  if (score >= 74) return 'PRIORITIZE';
  if (score >= 58) return 'HOLD';
  return 'PARK';
}

// Pull dim score (0–10 scale) from a scorecard snapshot
function dimScore(snap, key) {
  const dims = snap?.dimensions || {};
  const comp = snap?.component_scores || snap?.scores || {};
  const raw = Number(dims[key]?.score ?? comp[key] ?? 0);
  // scores may be 0-100 or 0-10 — normalise to 0-10
  return raw > 10 ? raw / 10 : raw;
}

// Build the IDEAS array from scorecardSnapshots.
//
// Each idea carries an `included` flag from snapshot.display_overrides.
// Excluded ideas are kept in the returned list (so the table can render
// them greyed at the bottom) but are skipped when computing hero-strip
// math, the quadrant, and the ranking pills 1/2/3.
function deriveIdeas(snapshots) {
  // Score-desc sort across all snapshots so rank numbers match the original
  // intent. We assign ranks AFTER splitting included/excluded — only
  // included ideas earn a 1/2/3 pick badge.
  const sorted = [...snapshots].sort((a, b) =>
    (Number(b.jaspen_score ?? b.score ?? 0)) - (Number(a.jaspen_score ?? a.score ?? 0))
  );
  let includedSeen = 0;
  return sorted.map((snap, i) => {
    const score = Math.round(Number(snap.jaspen_score ?? snap.score ?? 0));
    const dims  = DIM_KEYS.map(({ key }) => Number(dimScore(snap, key).toFixed(1)));
    const name  = snap.project_name || snap.name || snap.label || `Idea ${i + 1}`;
    const sub   = snap.recommendations?.[0]
      ? (typeof snap.recommendations[0] === 'string'
          ? snap.recommendations[0]
          : snap.recommendations[0].text || snap.recommendations[0].action || '')
      : (snap.key_insights?.[0] ? String(snap.key_insights[0]).slice(0, 60) : '');
    // Default included=true if the flag has never been set on this snapshot.
    const overrides = (snap?.display_overrides && typeof snap.display_overrides === 'object')
      ? snap.display_overrides
      : {};
    const included = overrides.tradeoff_included !== false; // undefined → true
    let rank = null;
    let pick = null;
    if (included) {
      includedSeen += 1;
      rank = includedSeen;
      pick = includedSeen <= 3 ? includedSeen : null;
    }
    return {
      id:     shortId(name),
      // Carry the canonical snapshot id so we can call the overrides PATCH
      // endpoint from the row toggle. shortId is just a 2-char display badge.
      snapId: String(snap?.id || snap?.analysis_id || snap?.analysisId || ''),
      name,
      sub:    sub.slice(0, 72) || '—',
      score,
      rank,
      dims,
      pick,
      included,
      status: included ? deriveStatus(score) : 'PARKED',
      _snap:  snap,
    };
  });
}

// ── Status label ──────────────────────────────────────────────────────────────
// PARKED uses the muted gray to read as "not currently in play".
const StatusLabel = ({ s }) => {
  let color = MUTED;
  if (s === 'PRIORITIZE') color = ROSE;
  else if (s === 'HOLD') color = SLATE;
  else if (s === 'PARKED') color = MUTED;
  return (
    <span style={{
      fontFamily: 'JetBrains Mono, monospace',
      fontSize: 10.5, fontWeight: 600, letterSpacing: '0.08em', color,
    }}>{s}</span>
  );
};

// ── Dimension bar ─────────────────────────────────────────────────────────────
const DimBar = ({ v, alt }) => {
  const pct   = Math.min(Math.max(v / 10, 0), 1) * 100;
  const color = v < 6 ? '#eab67b' : NAVY;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      <div style={{
        height: 5, borderRadius: 3, overflow: 'hidden',
        background: alt ? '#fff' : LINE, border: alt ? `1px solid ${LINE}` : 'none',
      }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 3 }} />
      </div>
      <div style={{
        fontFamily: 'JetBrains Mono, monospace',
        fontSize: 10, color: SLATE, textAlign: 'center',
      }}>{v.toFixed(1)}</div>
    </div>
  );
};

// ── Portfolio row ─────────────────────────────────────────────────────────────
// Excluded rows render at 50% opacity, drop the rank/pick badge, and the
// eye icon flips to eye-slash. Clicking the eye toggles include/exclude
// (persists via Jaspen.patchScorecardOverrides, fired by the parent).
const PortfolioRow = ({ d, alt, onSelect, selected, onToggleInclude, onBuildPlan, buildingPlan }) => {
  const excluded = !d.included;
  return (
  <div
    onClick={() => onSelect(d)}
    style={{
      display: 'grid',
      gridTemplateColumns: TABLE_GRID,
      alignItems: 'center', gap: 12,
      padding: '13px 18px',
      borderBottom: `1px solid ${LINE}`,
      background: selected ? '#fdf3f9' : alt ? BG_ALT : '#fff',
      position: 'relative', cursor: 'pointer',
      opacity: excluded ? 0.5 : 1,
      transition: 'background 0.1s, opacity 0.18s',
    }}
  >
    {d.pick && <div style={{ position:'absolute', left:0, top:0, bottom:0, width:3, background: ROSE }} />}
    <span style={{ fontFamily:'JetBrains Mono,monospace', fontSize:13, fontWeight:600, color: d.pick ? ROSE : SLATE }}>
      {excluded ? '—' : d.rank}
    </span>
    <div style={{
      width:28, height:28, borderRadius:7,
      background: alt ? '#fff' : BG_ALT, border: `1px solid ${LINE}`,
      display:'flex', alignItems:'center', justifyContent:'center',
      fontFamily:'JetBrains Mono,monospace', fontSize:10.5, fontWeight:600, color:NAVY, letterSpacing:'0.04em',
    }}>{d.id}</div>
    <div style={{ minWidth:0 }}>
      <div style={{
        fontSize:13, fontWeight: d.pick ? 600 : 500, color:NAVY,
        overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap',
        textDecoration: excluded ? 'line-through' : 'none',
      }}>{d.name}</div>
      <div style={{ fontSize:11, color:MUTED, marginTop:2, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{d.sub}</div>
    </div>
    {d.dims.map((v, i) => <DimBar key={i} v={v} alt={alt} />)}
    <div style={{ textAlign:'right' }}>
      <span style={{ fontFamily:'JetBrains Mono,monospace', fontSize: d.pick ? 18 : 16, fontWeight:600, color:NAVY, letterSpacing:'-0.02em' }}>{d.score}</span>
    </div>
    <div style={{ textAlign:'right' }}><StatusLabel s={d.status} /></div>
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        if (typeof onBuildPlan === 'function') onBuildPlan(d);
      }}
      disabled={Boolean(buildingPlan)}
      title="Build an execution plan from this idea"
      aria-label="Build an execution plan from this idea"
      style={{
        appearance:'none', border:'none', background:'transparent',
        cursor: buildingPlan ? 'wait' : 'pointer', padding:6, borderRadius:6,
        color: ROSE,
        display:'flex', alignItems:'center', justifyContent:'center',
        opacity: buildingPlan && !d._isBuilding ? 0.4 : 1,
        transition: 'background 0.12s, color 0.12s',
      }}
      onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(160,3,108,0.08)'; }}
      onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
    >
      <FontAwesomeIcon
        icon={d._isBuilding ? faSpinner : faDiagramProject}
        spin={Boolean(d._isBuilding)}
        style={{ fontSize: 13 }}
      />
    </button>
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        if (typeof onToggleInclude === 'function') onToggleInclude(d, !d.included);
      }}
      title={excluded ? 'Include in trade-off' : 'Park (exclude from trade-off)'}
      aria-label={excluded ? 'Include in trade-off' : 'Park (exclude from trade-off)'}
      style={{
        appearance:'none', border:'none', background:'transparent',
        cursor:'pointer', padding:6, borderRadius:6,
        color: excluded ? MUTED : NAVY,
        display:'flex', alignItems:'center', justifyContent:'center',
        transition: 'background 0.12s, color 0.12s',
      }}
      onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(160,3,108,0.08)'; }}
      onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
    >
      <FontAwesomeIcon icon={excluded ? faEyeSlash : faEye} style={{ fontSize: 13 }} />
    </button>
  </div>
);
};

// ── Scatter quadrant ──────────────────────────────────────────────────────────
// Excluded ideas are skipped from the plot — they have no rank/pick and
// would just visually compete with the included ones.
const TradeoffQuadrant = ({ ideas, xDim = 1, yDim = 0, xLabel = 'Cost efficiency', yLabel = 'Strategic fit' }) => {
  const W = 340, H = 210, pad = 20;
  const xFor = (v) => pad + ((v - 2) / 8) * (W - pad * 2);
  const yFor = (v) => H - pad - ((v - 2) / 8) * (H - pad * 2);
  const plotted = ideas.filter((d) => d.included);

  return (
    <div style={{ position:'relative', width:W, height:H }}>
      <svg width={W} height={H} style={{ position:'absolute', inset:0 }}>
        <rect x={pad} y={pad} width={W-pad*2} height={H-pad*2} fill={BG_ALT} stroke={LINE} />
        <line x1={pad+(W-pad*2)/2} y1={pad} x2={pad+(W-pad*2)/2} y2={H-pad} stroke="#e4e8f0" strokeDasharray="3 3" />
        <line x1={pad} y1={pad+(H-pad*2)/2} x2={W-pad} y2={pad+(H-pad*2)/2} stroke="#e4e8f0" strokeDasharray="3 3" />
        <text x={W-pad-4} y={pad+11} textAnchor="end" fontSize="8.5" fontFamily="JetBrains Mono" fill={ROSE}>PRIORITIZE →</text>
        <text x={pad+3} y={H-pad-5} fontSize="8.5" fontFamily="JetBrains Mono" fill={MUTED}>PARK</text>
      </svg>
      {plotted.map((d) => {
        const cx = xFor(d.dims[xDim] || 5);
        const cy = yFor(d.dims[yDim] || 5);
        const r  = d.pick ? 9 : 5;
        return (
          <div key={d.id} title={d.name} style={{
            position:'absolute', left: cx - r, top: cy - r,
            width: r*2, height: r*2, borderRadius: r,
            background: d.pick ? ROSE : NAVY,
            border: d.pick ? '2px solid #fff' : 'none',
            boxShadow: d.pick ? `0 0 0 1px ${ROSE}` : 'none',
            display:'flex', alignItems:'center', justifyContent:'center',
            fontSize: 8.5, color:'#fff', fontWeight:600,
            fontFamily:'JetBrains Mono,monospace',
            cursor:'default',
          }}>{d.pick || ''}</div>
        );
      })}
      <div style={{ position:'absolute', left:0, top:-2, fontSize:9.5, color:SLATE, fontFamily:'JetBrains Mono,monospace' }}>{yLabel} →</div>
      <div style={{ position:'absolute', right:0, bottom:-15, fontSize:9.5, color:SLATE, fontFamily:'JetBrains Mono,monospace' }}>{xLabel} →</div>
    </div>
  );
};

// ── Summary stats strip ───────────────────────────────────────────────────────
// Operates on INCLUDED ideas only. Excluded ("parked") ideas don't count
// toward Ideas scored, Session avg, or Top-3 capture.
const HeroStrip = ({ ideas, objective }) => {
  const includedIdeas = ideas.filter((d) => d.included);
  const total       = includedIdeas.length;
  const combined    = includedIdeas.reduce((s, d) => s + d.score, 0);
  const avg         = total ? (combined / total).toFixed(1) : 0;
  const top3        = includedIdeas.filter(d => d.pick);
  const top3Scores  = top3.reduce((s, d) => s + d.score, 0);
  const maxPossible = total * 100;
  const capture     = maxPossible ? Math.round((top3Scores / maxPossible) * 100) : 0;
  const parkedCount = ideas.length - total;

  // "Combined score" was confusing (sum of scores is meaningless to read at
  // a glance). Replaced with the session average — matches the existing
  // "Ideas scored" / "Top-3 capture" sibling stats in shape and tone.
  // When some ideas are parked, the "Ideas scored" subtext notes how many
  // are sitting out so the math is transparent.
  const ideasSub = parkedCount > 0
    ? `${total} included · ${parkedCount} parked`
    : `of ${total} in session`;
  const stats = [
    { k: 'Ideas scored',   v: `${total}`, sub: ideasSub },
    { k: 'Session avg',    v: `${avg}`,   sub: 'across included ideas' },
    { k: 'Top-3 capture',  v: `${capture}%`, sub: 'of projected impact' },
  ];

  return (
    <div style={{ display:'grid', gridTemplateColumns: `repeat(${stats.length}, 1fr)`, gap:20 }}>
      {stats.map((s, i) => (
        <div key={i} style={{ borderLeft: i ? `1px solid ${LINE}` : 'none', paddingLeft: i ? 20 : 0 }}>
          <div style={{ fontFamily:'JetBrains Mono,monospace', fontSize:10.5, color:MUTED, letterSpacing:'0.06em', textTransform:'uppercase' }}>{s.k}</div>
          <div style={{ fontFamily:'JetBrains Mono,monospace', fontSize:24, fontWeight:600, color:NAVY, marginTop:5, letterSpacing:'-0.02em' }}>{s.v}</div>
          <div style={{ fontSize:11, color:SLATE, marginTop:2 }}>{s.sub}</div>
        </div>
      ))}
      {objective && (
        <div style={{ borderLeft:`1px solid ${LINE}`, paddingLeft:20 }}>
          <div style={{ fontFamily:'JetBrains Mono,monospace', fontSize:10.5, color:MUTED, letterSpacing:'0.06em', textTransform:'uppercase' }}>Objective</div>
          <div style={{ fontSize:13, fontWeight:500, color:NAVY, marginTop:5 }}>{objective}</div>
        </div>
      )}
    </div>
  );
};

// ── AI recommendation sidebar ─────────────────────────────────────────────────
const TradeoffSidebar = ({ ideas, portfolioAnalysis, onAsk, asking }) => {
  const [input, setInput] = useState('');
  const inputRef = useRef(null);
  const top3 = ideas.filter(d => d.pick);

  const handleSubmit = () => {
    const text = input.trim();
    if (!text || asking) return;
    onAsk(text);
    setInput('');
  };

  return (
    <div style={{
      width: 380, flexShrink: 0,
      background: '#eff9fc',
      borderLeft: '1px solid #d6e9ef',
      display:'flex', flexDirection:'column', overflow:'hidden',
    }}>
      {/* Header */}
      <div style={{ padding:'16px 20px', borderBottom:'1px solid #d6e9ef', display:'flex', alignItems:'center', gap:10 }}>
        <div style={{ position:'relative' }}>
          <div style={{ width:28, height:28, borderRadius:14, background:ROSE }} />
          <span style={{ position:'absolute', bottom:-1, right:-1, width:9, height:9, borderRadius:5, background:NAVY, boxShadow:'0 0 0 2px #eff9fc' }} />
        </div>
        <div>
          <div style={{ fontSize:13, fontWeight:600, color:NAVY, lineHeight:1.1 }}>Jaspen</div>
          <div style={{ fontSize:11, color:SLATE }}>
            {portfolioAnalysis ? `Analyzed ${ideas.length} scorecards` : 'Analyzing portfolio…'}
          </div>
        </div>
      </div>

      {/* Body */}
      <div style={{ flex:1, padding:'20px 20px 0', overflow:'auto', display:'flex', flexDirection:'column', gap:14 }}>
        <div style={{ fontSize:10.5, fontWeight:600, letterSpacing:'0.08em', color:ROSE, textTransform:'uppercase' }}>
          ✦ &nbsp;Recommendation
        </div>

        {portfolioAnalysis ? (
          <>
            <div style={{ fontSize:17, lineHeight:1.4, color:NAVY, fontWeight:500, letterSpacing:'-0.01em' }}>
              {portfolioAnalysis.summary || `Prioritize the top ${top3.length} — they capture the strongest risk-adjusted return.`}
            </div>
            <div style={{ display:'flex', flexDirection:'column', gap:0 }}>
              {(portfolioAnalysis.picks || top3).slice(0, 3).map((p, i) => (
                <div key={p.id || i} style={{ padding:'12px 0', display:'flex', gap:10, borderBottom: i < 2 ? `1px solid #d6e9ef` : 'none' }}>
                  <span style={{
                    width:22, height:22, borderRadius:11, background:ROSE, color:'#fff',
                    display:'flex', alignItems:'center', justifyContent:'center',
                    fontFamily:'JetBrains Mono,monospace', fontSize:11, fontWeight:600, flexShrink:0, marginTop:1,
                  }}>{i + 1}</span>
                  <div style={{ minWidth:0 }}>
                    <div style={{ display:'flex', alignItems:'baseline', gap:7 }}>
                      <div style={{ fontSize:13.5, fontWeight:600, color:NAVY }}>{p.name}</div>
                      <span style={{ fontFamily:'JetBrains Mono,monospace', fontSize:10.5, color:MUTED }}>{p.id} · {p.score}</span>
                    </div>
                    <div style={{ fontSize:12, color:SLATE, marginTop:4, lineHeight:1.5 }}>{p.why || p.sub || '—'}</div>
                  </div>
                </div>
              ))}
            </div>
          </>
        ) : (
          <div style={{ fontSize:13, color:SLATE, lineHeight:1.6 }}>
            {ideas.length === 0
              ? 'No scorecards yet. Score an idea in the conversation and it will appear here.'
              : 'Ask Jaspen to rank, compare, or recommend from your scored ideas.'}
          </div>
        )}
      </div>

      {/* Ask anything */}
      <div style={{ padding:'12px 16px 16px' }}>
        <div style={{
          background:'#fff', border:'1px solid #d6e9ef', borderRadius:10,
          padding:'9px 11px', display:'flex', alignItems:'center', gap:8,
        }}>
          <span style={{ fontSize:13, color:ROSE }}>✦</span>
          <input
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSubmit(); } }}
            placeholder="Ask anything about these ideas…"
            disabled={asking}
            style={{
              flex:1, border:'none', outline:'none', fontSize:13, color:NAVY,
              background:'transparent', fontFamily:'inherit',
            }}
          />
          {input.trim() && (
            <button
              onClick={handleSubmit}
              disabled={asking}
              style={{
                background:NAVY, color:'#fff', border:'none', borderRadius:6,
                padding:'4px 10px', fontSize:12, fontWeight:500, cursor:'pointer',
                opacity: asking ? 0.6 : 1,
              }}
            >↑</button>
          )}
        </div>
      </div>
    </div>
  );
};

// ── Table header ──────────────────────────────────────────────────────────────
// Last two columns host the build-execution-plan and include/exclude (eye)
// controls.
const TABLE_GRID = '32px 28px 1.7fr repeat(6, 1fr) 56px 88px 36px 36px';
const TableHeader = () => (
  <div style={{
    display:'grid',
    gridTemplateColumns: TABLE_GRID,
    gap:12, padding:'11px 18px',
    background:'#fff', borderBottom:`1px solid ${LINE}`,
    fontFamily:'JetBrains Mono,monospace',
    fontSize:10, color:MUTED, letterSpacing:'0.06em', textTransform:'uppercase',
  }}>
    <span>#</span>
    <span />
    <span>Idea</span>
    {DIM_KEYS.map(d => <span key={d.key} style={{ textAlign:'center' }}>{d.short}</span>)}
    <span style={{ textAlign:'right' }}>Score</span>
    <span style={{ textAlign:'right' }}>Status</span>
    <span style={{ textAlign:'center' }} title="Build an execution plan from this idea">Plan</span>
    <span style={{ textAlign:'center' }} title="Include / exclude from trade-off">In</span>
  </div>
);

// ── Main TradeoffView ─────────────────────────────────────────────────────────
const TradeoffView = ({
  scorecardSnapshots = [],
  strategyObjective,
  portfolioAnalysis,   // { summary, picks: [{id,name,score,why}] } — from AI
  onAsk,               // fn(text) — sends to main chat
  asking = false,
  threadId,            // required to persist include/exclude toggles
  onBuildExecutionPlan, // fn(idea) — generate execution plan from this idea
  buildingPlanId,      // id of the idea currently generating (for spinner)
}) => {
  const [selected, setSelected] = useState(null);

  // Optimistic local override for the include/exclude flag — keyed by
  // scorecard id. The PATCH to /overrides is fire-and-forget; we update
  // localOverrides immediately so the UI feels snappy. On error, we roll
  // back so the user sees the actual server state.
  const [localOverrides, setLocalOverrides] = useState({});

  // Merge local overrides into the snapshot list before deriving ideas.
  const effectiveSnapshots = useMemo(() => {
    if (Object.keys(localOverrides).length === 0) return scorecardSnapshots;
    return (Array.isArray(scorecardSnapshots) ? scorecardSnapshots : []).map((s) => {
      const id = String(s?.id || s?.analysis_id || s?.analysisId || '');
      if (!id || !(id in localOverrides)) return s;
      return {
        ...s,
        display_overrides: {
          ...(s?.display_overrides && typeof s.display_overrides === 'object' ? s.display_overrides : {}),
          tradeoff_included: localOverrides[id],
        },
      };
    });
  }, [scorecardSnapshots, localOverrides]);

  // Sort: included first (score-desc), then excluded at the bottom
  // (score-desc within themselves). Drives both rank assignment and
  // table render order.
  const ideas = useMemo(() => {
    const all = deriveIdeas(effectiveSnapshots);
    const inc = all.filter((d) => d.included);
    const exc = all.filter((d) => !d.included);
    return [...inc, ...exc];
  }, [effectiveSnapshots]);

  const handleToggleInclude = useCallback((idea, nextIncluded) => {
    const snapId = idea?.snapId;
    if (!snapId) return;
    // Optimistic flip
    setLocalOverrides((prev) => ({ ...prev, [snapId]: nextIncluded }));
    if (!threadId) return;
    Jaspen.patchScorecardOverrides(threadId, snapId, { tradeoff_included: nextIncluded })
      .catch((err) => {
        // Roll back on failure so the UI matches the server.
        // eslint-disable-next-line no-console
        console.error('[TradeoffView] failed to persist tradeoff_included:', err);
        setLocalOverrides((prev) => ({ ...prev, [snapId]: !nextIncluded }));
      });
  }, [threadId]);

  if (ideas.length === 0) {
    return (
      <div style={{ flex:1, display:'flex', alignItems:'center', justifyContent:'center', color:MUTED, fontSize:14, padding:40 }}>
        Score an idea in the conversation — it will appear here automatically.
      </div>
    );
  }

  return (
    <div style={{ flex:1, display:'flex', minHeight:0, background:BG_ALT, fontFamily:"'Inter Tight', system-ui, sans-serif" }}>
      {/* Main content */}
      <div style={{ flex:1, display:'flex', flexDirection:'column', padding:'20px 24px', gap:14, overflow:'auto', minWidth:0 }}>

        {/* Hero + quadrant */}
        <div style={{ display:'grid', gridTemplateColumns:'1fr 390px', gap:14 }}>
          <div style={{ background:'#fff', border:`1px solid ${LINE}`, borderRadius:12, padding:'18px 20px' }}>
            <div style={{ display:'flex', alignItems:'baseline', gap:10, marginBottom:16 }}>
              <div style={{ fontSize:16, fontWeight:600, color:NAVY, letterSpacing:'-0.01em' }}>Portfolio</div>
              {strategyObjective && (
                <span style={{ fontFamily:'JetBrains Mono,monospace', fontSize:11, color:MUTED }}>
                  weighted on {strategyObjective}
                </span>
              )}
            </div>
            <HeroStrip ideas={ideas} objective={null} />
          </div>

          <div style={{ background:'#fff', border:`1px solid ${LINE}`, borderRadius:12, padding:'14px 16px' }}>
            <div style={{ display:'flex', alignItems:'baseline', justifyContent:'space-between', marginBottom:10 }}>
              <span style={{ fontSize:10.5, fontWeight:600, letterSpacing:'0.06em', color:MUTED, textTransform:'uppercase', fontFamily:'JetBrains Mono,monospace' }}>
                Strategic fit vs. Cost efficiency · all {ideas.length}
              </span>
              <span style={{ fontFamily:'JetBrains Mono,monospace', fontSize:10, color:MUTED }}>x: cost · y: fit</span>
            </div>
            <TradeoffQuadrant ideas={ideas} xDim={1} yDim={0} xLabel="Cost efficiency" yLabel="Strategic fit" />
          </div>
        </div>

        {/* Ranked table */}
        <div style={{ background:'#fff', border:`1px solid ${LINE}`, borderRadius:12, overflow:'hidden', flex:1, display:'flex', flexDirection:'column', minHeight:0 }}>
          <TableHeader />
          <div style={{ overflow:'auto', flex:1 }}>
            {ideas.map((d, i) => (
              <PortfolioRow
                key={d._snap?.id || i}
                d={{ ...d, _isBuilding: buildingPlanId != null && (buildingPlanId === d.snapId || buildingPlanId === d.id) }}
                alt={i % 2 === 1}
                onSelect={setSelected}
                selected={selected?._snap?.id === d._snap?.id}
                onToggleInclude={handleToggleInclude}
                onBuildPlan={onBuildExecutionPlan}
                buildingPlan={buildingPlanId != null}
              />
            ))}
          </div>
        </div>
      </div>

      {/* TradeoffSidebar removed: comparison view now uses full width.
          Recommendations and questions go through the main chat input below. */}
    </div>
  );
};

export default TradeoffView;
