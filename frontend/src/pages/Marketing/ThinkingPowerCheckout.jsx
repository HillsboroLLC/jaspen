import React, { useEffect, useRef, useState } from 'react';
import { useAuth } from '../../shared/auth/AuthContext';
import { authFetch, buildAuthHeaders } from '../../shared/auth/http';
import { API_BASE } from '../../config/apiBase';
import { ADVANTAGE_CREDITS, ADVANTAGE_PRICE } from './founderCampaigns';

const inputStyle = {
  width: '100%', padding: '11px 12px', border: '1px solid #e6eaf2', borderRadius: 8,
  fontSize: 14, fontFamily: 'inherit', color: '#0f172a', outline: 'none', background: '#fbfcff',
  marginBottom: 12,
};
const labelStyle = { display: 'block', fontSize: 12, fontWeight: 700, color: '#475569', marginBottom: 6 };
const errorBox = { marginTop: 4, marginBottom: 12, fontSize: 13, color: '#b42318', background: '#fef3f2', border: '1px solid #fecdca', borderRadius: 8, padding: '9px 11px' };
const noticeBox = { fontSize: 13, color: '#0f172a', background: '#f8f5f0', border: '1px solid #ecdcc9', borderRadius: 8, padding: '12px 14px', lineHeight: 1.5 };

function AccountStep({ returnPath }) {
  const { login, signup } = useAuth();
  const [mode, setMode] = useState('signup');
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const isSignup = mode === 'signup';

  const handleGoogle = () => {
    const next = `${returnPath}?advantage_checkout=resume`;
    window.location.href = `${API_BASE}/api/v1/auth/google/start?next=${encodeURIComponent(next)}`;
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (submitting) return;
    setError('');
    setNotice('');
    const normalizedEmail = String(email || '').trim().toLowerCase();
    if (!normalizedEmail || !password) return setError('Enter your email and password.');
    if (isSignup && !String(name).trim()) return setError('Enter your name.');
    if (isSignup && password !== confirm) return setError('Those passwords do not match.');

    setSubmitting(true);
    try {
      const result = isSignup
        ? await signup(normalizedEmail, password, String(name).trim(), { planKey: 'jaspen_advantage' })
        : await login(normalizedEmail, password);
      if (result?.success) return;
      if (result?.mfaRequired) {
        setNotice('Your account uses two-step verification. Sign in first, then reopen this offer to complete your purchase.');
      } else if (result?.verificationRequired) {
        setNotice(`Check ${normalizedEmail} to verify your account, then reopen this offer to complete payment.`);
      } else {
        setError(result?.error || (isSignup ? 'Unable to create your account right now.' : 'Incorrect email or password.'));
      }
    } catch (err) {
      setError(err?.message || 'Something went wrong. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div>
      <div className="fc-checkout-tabs" role="tablist" aria-label="Account options">
        {[['signup', 'Create account'], ['signin', 'Sign in']].map(([key, text]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={mode === key}
            onClick={() => { setMode(key); setError(''); setNotice(''); }}
          >
            {text}
          </button>
        ))}
      </div>
      <button type="button" className="fc-checkout-google" onClick={handleGoogle}>Continue with Google</button>
      <div className="fc-checkout-divider"><span />OR<span /></div>
      <form onSubmit={handleSubmit}>
        {isSignup && <><label htmlFor="advantage-name" style={labelStyle}>Full name</label><input id="advantage-name" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" style={inputStyle} /></>}
        <label htmlFor="advantage-email" style={labelStyle}>Email</label>
        <input id="advantage-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" style={inputStyle} />
        <label htmlFor="advantage-password" style={labelStyle}>Password</label>
        <input id="advantage-password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete={isSignup ? 'new-password' : 'current-password'} style={inputStyle} />
        {isSignup && <><label htmlFor="advantage-confirm" style={labelStyle}>Confirm password</label><input id="advantage-confirm" type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" style={inputStyle} /></>}
        {error && <div role="alert" style={errorBox}>{error}</div>}
        {notice && <div role="status" style={{ ...noticeBox, marginBottom: 12 }}>{notice}</div>}
        <button type="submit" className="fc-checkout-primary" disabled={submitting}>
          {submitting ? 'One moment...' : isSignup ? 'Create account and continue' : 'Sign in and continue'}
        </button>
      </form>
      <p className="fc-checkout-footnote">Next, Stripe will show the one-time purchase for your review. No subscription is created.</p>
    </div>
  );
}

function PurchaseStep({ campaignId, returnPath }) {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const startCheckout = async () => {
    if (submitting) return;
    setSubmitting(true);
    setError('');
    try {
      const response = await authFetch(`${API_BASE}/api/v1/billing/create-jaspen-advantage-checkout`, {
        method: 'POST',
        headers: buildAuthHeaders({ 'Content-Type': 'application/json' }, 'POST'),
        credentials: 'include',
        body: JSON.stringify({ campaign_id: campaignId, return_path: returnPath }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data?.url) throw new Error(data?.msg || 'Could not start secure checkout.');
      window.location.assign(data.url);
    } catch (err) {
      setError(err?.message || 'Could not start secure checkout.');
      setSubmitting(false);
    }
  };

  return (
    <div>
      <ul className="fc-checkout-summary">
        <li><strong>{ADVANTAGE_CREDITS}</strong><span>non-expiring usage credits</span></li>
        <li><strong>${ADVANTAGE_PRICE} once</strong><span>no subscription or auto renewal</span></li>
        <li><strong>Personal account</strong><span>non-transferable and not shared</span></li>
      </ul>
      {error && <div role="alert" style={errorBox}>{error}</div>}
      <button type="button" className="fc-checkout-primary" disabled={submitting} onClick={startCheckout}>
        {submitting ? 'Opening secure checkout...' : `Continue to pay $${ADVANTAGE_PRICE}`}
      </button>
      <p className="fc-checkout-footnote">Stripe securely processes the one-time payment. Your credits are granted after payment is confirmed.</p>
    </div>
  );
}

export default function ThinkingPowerCheckout({ onClose, campaignId = '', returnPath = '/thinking-power' }) {
  const { user } = useAuth();
  const closeRef = useRef(null);

  useEffect(() => {
    closeRef.current?.focus();
    const onKeyDown = (event) => { if (event.key === 'Escape') onClose?.(); };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  return (
    <div className="fc-checkout-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose?.(); }}>
      <div role="dialog" aria-modal="true" aria-labelledby="advantage-checkout-title" className="fc-checkout-dialog">
        <div className="fc-checkout-header">
          <div>
            <span>The Jaspen Advantage</span>
            <h2 id="advantage-checkout-title">${ADVANTAGE_PRICE} once. No subscription.</h2>
            <p>{user ? 'Review the offer, then continue to Stripe.' : 'Create or sign in to your personal Jaspen account.'}</p>
          </div>
          <button ref={closeRef} type="button" onClick={onClose} aria-label="Close checkout">×</button>
        </div>
        <div className="fc-checkout-body">
          {user ? <PurchaseStep campaignId={campaignId} returnPath={returnPath} /> : <AccountStep returnPath={returnPath} />}
        </div>
      </div>
    </div>
  );
}
