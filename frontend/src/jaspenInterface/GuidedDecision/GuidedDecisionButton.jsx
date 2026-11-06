import React from 'react';

// Lightbulb glyph, drawn in the same filled style as the title-bar sparkles,
// with the same small sparkle accent. Inline SVG, solid fill only.
function LightbulbIcon() {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M10.5 3a6 6 0 0 0-3.5 10.87V16a1 1 0 0 0 1 1h5a1 1 0 0 0 1-1v-2.13A6 6 0 0 0 10.5 3z" />
      <rect x="8" y="18.25" width="5" height="1.6" rx="0.8" />
      <rect x="8.75" y="20.75" width="3.5" height="1.5" rx="0.75" />
      <path d="M19.5 1.5l.6 1.6a1.5 1.5 0 0 0 .9.9l1.6.6-1.6.6a1.5 1.5 0 0 0-.9.9l-.6 1.6-.6-1.6a1.5 1.5 0 0 0-.9-.9l-1.6-.6 1.6-.6a1.5 1.5 0 0 0 .9-.9l.6-1.6z" opacity="0.7" />
    </svg>
  );
}

// Persistent top-nav entry point — lightbulb icon only.
export default function GuidedDecisionButton({ onClick }) {
  return (
    <button
      type="button"
      className="gd-nav-icon"
      onClick={onClick}
      title="Guided Decision"
      aria-label="Open Guided Decision"
    >
      <LightbulbIcon />
    </button>
  );
}
