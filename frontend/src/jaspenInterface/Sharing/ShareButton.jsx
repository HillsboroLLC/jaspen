import React, { useCallback, useState } from 'react';

import ShareDialog from './ShareDialog';
import DecisionShareDialog from './DecisionShareDialog';
import './Sharing.css';

// Self-contained "Share" action: owns its dialog so it can sit inside render
// helpers that cannot hold state (e.g. the inline chat scorecard).
export default function ShareButton({
  threadId,
  artifactType = 'scorecard',
  scorecardId = null,
  title = '',
  className = 'share-btn',
  label = 'Share',
}) {
  const [open, setOpen] = useState(false);
  const [jaspenOpen, setJaspenOpen] = useState(false);
  const onClose = useCallback(() => setOpen(false), []);
  const onJaspenClose = useCallback(() => setJaspenOpen(false), []);
  if (!threadId) return null;
  return (
    <>
      <button
        type="button"
        className={`${className} share-trigger`}
        onClick={(event) => { event.stopPropagation(); setOpen(true); }}
        title={artifactType === 'tradeoff' ? 'Share this trade-off comparison' : 'Share this scorecard'}
      >
        {label}
      </button>
      <button
        type="button"
        className={`${className} share-trigger`}
        onClick={(event) => { event.stopPropagation(); setJaspenOpen(true); }}
        title="Share this decision with the Jaspen team"
      >
        Share with Jaspen
      </button>
      {open && (
        <ShareDialog
          open={open}
          onClose={onClose}
          threadId={threadId}
          artifactType={artifactType}
          scorecardId={scorecardId}
          title={title}
        />
      )}
      {jaspenOpen && (
        <DecisionShareDialog
          open={jaspenOpen}
          onClose={onJaspenClose}
          threadId={threadId}
          scorecardId={scorecardId}
        />
      )}
    </>
  );
}
