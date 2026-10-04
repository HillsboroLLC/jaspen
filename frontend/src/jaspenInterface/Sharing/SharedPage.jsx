import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation, useParams } from 'react-router-dom';

import { API_BASE } from '../../config/apiBase';
import SharedArtifactView from './SharedArtifactView';
import './Sharing.css';

const REPORT_REASONS = [
  ['spam', 'Spam or advertising'],
  ['abusive', 'Abusive or hateful content'],
  ['private_information', "Someone's private information"],
  ['misleading', 'Misleading or fraudulent'],
  ['other', 'Something else'],
];

const formatDate = (iso) => {
  if (!iso) return '';
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? ''
    : date.toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' });
};

// Search engines must never index shared decisions. The API and Vercel send
// X-Robots-Tag too; the meta tag covers crawlers that only read the page.
function useNoIndex() {
  useEffect(() => {
    const meta = document.createElement('meta');
    meta.name = 'robots';
    meta.content = 'noindex, nofollow, noarchive';
    document.head.appendChild(meta);
    return () => { document.head.removeChild(meta); };
  }, []);
}

function ReportDialog({ token, onClose }) {
  const [reason, setReason] = useState('');
  const [details, setDetails] = useState('');
  const [phase, setPhase] = useState('form');
  const [error, setError] = useState('');

  const submit = async (event) => {
    event.preventDefault();
    if (!reason) {
      setError('Choose a reason.');
      return;
    }
    setPhase('sending');
    setError('');
    try {
      const response = await fetch(`${API_BASE}/api/v1/shares/public/${encodeURIComponent(token)}/report`, {
        method: 'POST',
        credentials: 'omit',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason, details }),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data?.error || 'We could not send your report. Try again later.');
      }
      setPhase('sent');
    } catch (reportError) {
      setError(reportError.message);
      setPhase('form');
    }
  };

  return (
    <div className="share-modal-backdrop" role="presentation" onClick={onClose}>
      <div className="share-modal share-modal--narrow" role="dialog" aria-modal="true" aria-labelledby="report-title" onClick={(e) => e.stopPropagation()}>
        <div className="share-modal__head">
          <h2 id="report-title">Report this page</h2>
          <button type="button" className="share-icon-btn" onClick={onClose} aria-label="Close">×</button>
        </div>
        {phase === 'sent' ? (
          <div className="share-modal__body">
            <p>Thanks. Our team will review this page.</p>
            <div className="share-modal__foot">
              <button type="button" className="share-btn share-btn--primary" onClick={onClose}>Done</button>
            </div>
          </div>
        ) : (
          <form className="share-modal__body" onSubmit={submit}>
            <fieldset className="share-fieldset">
              <legend>What's wrong with it?</legend>
              {REPORT_REASONS.map(([value, label]) => (
                <label key={value} className="share-radio">
                  <input type="radio" name="reason" value={value} checked={reason === value} onChange={() => setReason(value)} />
                  {label}
                </label>
              ))}
            </fieldset>
            <label className="share-label" htmlFor="report-details">Details (optional)</label>
            <textarea
              id="report-details"
              className="share-textarea"
              maxLength={2000}
              rows={4}
              value={details}
              onChange={(e) => setDetails(e.target.value)}
            />
            {error && <p className="share-error" role="alert">{error}</p>}
            <div className="share-modal__foot">
              <button type="button" className="share-btn" onClick={onClose}>Cancel</button>
              <button type="submit" className="share-btn share-btn--primary" disabled={phase === 'sending'}>
                {phase === 'sending' ? 'Sending…' : 'Send report'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

export default function SharedPage() {
  const { token } = useParams();
  const location = useLocation();
  const [state, setState] = useState({ phase: 'loading', data: null });
  const [reportOpen, setReportOpen] = useState(false);
  const printedRef = useRef(false);
  useNoIndex();

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const response = await fetch(`${API_BASE}/api/v1/shares/public/${encodeURIComponent(token || '')}`, {
          credentials: 'omit',
        });
        if (response.status === 429) {
          if (!cancelled) setState({ phase: 'busy', data: null });
          return;
        }
        if (!response.ok) {
          if (!cancelled) setState({ phase: 'unavailable', data: null });
          return;
        }
        const data = await response.json();
        if (!cancelled) setState({ phase: 'ready', data });
      } catch (_error) {
        if (!cancelled) setState({ phase: 'error', data: null });
      }
    })();
    return () => { cancelled = true; };
  }, [token]);

  const data = state.data;

  useEffect(() => {
    if (data?.title) document.title = `${data.title} · Shared via Jaspen`;
  }, [data]);

  const downloadPdf = useCallback(() => window.print(), []);

  // "Download PDF" from the share dialog opens this page with ?print=1.
  useEffect(() => {
    if (state.phase !== 'ready' || printedRef.current) return undefined;
    if (!new URLSearchParams(location.search).has('print')) return undefined;
    printedRef.current = true;
    const timer = setTimeout(() => window.print(), 600);
    return () => clearTimeout(timer);
  }, [state.phase, location.search]);

  if (state.phase !== 'ready') {
    const messages = {
      loading: 'Loading…',
      unavailable: 'This link is no longer available. It may have expired or been turned off by its owner.',
      busy: 'This page is getting a lot of requests. Please try again in a minute.',
      error: 'We could not load this page. Check your connection and try again.',
    };
    return (
      <div className="shared-page shared-page--empty">
        <div className="shared-page__notice" role={state.phase === 'loading' ? 'status' : 'alert'}>
          <a className="shared-page__brand" href="https://jaspen.ai">Jaspen</a>
          <p>{messages[state.phase]}</p>
        </div>
      </div>
    );
  }

  const kindLabel = data.artifact_type === 'tradeoff' ? 'Trade-off comparison' : 'Scorecard';
  return (
    <div className="shared-page">
      <header className="shared-page__header">
        <div className="shared-page__heading">
          <a className="shared-page__brand" href="https://jaspen.ai">Jaspen</a>
          <div className="shared-page__kicker">{kindLabel} · shared {formatDate(data.created_at)}</div>
          <h1 className="shared-page__title">{data.title}</h1>
          <div className="shared-page__meta">
            Read-only copy{data.expires_at ? ` · available until ${formatDate(data.expires_at)}` : ''}
          </div>
        </div>
        <div className="shared-page__actions">
          <button type="button" className="share-btn share-btn--primary" onClick={downloadPdf}>
            Download PDF
          </button>
        </div>
      </header>

      <main className="shared-page__body">
        <SharedArtifactView artifactType={data.artifact_type} snapshot={data.snapshot} />
      </main>

      <footer className="shared-page__footer">
        <a href="https://jaspen.ai" className="shared-page__made-with">Made with Jaspen</a>
        <span className="shared-page__footer-note">
          Scores reflect the information available when this was shared. AI can make mistakes.
        </span>
        <button type="button" className="shared-page__report" onClick={() => setReportOpen(true)}>
          Report this page
        </button>
      </footer>

      {reportOpen && <ReportDialog token={token} onClose={() => setReportOpen(false)} />}
    </div>
  );
}
