import React, { useEffect, useRef } from 'react';
import './WorkWithJaspenCanvas.css';

// Self-playing demo of the real Jaspen workspace for the homepage. It plays a
// realistic session: attach data, set an objective, describe the problem, watch
// four scorecards generate and scroll up the chat, then transition to the
// Trade-off comparison. Starts on scroll-into-view, then loops.

const PROMPT = "We keep absorbing supplier costs we didn't plan for — what should we do?";
const AGENT =
  "I pulled your Snowflake spend data — 38% of unplanned cost traces to 6 suppliers with overlapping scope. I scored four options on cost:";

const CRITERIA = ['Cost savings', 'Continuity', 'Speed to impact', 'Risk profile'];

const SCORECARDS = [
  { name: 'Consolidate suppliers', score: 84, tag: 'Strong', rec: true, crit: [8.8, 7.5, 6.5, 7.8] },
  { name: 'Renegotiate contracts', score: 72, tag: 'Good', rec: false, crit: [7.4, 7.0, 8.2, 8.0] },
  { name: 'Dual-source critical parts', score: 66, tag: 'Fair', rec: false, crit: [6.2, 8.5, 5.8, 8.2] },
  { name: 'Reshore key components', score: 58, tag: 'Watch', rec: false, crit: [5.5, 8.8, 4.5, 6.0] },
];

const INSIGHTS = [
  { label: 'Unplanned spend', value: '$2.4M' },
  { label: 'Traced to', value: '6 suppliers' },
  { label: 'Scope overlap', value: '38%', accent: true },
  { label: 'Continuity risk', value: 'Medium' },
];

const PLAN = [
  {
    phase: 'Discovery & Alignment',
    tasks: [
      { name: 'Map overlapping supplier scope', desc: 'Catalog the 6 suppliers and where their scope overlaps.', owner: 'Procurement Lead', init: 'PL', color: '#a0036c', date: '2026-06-30', pri: 'High' },
      { name: 'Rank suppliers by spend & risk', desc: 'Score each on spend, dependency, and continuity risk.', owner: 'Ops Analyst', init: 'OA', color: '#1b2236', date: '2026-07-07', pri: 'High' },
    ],
  },
  {
    phase: 'Negotiate & Transition',
    tasks: [
      { name: 'Open consolidation negotiations', desc: 'Engage top suppliers on consolidated volume and terms.', owner: 'Category Manager', init: 'CM', color: '#0f6e56', date: '2026-07-21', pri: 'High' },
      { name: 'Build continuity & transition plan', desc: 'Define cutover, dual-run, and risk mitigation steps.', owner: 'Supply Chain PM', init: 'SC', color: '#854f0b', date: '2026-08-11', pri: 'Medium' },
    ],
  },
];

const TRADEOFFS = [
  { label: 'Consolidate suppliers', score: 84, rec: true,
    dims: [{ label: 'Savings', level: 3, kind: 'egg' }, { label: 'Risk', level: 1, kind: 'amber' }, { label: 'Disruption', level: 2, kind: 'slate' }] },
  { label: 'Renegotiate contracts', score: 72, rec: false,
    dims: [{ label: 'Savings', level: 2, kind: 'egg' }, { label: 'Risk', level: 1, kind: 'amber' }, { label: 'Disruption', level: 1, kind: 'slate' }] },
  { label: 'Dual-source critical parts', score: 66, rec: false,
    dims: [{ label: 'Savings', level: 1, kind: 'egg' }, { label: 'Risk', level: 1, kind: 'amber' }, { label: 'Disruption', level: 2, kind: 'slate' }] },
  { label: 'Reshore key components', score: 58, rec: false,
    dims: [{ label: 'Savings', level: 1, kind: 'egg' }, { label: 'Risk', level: 2, kind: 'amber' }, { label: 'Disruption', level: 3, kind: 'slate' }] },
];

const ring = (score) => ({ background: `conic-gradient(#a0036c ${score * 3.6}deg, #eef0f3 0)` });

