import React, { useMemo, useState } from 'react';

export default function ExploreAnalysis({
  analysisResult,
  messages,
  readinessPercent,
  onSend,
  onFinish,
  onBackToSummary,
  onOpenChat,
  onOpenScenario,
  onConvertToProject,
}) {
  const derivedMessages = useMemo(() => {
    if (Array.isArray(messages)) return messages;
    const history =
      analysisResult?.chat_history ||
      analysisResult?.conversation_history ||
      analysisResult?.chatHistory ||
      [];
    if (!Array.isArray(history)) return [];
    return history.map((m) => ({
      role: m.role || m.sender || (m.is_user ? 'user' : 'ai'),
      text: m.text || m.content || '',
    }));
  }, [messages, analysisResult]);

  const fallbackPercent = Number(analysisResult?.readiness?.percent ?? analysisResult?.readiness ?? 0);
  const percent = Number.isFinite(readinessPercent)
    ? Math.round(readinessPercent)
    : (Number.isFinite(fallbackPercent) ? Math.round(fallbackPercent) : 0);

  const [draft, setDraft] = useState('');

  const handleSend = () => {
    if (onSend) {
      onSend(draft);
    } else if (onOpenChat) {
      onOpenChat();
    }
    setDraft('');
  };

  const handleFinish = () => {
    if (onFinish) {
      onFinish();
    } else if (onBackToSummary) {
      onBackToSummary();
    } else if (onOpenScenario) {
      onOpenScenario();
    } else if (onConvertToProject) {
      onConvertToProject();
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 200px)' }}>
      {/* Messages area */}
      <div className="miq-chat-messages" style={{ flex: 1, overflowY: 'auto', padding: 0 }}>
        {derivedMessages.map((msg, i) => {
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
                __html: String(msg.text || '').replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>'),
              }}
            />
          );
        })}
      </div>

      {/* Bottom input area */}
      <div style={{ flexShrink: 0, paddingTop: '16px' }}>
        {/* Input row */}
        <div style={{ display: 'flex', gap: '8px', alignItems: 'flex-end', marginBottom: '10px' }}>
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
            type="button"
            aria-label="Attach"
          >
            <i className="fa-solid fa-plus" />
          </button>

          <textarea
            className="miq-chat-textarea"
            rows={1}
            placeholder="Refine the conversation to improve your scorecard..."
            style={{ flex: 1 }}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />

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
              type="button"
              aria-label="Voice"
            >
              <i className="fa-solid fa-microphone" />
            </button>
            <button className="miq-chat-send" onClick={handleSend} type="button">
              <i className="fa-solid fa-arrow-up" />
            </button>
          </div>
        </div>

        {/* Status row */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div className="miq-progress" style={{ flex: 1 }}>
            <div className="miq-progress-fill magenta" style={{ width: `${percent}%` }} />
          </div>
          <span
            style={{
              fontSize: 'var(--miq-text-sm)',
              fontWeight: 600,
              color: 'var(--miq-gray-600)',
              whiteSpace: 'nowrap',
            }}
          >
            {percent}% ready
          </span>
          <button
            onClick={handleFinish}
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
            type="button"
          >
            <i className="fa-solid fa-check" />
            Finish &amp; Analyze
          </button>
        </div>
      </div>
    </div>
  );
}
