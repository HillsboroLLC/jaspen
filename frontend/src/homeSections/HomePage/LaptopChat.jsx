import React, { useEffect, useRef, useState } from 'react';
import JaspenWorkspace from './JaspenWorkspace';
import './TeamsConversation.css';

const FILLER = { name: 'Alex Rivera', initials: 'A', color: '#7a7f8a', preview: 'thanks — sending it over now' };

/* One laptop, one scenario. Two formats:
   - 'meeting': a group thread that stalls, then a cursor hops into a 1:1 where
     the private line lands.
   - 'peer': just a single 1:1 thread between two peers that plays straight
     through to its own punchline.
   Auto-plays only when it's the active card; reports up via onResolve. */
export default function LaptopChat({ scenario: sc, isActive, onResolve, onScreenChange }) {
  const isPeer = sc.format === 'peer';
  const primaryView = isPeer ? sc.dmWith : 'group';
  const primaryMsgs = isPeer ? sc.thread : sc.group;

  const [view, setView] = useState(primaryView);
  const [primaryN, setPrimaryN] = useState(0);
  const [dmPunch, setDmPunch] = useState(false);
  const [typing, setTyping] = useState(false);
  const [started, setStarted] = useState(false);
  const [manual, setManual] = useState(false);
  const [cursor, setCursor] = useState(null);
  const [screen, setScreen] = useState('chat'); // 'chat' (Teams) | 'jaspen' (workspace in-laptop)
  const [jaspenStage, setJaspenStage] = useState('discovery');

  const appRef = useRef(null);
  const dmItemRef = useRef(null);
  const listRef = useRef(null);
  const autoDm = useRef(false);
  const browserRef = useRef(null);
  const autoBrowser = useRef(false);

  const you = sc.you;
  const dmWith = sc.dmWith;
  const primaryDone = primaryN >= primaryMsgs.length;

  useEffect(() => { if (isActive) setStarted(true); }, [isActive]);
  useEffect(() => { if (onScreenChange) onScreenChange(screen); }, [screen]); // eslint-disable-line react-hooks/exhaustive-deps

  // reveal the primary conversation one message at a time
  useEffect(() => {
    if (!started || primaryN >= primaryMsgs.length) return undefined;
    if (view === primaryView) setTyping(true);
    const txt = primaryMsgs[primaryN].text;
    const t = setTimeout(() => { setTyping(false); setPrimaryN((n) => n + 1); }, Math.min(2400, 950 + txt.length * 20));
    return () => clearTimeout(t);
  }, [primaryN, started, primaryMsgs, view, primaryView]);

  // (meeting only) once the meeting stalls, hop into the private 1:1
  useEffect(() => {
    if (isPeer || !started || !primaryDone || manual || view !== 'group' || autoDm.current) return undefined;
    autoDm.current = true;
    const timers = [];
    timers.push(setTimeout(() => {
      const app = appRef.current, item = dmItemRef.current;
      if (!app || !item) { setView(dmWith); return; }
      const a = app.getBoundingClientRect(), b = item.getBoundingClientRect();
      const x = b.left - a.left + b.width * 0.55;
      const y = b.top - a.top + b.height * 0.5;
      setCursor({ x: a.width * 0.5, y: a.height * 0.86, click: false });
      timers.push(setTimeout(() => setCursor({ x, y, click: false }), 60));
      timers.push(setTimeout(() => setCursor({ x, y, click: true }), 1050));
      timers.push(setTimeout(() => setView(dmWith), 1500));
      timers.push(setTimeout(() => setCursor(null), 1820));
    }, 1150));
    return () => timers.forEach(clearTimeout);
  }, [primaryDone, started, manual, view, dmWith, isPeer]);

  // (meeting only) reveal the private punchline
  useEffect(() => {
    if (isPeer || !started || view !== dmWith || !primaryDone || dmPunch) return undefined;
    setTyping(true);
    const t = setTimeout(() => { setTyping(false); setDmPunch(true); }, 2000);
    return () => clearTimeout(t);
  }, [view, started, primaryDone, dmPunch, dmWith, isPeer]);

  // Once the conversation lands, the frustrated user opens the browser →
  // jaspen.ai → the Jaspen session, all inside the laptop.
  useEffect(() => {
    const finished = isPeer ? primaryDone : (view === dmWith && dmPunch);
    if (!started || !finished || manual || screen !== 'chat' || autoBrowser.current) return undefined;
    autoBrowser.current = true;
    const timers = [];
    timers.push(setTimeout(() => {
      const app = appRef.current, item = browserRef.current;
      if (!app || !item) { setScreen('jaspen'); return; }
      const a = app.getBoundingClientRect(), b = item.getBoundingClientRect();
      const x = b.left - a.left + b.width * 0.5;
      const y = b.top - a.top + b.height * 0.5;
      setCursor({ x: a.width * 0.5, y: a.height * 0.5, click: false });
      timers.push(setTimeout(() => setCursor({ x, y, click: false }), 60));
      timers.push(setTimeout(() => setCursor({ x, y, click: true }), 1100));
      timers.push(setTimeout(() => setScreen('jaspen'), 1560));
      timers.push(setTimeout(() => setCursor(null), 1880));
    }, 2200));
    return () => timers.forEach(clearTimeout);
  }, [started, manual, screen, view, dmPunch, primaryDone, isPeer, dmWith]);

  useEffect(() => {
    if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [primaryN, dmPunch, typing, view]);

  const openChat = (v) => { setManual(true); setCursor(null); setView(v); };

  // After Jaspen finishes, restart the whole story so it loops on its own.
  const resetStory = () => {
    setScreen('chat');
    setView(primaryView);
    setPrimaryN(0);
    setDmPunch(false);
    setJaspenStage('discovery');
    autoDm.current = false;
    autoBrowser.current = false;
  };

  const done = isPeer ? primaryDone : (view === dmWith && dmPunch);

  // Left-side narration so the viewer can keep up with each scene.
  const narration = (() => {
    if (screen === 'jaspen') {
      switch (jaspenStage) {
        case 'scoring': return { n: '04', t: 'Scoring the options', d: 'Jaspen scores every path against the criteria that actually matter.' };
        case 'trade-off': return { n: '05', t: 'Weighing the trade-offs', d: 'It lays the options side by side — what you gain, what you give up.' };
        case 'execution': return { n: '06', t: 'The execution plan', d: 'A coordinated plan lands — phases, owners, and dates.' };
        default: return { n: '03', t: 'Framing the decision', d: 'On jaspen.ai, it pulls the real context and frames the actual question.' };
      }
    }
    if (!isPeer && view === dmWith) return { n: '02', t: 'The backchannel', d: 'The honest version never makes the meeting — it goes to a DM.' };
    if (isPeer) return { n: '01', t: 'Two peers, stuck', d: 'The same conversation, on repeat, with no way to land it.' };
    return { n: '01', t: 'The meeting', d: 'Everyone understands the problem. Nobody can make the call.' };
  })();
  const meta = (name) => sc.people[name] || { role: '', color: FILLER.color, initials: name[0] };

  // current thread
  let rows = [];
  let typingFrom = null;
  if (view === primaryView) {
    rows = primaryMsgs.slice(0, primaryN);
    if (typing && primaryN < primaryMsgs.length) typingFrom = primaryMsgs[primaryN].from;
  } else if (!isPeer && view === dmWith) {
    rows = sc.dm.filter((m) => m.early);
    if (dmPunch) rows = rows.concat(sc.dm.filter((m) => m.punch));
    if (typing && !dmPunch) typingFrom = you;
  }

  // header
  let header;
  if (view === 'group') {
    header = (
      <div className="tc-main-head">
        <span className="tc-main-title"># {sc.title}</span>
        <span className="tc-main-people">{Object.keys(sc.people).join(', ')}</span>
      </div>
    );
  } else {
    const p = sc.people[view] || { role: '' };
    header = (
      <div className="tc-main-head">
        <span className="tc-main-title"><span className="tc-presence" />{view}</span>
        <span className="tc-main-people">{p.role ? `${p.role} · ` : ''}Direct message</span>
      </div>
    );
  }

  return (
    <div className="lc">
      <aside className="lc-narration" key={narration.n}>
        <span className="lc-step">{narration.n}</span>
        <h4 className="lc-step-title">{narration.t}</h4>
        <p className="lc-step-desc">{narration.d}</p>
      </aside>
      <div className="tc-laptop" style={{ '--rx': `${sc.tilt.rx}deg`, '--ry': `${sc.tilt.ry}deg` }}>
        <div className="tc-device">
        <div className="tc-screen">
          <div className="tc-app" ref={appRef}>
            <div className="tc-titlebar">
              <span className={`tc-tb-title ${screen === 'jaspen' ? 'is-url' : ''}`}>{screen === 'chat' ? 'Northwind · Workspace' : '🔒 jaspen.ai'}</span>
              <span className="tc-winctl" aria-hidden="true"><i>—</i><i>▢</i><i>✕</i></span>
            </div>

            {screen === 'chat' ? (
            <div className="tc-body">
              <div className="tc-rail" aria-hidden="true">
                <span className="tc-rail-logo">N</span>
                <span className="tc-rail-ic is-on" />
                <span className="tc-rail-ic" />
                <span className="tc-rail-ic" />
                <span className="tc-rail-ic" />
              </div>

              <div className="tc-list">
                <div className="tc-list-section">Favorites</div>
                {sc.favorites.map((name) => {
                  const p = sc.people[name];
                  const isDmTarget = name === dmWith;
                  return (
                    <button
                      key={name}
                      ref={isDmTarget ? dmItemRef : null}
                      className={`tc-chat ${view === name ? 'is-active' : ''}`}
                      onClick={() => openChat(name)}
                    >
                      <span className="tc-chat-avatars">
                        <span className="tc-mini" style={{ background: p.color }}>{p.initials}<i className="tc-mini-presence" /></span>
                      </span>
                      <span className="tc-chat-text">
                        <span className="tc-chat-title">{name}</span>
                        <span className="tc-chat-preview">{p.role}</span>
                      </span>
                    </button>
                  );
                })}

                <div className="tc-list-section">Recent</div>
                {!isPeer && (
                  <button className={`tc-chat ${view === 'group' ? 'is-active' : ''}`} onClick={() => openChat('group')}>
                    <span className="tc-chat-avatars is-group">
                      {Object.values(sc.people).slice(0, 3).map((p, i) => (
                        <span key={i} className="tc-mini" style={{ background: p.color }}>{p.initials}</span>
                      ))}
                    </span>
                    <span className="tc-chat-text">
                      <span className="tc-chat-title">{sc.title}</span>
                      <span className="tc-chat-preview">{sc.group[0].text}</span>
                    </span>
                  </button>
                )}
                <button className={`tc-chat ${view === FILLER.name ? 'is-active' : ''}`} onClick={() => openChat(FILLER.name)}>
                  <span className="tc-chat-avatars">
                    <span className="tc-mini" style={{ background: FILLER.color }}>{FILLER.initials}</span>
                  </span>
                  <span className="tc-chat-text">
                    <span className="tc-chat-title">{FILLER.name}</span>
                    <span className="tc-chat-preview">{FILLER.preview}</span>
                  </span>
                </button>
              </div>

              <div className="tc-main">
                {header}
                <div className="tc-messages" ref={listRef}>
                  {rows.length === 0 && view !== primaryView && (
                    <div className="tc-empty">This is the beginning of your chat with {view}.</div>
                  )}
                  {rows.map((m, i) => {
                    const p = meta(m.from);
                    const mine = m.from === you;
                    return (
                      <div className={`tc-msg ${mine ? 'is-mine' : ''} ${m.punch ? 'is-punch' : ''}`} key={`${sc.id}-${view}-${i}`}>
                        {!mine && <span className="tc-avatar" style={{ background: p.color }}>{p.initials}</span>}
                        <div className="tc-msg-body">
                          {!mine && <span className="tc-msg-meta"><strong>{m.from}</strong> <em>{p.role}</em></span>}
                          <div className="tc-bubble">{m.text}</div>
                        </div>
                      </div>
                    );
                  })}
                  {typing && typingFrom && (
                    <div className={`tc-msg ${typingFrom === you ? 'is-mine' : ''}`}>
                      {typingFrom !== you && (
                        <span className="tc-avatar" style={{ background: meta(typingFrom).color }}>{meta(typingFrom).initials}</span>
                      )}
                      <div className="tc-msg-body">
                        <div className="tc-bubble tc-typing"><i /><i /><i /></div>
                      </div>
                    </div>
                  )}
                </div>

                <div className={`tc-handoff ${done ? 'is-ready' : ''}`}>
                  <p className="tc-handoff-q">What if that conversation ended with a decision?</p>
                  <button type="button" className="tc-handoff-btn" onClick={() => onResolve(sc.id)}>
                    See how Jaspen helps
                    <i className="fa-solid fa-arrow-down" aria-hidden="true" />
                  </button>
                </div>

                <div className="tc-compose" aria-hidden="true">
                  <span className="tc-compose-ph">Type a message</span>
                  <span className="tc-send"><i className="fa-solid fa-paper-plane" /></span>
                </div>
              </div>
            </div>
            ) : (
              <div className="tc-jaspen"><JaspenWorkspace demo={sc.demo} onStage={setJaspenStage} loop={false} onDone={resetStory} /></div>
            )}

            <div className="tc-dock">
              <span className="tc-dock-ic is-win" aria-hidden="true"><span className="tc-win"><i /><i /><i /><i /></span></span>
              <button type="button" className={`tc-dock-ic is-teams ${screen === 'chat' ? 'on' : ''}`} onClick={() => setScreen('chat')} aria-label="Teams">T</button>
              <button ref={browserRef} type="button" className={`tc-dock-ic is-browser ${screen === 'jaspen' ? 'on' : ''}`} onClick={() => setScreen('jaspen')} aria-label="Open jaspen.ai"><i className="fa-solid fa-globe" /></button>
              <span className="tc-dock-ic is-excel" aria-hidden="true">X</span>
              <span className="tc-dock-ic is-ppt" aria-hidden="true">P</span>
              <span className="tc-dock-ic is-outlook" aria-hidden="true"><i className="fa-solid fa-envelope" /></span>
              <span className="tc-taskclock" aria-hidden="true">9:41 AM<em>Thu, Jun 25</em></span>
            </div>

            {cursor && (
              <div className={`tc-cursor ${cursor.click ? 'is-click' : ''}`} style={{ left: cursor.x, top: cursor.y }} aria-hidden="true">
                <i className="fa-solid fa-arrow-pointer" />
                <span className="tc-cursor-ring" />
              </div>
            )}
          </div>
        </div>
        <div className="tc-base" aria-hidden="true"><span /></div>
      </div>
      </div>
    </div>
  );
}
