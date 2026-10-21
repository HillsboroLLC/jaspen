import React from 'react';

// Deterministic cards shown in the conversation. They render application
// state (the stored rubric, a step that failed, a choice that needs the
// user's confirmation) so the AI never has to type it out, and code never
// writes the conversation.

const C = {
  navy: '#161f3b',
  ink: '#5a6585',
  line: '#e6eaf2',
  track: '#eef1f6',
  rose: '#a0036c',
  roseTint: '#fbeaf3',
  green: '#0e6b3f',
  greenTint: '#e8f5ee',
  red: '#b42318',
  redTint: '#fff5f5',
  redLine: '#f3d0d0',
};

const cardStyle = {
  background: '#fff',
  border: `1px solid ${C.line}`,
  borderRadius: 12,
  padding: '14px 16px',
  maxWidth: 560,
  fontFamily: "'Inter Tight', system-ui, sans-serif",
};

const eyebrowStyle = {
  fontFamily: 'JetBrains Mono, monospace',
  fontSize: 10.5,
  letterSpacing: '0.08em',
  textTransform: 'uppercase',
  fontWeight: 600,
  color: C.rose,
};

function ActionButtons({ actions, onSendText, primaryFirst = true }) {
  if (!actions?.length || !onSendText) return null;
  return (
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 12 }}>
      {actions.map((action, index) => {
        const primary = primaryFirst && index === 0;
        return (
          <button
            key={action.value || action.label}
            type="button"
            onClick={() => onSendText(action.value || action.label)}
            style={{
              padding: '7px 14px',
              borderRadius: 8,
              border: `1px solid ${primary ? C.rose : '#cbd5e1'}`,
              background: primary ? C.rose : '#fff',
              color: primary ? '#fff' : C.navy,
              fontSize: 12.5,
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            {action.label}
          </button>
        );
      })}
    </div>
  );
}

const RUBRIC_STATUS = {
  approved: { label: 'Approved', color: C.green, tint: C.greenTint },
  used: { label: 'Used to score', color: C.navy, tint: C.track },
  proposed: { label: 'Proposed', color: C.rose, tint: C.roseTint },
};

export function RubricCard({ data, onSendText = null, showActions = false }) {
  const criteria = Array.isArray(data?.criteria) ? data.criteria : [];
  if (!criteria.length) return null;
  const status = RUBRIC_STATUS[data?.status] || RUBRIC_STATUS.proposed;
  const weighted = criteria.filter((row) => !row.gate);
  const gates = criteria.filter((row) => row.gate);
  return (
    <div style={cardStyle} data-card="rubric">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, marginBottom: 10 }}>
        <span style={eyebrowStyle}>{data?.kit_label ? `${data.kit_label} rubric` : 'Scoring rubric'}</span>
        <span style={{
          fontSize: 11, fontWeight: 600, color: status.color, background: status.tint,
          borderRadius: 999, padding: '2px 9px',
        }}
        >
          {status.label}
        </span>
      </div>
      <div style={{ display: 'grid', gap: 7 }}>
        {weighted.map((row) => (
          <div key={row.label} style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) 120px 40px', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 13, color: C.navy, minWidth: 0 }}>{row.label}</span>
            <span style={{ height: 6, borderRadius: 3, background: C.track, overflow: 'hidden' }}>
              <span style={{ display: 'block', height: '100%', width: `${Math.max(0, Math.min(100, row.weight_pct || 0))}%`, background: C.navy }} />
            </span>
            <span style={{ fontSize: 12.5, color: C.navy, fontWeight: 600, textAlign: 'right' }}>{row.weight_pct}%</span>
          </div>
        ))}
      </div>
      {gates.length > 0 && (
        <div style={{ marginTop: 12, paddingTop: 10, borderTop: `1px solid ${C.line}` }}>
          <div style={{ fontSize: 11.5, color: C.ink, marginBottom: 6 }}>Required checks (pass or fail, not weighted)</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {gates.map((row) => (
              <span key={row.label} style={{ fontSize: 12, color: C.navy, border: `1px solid ${C.line}`, borderRadius: 999, padding: '3px 10px' }}>
                {row.label}
              </span>
            ))}
          </div>
        </div>
      )}
      {showActions && <ActionButtons actions={data?.actions} onSendText={onSendText} />}
    </div>
  );
}

