import React, { useState } from 'react';
import { submitLead } from '../../shared/lead/leadClient';
import LeadsMockNotice from './LeadsMockNotice';
import './DecisionWorkbookLeadCapture.css';

// Homepage lead magnet #2: the Jaspen Decision Workbook (an .xlsx template).
//
// This is a deliberately reviewed rewrite of the old scorecard LeadCapture — not
// a stale restore. It serves a DIFFERENT visitor need than the Decision Style
// Assessment: this is for someone who has a specific decision to make right now
// and wants a practical framework to organize it. Distinct lead source
// ("decision-workbook") so it stays separate from the assessment funnel in the
// backend's normalized email+source uniqueness model.
//
// Behavior: validate the email, kick off the file download immediately, and make
// a best-effort lead submission. A capture failure must NEVER block the download
// — the workbook is the value the visitor was promised.

const WORKBOOK_PATH = '/Jaspen-Decision-Workbook.xlsx';
const WORKBOOK_FILENAME = 'Jaspen-Decision-Workbook.xlsx';
const LEAD_SOURCE = 'decision-workbook';
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function startDownload() {
  const a = document.createElement('a');
  a.href = WORKBOOK_PATH;
  a.download = WORKBOOK_FILENAME;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

export default function DecisionWorkbookLeadCapture() {
  const [email, setEmail] = useState('');
  const [status, setStatus] = useState('idle'); // idle | sending | done
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

    // Best-effort capture — never blocks the download.
    try {
      await submitLead({ email: value, source: LEAD_SOURCE });
    } catch {
      /* Intentionally ignored: the download is the promised value. */
    }

    startDownload();
    setStatus('done');
  };

  return (
    <section className="dwlc" id="get-the-decision-workbook">
      <div className="dwlc-inner">
        <div className="dwlc-copy">
          <p className="dwlc-eyebrow">Free workbook</p>
          <h2 className="dwlc-heading">Have an important decision to make?</h2>
          <p className="dwlc-sub">
            The Jaspen Decision Workbook is a clean, guided template for working through one real
            decision — frame the problem, weigh your options, and capture the reasoning you&apos;ll
            want to reread later. A practical framework you can use right now.
          </p>
          <ul className="dwlc-list">
            <li>
              <i className="fa-solid fa-check dwlc-check" aria-hidden="true" />
              A guided four-step flow: frame, compare, pressure-test, decide
            </li>
            <li>
              <i className="fa-solid fa-check dwlc-check" aria-hidden="true" />
              Weight what matters and score your options — the workbook does the math
            </li>
            <li>
              <i className="fa-solid fa-check dwlc-check" aria-hidden="true" />
              A clean, shareable Decision Summary that fills itself in
            </li>
            <li>
              <i className="fa-solid fa-check dwlc-check" aria-hidden="true" />
              Works in Excel, Numbers, or Google Sheets
            </li>
          </ul>
        </div>

        <div className="dwlc-form-card">
          {status === 'done' ? (
            <div className="dwlc-done" role="status">
              <i className="fa-solid fa-circle-check dwlc-done-icon" aria-hidden="true" />
              <p className="dwlc-done-title">Your workbook is downloading.</p>
              <p className="dwlc-done-note">
                If it doesn&apos;t start automatically,{' '}
                <a href={WORKBOOK_PATH} download={WORKBOOK_FILENAME}>
                  download it here
                </a>
                . Open the Welcome tab first — it walks you through the four steps.
              </p>
            </div>
          ) : (
            <form className="dwlc-form" onSubmit={handleSubmit} noValidate>
              <LeadsMockNotice />
              <label className="dwlc-label" htmlFor="dwlc-email">
                Your email
              </label>
              <input
                id="dwlc-email"
                type="email"
                className="dwlc-input"
                placeholder="you@company.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                aria-invalid={!!error}
                aria-describedby={error ? 'dwlc-error' : 'dwlc-fine'}
              />
              {error && (
                <p className="dwlc-error" id="dwlc-error" role="alert">
                  {error}
                </p>
              )}
              <button type="submit" className="dwlc-button" disabled={status === 'sending'}>
                {status === 'sending' ? 'Getting it ready…' : 'Email me the Decision Workbook'}
              </button>
              <p className="dwlc-fine" id="dwlc-fine">
                Your download starts instantly. We may also send the occasional Jaspen update.
                Unsubscribe anytime.
              </p>
            </form>
          )}
        </div>
      </div>
    </section>
  );
}
