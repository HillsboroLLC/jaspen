import React, { useState } from 'react';
import { submitLead } from '../../shared/lead/leadClient';
import LeadsMockNotice from './LeadsMockNotice';
import './DecisionPlanningToolkitLeadCapture.css';

// Homepage lead magnet #2: the Jaspen Decision Planning Toolkit (an .xlsx).
//
// Positioning: this is the MANUAL planning companion to Jaspen, not a competitor
// or a lesser version. A workbook is great at helping someone organize their
// thinking (and gather input from a team); Jaspen is what challenges that
// thinking; it asks the questions a spreadsheet can't. The section answers a
// different visitor question than the Decision Style Assessment above it:
//   Assessment -> "How do I naturally make decisions?"
//   Toolkit    -> "How do I work through an important decision I'm facing now?"
//
// Distinct lead source ("decision-planning-toolkit") so the backend can record
// the source event while keeping one canonical contact per normalized email.
// The backend emails the toolkit; this component never exposes a direct public
// file link or downloads on a failed capture.
// (Note: any "upload into Jaspen" idea lives INSIDE the workbook, never here.)

const LEAD_SOURCE = 'decision-planning-toolkit';
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default function DecisionPlanningToolkitLeadCapture() {
  const [email, setEmail] = useState('');
  const [marketingOptIn, setMarketingOptIn] = useState(false);
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

    try {
      const res = await submitLead({ email: value, source: LEAD_SOURCE, marketingOptIn });
      if (!res?.ok) {
        throw new Error('delivery_failed');
      }
      setStatus('done');
    } catch {
      setStatus('idle');
      setError('We could not email the toolkit right now. Please try again in a moment.');
    }
  };

  return (
    <section className="dptl" id="get-the-decision-toolkit">
      <div className="dptl-inner">
        <div className="dptl-copy">
          <p className="dptl-eyebrow">Decision Planning Toolkit</p>
          <h2 className="dptl-heading">Have an important decision to work through?</h2>
          <p className="dptl-sub">
            A guided workbook for thinking one real decision all the way through: frame it, weigh
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
              Your own editable rubric that sets what matters and the weights, then does the math
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
              <p className="dptl-done-title">Your toolkit is on its way.</p>
              <p className="dptl-done-note">
                Check your inbox for the secure download link. Open the Welcome tab first. It
                walks you through the four steps.
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
              <label className="dptl-checkbox">
                <input
                  type="checkbox"
                  checked={marketingOptIn}
                  onChange={(e) => setMarketingOptIn(e.target.checked)}
                />
                <span>Send me Decision Notes and occasional Jaspen updates.</span>
              </label>
              {error && (
                <p className="dptl-error" id="dptl-error" role="alert">
                  {error}
                </p>
              )}
              <button type="submit" className="dptl-button" disabled={status === 'sending'}>
                {status === 'sending' ? 'Sending…' : 'Email me the toolkit'}
              </button>
              <p className="dptl-fine" id="dptl-fine">
                We&apos;ll email the toolkit to this address. Updates are optional and you can
                unsubscribe anytime.
              </p>
            </form>
          )}
        </div>
      </div>
    </section>
  );
}
