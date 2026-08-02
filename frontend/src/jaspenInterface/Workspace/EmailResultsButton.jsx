import React, { useCallback, useEffect, useRef, useState } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faEnvelope, faSpinner, faXmark } from '@fortawesome/free-solid-svg-icons';

import { Jaspen } from './JaspenClient';
import './EmailResultsButton.css';

const makeIdempotencyKey = () => {
  if (typeof window !== 'undefined' && window.crypto?.randomUUID) return window.crypto.randomUUID();
  return `email-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
};

const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

export default function EmailResultsButton({
  threadId,
  scorecardId = null,
  outputTypes = [],
  className = '',
  compact = false,
}) {
  const [open, setOpen] = useState(false);
  const [recipient, setRecipient] = useState('');
  const [phase, setPhase] = useState('confirm');
  const [error, setError] = useState('');
  const idempotencyKeyRef = useRef(null);
  const closeButtonRef = useRef(null);
  const mountedRef = useRef(true);

  useEffect(() => () => { mountedRef.current = false; }, []);

  useEffect(() => {
    if (!open) return undefined;
    closeButtonRef.current?.focus();
    const onKeyDown = (event) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [open, phase]);

  const openConfirmation = useCallback(async () => {
    if (!threadId) return;
    setOpen(true);
    setPhase('preparing');
    setError('');
    try {
      const result = await Jaspen.getEmailAssetRecipient();
      if (!mountedRef.current) return;
      setRecipient(result?.recipient_masked || 'your verified email');
      setPhase('confirm');
    } catch (requestError) {
      if (!mountedRef.current) return;
      setError(requestError?.message || 'We could not confirm your verified email.');
      setPhase('failed');
    }
  }, [threadId]);

  const pollDelivery = useCallback(async (deliveryId) => {
    for (let attempt = 0; attempt < 75; attempt += 1) {
      await sleep(800);
      if (!mountedRef.current) return;
      const result = await Jaspen.getEmailAssetStatus(deliveryId);
      if (!mountedRef.current) return;
      setRecipient(result?.recipient_masked || recipient);
      setPhase(result?.status || 'sending');
      if (result?.status === 'sent') return;
      if (result?.status === 'failed') {
        setError('We could not send these results. Your evaluation is safe and you can retry.');
        return;
      }
    }
    if (mountedRef.current) {
      setPhase('failed');
      setError('Sending is taking longer than expected. Your evaluation is safe and you can retry.');
    }
  }, [recipient]);

  const send = useCallback(async () => {
    setPhase('preparing');
    setError('');
    if (!idempotencyKeyRef.current) idempotencyKeyRef.current = makeIdempotencyKey();
    try {
      const result = await Jaspen.requestEmailAssets(threadId, {
        scorecardId,
        outputTypes,
        idempotencyKey: idempotencyKeyRef.current,
      });
      if (!mountedRef.current) return;
      setRecipient(result?.recipient_masked || recipient);
      setPhase(result?.status || 'preparing');
      if (result?.status === 'sent') return;
      await pollDelivery(result?.delivery_id);
    } catch (requestError) {
      if (!mountedRef.current) return;
      setPhase('failed');
      setError(requestError?.message || 'We could not send these results. Your evaluation is safe and you can retry.');
    }
  }, [outputTypes, pollDelivery, recipient, scorecardId, threadId]);

  const close = () => {
    setOpen(false);
    if (phase === 'sent') idempotencyKeyRef.current = null;
  };

  const busy = phase === 'preparing' || phase === 'sending';
  return (
    <>
      <button
        type="button"
        className={`jas-email-results-trigger ${compact ? 'is-compact' : ''} ${className}`.trim()}
        onClick={openConfirmation}
        disabled={!threadId}
      >
        <FontAwesomeIcon icon={faEnvelope} aria-hidden="true" />
        Email this to me
      </button>
      {open && (
        <div className="jas-email-results-backdrop" role="presentation" onMouseDown={(event) => {
          if (event.target === event.currentTarget) close();
        }}>
          <section
            className="jas-email-results-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="jas-email-results-title"
            aria-describedby="jas-email-results-message"
          >
            <button
              ref={closeButtonRef}
              type="button"
              className="jas-email-results-close"
              aria-label="Close"
              onClick={close}
            >
              <FontAwesomeIcon icon={faXmark} />
            </button>
            <div className="jas-email-results-icon"><FontAwesomeIcon icon={busy ? faSpinner : faEnvelope} spin={busy} /></div>
            <h2 id="jas-email-results-title">Email these results</h2>
            <div id="jas-email-results-message" aria-live="polite">
              {phase === 'confirm' && <p>Send these results to <strong>{recipient}</strong>?</p>}
              {phase === 'preparing' && <p>Preparing your results and downloadable files…</p>}
              {phase === 'sending' && <p>Sending to <strong>{recipient}</strong>…</p>}
              {phase === 'sent' && <p>Sent to <strong>{recipient}</strong>.</p>}
              {phase === 'failed' && <p className="jas-email-results-error">{error}</p>}
            </div>
            <div className="jas-email-results-actions">
              {phase === 'confirm' && (
                <>
                  <button type="button" className="secondary" onClick={close}>Cancel</button>
                  <button type="button" className="primary" onClick={send}>Send results</button>
                </>
              )}
              {busy && <button type="button" className="primary" disabled><FontAwesomeIcon icon={faSpinner} spin /> Working…</button>}
              {phase === 'sent' && <button type="button" className="primary" onClick={close}>Done</button>}
              {phase === 'failed' && (
                <>
                  <button type="button" className="secondary" onClick={close}>Close</button>
                  {recipient && <button type="button" className="primary" onClick={send}>Retry safely</button>}
                </>
              )}
            </div>
          </section>
        </div>
      )}
    </>
  );
}
