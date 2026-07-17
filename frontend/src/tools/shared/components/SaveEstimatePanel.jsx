import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../../../shared/auth/AuthContext';
import { submitLead } from '../../../shared/lead/leadClient';
import { saveEstimate } from '../savedEstimate';

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

// Optional "Save this calculation" — never a gate. Full results already shown.
// Authenticated users save to their account; anonymous users can email a copy
// (lead attribution) and/or create an account to save, compare, and track.
export default function SaveEstimatePanel({ utilityType, source, getSnapshot, estimateSummary, analytics }) {
  const { isAuthenticated, authFetch, user } = useAuth();
  const [email, setEmail] = useState(user?.email || '');
  const [marketingOptIn, setMarketingOptIn] = useState(false);
  const [status, setStatus] = useState('idle');
  const [message, setMessage] = useState('');

  const handleAccountSave = async () => {
    analytics.saveCtaClicked();
    setStatus('sending');
    try {
      const res = await saveEstimate({ authFetch, isAuthenticated: true, utilityType, snapshot: getSnapshot() });
      analytics.estimateSaved(res.mode);
      setStatus('saved');
      setMessage(
        res.mode === 'account'
          ? 'Saved to your account. Revisit it, compare scenarios, and track changes any time.'
          : 'Saved in this browser. Full account sync will be available shortly.'
      );
    } catch (err) {
      analytics.error('save_account', err?.message);
      setStatus('error');
      setMessage('We could not save this right now. Please try again.');
    }
  };

  const handleEmail = async (e) => {
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
      const res = await submitLead({ email: value, source, marketingOptIn, assessmentAnswers: estimateSummary });
      if (!res || !res.ok) throw new Error('Request was not accepted.');
      analytics.estimateSaved('email');
      setStatus('saved');
      setMessage('Your calculation is on its way. Check your inbox in the next few minutes.');
    } catch (err) {
      analytics.error('email_copy', err?.message);
      setStatus('error');
      setMessage('We could not email it right now. Your result is still here — try again in a moment.');
    }
  };

  return (
    <section className="tool-panel" aria-labelledby="tool-save-title">
      <h3 id="tool-save-title">Save this calculation</h3>
      {isAuthenticated ? (
        <>
          <p>
            Save this to your Jaspen account to revisit it, compare multiple scenarios, and build a
            history of calculations over time.
          </p>
          <button
            type="button"
            className="tool-btn tool-btn-primary"
            onClick={handleAccountSave}
            disabled={status === 'sending' || status === 'saved'}
          >
            {status === 'saved' ? 'Saved' : status === 'sending' ? 'Saving…' : 'Save to my account'}
          </button>
        </>
      ) : (
        <>
          <p>
            Want to keep this? Email yourself a copy, or create a free account to save it, compare
            scenarios later, and build a history. Your full results are already above — this is
            optional.
          </p>
          <form className="tool-form-row" onSubmit={handleEmail} noValidate>
            <input
              className="tool-input"
              type="email"
              placeholder="you@email.com"
              value={email}
              autoComplete="email"
              aria-label="Email address to send your calculation"
              onChange={(e) => setEmail(e.target.value)}
            />
            <button
              type="submit"
              className="tool-btn tool-btn-primary"
              disabled={status === 'sending' || status === 'saved'}
            >
              {status === 'saved' ? 'Sent' : status === 'sending' ? 'Sending…' : 'Email my copy'}
            </button>
          </form>
          <label className="tool-consent" style={{ marginTop: 14 }}>
            <input type="checkbox" checked={marketingOptIn} onChange={(e) => setMarketingOptIn(e.target.checked)} />
            <span>
              Also send me occasional Jaspen updates. Optional, separate from your copy, and you can
              unsubscribe any time.
            </span>
          </label>
          <p className="tool-insights-note" style={{ marginTop: 12, borderTop: 0, paddingTop: 0 }}>
            Prefer an account?{' '}
            <Link className="tool-link" to={`/login?auth=signup&source=${source}`} onClick={() => analytics.saveCtaClicked()} style={{ display: 'inline' }}>
              Create a free Jaspen account
            </Link>{' '}
            to save, compare, and track calculations.
          </p>
        </>
      )}
      {message ? (
        <p className={`tool-status ${status === 'error' ? 'tool-status-err' : 'tool-status-ok'}`} role="status">
          {message}
        </p>
      ) : null}
    </section>
  );
}
