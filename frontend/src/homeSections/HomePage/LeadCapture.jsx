import React, { useState } from 'react';
import { API_BASE } from '../../config/apiBase';
import './LeadCapture.css';

// Lead magnet capture. FRONTEND ONLY for now: on submit it starts the instant
// download and makes a best-effort POST to LEADS_ENDPOINT. That endpoint is
// not built yet, so the POST is wrapped to fail silently and never block the
// download. When the backend lead route exists, storage + a delivery email
// happen there and nothing here needs to change except (optionally) removing
// the download-only fallback.
const LEADS_ENDPOINT = `${API_BASE}/api/v1/public/leads`;
const ASSET_PATH = '/Jaspen-Decision-Scorecard.xlsx';
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function startDownload() {
  const a = document.createElement('a');
  a.href = ASSET_PATH;
  a.download = 'Jaspen-Decision-Scorecard.xlsx';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

export default function LeadCapture() {
  const [email, setEmail] = useState('');
  const [status, setStatus] = useState('idle'); // idle | sending | done | error
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    const value = email.trim();
    if (!EMAIL_RE.test(value)) {
      setError('Please enter a valid email address.');
      return;
    }
    setError('');
    setStatus('sending');

    // Best-effort capture. Safe to fail until the backend route is wired.
    try {
      await fetch(LEADS_ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: value, source: 'decision-scorecard' }),
      });
    } catch {
      // Intentionally ignored: no backend yet. The download is the value.
    }

    startDownload();
    setStatus('done');
  };

  return (
    <section className="lead-capture" id="get-the-scorecard">
      <div className="lc-inner">
        <div className="lc-copy">
          <p className="lc-eyebrow">Free template</p>
          <h2 className="lc-heading">Get the Decision Scorecard</h2>
          <p className="lc-sub">
            Jaspen&apos;s exact scoring method as a one-page spreadsheet. Weight your criteria,
            grade your confidence, and get a score that holds up. Yours free, no strings.
          </p>
          <ul className="lc-list">
            <li><i className="fa-solid fa-check lc-check" aria-hidden="true" /> Confidence caps built in, so weak evidence cannot inflate the score</li>
            <li><i className="fa-solid fa-check lc-check" aria-hidden="true" /> Six default criteria you can reweight or replace with your own</li>
            <li><i className="fa-solid fa-check lc-check" aria-hidden="true" /> Works in Excel, Numbers, or Google Sheets</li>
          </ul>
        </div>

        <div className="lc-form-card">
          {status === 'done' ? (
            <div className="lc-done" role="status">
              <i className="fa-solid fa-circle-check lc-done-icon" aria-hidden="true" />
              <p className="lc-done-title">Your download is starting.</p>
              <p className="lc-done-note">
                If it does not begin automatically,{' '}
                <a href={ASSET_PATH} download>download it here</a>.
              </p>
            </div>
          ) : (
            <form className="lc-form" onSubmit={handleSubmit} noValidate>
              <label className="lc-label" htmlFor="lc-email">Your email</label>
              <input
                id="lc-email"
                type="email"
                className="lc-input"
                placeholder="you@company.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
              />
              <button type="submit" className="lc-button" disabled={status === 'sending'}>
                {status === 'sending' ? 'Getting it ready...' : 'Get the scorecard'}
              </button>
              {error && <p className="lc-error" role="alert">{error}</p>}
              <p className="lc-fine">
                Your download starts instantly. We may also send the occasional Jaspen
                update. Unsubscribe anytime.
              </p>
            </form>
          )}
        </div>
      </div>
    </section>
  );
}
