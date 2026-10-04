import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { Jaspen } from '../Workspace/JaspenClient';
import SharedArtifactView from './SharedArtifactView';
import './Sharing.css';

const EXPIRY_OPTIONS = [
  ['7', '7 days'],
  ['30', '30 days'],
  ['90', '90 days'],
  ['never', 'No expiration'],
];

const BLOCK_COPY = {
  paid_plan_required: 'Sharing is available on paid plans, starting with Starter.',
  sharing_disabled: 'Sharing has been turned off for this account. Contact support if you think this is a mistake.',
};

const formatDate = (iso) => {
  if (!iso) return '';
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
};

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (_error) {
    return false;
  }
}

function Included({ ok, children }) {
  return (
    <li className={`share-include ${ok ? 'is-in' : 'is-out'}`}>
      <span className="share-include__mark" aria-hidden="true">{ok ? '✓' : '—'}</span>
      <span>{children}</span>
    </li>
  );
}

// The distribution actions for one link: all three point at the same frozen copy.
function LinkActions({ link, title }) {
  const [copied, setCopied] = useState(false);
  const onCopy = async () => {
    if (await copyText(link.url)) {
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    }
  };
  const mailto = `mailto:?subject=${encodeURIComponent(`${title} (Jaspen)`)}&body=${encodeURIComponent(
    `Here is a read-only copy of "${title}":\n\n${link.url}\n`,
  )}`;
  return (
    <div className="share-link-actions">
      <button type="button" className="share-btn share-btn--primary" onClick={onCopy}>
        {copied ? 'Copied' : 'Copy link'}
      </button>
      <a className="share-btn" href={`${link.url}?print=1`} target="_blank" rel="noopener noreferrer">
        Download PDF
      </a>
      <a className="share-btn" href={mailto}>Email</a>
    </div>
  );
}

