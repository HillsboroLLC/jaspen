import React, { useEffect, useRef, useState, useCallback } from 'react';
import './WorkWithJaspenCanvas.css';

// ── Panel content ─────────────────────────────────────────────────────────────

function IdeasPanel() {
  const [score, setScore] = useState(0);
  const [visible, setVisible] = useState([]);
  const raf = useRef(null);
  useEffect(() => {
    const target = 82, duration = 1100, start = performance.now();
    const tick = (now) => {
      const t = Math.min((now - start) / duration, 1);
      setScore(Math.round((1 - Math.pow(1 - t, 3)) * target));
      if (t < 1) raf.current = requestAnimationFrame(tick);
      else [0,1,2,3].forEach(i => setTimeout(() => setVisible(p => [...p, i]), i * 160));
    };
    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
  }, []);
  const insights = [
    { label: 'Market Demand',       badge: 'High',     type: 'high' },
    { label: 'Competition',         badge: 'Moderate', type: 'med'  },
    { label: 'Risk Level',          badge: 'Medium',   type: 'med'  },
    { label: 'Execution Readiness', badge: 'Strong',   type: 'high' },
  ];
  return (
    <div className="jwj-panel">
      <div className="jwj-panel-label">Idea Score</div>
      <div className="jwj-panel-score">{score}<span>/100</span></div>
      <p className="jwj-panel-idea-text">AI-powered meal prep service analyzing biometrics and local grocery inventory to generate weekly recipes.</p>
      <div className="jwj-panel-insights">
        {insights.map((ins, i) => (
          <div key={i} className={`jwj-insight${visible.includes(i) ? ' visible' : ''}`}>
            <span>{ins.label}</span>
            <span className={`jwj-badge jwj-badge--${ins.type}`}>{ins.badge}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function TradeoffsPanel() {
  const [scoreA, setScoreA] = useState(0);
  const [scoreB, setScoreB] = useState(0);
  const [rowsA, setRowsA] = useState([]);
  const [rowsB, setRowsB] = useState([]);
  const [showB, setShowB] = useState(false);
  const [winner, setWinner] = useState(false);
  const raf = useRef(null); const timers = useRef([]);
  const later = (fn, ms) => { const t = setTimeout(fn, ms); timers.current.push(t); };
  const countUp = (target, setter, dur = 900) => new Promise(res => {
    const start = performance.now();
    const tick = now => {
      const t = Math.min((now - start) / dur, 1);
      setter(Math.round((1 - Math.pow(1 - t, 3)) * target));
      if (t < 1) raf.current = requestAnimationFrame(tick); else res();
    };
    raf.current = requestAnimationFrame(tick);
  });
  useEffect(() => {
    later(async () => {
      setRowsA([0]); later(() => setRowsA([0,1]), 300);
      later(async () => {
        await countUp(76, setScoreA);
        [0,1,2].forEach(i => later(() => setRowsA(p => [...p, i+2]), i*140));
        later(() => {
          setShowB(true);
          later(() => setRowsB([0]), 200);
          later(() => setRowsB([0,1]), 500);
          later(async () => {
            await countUp(71, setScoreB);
            [0,1,2].forEach(i => later(() => setRowsB(p => [...p, i+2]), i*140));
            later(() => setWinner(true), 700);
          }, 600);
        }, 900);
      }, 700);
    }, 200);
    return () => { timers.current.forEach(clearTimeout); cancelAnimationFrame(raf.current); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const optA = [
    { l:'Budget',  v:'$800K → $1.2M', d:'+$400K', pos:true },
    { l:'Team',    v:'6 → 10 people',  d:'+4',     pos:true },
    { l:'ROI',     v:'64%',            d:'+19pp',  pos:true },
    { l:'3-Yr NPV',v:'$2.1M',          d:'+$900K', pos:true },
    { l:'Payback', v:'13 mo',           d:'−5 mo',  pos:true },
  ];
  const optB = [
    { l:'Timeline',v:'12 → 18 mo',     d:'+6 mo',  pos:false },
    { l:'Market',  v:'City → Regional',d:'Expanded',pos:true },
    { l:'ROI',     v:'53%',            d:'+8pp',   pos:true },
    { l:'3-Yr NPV',v:'$1.6M',          d:'+$400K', pos:true },
    { l:'Payback', v:'16 mo',           d:'−2 mo',  pos:true },
  ];
  return (
    <div className="jwj-panel jwj-panel--tradeoffs">
      <div className="jwj-panel-label">Trade-Off Engine</div>
      <div className="jwj-panel-project">AI Meal Prep Platform <span className="jwj-baseline">Baseline 68/100</span></div>
      <div className="jwj-to-grid">
        <div className={`jwj-option${winner ? ' jwj-option--winner' : ''}`}>
          <div className="jwj-option-head">
            <span>Option A</span>
            {scoreA > 0 && <><span className="jwj-opt-score">{scoreA}<small>/100</small></span><span className="jwj-delta pos">+{scoreA-68}</span></>}
          </div>
          {optA.map((r,i) => rowsA.includes(i) && (
            <div key={i} className="jwj-opt-row">
              <span>{r.l}</span><span>{r.v}</span><span className={r.pos?'pos':'neg'}>{r.d}</span>
            </div>
          ))}
          {winner && <span className="jwj-winner-badge">Best outcome</span>}
        </div>
        {showB && (
          <div className="jwj-option">
            <div className="jwj-option-head">
              <span>Option B</span>
              {scoreB > 0 && <><span className="jwj-opt-score">{scoreB}<small>/100</small></span><span className="jwj-delta pos">+{scoreB-68}</span></>}
            </div>
            {optB.map((r,i) => rowsB.includes(i) && (
              <div key={i} className="jwj-opt-row">
                <span>{r.l}</span><span>{r.v}</span><span className={r.pos?'pos':'neg'}>{r.d}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function PlanPanel() {
  const [visible, setVisible] = useState([]);
  useEffect(() => {
    [0,1,2,3].forEach(i => setTimeout(() => setVisible(p => [...p, i]), 200 + i * 260));
  }, []);
  const steps = [
    { n:'01', t:'Data Integration & MVP',       d:'Connect core health APIs with a single grocery chain. Validate the recommendation loop.' },
    { n:'02', t:'Recipe Generation Engine',     d:'Train on nutritional databases to generate recipes from constrained inventory.' },
    { n:'03', t:'Logistics & Fulfillment',      d:'Partner with last-mile delivery (Instacart, DoorDash) rather than building in-house.' },
    { n:'04', t:'Beta Launch & Iteration',      d:'Launch closed beta in a single dense urban market. Refine and iterate.' },
  ];
  return (
    <div className="jwj-panel">
      <div className="jwj-panel-label">Execution Plan</div>
      <div className="jwj-panel-project">AI Meal Prep Platform — 4 Phases</div>
      <div className="jwj-steps">
        {steps.map((s,i) => (
          <div key={i} className={`jwj-step${visible.includes(i) ? ' visible' : ''}`}>
            <span className="jwj-step-num">{s.n}</span>
            <div><strong>{s.t}</strong><p>{s.d}</p></div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Node network config ───────────────────────────────────────────────────────

const ACTION_NODES = [
  { id: 'ideas',     label: 'Explore Ideas',      rx: 0.22, ry: 0.18, panel: 0 },
  { id: 'tradeoffs', label: 'Evaluate Tradeoffs',  rx: 0.78, ry: 0.28, panel: 1 },
  { id: 'plan',      label: 'Build Plans',          rx: 0.50, ry: 0.82, panel: 2 },
];

const PROBLEM_NODES = [
  { id: 'p1', label: 'hidden costs',      rx: 0.08, ry: 0.45, link: 'ideas'     },
  { id: 'p2', label: 'slow decisions',    rx: 0.34, ry: 0.10, link: 'ideas'     },
  { id: 'p3', label: 'same conversation', rx: 0.92, ry: 0.50, link: 'tradeoffs' },
  { id: 'p4', label: 'no shared truth',   rx: 0.70, ry: 0.68, link: 'tradeoffs' },
  { id: 'p5', label: 'lost context',      rx: 0.22, ry: 0.78, link: 'plan'      },
  { id: 'p6', label: 'wrong priorities',  rx: 0.68, ry: 0.92, link: 'plan'      },
];

const CONNECTIONS = [
  ['jaspen','ideas'],['jaspen','tradeoffs'],['jaspen','plan'],
  ['p1','ideas'],['p2','ideas'],
  ['p3','tradeoffs'],['p4','tradeoffs'],
  ['p5','plan'],['p6','plan'],
];

const ALL_NODES = [
  { id:'jaspen', label:'Jaspen', isCenter:true, rx:0.50, ry:0.50, phase:0 },
  ...ACTION_NODES.map(n => ({ ...n, isAction:true, phase: Math.random()*Math.PI*2 })),
  ...PROBLEM_NODES.map(n => ({ ...n, isProblem:true, phase: Math.random()*Math.PI*2 })),
];

// ── Main component ────────────────────────────────────────────────────────────

const PANELS = [IdeasPanel, TradeoffsPanel, PlanPanel];

export default function WorkWithJaspenCanvas() {
  const canvasRef   = useRef(null);
  const mouseRef    = useRef({ x:-9999, y:-9999 });
  const rafRef      = useRef(null);
  const t0Ref       = useRef(null);
  const hoverTimer  = useRef(null);
  const [activePanel, setActivePanel] = useState(0);
  const [panelKey,    setPanelKey]    = useState(0);
  const activePanelRef = useRef(0);

  const switchPanel = useCallback((idx) => {
    if (idx === activePanelRef.current) return;
    activePanelRef.current = idx;
    setActivePanel(idx);
    setPanelKey(k => k + 1);
  }, []);

  // Auto-cycle
  useEffect(() => {
    const id = setInterval(() => {
      const next = (activePanelRef.current + 1) % 3;
      switchPanel(next);
    }, 5000);
    return () => clearInterval(id);
  }, [switchPanel]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    let W = 0, H = 0;

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      W = rect.width; H = rect.height;
      canvas.width  = W * dpr;
      canvas.height = H * dpr;
      ctx.scale(dpr, dpr);
    };

    const getPos = (n, t) => ({
      x: n.rx * W + Math.sin(t * 0.35 + (n.phase||0)) * (n.isCenter ? 0 : 12),
      y: n.ry * H + Math.cos(t * 0.35 + (n.phase||0) * 1.3) * (n.isCenter ? 0 : 8),
    });

    const draw = (ts) => {
      if (!t0Ref.current) t0Ref.current = ts;
      const t   = (ts - t0Ref.current) / 1000;
      const ap  = activePanelRef.current;
      ctx.clearRect(0, 0, W, H);

      const posMap = {};
      ALL_NODES.forEach(n => { posMap[n.id] = getPos(n, t); });

      // ── connections
      CONNECTIONS.forEach(([a, b]) => {
        const pa = posMap[a], pb = posMap[b];
        const bNode = ALL_NODES.find(n => n.id === b) || ALL_NODES.find(n => n.id === a);
        const isActive = bNode?.panel === ap || (bNode?.link && ACTION_NODES.find(an => an.id === bNode.link)?.panel === ap);
        ctx.save();
        ctx.beginPath();
        ctx.moveTo(pa.x, pa.y);
        ctx.lineTo(pb.x, pb.y);
        if (isActive) {
          const offset = -(t * 22) % 18;
          ctx.setLineDash([5, 8]);
          ctx.lineDashOffset = offset;
          ctx.strokeStyle = 'rgba(160,3,108,0.45)';
          ctx.lineWidth = 1.3;
        } else {
          ctx.setLineDash([3, 8]);
          ctx.strokeStyle = 'rgba(0,0,0,0.07)';
          ctx.lineWidth = 0.8;
        }
        ctx.stroke();
        ctx.restore();
      });

      // ── nodes
      ALL_NODES.forEach(n => {
        const { x, y } = posMap[n.id];
        const isActive = n.panel === ap || (n.link && ACTION_NODES.find(an => an.id === n.link)?.panel === ap);
        const r = n.isCenter ? 30 + Math.sin(t * 1.4) * 2
                : n.isAction ? (isActive ? 28 : 22)
                : (isActive ? 16 : 13);

        // Pulse ring on active action node
        if (n.isAction && isActive) {
          const pulse = (Math.sin(t * 2.2) + 1) / 2;
          ctx.beginPath();
          ctx.arc(x, y, r + 10 + pulse * 6, 0, Math.PI*2);
          ctx.strokeStyle = `rgba(160,3,108,${0.1 + pulse * 0.1})`;
          ctx.lineWidth = 1;
          ctx.setLineDash([]);
          ctx.stroke();
        }

        // Center ring
        if (n.isCenter) {
          ctx.beginPath();
          ctx.arc(x, y, r + 12, 0, Math.PI*2);
          ctx.strokeStyle = `rgba(160,3,108,${0.1 + Math.sin(t*1.4)*0.05})`;
          ctx.lineWidth = 1;
          ctx.setLineDash([]);
          ctx.stroke();
        }

        // Fill
        ctx.beginPath();
        ctx.arc(x, y, r, 0, Math.PI*2);
        ctx.setLineDash([]);
        if (n.isCenter) {
          ctx.fillStyle = 'rgba(160,3,108,0.08)';
          ctx.strokeStyle = 'rgba(160,3,108,0.4)';
          ctx.lineWidth = 1.5;
        } else if (isActive) {
          ctx.fillStyle = 'rgba(160,3,108,0.1)';
          ctx.strokeStyle = 'rgba(160,3,108,0.55)';
          ctx.lineWidth = 1.5;
        } else {
          ctx.fillStyle = 'rgba(255,255,255,0.85)';
          ctx.strokeStyle = 'rgba(0,0,0,0.1)';
          ctx.lineWidth = 1;
        }
        ctx.fill();
        ctx.stroke();

        // Label
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        if (n.isCenter) {
          ctx.font = '600 12px Inter,-apple-system,sans-serif';
          ctx.fillStyle = 'rgba(140,2,95,0.85)';
          ctx.fillText('Jaspen', x, y);
        } else if (n.isAction) {
          ctx.font = `${isActive ? 500 : 400} 10px Inter,-apple-system,sans-serif`;
          ctx.fillStyle = isActive ? 'rgba(140,2,95,0.9)' : 'rgba(15,15,30,0.45)';
          const words = n.label.split(' ');
          if (words.length === 2) {
            ctx.fillText(words[0], x, y - 6);
            ctx.fillText(words[1], x, y + 7);
          } else {
            ctx.fillText(words.slice(0,2).join(' '), x, y - 6);
            ctx.fillText(words[2] || '', x, y + 7);
          }
        } else {
          ctx.font = '10px Inter,-apple-system,sans-serif';
          ctx.fillStyle = isActive ? 'rgba(140,2,95,0.8)' : 'rgba(15,15,30,0.3)';
          const w = n.label.split(' ');
          if (w.length > 1 && ctx.measureText(n.label).width > r * 2.1) {
            ctx.fillText(w[0], x, y - 5);
            ctx.fillText(w.slice(1).join(' '), x, y + 6);
          } else {
            ctx.fillText(n.label, x, y);
          }
        }
      });

      rafRef.current = requestAnimationFrame(draw);
    };

    const onMouseMove = (e) => {
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      mouseRef.current = { x: mx, y: my };

      // Check if near an action node
      const t = t0Ref.current ? (performance.now() - t0Ref.current) / 1000 : 0;
      for (const n of ACTION_NODES) {
        const pos = {
          x: n.rx * W + Math.sin(t * 0.35 + (n.phase||0)) * 12,
          y: n.ry * H + Math.cos(t * 0.35 + (n.phase||0) * 1.3) * 8,
        };
        if (Math.hypot(pos.x - mx, pos.y - my) < 36) {
          clearTimeout(hoverTimer.current);
          hoverTimer.current = setTimeout(() => switchPanel(n.panel), 400);
          return;
        }
      }
      clearTimeout(hoverTimer.current);
    };

    const onMouseLeave = () => {
      mouseRef.current = { x:-9999, y:-9999 };
      clearTimeout(hoverTimer.current);
    };

    resize();
    window.addEventListener('resize', resize);
    canvas.addEventListener('mousemove', onMouseMove);
    canvas.addEventListener('mouseleave', onMouseLeave);
    rafRef.current = requestAnimationFrame(draw);

    return () => {
      cancelAnimationFrame(rafRef.current);
      clearTimeout(hoverTimer.current);
      window.removeEventListener('resize', resize);
    };
  }, [switchPanel]);

  const PanelComponent = PANELS[activePanel];

  return (
    <section className="jwj-section">
      <div className="jwj-inner">
        {/* Left: node network */}
        <div className="jwj-left">
          <div className="jwj-text-block">
            <span className="jwj-eyebrow">How it works</span>
            <h2 className="jwj-heading">Work with Jaspen</h2>
            <p className="jwj-sub">Bring your problem. Leave with clarity.</p>
          </div>
          <canvas ref={canvasRef} className="jwj-canvas" aria-hidden="true" />
        </div>

        {/* Right: demo panel */}
        <div className="jwj-right">
          <div className="jwj-panel-tabs">
            {['Explore Ideas','Evaluate Tradeoffs','Build Plans'].map((label, i) => (
              <button
                key={i}
                className={`jwj-tab${activePanel === i ? ' active' : ''}`}
                onClick={() => switchPanel(i)}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="jwj-panel-wrap">
            <PanelComponent key={panelKey} />
          </div>
        </div>
      </div>
    </section>
  );
}
