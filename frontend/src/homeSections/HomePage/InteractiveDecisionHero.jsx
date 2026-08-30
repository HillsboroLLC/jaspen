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
import ConfidenceCheckPanel from './ConfidenceCheckPanel';

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
  system_mapping: 'How it works end-to-end is explained',
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
  ready: 'Enough context to begin. Your workspace picks up right here.',
};

// Once remaining budget gets this low, nudge toward continuing in the
// workspace instead of letting the visitor run into the hard server cap.
const LOW_BUDGET_WARNING_THRESHOLD = 800;

// Re-exported for existing importers; canonical definition lives in
// shared/auth/pendingIntakeContext.js.
export { PENDING_CONTEXT_STORAGE_KEY };

// Fixed interface copy for the account handoff. It is not used as a
// substitute chat response when live AI is unavailable.
function assistantBubbleFor(analysis, isFirstTurn) {
  if (analysis.turn_limit_reached && !analysis.ready) {
    return 'To continue, create a free account so this conversation can be securely saved. Jaspen will continue the intake inside your workspace.';
  }
  if (analysis.ready) {
    return "You've told Jaspen enough to start building a scorecard. Create a free account to securely save this conversation and continue in your workspace.";
  }
  const question = analysis.next_question || "Tell me more about what you're working through.";
  return isFirstTurn ? question : `Got it. ${question}`;
}

