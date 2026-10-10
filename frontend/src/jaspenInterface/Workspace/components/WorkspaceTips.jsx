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

export default function WorkspaceTips({ tips = [] }) {
  const [visible, setVisible] = useState(() => tips.length > 0 && !tipsWereDismissed(tips.length));

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

  return (
    <aside className="jas-floattip" aria-label="Workspace tips">
      <button className="jas-floattip-close" onClick={closeTips} aria-label="Close tips">×</button>
      <p className="jas-floattip-heading">Tips</p>
      <div className="jas-floattip-list" tabIndex="0" aria-label="All workspace tips">
        {tips.map((tip) => (
          <section className="jas-floattip-item" key={tip.id}>
            <p className="jas-floattip-title">{tip.title}</p>
            <p className="jas-floattip-body">{tip.body}</p>
          </section>
        ))}
      </div>
    </aside>
  );
}