export default function ShareDialog({ open, onClose, threadId, artifactType, scorecardId = null, title = '' }) {
  const [expiry, setExpiry] = useState('30');
  const [includeEvidence, setIncludeEvidence] = useState(false);
  const [preview, setPreview] = useState(null);
  const [previewError, setPreviewError] = useState('');
  const [previewLoading, setPreviewLoading] = useState(false);
  const [links, setLinks] = useState([]);
  const [blockReason, setBlockReason] = useState(null);
  const [created, setCreated] = useState(null);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState('');
  const closeRef = useRef(null);

  const request = useMemo(() => ({
    artifact_type: artifactType,
    thread_id: threadId,
    ...(artifactType === 'scorecard' ? { scorecard_id: scorecardId } : {}),
    include_evidence: includeEvidence,
  }), [artifactType, threadId, scorecardId, includeEvidence]);

  const loadLinks = useCallback(async () => {
    try {
      const result = await Jaspen.listShares(threadId);
      setBlockReason(result?.block_reason || null);
      setLinks((result?.links || []).filter((link) => link.artifact_type === artifactType
        && (artifactType !== 'scorecard' || String(link.source_id) === String(scorecardId))));
    } catch (_error) {
      setLinks([]);
    }
  }, [threadId, artifactType, scorecardId]);

  useEffect(() => {
    if (!open) return undefined;
    setCreated(null);
    setError('');
    closeRef.current?.focus();
    void loadLinks();
    const onKey = (event) => { if (event.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, loadLinks, onClose]);

  // Rebuild the exact frozen copy whenever an option that changes it changes.
  useEffect(() => {
    if (!open || created || blockReason) return undefined;
    let cancelled = false;
    setPreviewLoading(true);
    setPreviewError('');
    Jaspen.previewShare(request)
      .then((result) => { if (!cancelled) setPreview(result); })
      .catch((previewErr) => {
        if (cancelled) return;
        const code = previewErr?.data?.code;
        if (BLOCK_COPY[code]) setBlockReason(code);
        setPreviewError(previewErr?.message || 'We could not build the preview.');
        setPreview(null);
      })
      .finally(() => { if (!cancelled) setPreviewLoading(false); });
    return () => { cancelled = true; };
  }, [open, request, created, blockReason]);

  const onCreate = async () => {
    setCreating(true);
    setError('');
    try {
      const result = await Jaspen.createShare({
        ...request,
        expires_in_days: expiry === 'never' ? 'never' : Number(expiry),
      });
      setCreated(result?.link || null);
      void loadLinks();
    } catch (createError) {
      setError(createError?.message || 'We could not create the link.');
    } finally {
      setCreating(false);
    }
  };

  const onRevoke = async (linkId) => {
    try {
      await Jaspen.revokeShare(linkId);
      if (created?.id === linkId) setCreated(null);
      await loadLinks();
    } catch (revokeError) {
      setError(revokeError?.message || 'We could not turn off that link.');
    }
  };

  if (!open) return null;

  const summary = preview?.summary;
  const quotes = summary?.evidence_quotes_available || 0;
  const activeLinks = links.filter((link) => link.status === 'active');
  const kind = artifactType === 'tradeoff' ? 'trade-off comparison' : 'scorecard';
  const shareTitle = preview?.title || title || (artifactType === 'tradeoff' ? 'Trade-off comparison' : 'Scorecard');

  return (
    <div className="share-modal-backdrop" role="presentation" onClick={onClose}>
      <div className="share-modal" role="dialog" aria-modal="true" aria-labelledby="share-title" onClick={(e) => e.stopPropagation()}>
        <div className="share-modal__head">
          <div>
            <h2 id="share-title">Share {kind}</h2>
            <p className="share-muted">{shareTitle}</p>
          </div>
          <button ref={closeRef} type="button" className="share-icon-btn" onClick={onClose} aria-label="Close">×</button>
        </div>

        {blockReason ? (
          <div className="share-modal__body">
            <p>{BLOCK_COPY[blockReason] || 'Sharing is not available for this account.'}</p>
            {blockReason === 'paid_plan_required' && (
              <div className="share-modal__foot">
                <a className="share-btn share-btn--primary" href="/pricing">See plans</a>
              </div>
            )}
          </div>
        ) : created ? (
          <div className="share-modal__body">
            <p className="share-success">Link created. Anyone with this link can view a read-only copy.</p>
            <input className="share-url" readOnly value={created.url} onFocus={(e) => e.target.select()} aria-label="Share link" />
            <LinkActions link={created} title={shareTitle} />
            <p className="share-muted">
              {created.expires_at ? `Works until ${formatDate(created.expires_at)}.` : 'Works until you turn it off.'}
              {' '}Changes you make later are not shown; share again to send an updated copy.
            </p>
            <div className="share-modal__foot">
              <button type="button" className="share-btn" onClick={() => onRevoke(created.id)}>Turn off link</button>
              <button type="button" className="share-btn share-btn--primary" onClick={onClose}>Done</button>
            </div>
          </div>
        ) : (
          <div className="share-modal__body share-modal__body--split">
            <div className="share-options">
              <label className="share-label" htmlFor="share-expiry">Link expires</label>
              <select id="share-expiry" className="share-select" value={expiry} onChange={(e) => setExpiry(e.target.value)}>
                {EXPIRY_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
              {expiry === 'never' && (
                <p className="share-warning">This link keeps working until you turn it off.</p>
              )}

              <h3 className="share-subhead">What viewers will see</h3>
              {summary ? (
                <ul className="share-includes">
                  <Included ok>Scores, criteria, and tiers{summary.scorecard_count > 1 ? ` for ${summary.scorecard_count} options` : ''}</Included>
                  <Included ok={summary.includes_rationale}>Rationale and summaries</Included>
                  <Included ok={summary.includes_risks}>Risks and considerations</Included>
                  <Included ok={summary.includes_financials}>Financial figures</Included>
                  <Included ok={summary.includes_assumptions}>Assumptions</Included>
                  <Included ok={summary.evidence_quotes_included}>
                    Evidence quotes from your conversation
                    {quotes ? ` (${quotes})` : ' (none on this ' + (artifactType === 'tradeoff' ? 'comparison' : 'scorecard') + ')'}
                  </Included>
                </ul>
              ) : (
                <p className="share-muted">{previewLoading ? 'Building preview…' : previewError}</p>
              )}

              <label className={`share-check ${quotes ? '' : 'is-disabled'}`}>
                <input
                  type="checkbox"
                  checked={includeEvidence}
                  disabled={!quotes}
                  onChange={(e) => setIncludeEvidence(e.target.checked)}
                />
                <span>
                  Include evidence quotes
                  <small>These are your own words from the conversation. Leave off unless the viewer should see them.</small>
                </span>
              </label>

              {summary && (
                <details className="share-never">
                  <summary>Never shared</summary>
                  <ul>{summary.excluded_always.map((item) => <li key={item}>{item}</li>)}</ul>
                </details>
              )}

              {error && <p className="share-error" role="alert">{error}</p>}
              <button
                type="button"
                className="share-btn share-btn--primary share-btn--block"
                onClick={onCreate}
                disabled={creating || !preview}
              >
                {creating ? 'Creating link…' : 'Create link'}
              </button>

              {activeLinks.length > 0 && (
                <div className="share-existing">
                  <h3 className="share-subhead">Active links</h3>
                  {activeLinks.map((link) => (
                    <div key={link.id} className="share-existing__row">
                      <div>
                        <div>{formatDate(link.created_at)} · {link.view_count} view{link.view_count === 1 ? '' : 's'}</div>
                        <div className="share-muted">
                          {link.expires_at ? `Until ${formatDate(link.expires_at)}` : 'No expiration'}
                          {link.include_evidence ? ' · includes evidence' : ''}
                        </div>
                      </div>
                      <div className="share-existing__actions">
                        <button type="button" className="share-link-btn" onClick={() => copyText(link.url)}>Copy</button>
                        <button type="button" className="share-link-btn is-danger" onClick={() => onRevoke(link.id)}>Turn off</button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="share-preview" aria-label="Preview of the shared page">
              <div className="share-preview__label">Preview · exactly what viewers will see</div>
              <div className="share-preview__frame">
                {preview ? (
                  <SharedArtifactView artifactType={preview.artifact_type} snapshot={preview.snapshot} />
                ) : (
                  <p className="share-muted share-preview__empty">{previewLoading ? 'Building preview…' : previewError}</p>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
