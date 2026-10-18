import React from 'react';

export default function ScoreReuseNotice({ provenance, scorecardId, optionKey, onScoreFresh }) {
  if (!provenance) return null;
  return (
    <div role="status" style={{
      margin: '0 0 14px', padding: '10px 12px', borderRadius: 8,
      background: '#eff9fc', border: '1px solid #cfe8ef',
      color: '#161f3b', fontSize: 12.5, lineHeight: 1.45,
    }}>
      <strong>Reused {provenance.source_user_name || 'a teammate'}’s judgment</strong>
      {provenance.source_created_at
        ? ` from ${new Date(provenance.source_created_at).toLocaleDateString()}`
        : ''}. Your decision inputs match exactly. No Thinking Power was charged.
      {onScoreFresh && (
        <button
          type="button"
          onClick={() => onScoreFresh({ scorecardId, optionKey })}
          style={{ marginLeft: 8, border: 0, background: 'transparent', color: '#a0036c', fontWeight: 700, cursor: 'pointer', padding: 0 }}
        >Score fresh</button>
      )}
    </div>
  );
}
