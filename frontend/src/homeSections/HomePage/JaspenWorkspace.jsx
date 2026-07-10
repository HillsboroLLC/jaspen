import React, { useEffect, useRef } from 'react';
import { SCENARIOS } from './scenarioData';
import './WorkWithJaspenCanvas.css';

// The live Jaspen workspace window + its self-playing session. Extracted so it
// can render both as a full-width section AND embedded inside the laptop.
// Plays from a `demo` config and replays when it changes.

const ring = (score) => ({ background: `conic-gradient(#a0036c ${score * 3.6}deg, #eef0f3 0)` });

export default function JaspenWorkspace({ demo, onStage, loop = true, onDone }) {
  const d = demo || SCENARIOS[0].demo;
  const rootRef = useRef(null);
  const onStageRef = useRef(onStage);
  onStageRef.current = onStage;
  const onDoneRef = useRef(onDone);
  onDoneRef.current = onDone;

  const activeObjective = (d.objectiveChips.find((c) => c.active) || {}).label || '';
  const activeData = (d.dataChips.find((c) => c.active) || {}).label || '';

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return undefined;
    let cancelled = false;
    let running = false;

    const q = (s) => root.querySelector(`[data-jd="${s}"]`);
    const qa = (s) => Array.from(root.querySelectorAll(`[data-jd="${s}"]`));
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const stage = (s) => { if (!cancelled && onStageRef.current) onStageRef.current(s); };

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
      stage('discovery');
      const scroller = q('scroller');
      await sleep(900); if (cancelled) return;

      q('snow').classList.add('on');
      q('snowck').style.display = 'inline-flex';
      q('snow').style.transform = 'scale(1.05)';
      await sleep(200); q('snow').style.transform = 'scale(1)';
      await sleep(220);
      q('ctxdata').classList.add('show');
      await sleep(450); if (cancelled) return;

      q('obj').classList.add('on');
      await sleep(220);
      q('ctxobj').classList.add('show');
      await sleep(650); if (cancelled) return;

      await type(q('input'), d.prompt, 33); if (cancelled) return;
      await sleep(520);

      q('send').style.transform = 'scale(0.85)';
      await sleep(150); q('send').style.transform = 'scale(1)';
      await sleep(260); if (cancelled) return;

      q('icaret').style.display = 'none';
      q('input').textContent = '';
      q('usermsg').textContent = d.prompt;
      q('welcome').style.opacity = '0';
      q('convo').style.opacity = '1';
      q('disc').classList.remove('on');
      q('scor').classList.add('on');
      stage('scoring');
      await sleep(620); if (cancelled) return;

      q('acaret').style.display = 'inline-block';
      await type(q('agent'), d.agent, 20); if (cancelled) return;
      q('acaret').style.display = 'none';
      await sleep(250);

      q('insights').style.width = '220px';
      qa('insrow').forEach((r, i) => setTimeout(() => { if (!cancelled) r.classList.add('show'); }, 200 + i * 150));

      const cards = qa('sc');
      for (let i = 0; i < cards.length; i += 1) {
        if (cancelled) return;
        cards[i].classList.add('show');
        await sleep(70); // eslint-disable-line no-await-in-loop
        cards[i].querySelectorAll('.wj-crit-bar i').forEach((b) => { b.style.width = b.dataset.w; });
        await scrollDown(scroller); // eslint-disable-line no-await-in-loop
        await sleep(3400); // eslint-disable-line no-await-in-loop
      }
      if (cancelled) return;

      q('scor').classList.remove('on');
      q('trade').classList.add('on');
      stage('trade-off');
      q('tradeoff').classList.add('show');
      await sleep(280);
      await scrollDown(scroller);
      await sleep(5800); if (cancelled) return;

      const rec = root.querySelector('.wj-sc.rec');
      await scrollToEl(scroller, rec);
      await sleep(800); if (cancelled) return;
      q('build').classList.add('pulse');
      await sleep(280); q('build').classList.remove('pulse');
      await sleep(450); if (cancelled) return;

      q('trade').classList.remove('on');
      q('execst').classList.add('on');
      stage('execution');
      q('exec').classList.add('show');
      await sleep(300);
      await scrollToEl(scroller, q('exec'));

      await sleep(8600); if (cancelled) return;
      q('convo').style.opacity = '0';
      await sleep(750);
    };

    const play = async () => {
      if (running) return;
      running = true;
      if (loop) {
        while (!cancelled) await run(); // eslint-disable-line no-await-in-loop
      } else {
        await run();
        if (!cancelled && onDoneRef.current) onDoneRef.current();
      }
      running = false;
    };

    const io = new IntersectionObserver(
      (entries) => entries.forEach((e) => { if (e.isIntersecting) play(); }),
      { threshold: 0.3 },
    );
    io.observe(root);

    return () => { cancelled = true; io.disconnect(); };
  }, [d]);

  return (
    <div className="wj-window" ref={rootRef}>
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
                      {d.scorecards.map((c) => (
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
                            {d.criteria.map((label, i) => (
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
                      <div className="wj-card-eyebrow">{d.tradeoffEyebrow}</div>
                      {d.tradeoffs.map((o) => (
                        <div className={`wj-to-card${o.rec ? ' rec' : ''}`} key={o.label}>
                          <div className="wj-to-name">
                            {o.label}
                            <span className="wj-to-score">{o.score}</span>
                          </div>
                          <div className="wj-to-dims">
                            {o.dims.map((dim) => (
                              <div className="wj-to-dim" key={dim.label}>
                                <span className="wj-to-dim-label">{dim.label}</span>
                                <span className="wj-segs">
                                  {[0, 1, 2].map((i) => (
                                    <span key={i} className={`wj-seg${i < dim.level ? ` on ${dim.kind}` : ''}`} />
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
                        <span className="wj-card-eyebrow">Execution plan · {d.exec.title}</span>
                        <div className="wj-exec-meta">
                          <span className="wj-badge-score">Score {d.exec.score}</span>
                          <span className="wj-badge-tag">{d.exec.tag}</span>
                          <span className="wj-exec-sub">{d.exec.meta}</span>
                        </div>
                      </div>
                      {d.plan.map((ph, pi) => (
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
              {d.insights.map((it) => (
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
                <span className="wj-ctx-tag" data-jd="ctxobj">{activeObjective}</span>
                <span className="wj-ctx-tag" data-jd="ctxdata"><span className="wj-ctx-ck" aria-hidden="true">✓</span>{activeData}</span>
              </div>
              <span className="wj-send" data-jd="send" aria-hidden="true">↑</span>
            </div>
          </div>
          <div className="wj-chiprow">
            <span className="wj-chiplabel">Primary objective?</span>
            {d.objectiveChips.map((c) => (
              <span key={c.label} className="wj-chip" {...(c.active ? { 'data-jd': 'obj' } : {})}>{c.label}</span>
            ))}
          </div>
          <div className="wj-chiprow">
            <span className="wj-chiplabel">Data context</span>
            {d.dataChips.map((c) => (
              c.active ? (
                <span key={c.label} className="wj-chip" data-jd="snow">
                  <span className="wj-chip-ck" data-jd="snowck" aria-hidden="true">✓</span>
                  {c.label}
                </span>
              ) : (
                <span key={c.label} className="wj-chip">{c.label}</span>
              )
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
