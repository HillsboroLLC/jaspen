import React, { useEffect, useRef, useState } from 'react';
import './InteractiveDecisionHero.css';
import { API_BASE } from '../../config/apiBase';
import {
  PENDING_CONTEXT_STORAGE_KEY,
  joinTurns,
  writePendingIntakeContext,
  MAX_INTAKE_LENGTH_HINT,
} from '../../shared/auth/pendingIntakeContext';
import StarterDecisionChips from './StarterDecisionChips';

const BOTTOM_WORDS = [
  { word: 'idea',       article: 'an', color: '#e9b57b' },
  { word: 'team',       article: 'a',  color: '#5a26c6' },
  { word: 'enterprise', article: 'an', color: '#fd6b02' },
];

// The homepage now runs the SAME readiness engine + active spec as the
// authenticated workspace (see backend/app/routes/public_intake.py). Its
// category keys/labels come from whichever spec is live server-side, so this
// map is a presentation-only overlay for friendlier homepage copy — any key
// not listed here just falls back to the server's own label, and nothing
// breaks if the active spec changes.
const FRIENDLY_CATEGORY_LABELS = {
  goal_definition: 'A clear goal with a target',
  evidence_baseline: 'Real evidence backs it up',
  sme_drivers: "Who's involved is named",
  system_mapping: 'How it works end-to-end is mapped',
  constraint_unlock: 'The main constraint is named',
  execution_sequence: 'A rough sequence of work',
  replication_plan: 'How this could repeat elsewhere',
  // readiness-v1 keys, kept for compatibility if that profile is ever active:
  problem_clarity: "There's a clear problem to solve",
  market_context: 'Who this is for is named',
  business_model: 'How this creates value is named',
  execution_plan: 'A timeline and resources are named',
};

const BAND_LABELS = {
  starting: 'Jaspen is just getting started with this.',
  building: 'Jaspen is building a clearer picture.',
  ready: 'Enough context to begin — your workspace picks up right here.',
};

// Once remaining budget gets this low, nudge toward continuing in the
// workspace instead of letting the visitor run into the hard server cap.
const LOW_BUDGET_WARNING_THRESHOLD = 800;

// How long to stay off the AI path after it fails to produce a single token
// (network error, timeout, kill switch, flag off, etc.) before trying again.
// This is a COOLDOWN, not a permanent session-long disable: a transient
// outage should degrade one conversation's tone for about a minute, never
// the rest of the visit. Retried lazily — on the next message the visitor
// sends after the cooldown elapses — rather than on a background timer, so
// we never poll an endpoint nobody is actively using.
const AI_RETRY_COOLDOWN_MS = 60_000;

// Re-exported for existing importers; canonical definition lives in
// shared/auth/pendingIntakeContext.js.
export { PENDING_CONTEXT_STORAGE_KEY };

// Deterministic assistant bubble — built entirely from the engine's own
// next_question, never invented copy. Mirrors backend/app/routes/
// public_intake.py's deterministic_reply_text() exactly; keep both in sync.
// This is what every turn shows when AI is off, unavailable, or falls back.
function assistantBubbleFor(analysis, isFirstTurn) {
  if (analysis.ready) {
    return "You've told Jaspen enough to start building a scorecard on this.";
  }
  const question = analysis.next_question || "Tell me more about what you're working through.";
  return isFirstTurn ? question : `Got it. ${question}`;
}

// Parses a fetch Response's SSE body, calling onEvent(parsedJson) for each
// "data: {...}" frame as it arrives. Used only for the pre-signup AI chat
// attempt (/chat) — the deterministic path (/analyze) is plain JSON.
async function readSseEvents(response, onEvent) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let boundary;
    while ((boundary = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, boundary).trim();
      buffer = buffer.slice(boundary + 2);
      if (!frame.startsWith('data:')) continue;
      const payload = frame.slice(5).trim();
      if (!payload) continue;
      try {
        onEvent(JSON.parse(payload));
      } catch {
        // Malformed frame — ignore rather than break the whole stream.
      }
    }
  }
}