export default function WorkWithJaspenCanvas() {
  const rootRef = useRef(null);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return undefined;
    let cancelled = false;
    let running = false;

    const q = (s) => root.querySelector(`[data-jd="${s}"]`);
    const qa = (s) => Array.from(root.querySelectorAll(`[data-jd="${s}"]`));
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

    const type = async (el, txt, sp) => {
      el.textContent = '';
      for (let i = 0; i < txt.length; i += 1) {
        if (cancelled) return;
        el.textContent += txt[i];
        await sleep(sp); // eslint-disable-line no-await-in-loop
      }
    };

    const animateScroll = (el, target) => new Promise((res) => {
      const clamped = Math.max(0, Math.min(target, el.scrollHeight - el.clientHeight));
      const start = el.scrollTop;
      const t0 = performance.now();
      const tick = (now) => {
        if (cancelled) { res(); return; }
        const p = Math.min((now - t0) / 650, 1);
        const e = p < 0.5 ? 2 * p * p : 1 - ((-2 * p + 2) ** 2) / 2;
        el.scrollTop = start + (clamped - start) * e;
        if (p < 1) requestAnimationFrame(tick); else res();
      };
      requestAnimationFrame(tick);
    });
    const scrollDown = (el) => animateScroll(el, el.scrollHeight - el.clientHeight);
    const scrollToEl = (el, target) => {
      const cRect = el.getBoundingClientRect();
      const eRect = target.getBoundingClientRect();
      return animateScroll(el, el.scrollTop + (eRect.top - cRect.top) - 14);
    };

    const reset = () => {
      const scroller = q('scroller');
      scroller.scrollTop = 0;
      q('input').textContent = '';
      q('icaret').style.display = 'inline-block';
      q('agent').textContent = '';
      q('acaret').style.display = 'none';
      q('welcome').style.opacity = '1';
      q('convo').style.opacity = '0';
      q('usermsg').textContent = '';
      q('snow').classList.remove('on');
      q('snowck').style.display = 'none';
      q('obj').classList.remove('on');
      q('ctxobj').classList.remove('show');
      q('ctxdata').classList.remove('show');
      q('tradeoff').classList.remove('show');
      q('exec').classList.remove('show');
      q('build').classList.remove('pulse');
      q('insights').style.width = '0px';
      q('disc').classList.add('on');
      q('scor').classList.remove('on');
      q('trade').classList.remove('on');
      q('execst').classList.remove('on');
      qa('sc').forEach((c) => c.classList.remove('show'));
      qa('insrow').forEach((r) => r.classList.remove('show'));
      root.querySelectorAll('.wj-crit-bar i').forEach((b) => { b.style.width = '0px'; });
    };

    const run = async () => {
      reset();
      const scroller = q('scroller');
      await sleep(900); if (cancelled) return;

      q('snow').classList.add('on');
      q('snowck').style.display = 'inline-flex';
      q('snow').style.transform = 'scale(1.05)';
      await sleep(200); q('snow').style.transform = 'scale(1)';
      await sleep(220);
      q('ctxdata').classList.add('show'); // merges up next to the model
      await sleep(450); if (cancelled) return;

      q('obj').classList.add('on');
      await sleep(220);
      q('ctxobj').classList.add('show');
      await sleep(650); if (cancelled) return;

      await type(q('input'), PROMPT, 30); if (cancelled) return;
      await sleep(420);

      q('send').style.transform = 'scale(0.85)';
      await sleep(150); q('send').style.transform = 'scale(1)';
      await sleep(260); if (cancelled) return;

      q('icaret').style.display = 'none';
      q('input').textContent = '';
      q('usermsg').textContent = PROMPT;
      q('welcome').style.opacity = '0';
      q('convo').style.opacity = '1';
      q('disc').classList.remove('on');
      q('scor').classList.add('on');
      await sleep(520); if (cancelled) return;

      q('acaret').style.display = 'inline-block';
      await type(q('agent'), AGENT, 15); if (cancelled) return;
      q('acaret').style.display = 'none';
      await sleep(250);

      // Insights drawer fills in alongside the scoring.
      q('insights').style.width = '220px';
      qa('insrow').forEach((r, i) => setTimeout(() => { if (!cancelled) r.classList.add('show'); }, 200 + i * 150));

      // Generate the four scorecards one at a time. Each one lands, scrolls
      // into view, and SITS long enough to actually read before the next.
      const cards = qa('sc');
      for (let i = 0; i < cards.length; i += 1) {
        if (cancelled) return;
        cards[i].classList.add('show');
        await sleep(70); // eslint-disable-line no-await-in-loop
        cards[i].querySelectorAll('.wj-crit-bar i').forEach((b) => { b.style.width = b.dataset.w; });
        await scrollDown(scroller); // eslint-disable-line no-await-in-loop
        // dwell so each scorecard is readable before the next
        await sleep(2700); // eslint-disable-line no-await-in-loop
      }
      if (cancelled) return;

      // Advance to Trade-off and stack the options against each other.
      q('scor').classList.remove('on');
      q('trade').classList.add('on');
      q('tradeoff').classList.add('show');
      await sleep(240);
      await scrollDown(scroller);
      await sleep(4800); if (cancelled) return;

      // Scroll back up to the recommended scorecard and build its plan.
      const rec = root.querySelector('.wj-sc.rec');
      await scrollToEl(scroller, rec);
      await sleep(800); if (cancelled) return;
      q('build').classList.add('pulse');
      await sleep(280); q('build').classList.remove('pulse');
      await sleep(450); if (cancelled) return;

      // Advance to Execution and generate the plan.
      q('trade').classList.remove('on');
      q('execst').classList.add('on');
      q('exec').classList.add('show');
      await sleep(260);
      await scrollToEl(scroller, q('exec'));

      await sleep(7200); if (cancelled) return;
      q('convo').style.opacity = '0';
      await sleep(750);
    };

    const loop = async () => {
      if (running) return;
      running = true;
      while (!cancelled) await run(); // eslint-disable-line no-await-in-loop
      running = false;
    };

    const io = new IntersectionObserver(
      (entries) => entries.forEach((e) => { if (e.isIntersecting) loop(); }),
      { threshold: 0.3 },
    );
    io.observe(root);

    return () => { cancelled = true; io.disconnect(); };
  }, []);

  return (
    <section className="wj-section" ref={rootRef}>
      <div className="wj-head">
        <span className="wj-eyebrow">How it works</span>
        <h3>Work with Jaspen</h3>
        <p>Bring your problem. Leave with clarity.</p>
      </div>

      <div className="wj-window">
        <div className="wj-rail">
          <span className="wj-rail-logo">J</span>
          <span className="wj-rail-ic" aria-hidden="true">≡</span>
          <span className="wj-rail-ic" aria-hidden="true">◷</span>
        </div>

        <div className="wj-main">
          <div className="wj-topbar">
            <div className="wj-stages">
              <span className="wj-brand">Jaspen</span>
              <span className="wj-stage" data-jd="disc">DISCOVERY</span>
              <span className="wj-sep">›</span>
              <span className="wj-stage" data-jd="scor">SCORING</span>
              <span className="wj-sep">›</span>
              <span className="wj-stage" data-jd="trade">TRADE-OFF</span>
              <span className="wj-sep">›</span>
              <span className="wj-stage" data-jd="execst">EXECUTION</span>
            </div>
            <div className="wj-topicons">
              <span className="wj-spark" aria-hidden="true">✦</span>
              <span className="wj-bell" aria-hidden="true">◔</span>
            </div>
          </div>

          <div className="wj-body">
            <div className="wj-convo-wrap">
              <div className="wj-welcome" data-jd="welcome">
                <div className="wj-welcome-title">Good afternoon. Ready to build momentum?</div>
                <div className="wj-welcome-sub">
                  Describe a problem or goal, attach what you have, and Jaspen turns it into a clear, scored path forward.
                </div>
              </div>

              <div className="wj-scroller" data-jd="scroller">
                <div className="wj-convo" data-jd="convo">
                  <div className="wj-usermsg" data-jd="usermsg" />
                  <div className="wj-agentrow">
                    <span className="wj-agent-avatar" aria-hidden="true">✦</span>
                    <div className="wj-agent-col">
                      <div className="wj-agent-text">
                        <span data-jd="agent" />
                        <span className="wj-caret" data-jd="acaret" />
                      </div>

                      <div className="wj-cards">
                        {SCORECARDS.map((c) => (
                          <div className={`wj-sc${c.rec ? ' rec' : ''}`} data-jd="sc" key={c.name}>
                            <div className="wj-sc-top">
                              <div className="wj-ring" style={ring(c.score)}>
                                <span>{c.score}</span>
                              </div>
                              <div className="wj-sc-meta">
                                <span className="wj-sc-tag">{c.tag}</span>
                                <span className="wj-sc-name">
                                  {c.name}
                                  {c.rec && <span className="wj-rec-tag">Recommended</span>}
                                </span>
                              </div>
                            </div>
                            <div className="wj-sc-crit">
                              {CRITERIA.map((label, i) => (
                                <div className="wj-crit" key={label}>
                                  <span className="wj-crit-label">{label}</span>
                                  <span className="wj-crit-bar"><i data-w={`${c.crit[i] * 10}%`} /></span>
                                  <span className="wj-crit-v">{c.crit[i].toFixed(1)}<em>/10</em></span>
                                </div>
                              ))}
                            </div>
                            {c.rec && (
                              <div className="wj-sc-foot">
                                <span className="wj-build" data-jd="build">Build Execution Plan →</span>
                              </div>
                            )}
                          </div>
                        ))}
                      </div>

                      <div className="wj-tradeoff" data-jd="tradeoff">
                        <div className="wj-card-eyebrow">Trade-offs · savings vs. risk vs. disruption</div>
                        {TRADEOFFS.map((o) => (
                          <div className={`wj-to-card${o.rec ? ' rec' : ''}`} key={o.label}>
                            <div className="wj-to-name">
                              {o.label}
                              <span className="wj-to-score">{o.score}</span>
                            </div>
                            <div className="wj-to-dims">
                              {o.dims.map((d) => (
                                <div className="wj-to-dim" key={d.label}>
                                  <span className="wj-to-dim-label">{d.label}</span>
                                  <span className="wj-segs">
                                    {[0, 1, 2].map((i) => (
                                      <span key={i} className={`wj-seg${i < d.level ? ` on ${d.kind}` : ''}`} />
                                    ))}
                                  </span>
                                </div>
                              ))}
                            </div>
                          </div>
                        ))}
                      </div>

                      <div className="wj-exec" data-jd="exec">
                        <div className="wj-exec-head">
                          <span className="wj-card-eyebrow">Execution plan · Consolidate suppliers</span>
                          <div className="wj-exec-meta">
                            <span className="wj-badge-score">Score 84</span>
                            <span className="wj-badge-tag">Excellent</span>
                            <span className="wj-exec-sub">2 phases · 4 tasks · starts Jun 30</span>
                          </div>
                        </div>
                        {PLAN.map((ph, pi) => (
                          <div className="wj-phase" key={ph.phase}>
                            <div className="wj-phase-head">
                              <span className="wj-phase-no">Phase {pi + 1}</span>
                              <span className="wj-phase-name">{ph.phase}</span>
                              <span className="wj-phase-count">0 / {ph.tasks.length}</span>
                            </div>
                            {ph.tasks.map((t) => (
                              <div className="wj-task" key={t.name}>
                                <span className="wj-task-avatar" style={{ background: t.color }}>{t.init}</span>
                                <div className="wj-task-main">
                                  <div className="wj-task-name">{t.name}</div>
                                  <div className="wj-task-desc">{t.desc}</div>
                                </div>
                                <span className={`wj-pri ${t.pri === 'High' ? 'hi' : 'med'}`}>{t.pri}</span>
                                <span className="wj-task-date">{t.date}</span>
                                <span className="wj-status">To Do</span>
                              </div>
                            ))}
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div className="wj-insights" data-jd="insights">
              <div className="wj-insights-inner">
                <div className="wj-insights-title">Jaspen insights</div>
                {INSIGHTS.map((it) => (
                  <div className="wj-insrow" data-jd="insrow" key={it.label}>
                    <div className="wj-ins-label">{it.label}</div>
                    <div className={`wj-ins-value${it.accent ? ' accent' : ''}`}>{it.value}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="wj-composer">
            <div className="wj-input-box">
              <div className="wj-input-text">
                <span data-jd="input" />
                <span className="wj-caret" data-jd="icaret" />
              </div>
              <div className="wj-input-foot">
                <div className="wj-input-ctx">
                  <span className="wj-model">Pluto-1.0</span>
                  <span className="wj-ctx-tag" data-jd="ctxobj">Cost Optimization</span>
                  <span className="wj-ctx-tag" data-jd="ctxdata"><span className="wj-ctx-ck" aria-hidden="true">✓</span>Snowflake</span>
                </div>
                <span className="wj-send" data-jd="send" aria-hidden="true">↑</span>
              </div>
            </div>
            <div className="wj-chiprow">
              <span className="wj-chiplabel">Primary objective?</span>
              <span className="wj-chip">Balanced</span>
              <span className="wj-chip" data-jd="obj">Cost Optimization</span>
              <span className="wj-chip">Speed to Market</span>
              <span className="wj-chip">Growth</span>
            </div>
            <div className="wj-chiprow">
              <span className="wj-chiplabel">Data context</span>
              <span className="wj-chip">Jira</span>
              <span className="wj-chip">Salesforce</span>
              <span className="wj-chip" data-jd="snow">
                <span className="wj-chip-ck" data-jd="snowck" aria-hidden="true">✓</span>
                Snowflake
              </span>
            </div>
          </div>
        </div>
      </div>

      <p className="wj-footnote">
        Contextual awareness throughout — Jaspen remembers every decision, constraint, and tradeoff, so you never repeat yourself.
      </p>
    </section>
  );
}
