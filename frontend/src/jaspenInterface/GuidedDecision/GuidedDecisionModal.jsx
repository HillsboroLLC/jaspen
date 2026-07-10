import React, { useEffect, useState } from 'react';
import GuidedDecisionWizard from './GuidedDecisionWizard';
import * as S from './guidedDecisionStyles';
import './GuidedDecision.css';

// Overlay shell for the wizard. Handles backdrop, Escape, and scroll lock.
// Critical container styles are inlined so the app's global CSS can't break
// the modal layout.
export default function GuidedDecisionModal({ open, onClose, onUse }) {
  const [hoverClose, setHoverClose] = useState(false);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div style={S.overlay} role="dialog" aria-modal="true" aria-label="Guided Decision">
      <div style={S.backdrop} onClick={onClose} />
      <div style={S.wizardCard} className="gd-modal-card">
        <button
          type="button"
          style={{ ...S.closeBtn, background: hoverClose ? 'rgba(26,29,36,0.07)' : 'transparent' }}
          onMouseEnter={() => setHoverClose(true)}
          onMouseLeave={() => setHoverClose(false)}
          onClick={onClose}
          aria-label="Close Guided Decision"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true">
            <path d="M6 6l12 12M18 6L6 18" />
          </svg>
        </button>
        <GuidedDecisionWizard onUse={onUse} onClose={onClose} />
      </div>
    </div>
  );
}
