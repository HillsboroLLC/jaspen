import React, { useEffect } from 'react';
import './GuidedDecision.css';

// First-login welcome. Invites the user into Guided Decision without
// requiring it. Dismissal is persisted by the caller.
export default function FirstRunModal({ open, onStart, onSkip }) {
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
    <div className="gd-overlay" role="dialog" aria-modal="true" aria-label="Welcome">
      <div className="gd-backdrop" onClick={onSkip} />
      <div className="gd-welcome">
        <h2 className="gd-welcome-title">Let&apos;s solve a problem together.</h2>
        <p className="gd-welcome-body">
          You don&apos;t need to learn Jaspen before using it. Share your situation however you&apos;d
          like, and Jaspen will help transform a complex situation into a clear path forward.
        </p>
        <div className="gd-welcome-actions">
          <button type="button" className="gd-btn gd-btn--ghost" onClick={onSkip}>
            Skip for now
          </button>
          <button type="button" className="gd-btn gd-btn--primary" onClick={onStart}>
            Start Guided Decision
          </button>
        </div>
      </div>
    </div>
  );
}
