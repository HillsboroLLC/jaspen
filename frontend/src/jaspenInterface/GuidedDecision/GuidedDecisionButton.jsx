import React from 'react';

// Sparkles glyph (standalone "sparkles" is Font Awesome Pro-only, so we use a
// crisp inline SVG to match the requested look with the free icon set).
function SparklesIcon() {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M12 2.5l1.6 4.3a4 4 0 0 0 2.36 2.36L20.26 10.75l-4.3 1.6a4 4 0 0 0-2.36 2.36L12 19l-1.6-4.3a4 4 0 0 0-2.36-2.36L3.74 10.75l4.3-1.6a4 4 0 0 0 2.36-2.36L12 2.5z" />
      <path d="M18.5 14.5l.7 1.9a1.8 1.8 0 0 0 1.05 1.05l1.9.7-1.9.7a1.8 1.8 0 0 0-1.05 1.05l-.7 1.9-.7-1.9a1.8 1.8 0 0 0-1.05-1.05l-1.9-.7 1.9-.7a1.8 1.8 0 0 0 1.05-1.05l.7-1.9z" opacity="0.7" />
    </svg>
  );
}

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
      <SparklesIcon />
    </button>
  );
}
