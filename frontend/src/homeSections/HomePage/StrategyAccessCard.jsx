import React, { useEffect, useMemo, useState } from 'react';
import { useAuth } from '../../shared/auth/AuthContext';
import { API_BASE } from '../../config/apiBase';
import { readAuthQueryNotice } from './authStatus';
import AuthModal from './AuthModal';

const TARGET_SCORE = 87;
const ANIMATION_DURATION_MS = 1200;

export default function StrategyAccessCard() {
  const { login, signup, mfaEnforcement, setMfaEnforcement } = useAuth();
  const [score, setScore] = useState(0);
  const [status, setStatus] = useState('Pending');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [authStatus, setAuthStatus] = useState('idle');
  const [authMode, setAuthMode] = useState('email');
  const [authError, setAuthError] = useState('');
  const [authErrorDetail, setAuthErrorDetail] = useState('');
  const [showAuthModal, setShowAuthModal] = useState(false);
  const [authModalMode, setAuthModalMode] = useState('email');
  const [mfaData, setMfaData] = useState(null);

  // Capture the URL auth notice ONCE at component creation time (lazy initializer).
  // This runs before any effects fire, so it always sees the original URL params
  // even after HomePage cleans them via setSearchParams. Subsequent re-renders
  // don't re-read window.location.search, eliminating the message flash.
  const [initialAuthNotice] = useState(() => {
    if (typeof window === 'undefined') return null;
    try { return readAuthQueryNotice(window.location.search || ''); } catch { return null; }
  });

  useEffect(() => {
    const prefersReducedMotion =
      typeof window !== 'undefined' &&
      window.matchMedia &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    if (prefersReducedMotion) {
      setScore(TARGET_SCORE);
      setStatus('Execution Ready');
      return undefined;
    }

    let rafId = 0;
    const startTime = performance.now();

    const tick = (now) => {
      const progress = Math.min((now - startTime) / ANIMATION_DURATION_MS, 1);
      const nextScore = Math.round(progress * TARGET_SCORE);
      setScore(nextScore);

      if (progress < 1) {
        rafId = requestAnimationFrame(tick);
      } else {
        setStatus('Execution Ready');
      }
    };

    rafId = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(rafId);
    };
  }, []);

  // If checkAuthStatus detected MFA enforcement (existing session, org requires MFA),
  // auto-open the AuthModal with MFA data
  useEffect(() => {
    if (mfaEnforcement?.mfaRequired) {
      setMfaData(mfaEnforcement);
      setShowAuthModal(true);
      setAuthModalMode('email');
      // Clear so it doesn't re-trigger
      if (typeof setMfaEnforcement === 'function') setMfaEnforcement(null);
    }
  }, [mfaEnforcement, setMfaEnforcement]);

  const helperText = useMemo(() => {
    if (authError) return authError;
    if (authStatus === ‘reset_sent’) return ‘If that account exists, we’ll send a password reset link shortly.’;
    if (authStatus === ‘sent’) return ‘Authenticated. Redirecting...’;
    if (initialAuthNotice?.message) return initialAuthNotice.message;
    return ‘By continuing, you agree to receive product updates.’;
  }, [authError, authStatus, initialAuthNotice]);

  const helperDetail = useMemo(() => {
    if (authErrorDetail) return authErrorDetail;
    return initialAuthNotice?.detail || ‘’;
  }, [authErrorDetail, initialAuthNotice]);

  const queryNoticeTone = initialAuthNotice?.tone || ‘’;

  const helperClassName = authError
    ? 'strategy-card-disclaimer is-error'
    : authStatus === 'reset_sent'
      ? 'strategy-card-disclaimer is-success'
    : authStatus === 'sent'
      ? 'strategy-card-disclaimer is-success'
      : queryNoticeTone === 'error'
        ? 'strategy-card-disclaimer is-error'
        : queryNoticeTone === 'success'
          ? 'strategy-card-disclaimer is-success'
      : 'strategy-card-disclaimer';

  /** Determine where to redirect after successful auth. */
  const getPostAuthRedirect = () => {
    try {
      const current = new URLSearchParams(window.location.search || '');
      const planKey = (current.get('plan') || current.get('plan_key') || '').trim().toLowerCase();
      if (planKey && planKey !== 'free') {
        return `/pages/pricing?plan=${encodeURIComponent(planKey)}#plans`;
      }
    } catch (e) { /* ignore */ }
    return '/new';
  };

  const handleGoogleClick = () => {
    setAuthError('');
    setAuthErrorDetail('');
    const redirect = getPostAuthRedirect();
    const params = new URLSearchParams({ next: redirect });
    try {
      const current = new URLSearchParams(window.location.search || '');
      const referralCode = current.get('referral_code') || current.get('invite_code') || current.get('ref') || current.get('invite');
      if (referralCode) params.set('referral_code', referralCode);
    } catch (error) {
      console.debug('Unable to preserve referral code for Google auth:', error);
    }
    window.location.href = `${API_BASE}/api/v1/auth/google/start?${params.toString()}`;
  };

  const handleForgotPassword = async (event) => {
    event?.preventDefault?.();

    const normalizedEmail = String(email || '').trim().toLowerCase();
    if (!normalizedEmail) {
      setAuthError('Enter your email first so we know where to send the reset link.');
      setAuthErrorDetail('');
      return;
    }

    setAuthStatus('sending');
    setAuthError('');
    setAuthErrorDetail('');
    try {
      const response = await fetch(`${API_BASE}/api/v1/auth/forgot-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ email: normalizedEmail }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data?.message || 'Unable to send a reset link right now.');
      }
      setAuthStatus('reset_sent');
      setAuthMode('forgot');
    } catch (error) {
      setAuthError(error?.message || 'Unable to send a reset link right now.');
      setAuthErrorDetail('');
      setAuthStatus('idle');
    }
  };

  const handleEmailSubmit = async (event) => {
    event.preventDefault();

    const normalizedEmail = String(email || '').trim().toLowerCase();
    if (!normalizedEmail) {
      setAuthError('Please enter a valid email address.');
      setAuthErrorDetail('');
      return;
    }
    if (!password || String(password).length < 8) {
      setAuthError('Password must be at least 8 characters.');
      setAuthErrorDetail('');
      return;
    }

    setAuthStatus('sending');
    setAuthError('');
    try {
      const loginAttempt = await login(normalizedEmail, password);

      // MFA required — open the AuthModal which has full MFA flow
      if (loginAttempt?.mfaRequired) {
        setAuthStatus('idle');
        setMfaData(loginAttempt);
        setShowAuthModal(true);
        setAuthModalMode('email');
        return;
      }

      if (loginAttempt?.success) {
        setAuthStatus('sent');
        window.location.href = getPostAuthRedirect();
        return;
      }

      const inferredName = normalizedEmail.split('@')[0] || 'Jaspen User';
      const signupAttempt = await signup(normalizedEmail, password, inferredName);
      if (signupAttempt?.success) {
        setAuthStatus('sent');
        window.location.href = getPostAuthRedirect();
        return;
      }

      setAuthError(
        loginAttempt?.error
        || signupAttempt?.error
        || 'Unable to sign in with email right now.'
      );
      setAuthErrorDetail(loginAttempt?.detail || signupAttempt?.detail || '');
      setAuthStatus('idle');
    } catch (error) {
      setAuthError(error?.message || 'Unable to sign in with email right now.');
      setAuthErrorDetail(error?.detail || '');
      setAuthStatus('idle');
    }
  };

  return (
    <div className="strategy-access-card">
      <div className="strategy-card-header">STRATEGY ACCESS</div>

      <div className="strategy-card-section strategy-card-score">
        <div className="strategy-score-circle">
          <div className="score-value">{score}</div>
          <div className="score-label">Score</div>
        </div>
        <div className={`strategy-score-status ${status === 'Execution Ready' ? 'ready' : 'pending'}`}>
          {status}
        </div>
      </div>

      <div className="strategy-card-section strategy-card-auth">
        {authMode !== 'forgot' && (
          <>
            <button
              type="button"
              className="jaspen-btn jaspen-btn-outline strategy-google-btn"
              onClick={handleGoogleClick}
            >
              Continue with Google
            </button>
            <div className="strategy-card-divider"><span>OR</span></div>
          </>
        )}
        <form className="strategy-card-form" onSubmit={authMode === 'forgot' ? handleForgotPassword : handleEmailSubmit}>
          <input
            type="email"
            className="strategy-email-input"
            placeholder="Enter your email"
            aria-label="Email address"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            disabled={authStatus === 'sending' || authStatus === 'sent'}
          />
          {authMode !== 'forgot' && (
            <input
              type="password"
              className="strategy-email-input"
              placeholder="Password"
              aria-label="Password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              disabled={authStatus === 'sending' || authStatus === 'sent'}
            />
          )}
          <button
            type="submit"
            className="jaspen-btn jaspen-btn-primary strategy-email-btn"
            disabled={authStatus === 'sending' || authStatus === 'sent'} aria-disabled={authStatus === 'sending' || authStatus === 'sent'}
          >
            {authStatus === 'sending'
              ? (authMode === 'forgot' ? 'Sending reset link…' : 'Sending...')
              : (authMode === 'forgot' ? 'Send reset link' : 'Continue with email')}
          </button>
        </form>
        <div className="strategy-card-meta">
          {authMode === 'forgot' ? (
            <button
              type="button"
              className="strategy-meta-link"
              onClick={() => {
                setAuthMode('email');
                setAuthStatus('idle');
                setAuthError('');
                setAuthErrorDetail('');
              }}
            >
              Back to sign in
            </button>
          ) : (
            <button
              type="button"
              className="strategy-meta-link"
              onClick={() => {
                setAuthMode('forgot');
                setAuthStatus('idle');
                setAuthError('');
                setAuthErrorDetail('');
              }}
            >
              Forgot password?
            </button>
          )}
        </div>
      </div>

      <div className={helperClassName}>
        <strong>{helperText}</strong>
        {helperDetail && <span>{helperDetail}</span>}
      </div>

      <AuthModal
        isOpen={showAuthModal}
        mode={authModalMode}
        onClose={() => { setShowAuthModal(false); setMfaData(null); }}
        onModeChange={setAuthModalMode}
        initialMfaData={mfaData}
      />
    </div>
  );
}