// Parses a fetch Response's SSE body, calling onEvent(parsedJson) for each
// "data: {...}" frame as it arrives. Used only for the pre-signup AI chat
// attempt (/chat).
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
  // ALWAYS driven by the readiness engine's response (the `insights`
  // state below), regardless of which transport produced the reply text.
  // AI (when available) only changes what the assistant bubble SAYS.
  const [messages, setMessages] = useState([]);
  const [draftText, setDraftText] = useState('');
  const [hasStarted, setHasStarted] = useState(false);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analyzeError, setAnalyzeError] = useState('');
  const [insights, setInsights] = useState(null); // latest canonical `done` payload
  const [bottomIdx, setBottomIdx] = useState(0);
  const [bottomVisible, setBottomVisible] = useState(true);
  const inputRef = useRef(null);
  const transcriptRef = useRef(null);
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

  // Attempts the AI-facilitated conversation. Returns handled=true if real AI
  // text arrived (in which case the caller does nothing further — this
  // function already updated messages/insights/handoff itself); returns
  // text or the final handoff arrived. Otherwise the caller restores the
  // user's draft and presents a retry message. Readiness/insights come from the
  // `done` event this stream sends — never inferred from the AI's own text.
  const tryAiTurn = async (nextMessages, isFirstTurn) => {
    let gotAnyDelta = false;
    let handoffReceived = false;
    let unavailableMessage = '';
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
        return { handled: false, error: "Jaspen couldn't respond just now. Please try again." };
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
          if (gotAnyDelta || evt.ready || evt.turn_limit_reached) {
            setInsights(evt);
          }
          if (!gotAnyDelta && (evt.ready || evt.turn_limit_reached)) {
            handoffReceived = true;
            setMessages((prev) => [...prev, { role: 'assistant', content: assistantBubbleFor(evt, isFirstTurn) }]);
          }
        } else if (evt.type === 'unavailable') {
          unavailableMessage = evt.message || 'Jaspen is temporarily unavailable. Please try again.';
        }
      });
    } catch {
      // Network failure mid-stream. If nothing arrived yet, treat exactly
      // like "AI unavailable" and let the caller offer a retry. If some text
      // already streamed, leave it rather than duplicating the response.
      if (!gotAnyDelta) {
        unavailableMessage = "Jaspen couldn't reach the server. Check your connection and try again.";
      }
      return { handled: gotAnyDelta, error: unavailableMessage };
    }

    if (!gotAnyDelta) {
      return { handled: handoffReceived, error: unavailableMessage };
    }

    // If the stream ended without a `done` event (rare — a raw connection
    // drop after some deltas), insights stay one turn stale until the next
    // message; readiness/CTA are never wrong, only briefly behind.
    const canonical = userAuthoredText(nextMessages);
    if (onContextChange) onContextChange(canonical);
    writePendingIntakeContext(canonical);

    return { handled: true, error: '' };
  };

  const handleSend = async () => {
    const answer = draftText.trim();
    if (!answer || isAnalyzing || insights?.ready || insights?.turn_limit_reached) return;

    const isFirstTurn = messages.filter((m) => m.role === 'user').length === 0;
    const projected = userAuthoredText([...messages, { role: 'user', content: answer }]);
    if (projected.length > MAX_INTAKE_LENGTH_HINT) {
      setAnalyzeError(
        "That's a lot of context. Let's continue this in your workspace, where Jaspen can go deeper."
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
      const result = await tryAiTurn(nextMessages, isFirstTurn);
      if (result.handled) return;
      setAnalyzeError(result.error || 'Jaspen is temporarily unavailable. Please try again.');
      setMessages((prev) => prev.slice(0, -1));
      setDraftText(answer);
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
  const turnLimitReached = Boolean(insights?.turn_limit_reached);
  const handoffRequired = Boolean(insights?.ready || turnLimitReached);
  const showLowBudgetNotice = !handoffRequired
    && typeof charactersRemaining === 'number'
    && charactersRemaining <= LOW_BUDGET_WARNING_THRESHOLD;

  return (
    <section className={`interactive-decision-hero${hasStarted ? ' is-thinking' : ''}`} id="hero-content">

      <div className="idh-shell">
        <div className="idh-copy">
          {/* The old headline, "a thought partner that won't just tell you what
              you want to hear", is a claim every assistant on the market makes,
              so it could not differentiate. This asks a question only Jaspen
              answers.

              "Direction" rather than "plan" or "decision" on purpose: a single
              decision, competing options, a ranked portfolio and a full plan are
              all directions, so the breadth of the product survives without the
              page listing what it accepts. The moment, before you commit, is
              what they have in common and is where the urgency comes from. */}
          <p className="idh-eyebrow">Decision confidence</p>
          <h1>How much of your direction is backed by evidence?</h1>
          <p className="idh-subcopy">
            Jaspen separates what is evidenced from what is assumed, shows where you
            are exposed, and names the assumptions that could change the answer,
            before you commit.
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
            {/* Artifact-first framing, delivered through copy rather than a
                file control. The wedge is someone who has already built the
                plan and wants it pressure-tested, so the prompt has to invite
                an existing document, not only a typed description.

                It stays a paste affordance on purpose. See the note by the
                textarea: a pre-auth attachment control was removed once
                already because it did less than the authenticated one, and a
                picker that handled only plain text would repeat that. Pasting
                works from every format a plan actually arrives in.

                "Weighing" rather than "decision" keeps the breadth. A single
                decision, competing options, a ranked portfolio and a plan are
                all things someone weighs, and the moment before committing is
                what they have in common. */}
            {!hasStarted && (
              <label className="idh-input-label" htmlFor="decision-context">
                What are you weighing?
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
              {starterPromptText && draftText.trim() === starterPromptText.trim() && (
                <div className="idh-example-draft-label">
                  Fictional example. Edit anything
                </div>
              )}
              <textarea
                ref={inputRef}
                id="decision-context"
                value={draftText}
                onChange={handleTextChange}
                placeholder={!hasStarted
                  ? 'Paste the plan, proposal, or options you are about to commit to. Notes and emails work too.'
                  : 'Type your reply...'}
                rows={hasStarted ? 2 : 3}
                disabled={handoffRequired}
                aria-describedby={handoffRequired ? 'idh-handoff-message' : undefined}
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
                disabled={isAnalyzing || handoffRequired || draftText.trim().length < 1}
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
                  Getting long. Your workspace can hold much more once you continue there.
                </p>
              )}
            </div>

            {handoffRequired && (
              <div className="idh-workspace-explainer" id="idh-handoff-message">
                <p className="idh-workspace-explainer-heading">
                  Create a free account to continue.
                </p>
                <p className="idh-workspace-explainer-body">
                  {insights?.ready
                    ? 'Securely save this conversation to your workspace and use it to begin building your scorecard.'
                    : 'Securely save this conversation. Jaspen will continue the intake inside your workspace.'}
                </p>
              </div>
            )}
          </div>

          <aside className="idh-insights-panel" aria-label="Jaspen insights preview">
            {/* The band label sits above the panel and contradicts it: "Jaspen
                is just getting started with this" directly over "What Jaspen
                can already see" says both nothing-yet and here-is-something in
                the same breath, and nothing-yet is the framing this panel
                exists to replace. The progress bar above the workspace still
                carries the same signal for anyone tracking it. */}
            {!insights?.confidence_check && (
              <div className="idh-insights-header">
                <span>{bandLabel}</span>
              </div>
            )}

            {/* Deterministic only: every line traces to something the intake
                engine already computed, and the sentences arrive rendered from
                the server so no wording is generated here.

                This replaces the old known/missing checklist. The checklist
                reported what the visitor had failed to supply, which is the
                cold-start problem: thin context is exactly when Jaspen's own
                mechanic produces the least impressive result, and exactly when
                someone is deciding whether to stay. ConfidenceCheckPanel shows
                the same booleans as an early finding instead. */}
            {insights?.confidence_check && (
              <ConfidenceCheckPanel check={insights.confidence_check} />
            )}

            {/* Fallback for a server that predates confidence_check. */}
            {insights && !insights.confidence_check && (
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

            {insights && !handoffRequired && insights.next_question && (
              <div className="idh-question-callout">
                <p className="idh-question-eyebrow">Jaspen's next question</p>
                <p className="idh-question-text">{insights.next_question}</p>
              </div>
            )}

            {handoffRequired && (
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
            {/* Names a failure the reader has personally lost to, rather than
                asserting that decisions are hard. Softened from an earlier
                draft that said the best-evidenced case rarely wins: the point
                lands without implying most corporate decisions are badly
                evidenced, which is both unprovable and needlessly cynical. */}
            <p className="idh-why-eyebrow">Why Jaspen</p>
            <p className="idh-why-heading">
              A well-presented case can look stronger than the evidence behind it.
            </p>
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
