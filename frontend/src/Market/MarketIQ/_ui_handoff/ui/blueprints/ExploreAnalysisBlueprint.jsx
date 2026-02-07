/**
 * ExploreAnalysisBlueprint.jsx — Refine & Rescore tab main content
 *
 * Shows:
 *  - Full-height chat conversation area (user messages in magenta, AI in white)
 *  - Bottom bar: attachment button, text input, mic button, send button
 *  - Status row: readiness progress bar, percentage, "Finish & Analyze" button
 *
 * INTEGRATION: replace mockMessages with your real conversation state.
 * INTEGRATION: wire onSend, onFinish to your real handlers.
 */
import React from 'react';

// ---- Mock Data ----
const mockMessages = [
  {
    role: 'ai',
    text: 'Excellent \u2014 that\u2019s a **comprehensive picture**. You\u2019ve got proven unit economics, clear differentiation (speed + quality), and disciplined capital allocation across buildout, working capital, and staffing. One last critical piece for your scorecard: **What\u2019s your biggest concern or constraint going into this expansion?**',
  },
  { role: 'tag', text: '[context-sync]' },
  {
    role: 'ai',
    text: 'I have enough to build your scorecard. Click **Finish & Analyze** when you\u2019re ready.',
  },
];

const mockReadinessPercent = 88;

export default function ExploreAnalysisBlueprint({
  // INTEGRATION: accept these as props
  messages = mockMessages,
  readinessPercent = mockReadinessPercent,
  onSend,
  onFinish,
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 200px)' }}>

      {/* Messages area */}
      <div className="miq-chat-messages" style={{ flex: 1, overflowY: 'auto', padding: 0 }}>
        {/* INTEGRATION: replace mockMessages with real conversation */}
        {messages.map((msg, i) => {
          if (msg.role === 'tag') {
            return (
              <span key={i} className="miq-chat-tag" style={{ alignSelf: 'flex-end' }}>
                {msg.text}
              </span>
            );
          }
          return (
            <div
              key={i}
              className={`miq-chat-msg ${msg.role === 'user' ? 'user' : 'ai'}`}
              style={{
                maxWidth: '80%',
                padding: '14px 18px',
                fontSize: 'var(--miq-text-md)',
                lineHeight: 1.6,
              }}
              dangerouslySetInnerHTML={{
                __html: msg.text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>'),
              }}
            />
          );
        })}
      </div>

      {/* Bottom input area */}
      <div style={{ flexShrink: 0, paddingTop: '16px' }}>

        {/* Input row */}
        <div style={{ display: 'flex', gap: '8px', alignItems: 'flex-end', marginBottom: '10px' }}>
          {/* Attach button */}
          <button
            style={{
              width: 36,
              height: 36,
              border: '1px solid var(--miq-border)',
              borderRadius: 'var(--miq-radius-sm)',
              background: 'var(--miq-white)',
              color: 'var(--miq-gray-600)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              cursor: 'pointer',
              fontSize: 'var(--miq-text-md)',
              flexShrink: 0,
            }}
          >
            <i className="fa-solid fa-plus" />
          </button>

          {/* Text input */}
          <textarea
            className="miq-chat-textarea"
            rows={1}
            placeholder="Refine the conversation to improve your scorecard..."
            style={{ flex: 1 }}
          />

          {/* Icon buttons */}
          <div style={{ display: 'flex', gap: '4px', flexShrink: 0 }}>
            <button
              style={{
                width: 36,
                height: 36,
                border: 'none',
                borderRadius: 'var(--miq-radius-sm)',
                background: 'none',
                color: 'var(--miq-gray-600)',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: 'var(--miq-text-md)',
              }}
            >
              <i className="fa-solid fa-microphone" />
            </button>
            <button
              className="miq-chat-send"
              onClick={onSend}
            >
              <i className="fa-solid fa-arrow-up" />
            </button>
          </div>
        </div>

        {/* Status row */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          {/* Progress bar */}
          <div className="miq-progress" style={{ flex: 1 }}>
            <div
              className="miq-progress-fill magenta"
              style={{ width: `${readinessPercent}%` }}
            />
          </div>
          <span
            style={{
              fontSize: 'var(--miq-text-sm)',
              fontWeight: 600,
              color: 'var(--miq-gray-600)',
              whiteSpace: 'nowrap',
            }}
          >
            {readinessPercent}% ready
          </span>
          {/* Finish button */}
          <button
            onClick={onFinish}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '8px 20px',
              border: 'none',
              borderRadius: 'var(--miq-radius-sm)',
              background: 'var(--miq-magenta)',
              color: 'var(--miq-white)',
              fontSize: 'var(--miq-text-base)',
              fontWeight: 600,
              fontFamily: 'var(--miq-font)',
              cursor: 'pointer',
              flexShrink: 0,
            }}
          >
            <i className="fa-solid fa-check" />
            Finish &amp; Analyze
          </button>
        </div>
      </div>
    </div>
  );
}
