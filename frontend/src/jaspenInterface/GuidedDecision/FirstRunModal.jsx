import React, { useEffect, useState } from 'react';
import * as S from './guidedDecisionStyles';
import './GuidedDecision.css';

// First-login welcome. Invites the user into Guided Decision without
// requiring it. Dismissal is persisted by the caller.
export default function FirstRunModal({ open, onStart, onSkip }) {
  const [hoverStart, setHoverStart] = useState(false);
  const [hoverSkip, setHoverSkip] = useState(false);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key === 'Escape') onSkip();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onSkip]);

  if (!open) return null;

  return (
    <div style={S.overlay} role="dialog" aria-modal="true" aria-label="Welcome">
      <div style={S.backdrop} onClick={onSkip} />
      <div style={S.welcomeCard}>
        <div
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '8px',
            fontSize: '0.72rem',
            fontWeight: 600,
            letterSpacing: '0.12em',
            textTransform: 'uppercase',
            color: S.ACCENT,
            marginBottom: '16px',
          }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d="M12 2.5l1.6 4.3a4 4 0 0 0 2.36 2.36L20.26 10.75l-4.3 1.6a4 4 0 0 0-2.36 2.36L12 19l-1.6-4.3a4 4 0 0 0-2.36-2.36L3.74 10.75l4.3-1.6a4 4 0 0 0 2.36-2.36L12 2.5z" />
          </svg>
          Guided Decision
        </div>
        <h2 style={S.welcomeTitle}>Let&apos;s solve a problem together.</h2>
        <p style={S.welcomeBody}>
          You don&apos;t need to learn Jaspen before using it. Share your situation however you&apos;d
          like, and Jaspen will help transform a complex situation into a clear path forward.
        </p>
        <div style={S.welcomeActions}>
          <button
            type="button"
            style={{
              ...S.btnGhost,
              background: hoverSkip ? 'rgba(26,29,36,0.06)' : 'transparent',
            }}
            onMouseEnter={() => setHoverSkip(true)}
            onMouseLeave={() => setHoverSkip(false)}
            onClick={onSkip}
          >
            Skip for now
          </button>
          <button
            type="button"
            style={{ ...S.btnPrimary, background: hoverStart ? '#850359' : S.ACCENT }}
            onMouseEnter={() => setHoverStart(true)}
            onMouseLeave={() => setHoverStart(false)}
            onClick={onStart}
          >
            Start Guided Decision
          </button>
        </div>
      </div>
    </div>
  );
}
