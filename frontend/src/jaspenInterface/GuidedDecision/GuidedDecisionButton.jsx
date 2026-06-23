import React from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faCompass } from '@fortawesome/free-solid-svg-icons';

// Persistent top-nav entry point. Subtle by default, accent on hover/focus.
export default function GuidedDecisionButton({ onClick }) {
  return (
    <button
      type="button"
      className="gd-nav-btn"
      onClick={onClick}
      title="Guided Decision"
      aria-label="Open Guided Decision"
    >
      <FontAwesomeIcon icon={faCompass} />
    </button>
  );
}
