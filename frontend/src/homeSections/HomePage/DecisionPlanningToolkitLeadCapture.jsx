import React, { useState } from 'react';
import { submitLead } from '../../shared/lead/leadClient';
import LeadsMockNotice from './LeadsMockNotice';
import './DecisionPlanningToolkitLeadCapture.css';

// Homepage lead magnet #2: the Jaspen Decision Planning Toolkit (an .xlsx).
//
// Positioning: this is the MANUAL planning companion to Jaspen, not a competitor
// or a lesser version. A workbook is great at helping someone organize their
// thinking (and gather input from a team); Jaspen is what challenges that
// thinking — it asks the questions a spreadsheet can't. The section answers a
// different visitor question than the Decision Style Assessment above it:
//   Assessment -> "How do I naturally make decisions?"
//   Toolkit    -> "How do I work through an important decision I'm facing now?"
//
// Distinct lead source ("decision-planning-toolkit") so it stays its own funnel
// under the backend's normalized email+source uniqueness. A capture failure must
// never block the download — the toolkit is the value the visitor was promised.
// (Note: any "upload into Jaspen" idea lives INSIDE the workbook, never here.)

const TOOLKIT_PATH = '/Jaspen-Decision-Planning-Toolkit.xlsx';
const TOOLKIT_FILENAME = 'Jaspen-Decision-Planning-Toolkit.xlsx';
const LEAD_SOURCE = 'decision-planning-toolkit';
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function startDownload() {
  const a = document.createElement('a');
  a.href = TOOLKIT_PATH;
  a.download = TOOLKIT_FILENAME;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

export default function DecisionPlanningToolkitLeadCapture() {
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
    <section className="dptl" id="get-the-decision-toolkit">
      <div className="dptl-inner">
        <div className="dptl-copy">
          <p className="dptl-eyebrow">Decision Planning Toolkit</p>
          <h2 className="dptl-heading">Have an important decision to work through?</h2>
          <p className="dptl-sub">
            A guided workbook for thinking one real decision all the way through — frame it, weigh
            what matters on a rubric that&apos;s yours to edit, and capture your options,
            assumptions, and reasoning in one place. Use it on your own, or share it with your team
            to gather everyone&apos;s input before you decide.
          </p>
          <ul className="dptl-list">
            <li>
              <i className="fa-solid fa-check dptl-check" aria-hidden="true" />
              A calm four-step flow: frame, weigh your options, pressure-test, decide
            </li>
            <li>
              <i className="fa-solid fa-check dptl-check" aria-hidden="true" />
              Your own editable rubric — set what matters and the weights; it does the math
            </li>
            <li>
              <i className="fa-solid fa-check dptl-check" aria-hidden="true" />
              A shareable, one-page Decision Summary that fills itself in
            </li>
            <li>
              <i className="fa-solid fa-check dptl-check" aria-hidden="true" />
              Works in Excel, Numbers, or Google Sheets
            </li>
          </ul>
          <p className="dptl-bridge">
            A workbook helps you organize your thinking. When you&apos;re ready to have it
            challenged, that&apos;s where Jaspen comes in.
          </p>
        </div>

        <div className="dptl-form-card">
          {status === 'done' ? (
            <div className="dptl-done" role="status">
              <i className="fa-solid fa-circle-check dptl-done-icon" aria-hidden="true" />
              <p className="dptl-done-title">Your toolkit is downloading.</p>
              <p className="dptl-done-note">
                If it doesn&apos;t start automatically,{' '}
                <a href={TOOLKIT_PATH} download={TOOLKIT_FILENAME}>
                  download it here
                </a>
                . Open the Welcome tab first — it walks you through the four steps.
              </p>
            </div>
          ) : (
            <form className="dptl-form" onSubmit={handleSubmit} noValidate>
              <LeadsMockNotice />
              <label className="dptl-label" htmlFor="dptl-email">
                Where should we send it?
              </label>
              <input
                id="dptl-email"
                type="email"
                className="dptl-input"
                placeholder="you@company.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                aria-invalid={!!error}
                aria-describedby={error ? 'dptl-error' : 'dptl-fine'}
              />
              {error && (
                <p className="dptl-error" id="dptl-error" role="alert">
                  {error}
                </p>
              )}
              <button type="submit" className="dptl-button" disabled={status === 'sending'}>
                {status === 'sending' ? 'Getting it ready…' : 'Email me the toolkit'}
              </button>
              <p className="dptl-fine" id="dptl-fine">
                We&apos;ll email you the toolkit and the occasional Jaspen update. Unsubscribe
                anytime.
              </p>
            </form>
          )}
        </div>
      </div>
    </section>
  );
}
