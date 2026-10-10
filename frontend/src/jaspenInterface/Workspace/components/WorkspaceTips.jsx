import React, { useState } from 'react';

const DISMISSED_KEY = 'jaspen_tips_dismissed';
const LEGACY_INDEX_KEY = 'jaspen_tip_idx';

const tipsWereDismissed = (tipCount) => {
  try {
    if (localStorage.getItem(DISMISSED_KEY) === 'true') return true;
    const legacyIndex = parseInt(localStorage.getItem(LEGACY_INDEX_KEY) || '0', 10);
    return Number.isFinite(legacyIndex) && legacyIndex >= tipCount;
  } catch {
    return false;
  }
};

// One tip at a time. Back/Next step through the tips only when the user
// wants to; the × closes the whole carousel from any tip, for good.
export default function WorkspaceTips({ tips = [] }) {
  const [visible, setVisible] = useState(() => tips.length > 0 && !tipsWereDismissed(tips.length));
  const [index, setIndex] = useState(0);

  const closeTips = () => {
    try {
      localStorage.setItem(DISMISSED_KEY, 'true');
      // Preserve compatibility with clients that still read the old carousel index.
      localStorage.setItem(LEGACY_INDEX_KEY, String(tips.length));
    } catch {
      // Closing the surface must still work when browser storage is unavailable.
    }
    setVisible(false);
  };

  if (!visible) return null;

  const tip = tips[index];
  const last = tips.length - 1;

  return (
    <aside className="jas-floattip" aria-label="Workspace tips">
      <button className="jas-floattip-close" onClick={closeTips} aria-label="Close tips">×</button>
      <p className="jas-floattip-heading">Tip {index + 1} of {tips.length}</p>
      <div className="jas-floattip-item" aria-live="polite">
        <p className="jas-floattip-title">{tip.title}</p>
        <p className="jas-floattip-body">{tip.body}</p>
      </div>
      {tips.length > 1 && (
        <div className="jas-floattip-nav">
          <button
            type="button"
            className="jas-floattip-step"
            onClick={() => setIndex((i) => Math.max(0, i - 1))}
            disabled={index === 0}
            aria-label="Previous tip"
          >
            ‹
          </button>
          <div className="jas-floattip-dots">
            {tips.map((t, i) => (
              <button
                type="button"
                key={t.id}
                className={`jas-floattip-dot${i === index ? ' active' : ''}`}
                onClick={() => setIndex(i)}
                aria-label={`Show tip ${i + 1}`}
                aria-current={i === index ? 'true' : undefined}
              />
            ))}
          </div>
          <button
            type="button"
            className="jas-floattip-step"
            onClick={() => setIndex((i) => Math.min(last, i + 1))}
            disabled={index === last}
            aria-label="Next tip"
          >
            ›
          </button>
        </div>
      )}
    </aside>
  );
}
