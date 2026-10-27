import React, { useCallback, useEffect, useRef, useState } from 'react';

import { Jaspen } from '../Workspace/JaspenClient';
import SharedArtifactView from './SharedArtifactView';
import './Sharing.css';

export default function DecisionShareDialog({ open, onClose, threadId, scorecardId = null }) {
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [shared, setShared] = useState(false);
  const closeRef = useRef(null);

  const loadPreview = useCallback((isCancelled = () => false) => {
    setPreview(null);
    setLoading(true);
    return Jaspen.previewDecisionShare({ thread_id: threadId, ...(scorecardId ? { scorecard_id: scorecardId } : {}) })
      .then((result) => { if (!isCancelled()) setPreview(result); })
      .catch((err) => { if (!isCancelled()) setError(err?.message || 'We could not build the preview.'); })
      .finally(() => { if (!isCancelled()) setLoading(false); });
  }, [scorecardId, threadId]);

  useEffect(() => {
    if (!open) return undefined;
    let cancelled = false;
    setError('');
    setShared(false);
    closeRef.current?.focus();
    loadPreview(() => cancelled);
    const onKey = (event) => { if (event.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => {
      cancelled = true;
      document.removeEventListener('keydown', onKey);
    };
  }, [open, onClose, loadPreview]);

  const onConfirm = async () => {
    if (!preview?.snapshot_sha256) return;
    setSharing(true);
    setError('');
    try {
      await Jaspen.createDecisionShare({
        thread_id: threadId,
        ...(scorecardId ? { scorecard_id: scorecardId } : {}),
        snapshot_sha256: preview.snapshot_sha256,
        preview_confirmed: true,
      });
      setShared(true);
    } catch (err) {
      setError(err?.message || 'We could not share this decision.');
      // The decision changed after the preview: show the current version so
      // the person confirms exactly what will be stored.
      if (err?.status === 409) await loadPreview();
    } finally {
      setSharing(false);
    }
  };

  if (!open) return null;
  return (
    <div className="share-modal-backdrop" role="presentation" onClick={onClose}>
      <div className="share-modal" role="dialog" aria-modal="true" aria-labelledby="decision-share-title" onClick={(event) => event.stopPropagation()}>
        <div className="share-modal__head">
          <div>
            <h2 id="decision-share-title">Share with Jaspen</h2>
            <p className="share-muted">The Jaspen team can see this copy; access is limited and logged, and you can withdraw it later.</p>
          </div>
          <button ref={closeRef} type="button" className="share-icon-btn" onClick={onClose} aria-label="Close">×</button>
        </div>
        <div className="share-modal__body">
          {shared ? (
            <p className="share-success">Decision shared with Jaspen.</p>
          ) : loading ? (
            <p className="share-muted">Building preview…</p>
          ) : preview ? (
            <div className="share-preview-frame">
              <SharedArtifactView artifactType={preview.artifact_type} snapshot={preview.snapshot} />
            </div>
          ) : null}
          {error && <p className="share-error" role="alert">{error}</p>}
          <div className="share-modal__foot">
            <button type="button" className="share-btn" onClick={onClose}>{shared ? 'Done' : 'Cancel'}</button>
            {!shared && (
              <button type="button" className="share-btn share-btn--primary" onClick={onConfirm} disabled={!preview || sharing}>
                {sharing ? 'Sharing…' : 'Confirm share'}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
