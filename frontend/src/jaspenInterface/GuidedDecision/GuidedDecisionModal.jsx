import React, { useEffect } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faXmark } from '@fortawesome/free-solid-svg-icons';
import GuidedDecisionWizard from './GuidedDecisionWizard';
import './GuidedDecision.css';

// Overlay shell for the wizard. Handles backdrop, Escape, and scroll lock.
export default function GuidedDecisionModal({ open, onClose, onUse }) {
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
    <div className="gd-overlay" role="dialog" aria-modal="true" aria-label="Guided Decision">
      <div className="gd-backdrop" onClick={onClose} />
      <div className="gd-modal">
        <button
          type="button"
          className="gd-modal-close"
          onClick={onClose}
          aria-label="Close Guided Decision"
        >
          <FontAwesomeIcon icon={faXmark} />
        </button>
        <GuidedDecisionWizard onUse={onUse} onClose={onClose} />
      </div>
    </div>
  );
}
