import React, { useEffect, useRef, useState } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faMicrophone, faKeyboard, faWandMagicSparkles, faStop } from '@fortawesome/free-solid-svg-icons';
import { METHOD_OPTIONS } from './guidedDecisionState';

const ICONS = {
  microphone: faMicrophone,
  keyboard: faKeyboard,
  'wand-magic-sparkles': faWandMagicSparkles,
};

// Optional, progressive: live dictation when the browser supports it,
// otherwise the user simply types. Never required.
function useDictation(onText) {
  const recognitionRef = useRef(null);
  const [listening, setListening] = useState(false);
  const [supported, setSupported] = useState(false);

  useEffect(() => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    setSupported(Boolean(SR));
    return () => {
      try { recognitionRef.current?.stop(); } catch { /* noop */ }
    };
  }, []);

  const start = () => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) return;
    const rec = new SR();
    rec.continuous = true;
    rec.interimResults = false;
    rec.lang = 'en-US';
    rec.onresult = (event) => {
      let chunk = '';
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        chunk += event.results[i][0].transcript;
      }
      if (chunk.trim()) onText(chunk.trim());
    };
    rec.onend = () => setListening(false);
    rec.onerror = () => setListening(false);
    recognitionRef.current = rec;
    try {
      rec.start();
      setListening(true);
    } catch { /* already started */ }
  };

  const stop = () => {
    try { recognitionRef.current?.stop(); } catch { /* noop */ }
    setListening(false);
  };

  return { supported, listening, start, stop };
}

export default function CaptureContextStep({ draft, update }) {
  // Functional update so each dictated phrase appends to the latest text,
  // not a stale snapshot captured when recognition started.
  const appendText = (chunk) =>
    update((prev) => ({
      contextText: prev.contextText ? `${prev.contextText} ${chunk}` : chunk,
    }));
  const { supported, listening, start, stop } = useDictation(appendText);

  const showCapture = draft.method === 'speak' || draft.method === 'type';

  return (
    <div className="gd-step">
      <h2 className="gd-step-title">How would you like to provide information?</h2>

      <div className="gd-card-grid" role="radiogroup" aria-label="Choose how to provide information">
        {METHOD_OPTIONS.map((opt) => {
          const active = draft.method === opt.id;
          return (
            <button
              key={opt.id}
              type="button"
              role="radio"
              aria-checked={active}
              className={`gd-card${active ? ' gd-card--active' : ''}`}
              onClick={() => update({ method: opt.id })}
            >
              <span className="gd-card-icon">
                <FontAwesomeIcon icon={ICONS[opt.icon]} />
              </span>
              <span className="gd-card-title">{opt.title}</span>
              <span className="gd-card-desc">{opt.description}</span>
            </button>
          );
        })}
      </div>

      {showCapture && (
        <div className="gd-capture-panel">
          <div className="gd-capture-head">
            <span className="gd-capture-label">
              {draft.method === 'speak' ? 'Share your situation' : 'Your thoughts'}
            </span>
            {draft.method === 'speak' && supported && (
              <button
                type="button"
                className={`gd-mic-btn${listening ? ' gd-mic-btn--live' : ''}`}
                onClick={listening ? stop : start}
              >
                <FontAwesomeIcon icon={listening ? faStop : faMicrophone} />
                {listening ? 'Stop' : 'Start speaking'}
              </button>
            )}
          </div>
          <textarea
            className="gd-textarea gd-textarea--tall"
            rows={6}
            placeholder={
              draft.method === 'speak'
                ? 'Start speaking, or type here — whatever feels natural.'
                : 'Share whatever information you have. Nothing is required.'
            }
            value={draft.contextText}
            onChange={(e) => update({ contextText: e.target.value })}
          />
          {draft.method === 'speak' && !supported && (
            <p className="gd-capture-hint">
              Voice input isn&apos;t available in this browser, so feel free to type instead.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
