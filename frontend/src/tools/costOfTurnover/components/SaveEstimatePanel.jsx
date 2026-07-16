import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../../../shared/auth/AuthContext';
import { saveEstimate } from '../services/savedEstimate';
import { submitUtilityLead, UTILITY_SOURCE } from '../services/leadService';
import { analytics } from '../services/analytics';
import { formatCurrency } from '../engine/formatting';

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

// Optional "Save This Estimate" — never a gate. Full results are already shown.
// Authenticated users can save to their account; anonymous users can email a
// report (lead attribution) and/or create an account.
export default function SaveEstimatePanel({ getSnapshot, estimateSummary }) {
  const { isAuthenticated, authFetch, user } = useAuth();
  const [email, setEmail] = useState(user?.email || '');
  const [marketingOptIn, setMarketingOptIn] = useState(false);
  const [status, setStatus] = useState('idle'); // idle | sending | saved | error
  const [message, setMessage] = useState('');

  const handleAccountSave = async () => {
    analytics.saveCtaClicked();
    setStatus('sending');
    try {
      const res = await saveEstimate({ authFetch, isAuthenticated: true, snapshot: getSnapshot() });
      analytics.estimateSaved(res.mode);
      setStatus('saved');
      setMessage(
        res.mode === 'account'
          ? 'Saved to your account. You can revisit and adjust it any time.'
          : 'Saved in this browser. Full account sync will be available shortly.'
      );
    } catch (err) {
      analytics.error('save_account', err?.message);
      setStatus('error');
      setMessage('We could not save this estimate right now. Please try again.');
    }
  };

  const handleEmailReport = async (e) => {
    e.preventDefault();
    analytics.saveCtaClicked();
    const value = email.trim().toLowerCase();
    if (!EMAIL_RE.test(value)) {
      setStatus('error');
      setMessage('Please enter a valid email address.');
      return;
    }
    setStatus('sending');
    try {
      const res = await submitUtilityLead({ email: value, marketingOptIn, estimateSummary });
      if (!res || !res.ok) throw new Error('Report request was not accepted.');
      analytics.estimateSaved('email');
      setStatus('saved');
      setMessage('Your estimate is on its way. Check your inbox in the next few minutes.');
    } catch (err) {
      analytics.error('email_report', err?.message);
      setStatus('error');
      setMessage('We could not email your report right now. Your result is still here — try again in a moment.');
    }
  };

  return (
    <section className="cot-panel" aria-labelledby="cot-save-title">
      <h3 id="cot-save-title">Save this estimate</h3>
      {isAuthenticated ? (
        <>
          <p>
            Save this estimate to your Jaspen account to revisit it, update the assumptions, and
            compare multiple scenarios over time.
          </p>
          <button
            type="button"
            className="cot-btn cot-btn-primary"
            onClick={handleAccountSave}
            disabled={status === 'sending' || status === 'saved'}
          >
            {status === 'saved' ? 'Saved' : status === 'sending' ? 'Saving…' : 'Save to my account'}
          </button>
        </>
      ) : (
        <>
          <p>
            Want to keep this? Email yourself the full report, or create a free account to save it,
            revisit it later, and compare scenarios. Your results are already complete above — this
            is optional.
          </p>
          <form className="cot-form-row" onSubmit={handleEmailReport} noValidate>
            <input
              className="cot-input"
              type="email"
              placeholder="you@company.com"
              value={email}
              autoComplete="email"
              aria-label="Email address for your report"
              onChange={(e) => setEmail(e.target.value)}
            />
            <button
              type="submit"
              className="cot-btn cot-btn-primary"
              disabled={status === 'sending' || status === 'saved'}
            >
              {status === 'saved' ? 'Sent' : status === 'sending' ? 'Sending…' : 'Email my report'}
            </button>
          </form>
          <label className="cot-consent" style={{ marginTop: 14 }}>
            <input
              type="checkbox"
              checked={marketingOptIn}
              onChange={(e) => setMarketingOptIn(e.target.checked)}
            />
            <span>
              Also send me occasional Jaspen updates. Optional, and separate from your report — you
              can unsubscribe any time.
            </span>
          </label>
          <p className="cot-note" style={{ marginTop: 12 }}>
            Prefer an account?{' '}
            <Link
              className="cot-link"
              to={`/login?auth=signup&source=${UTILITY_SOURCE}`}
              onClick={() => analytics.saveCtaClicked()}
              style={{ display: 'inline' }}
            >
              Create a free Jaspen account
            </Link>{' '}
            to save and compare estimates.
          </p>
        </>
      )}
      {message ? (
        <p className={`cot-status ${status === 'error' ? 'cot-status-err' : 'cot-status-ok'}`} role="status">
          {message}
        </p>
      ) : null}
      {estimateSummary ? (
        <p className="cot-sr-only">
          Estimated total midpoint {formatCurrency(estimateSummary.total_mid)}.
        </p>
      ) : null}
    </section>
  );
}