export default function InteractiveDecisionHero({ onOpenModal, onContextChange }) {
  // Real conversation transcript: [{ role: 'user'|'assistant', content }].
  // Readiness — and everything the UI shows (progress, insights, CTA) — is
  // ALWAYS driven by the deterministic engine's response (the `insights`
  // state below), regardless of which transport produced the reply text.
  // AI (when available) only changes what the assistant bubble SAYS.
  const [messages, setMessages] = useState([]);
  const [draftText, setDraftText] = useState('');
  const [hasStarted, setHasStarted] = useState(false);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analyzeError, setAnalyzeError] = useState('');
  const [insights, setInsights] = useState(null); // latest deterministic `done`/`/analyze` payload
  const [bottomIdx, setBottomIdx] = useState(0);
  const [bottomVisible, setBottomVisible] = useState(true);
  const inputRef = useRef(null);
  const transcriptRef = useRef(null);
  // Timestamp (ms since epoch) until which /chat is skipped in favor of the
  // deterministic path directly — 0 means "not on cooldown, try AI." Set
  // whenever /chat fails to produce a single token; cleared naturally once
  // Date.now() passes it, so the very next message after the cooldown tries
  // AI again on its own. Never persisted (no storage) — a page refresh
  // starts a fresh component instance with this back at 0.
  const aiCooldownUntilRef = useRef(0);

  // Speech-to-text (Web Speech API). Feature-detected so the mic only appears
  // where it works (Chrome, Edge, Safari). The AI/analyze flow is untouched:
  // dictation just writes into the same draft textarea the user types into.
  const [isListening, setIsListening] = useState(false);
  const [speechSupported, setSpeechSupported] = useState(false);
  const recognitionRef = useRef(null);
  const speechBaseRef = useRef(''); // draft text captured when dictation starts

  useEffect(() => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) return undefined;

    const recognition = new SR();
    recognition.lang = 'en-US';
    recognition.continuous = true;
    recognition.interimResults = true;

    recognition.onresult = (event) => {
      let transcript = '';
      for (let i = 0; i < event.results.length; i += 1) {
        transcript += event.results[i][0].transcript;
      }
      const base = speechBaseRef.current;
      const sep = base && !/\s$/.test(base) ? ' ' : '';
      setDraftText(base + sep + transcript);
    };
    recognition.onerror = () => setIsListening(false);
    recognition.onend = () => setIsListening(false);

    recognitionRef.current = recognition;
    setSpeechSupported(true);

    return () => {
      try { recognition.abort(); } catch { /* already stopped */ }
    };
  }, []);

  const toggleDictation = () => {
    const recognition = recognitionRef.current;
    if (!recognition) return;
    if (isListening) {
      recognition.stop();
      setIsListening(false);
      return;
    }
    speechBaseRef.current = draftText;
    try {
      recognition.start();
      setIsListening(true);
      if (inputRef.current) inputRef.current.focus();
    } catch {
      // start() throws if called while already active; ignore.
    }
  };

  useEffect(() => {
    const cycle = setInterval(() => {
      setBottomVisible(false);
      setTimeout(() => {
        setBottomIdx(i => (i + 1) % BOTTOM_WORDS.length);
        setBottomVisible(true);
      }, 400);
    }, 2600);
    return () => clearInterval(cycle);
  }, []);

  useEffect(() => {
    if (transcriptRef.current) {
      transcriptRef.current.scrollTop = transcriptRef.current.scrollHeight;
    }
  }, [messages]);

  const handleTextChange = (event) => {
    setDraftText(event.target.value);
  };

  const [starterPromptText, setStarterPromptText] = useState('');

  const handleStarterDecisionSelect = (starter) => {
    const nextPrompt = String(starter?.prompt || '');
    if (!nextPrompt) return;

    const hasDraft = draftText.trim().length > 0;
    const hasEditedStarter = starterPromptText
      && draftText.trim() !== starterPromptText.trim();
    const hasOwnDraft = hasDraft && !starterPromptText;

    if ((hasEditedStarter || hasOwnDraft) && !window.confirm('Replace your current draft with this example decision?')) {
      return;
    }

    setDraftText(nextPrompt);
    setStarterPromptText(nextPrompt);
    window.requestAnimationFrame(() => {
      if (inputRef.current) inputRef.current.focus();
    });
  };

  const userAuthoredText = (msgList) => joinTurns(
    msgList.filter((m) => m.role === 'user').map((m) => m.content)
  );

  // The always-available path: deterministic readiness only, no AI call at
  // all. Used directly when AI is unavailable, and as the fallback target
  // when an AI attempt yields zero tokens for any reason. Byte-identical to
  // the original Option A implementation — the fallback a visitor gets is
  // exactly what they'd have gotten had AI never existed.
  const runDeterministicTurn = async (nextMessages, isFirstTurn) => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/public/intake/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ history: nextMessages }),
      });
      const data = await res.json().catch(() => ({}));

      if (!res.ok) {
        if (data?.code === 'message_too_long') {
          setAnalyzeError(
            "That's a lot of context — let's continue this in your workspace, where Jaspen can go deeper."
          );
        } else {
          setAnalyzeError(data?.error || "Jaspen couldn't respond just now. Try again.");
        }
        setMessages((prev) => prev.slice(0, -1));
        return;
      }

      setInsights(data);
      setMessages((prev) => [...prev, { role: 'assistant', content: assistantBubbleFor(data, isFirstTurn) }]);

      const canonical = userAuthoredText(nextMessages);
      if (onContextChange) onContextChange(canonical);
      writePendingIntakeContext(canonical);
    } catch {
      setAnalyzeError("Jaspen couldn't reach the server. Check your connection and try again.");
      setMessages((prev) => prev.slice(0, -1));
    }
  };

  // Attempts the AI-facilitated conversation. Returns true if any real AI
  // text arrived (in which case the caller does nothing further — this
  // function already updated messages/insights/handoff itself); returns
  // false if nothing arrived at all, meaning the caller should run the
  // deterministic turn instead. Readiness/insights ALWAYS come from the
  // `done` event this stream sends — never inferred from the AI's own text.
  const tryAiTurn = async (nextMessages, isFirstTurn) => {
    let gotAnyDelta = false;
    let hasAppendedAssistantMessage = false;
    // Accumulated OUTSIDE any setState updater (mutated here, in the plain
    // callback body) so the updaters below stay pure functions of (prev,
    // accumulatedText) — React 18 StrictMode double-invokes setState
    // updaters in dev to catch impure ones; a updater that itself mutates a
    // closed-over index/variable gets that mutation applied twice and
    // corrupts state. Reading (not writing) an outer value from a pure
    // updater is safe; this pattern keeps every updater idempotent.
    let accumulatedText = '';

    try {
      const res = await fetch(`${API_BASE}/api/v1/public/intake/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ history: nextMessages }),
      });

      if (!res.ok || !res.body) {
        aiCooldownUntilRef.current = Date.now() + AI_RETRY_COOLDOWN_MS;
        return false;
      }

      await readSseEvents(res, (evt) => {
        if (evt.type === 'delta' && evt.text) {
          gotAnyDelta = true;
          accumulatedText += evt.text;
          if (!hasAppendedAssistantMessage) {
            hasAppendedAssistantMessage = true;
            const textAtAppend = accumulatedText;
            setMessages((prev) => [...prev, { role: 'assistant', content: textAtAppend }]);
          } else {
            const textAtUpdate = accumulatedText;
            setMessages((prev) => {
              const copy = prev.slice();
              copy[copy.length - 1] = { role: 'assistant', content: textAtUpdate };
              return copy;
            });
          }
        } else if (evt.type === 'done') {
          setInsights(evt);
        }
      });
    } catch {
      // Network failure mid-stream. If nothing arrived yet, treat exactly
      // like "AI unavailable" and let the caller fall back. If some text
      // already streamed, leave it — do not also append a deterministic
      // reply on top of a partial AI one.
      if (!gotAnyDelta) {
        aiCooldownUntilRef.current = Date.now() + AI_RETRY_COOLDOWN_MS;
      }
      return gotAnyDelta;
    }

    if (!gotAnyDelta) {
      aiCooldownUntilRef.current = Date.now() + AI_RETRY_COOLDOWN_MS;
      return false;
    }

    // A real reply arrived — clear any earlier cooldown outright rather than
    // just letting it lapse, so a mid-cooldown recovery (e.g. an admin
    // re-enabling the kill switch) is picked up immediately rather than
    // waiting out the rest of the timer.
    aiCooldownUntilRef.current = 0;

    // If the stream ended without a `done` event (rare — a raw connection
    // drop after some deltas), insights stay one turn stale until the next
    // message; readiness/CTA are never wrong, only briefly behind.
    const canonical = userAuthoredText(nextMessages);
    if (onContextChange) onContextChange(canonical);
    writePendingIntakeContext(canonical);

    return true;
  };

  const handleSend = async () => {
    const answer = draftText.trim();
    if (!answer || isAnalyzing) return;

    const isFirstTurn = messages.filter((m) => m.role === 'user').length === 0;
    const projected = userAuthoredText([...messages, { role: 'user', content: answer }]);
    if (projected.length > MAX_INTAKE_LENGTH_HINT) {
      setAnalyzeError(
        "That's a lot of context — let's continue this in your workspace, where Jaspen can go deeper."
      );
      return;
    }

    const nextMessages = [...messages, { role: 'user', content: answer }];
    setMessages(nextMessages);
    setDraftText('');
    setHasStarted(true);
    setIsAnalyzing(true);
    setAnalyzeError('');

    try {
      if (Date.now() >= aiCooldownUntilRef.current) {
        const handled = await tryAiTurn(nextMessages, isFirstTurn);
        if (handled) return;
        // No AI text arrived at all — a cooldown is now set, so turns sent
        // in the next ~60s skip straight past /chat. Fall through to the
        // deterministic path so this turn still gets a reply.
      }
      await runDeterministicTurn(nextMessages, isFirstTurn);
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleContinue = (flow) => {
    if (onOpenModal) { onOpenModal(flow); return; }
    window.location.assign('/login?source=hero-scorecard');
  };

  const band = insights?.band || 'starting';
  const bandLabel = BAND_LABELS[band] || BAND_LABELS.starting;
  const displayBarPercent = insights ? Math.min(92, Math.max(6, insights.overall_percent || 0)) : 0;

  const charactersRemaining = insights?.characters_remaining;
  const showLowBudgetNotice = !insights?.ready
    && typeof charactersRemaining === 'number'
    && charactersRemaining <= LOW_BUDGET_WARNING_THRESHOLD;

  return (
    <section className={`interactive-decision-hero${hasStarted ? ' is-thinking' : ''}`} id="hero-content">

      <div className="idh-shell">
        <div className="idh-copy">
          <p className="idh-eyebrow">Decision intelligence starts here</p>
          <h1>Make the call you can defend.</h1>
          <p className="idh-subcopy">
            Paste your notes, emails, or data. Jaspen scores your options and shows
            exactly how it got the number.
          </p>
        </div>

        {hasStarted && (
          <div className="idh-understanding is-visible">
            <div className="idh-progress-track">
              <span style={{ width: `${displayBarPercent}%` }} />
            </div>
            <p className="idh-progress-label">{bandLabel}</p>
          </div>
        )}

        <div className="idh-workspace" aria-live="polite">
          <div className="idh-chat-panel">
            {!hasStarted && (
              <label className="idh-input-label" htmlFor="decision-context">
                What decision are you working through?
              </label>
            )}

            {hasStarted && (
              <div className="idh-chat-transcript" ref={transcriptRef} aria-label="Conversation with Jaspen">
                {messages.map((m, i) => (
                  <div className={`idh-chat-row idh-chat-row-${m.role}`} key={i}>
                    <div className="idh-chat-bubble">{m.content}</div>
                  </div>
                ))}
              </div>
            )}

            <div className="idh-textarea-wrap">
              <textarea
                ref={inputRef}
                id="decision-context"
                value={draftText}
                onChange={handleTextChange}
                placeholder={!hasStarted
                  ? "Paste notes, emails, meeting context — whatever you're working with..."
                  : 'Type your reply...'}
                rows={hasStarted ? 2 : 3}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleSend();
                  }
                }}
              />
              {/* No attachment affordance pre-auth: file understanding is an
                  authenticated-workspace capability. The homepage must never
                  show a control that silently does less than the real one —
                  the old paperclip only pasted the filename as text. */}
              {speechSupported && (
                <div className="idh-textarea-actions">
                  <button
                    type="button"
                    className={`idh-mic-btn${isListening ? ' is-listening' : ''}`}
                    onClick={toggleDictation}
                    aria-pressed={isListening}
                    aria-label={isListening ? 'Stop dictation' : 'Dictate with your voice'}
                    title={isListening ? 'Stop dictation' : 'Dictate with your voice'}
                  >
                    <i className="fa-solid fa-microphone" aria-hidden="true"></i>
                  </button>
                </div>
              )}
            </div>

            {!hasStarted && (
              <StarterDecisionChips onSelect={handleStarterDecisionSelect} />
            )}

            <div className="idh-analyze-row">
              <button
                type="button"
                className="idh-analyze-btn"
                onClick={handleSend}
                disabled={isAnalyzing || draftText.trim().length < 1}
                aria-label="Send to Jaspen"
                title="Send to Jaspen"
              >
                {isAnalyzing
                  ? <i className="fa-solid fa-spinner fa-spin" aria-hidden="true"></i>
                  : <i className="fa-solid fa-paper-plane" aria-hidden="true"></i>}
              </button>
              {analyzeError && <p className="idh-analyze-error" role="alert">{analyzeError}</p>}
              {!analyzeError && showLowBudgetNotice && (
                <p className="idh-low-budget-notice">
                  Getting long — your workspace can hold much more once you continue there.
                </p>
              )}
            </div>

            {insights?.ready && (
              <div className="idh-workspace-explainer">
                <p className="idh-workspace-explainer-heading">
                  Your scorecard becomes the beginning of your decision workspace.
                </p>
                <p className="idh-workspace-explainer-body">
                  We create your workspace before generating it so your context, scorecards,
                  evidence, and execution plans stay together as your decision evolves. This is
                  why we ask you to create a free account at this point—not before.
                </p>
              </div>
            )}
          </div>

          <aside className="idh-insights-panel" aria-label="Jaspen insights preview">
            <div className="idh-insights-header">
              <span>{bandLabel}</span>
            </div>

            {/* Deterministic only: every row mirrors a boolean the intake engine
                already computed, using the workspace's own active readiness
                spec (known = completed, missing = not yet). No wording here
                is generated — this panel just exposes what Jaspen has
                confidently identified so far. */}
            {insights && (
              <div className="idh-insight-list">
                {insights.known.map((category) => (
                  <div className="idh-insight-row is-complete" key={category.key}>
                    <span className="idh-step-icon">
                      <i className="fa-solid fa-check" aria-hidden="true"></i>
                    </span>
                    <span>{FRIENDLY_CATEGORY_LABELS[category.key] || category.label}</span>
                  </div>
                ))}
                {insights.missing.map((category) => (
                  <div className="idh-insight-row" key={category.key}>
                    <span className="idh-step-icon"><span /></span>
                    <span>{FRIENDLY_CATEGORY_LABELS[category.key] || category.label}</span>
                  </div>
                ))}
              </div>
            )}

            {insights && !insights.ready && insights.next_question && (
              <div className="idh-question-callout">
                <p className="idh-question-eyebrow">Jaspen's next question</p>
                <p className="idh-question-text">{insights.next_question}</p>
              </div>
            )}

            {insights?.ready && (
              <div className="idh-panel-cta-wrap">
                <button type="button" className="idh-panel-cta" onClick={() => handleContinue('signup')}>
                  <span>Create my workspace</span>
                  <i className="fa-solid fa-arrow-right" aria-hidden="true"></i>
                </button>
                <p className="idh-ready-subtext">Free account</p>
                <button type="button" className="idh-panel-cta-secondary" onClick={() => handleContinue('signin')}>
                  Already have a workspace? Log in
                </button>
              </div>
            )}
          </aside>
        </div>

        {!hasStarted && (
          <div className="idh-why">
            <p className="idh-why-eyebrow">Why Jaspen</p>
            <p className="idh-why-heading">A thought partner that won't just tell you what you want to hear.</p>
          </div>
        )}

        {!hasStarted && (
          <h2 className="idh-below-clock-text">
            Working with you and {BOTTOM_WORDS[bottomIdx].article}{' '}
            <span
              className={`idh-cycling-word${bottomVisible ? ' is-visible' : ''}`}
              style={{ color: BOTTOM_WORDS[bottomIdx].color }}
            >
              {BOTTOM_WORDS[bottomIdx].word}
            </span>
            .
          </h2>
        )}

      </div>
    </section>
  );
}