export function StatusCard({ data, onSendText = null, showRetry = false }) {
  const message = String(data?.message || '').trim();
  if (!message) return null;
  // "info": nothing went wrong, the user just needs to choose (for example,
  // which option they meant). "error": a step failed and can be retried.
  const info = data?.tone === 'info';
  const choices = Array.isArray(data?.actions) ? data.actions : [];
  const palette = info
    ? { line: C.line, bg: C.track, text: C.navy }
    : { line: C.redLine, bg: C.redTint, text: C.red };
  return (
    <div
      role={info ? 'status' : 'alert'}
      data-card="status"
      style={{
        maxWidth: 560, padding: '9px 12px', borderRadius: 8,
        border: `1px solid ${palette.line}`, background: palette.bg, color: palette.text,
        fontSize: 12.5, lineHeight: 1.4,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
        <span style={{ flex: 1, minWidth: 0 }}>{message}</span>
        {!choices.length && showRetry && data?.retry_message && onSendText && (
          <button
            type="button"
            onClick={() => onSendText(data.retry_message)}
            style={{
              flex: '0 0 auto', padding: '5px 12px', borderRadius: 6,
              border: `1px solid ${palette.text}`, background: '#fff', color: palette.text,
              fontSize: 12, fontWeight: 600, cursor: 'pointer',
            }}
          >
            Retry
          </button>
        )}
      </div>
      {showRetry && <ActionButtons actions={choices} onSendText={onSendText} primaryFirst={false} />}
    </div>
  );
}

export function ReceiptsCard({ data }) {
  const items = (Array.isArray(data?.items) ? data.items : []).map((item) => String(item || '').trim()).filter(Boolean);
  if (!items.length) return null;
  return (
    <ul data-card="receipts" style={{ listStyle: 'none', margin: 0, padding: 0, maxWidth: 560, display: 'grid', gap: 3 }}>
      {items.map((item) => (
        <li key={item} style={{ display: 'flex', gap: 7, fontSize: 12, color: C.ink, lineHeight: 1.45 }}>
          <span aria-hidden="true" style={{ color: C.green, fontWeight: 700 }}>✓</span>
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

export function ConfirmCard({ data, onSendText = null, showActions = false }) {
  if (data?.kind === 'decision_override') {
    const checks = Array.isArray(data.failed_check_labels) ? data.failed_check_labels.filter(Boolean) : [];
    return (
      <div style={cardStyle} data-card="confirm">
        <div style={{ ...eyebrowStyle, marginBottom: 8 }}>Override</div>
        <div style={{ fontSize: 13.5, color: C.navy, lineHeight: 1.5 }}>
          Moving forward with <strong>{data.option_name || 'this option'}</strong>
        </div>
        <div style={{ fontSize: 12, color: C.ink, marginTop: 4 }}>
          {data.override_of === 'decline'
            ? "Overrides Jaspen's No-Bid."
            : `Overrides a failed required check${checks.length ? `: ${checks.join(', ')}` : ''}.`}
        </div>
        {showActions && <ActionButtons actions={data?.actions} onSendText={onSendText} />}
      </div>
    );
  }
  if (data?.kind !== 'decision_kit_change') return null;
  return (
    <div style={cardStyle} data-card="confirm">
      <div style={{ ...eyebrowStyle, marginBottom: 8 }}>Decision Kit change</div>
      <div style={{ fontSize: 13.5, color: C.navy, lineHeight: 1.5 }}>
        {data.from_label || 'Current kit'} → <strong>{data.to_label || 'No kit'}</strong>
      </div>
      <div style={{ fontSize: 12, color: C.ink, marginTop: 4 }}>Changing the kit re-scores this decision.</div>
      {showActions && <ActionButtons actions={data?.actions} onSendText={onSendText} />}
    </div>
  );
}

// True when `message` holds the newest card of its type in the conversation,
// so only that card offers buttons.
export function isLatestCard(message, messages) {
  const type = message?.artifact?.type;
  if (!type || !Array.isArray(messages)) return false;
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index]?.artifact?.type === type) return messages[index].artifact === message.artifact;
  }
  return false;
}
