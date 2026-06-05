import React, { useState } from 'react';

// Choice-prompt primitive (C.9). The agent emits a structured block in its reply:
//
//   [[choice]]
//   {"question":"...","options":[{"label":"A","description":"..."},{"label":"B"}],
//    "allow_text":true,"allow_multi":false}
//   [[/choice]]
//
// The frontend parses it out of the assistant text and renders clickable option
// cards (exactly like the option boxes Claude shows the user). Clicking an option
// sends its label as the next user turn; "Other" lets the user type their own.
// Works in BOTH chat renderers (main /new and the workspace sidebar) via the same
// parse + component.

const OPEN = '[[choice]]';
const CLOSE = '[[/choice]]';

// Returns { text, choice }: `text` is the prose with the choice block removed,
// `choice` is the parsed object (or null). An UNCLOSED block (mid-stream) is
// hidden from `text` so the raw tag never flashes.
export function parseChoicePrompt(raw) {
  let text = String(raw || '');
  let choice = null;

  const open = text.indexOf(OPEN);
  if (open >= 0) {
    const close = text.indexOf(CLOSE, open);
    if (close >= 0) {
      const json = text.slice(open + OPEN.length, close).trim();
      try {
        const parsed = JSON.parse(json);
        if (parsed && typeof parsed === 'object' && Array.isArray(parsed.options) && parsed.options.length) {
          choice = {
            question: String(parsed.question || '').trim(),
            options: parsed.options
              .map((o) => (typeof o === 'string' ? { label: o } : o))
              .filter((o) => o && String(o.label || '').trim())
              .map((o) => ({ label: String(o.label).trim(), description: String(o.description || '').trim() || undefined })),
            allow_text: parsed.allow_text !== false,
            allow_multi: Boolean(parsed.allow_multi),
          };
          if (!choice.options.length) choice = null;
        }
      } catch (_) {
        choice = null;
      }
      text = (text.slice(0, open) + text.slice(close + CLOSE.length)).trim();
    } else {
      // Unclosed (still streaming) — hide everything from the opening tag.
      text = text.slice(0, open).trim();
    }
  }
  return { text, choice };
}

export default function ChoicePrompt({ choice, onChoose, disabled = false, accent = '#a0036c' }) {
  const [selected, setSelected] = useState([]);
  const [showOther, setShowOther] = useState(false);
  const [otherText, setOtherText] = useState('');

  if (!choice || !Array.isArray(choice.options) || !choice.options.length) return null;
  const { question, options, allow_text, allow_multi } = choice;

  const submit = (value) => {
    const v = String(value || '').trim();
    if (!v || disabled) return;
    onChoose?.(v);
  };

  const toggleMulti = (label) => {
    setSelected((prev) => (prev.includes(label) ? prev.filter((l) => l !== label) : [...prev, label]));
  };

  return (
    <div style={{ marginTop: 10, border: '1px solid #e6eaf2', borderRadius: 12, padding: 14, background: '#fbfcfe' }}>
      {question && (
        <div style={{ fontSize: 13.5, fontWeight: 600, color: '#0f172a', marginBottom: 10, lineHeight: 1.45 }}>
          {question}
        </div>
      )}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {options.map((opt, i) => {
          const isSel = allow_multi && selected.includes(opt.label);
          return (
            <button
              key={i}
              type="button"
              disabled={disabled}
              onClick={() => (allow_multi ? toggleMulti(opt.label) : submit(opt.label))}
              onMouseEnter={(e) => { if (!disabled && !isSel) e.currentTarget.style.borderColor = accent; }}
              onMouseLeave={(e) => { if (!isSel) e.currentTarget.style.borderColor = '#e6eaf2'; }}
              style={{
                textAlign: 'left', padding: '10px 12px', borderRadius: 9,
                border: `1px solid ${isSel ? accent : '#e6eaf2'}`,
                background: isSel ? `${accent}0d` : '#fff',
                cursor: disabled ? 'default' : 'pointer', opacity: disabled ? 0.6 : 1,
                display: 'flex', flexDirection: 'column', gap: 2,
              }}
            >
              <span style={{ fontSize: 13, fontWeight: 500, color: '#0f172a' }}>{opt.label}</span>
              {opt.description && (
                <span style={{ fontSize: 11.5, color: '#64748b', lineHeight: 1.4 }}>{opt.description}</span>
              )}
            </button>
          );
        })}
      </div>

      {allow_multi && selected.length > 0 && (
        <button
          type="button"
          disabled={disabled}
          onClick={() => submit(selected.join(', '))}
          style={{ marginTop: 10, border: 'none', borderRadius: 8, background: accent, color: '#fff', padding: '8px 14px', fontSize: 13, fontWeight: 600, cursor: disabled ? 'default' : 'pointer' }}
        >
          Send {selected.length} selected
        </button>
      )}

      {allow_text && (
        showOther ? (
          <form
            onSubmit={(e) => { e.preventDefault(); submit(otherText); }}
            style={{ marginTop: 10, display: 'flex', gap: 8 }}
          >
            <input
              autoFocus
              value={otherText}
              onChange={(e) => setOtherText(e.target.value)}
              placeholder="Type your own answer…"
              disabled={disabled}
              style={{ flex: 1, border: '1px solid #e6eaf2', borderRadius: 8, padding: '8px 10px', fontSize: 13, outline: 'none' }}
            />
            <button
              type="submit"
              disabled={disabled || !otherText.trim()}
              style={{ border: 'none', borderRadius: 8, background: accent, color: '#fff', padding: '8px 12px', fontSize: 13, fontWeight: 600, cursor: 'pointer', opacity: otherText.trim() ? 1 : 0.6 }}
            >Send</button>
          </form>
        ) : (
          <button
            type="button"
            disabled={disabled}
            onClick={() => setShowOther(true)}
            style={{ marginTop: 8, border: 'none', background: 'transparent', color: '#64748b', fontSize: 12.5, cursor: disabled ? 'default' : 'pointer', padding: '4px 2px' }}
          >Other — type my own answer →</button>
        )
      )}
    </div>
  );
}
