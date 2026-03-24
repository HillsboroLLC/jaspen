import React, { useEffect, useMemo, useState } from 'react';
import { useAuth } from '../../shared/auth/AuthContext';
import { API_BASE } from '../../config/apiBase';
import { readAuthQueryNotice } from './authStatus';

const TARGET_SCORE = 87;
const ANIMATION_DURATION_MS = 1200;

export default function StrategyAccessCard() {
  const { login, signup } = useAuth();
  const [score, setScore] = useState(0);
  const [status, setStatus] = useState('Pending');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [authStatus, setAuthStatus] = useState('idle');
  const [authError, setAuthError] = useState('');
  const [authErrorDetail, setAuthErrorDetail] = useState('');

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

  const helperText = useMemo(() => {
    if (authError) return authError;
    if (authStatus === 'sent') return 'Authenticated. Redirecting...';
    if (typeof window !== 'undefined') {
      const authNotice = readAuthQueryNotice(window.location.search || '');
      if (authNotice?.message) return authNotice.message;
    }
    return 'By continuing, you agree to receive product updates.';
  }, [authError, authStatus]);

  const helperDetail = useMemo(() => {
    if (authErrorDetail) return authErrorDetail;
    if (typeof window !== 'undefined') {
      return readAuthQueryNotice(window.location.search || '')?.detail || '';
    }
    return '';
  }, [authErrorDetail]);

  const queryNoticeTone = useMemo(() => {
    if (typeof window === 'undefined') return '';
    return readAuthQueryNotice(window.location.search || '')?.tone || '';
  }, []);

  const helperClassName = authError
    ? 'strategy-card-disclaimer is-error'
    : authStatus === 'sent'
      ? 'strategy-card-disclaimer is-success'
      : queryNoticeTone === 'error'
        ? 'strategy-card-disclaimer is-error'
        : queryNoticeTone === 'success'
          ? 'strategy-card-disclaimer is-success'
      : 'strategy-card-disclaimer';

  const handleGoogleClick = () => {
    setAuthError('');
    setAuthErrorDetail('');
    const params = new URLSearchParams({ next: '/new' });
    try {
      const current = new URLSearchParams(window.location.search || '');
      const referralCode = current.get('referral_code') || current.get('invite_code') || current.get('ref') || current.get('invite');
      if (referralCode) params.set('referral_code', referralCode);
    } catch (error) {
      console.debug('Unable to preserve referral code for Google auth:', error);
    }
    window.location.href = `${API_BASE}/api/v1/auth/google/start?${params.toString()}`;
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
      if (loginAttempt?.success) {
        setAuthStatus('sent');
        window.location.href = '/new';
        return;
      }

      const inferredName = normalizedEmail.split('@')[0] || 'Jaspen User';
      const signupAttempt = await signup(normalizedEmail, password, inferredName);
      if (signupAttempt?.success) {
        setAuthStatus('sent');
        window.location.href = '/new';
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
        <form className="strategy-card-form" onSubmit={handleEmailSubmit}>
          <input
            type="email"
            className="strategy-email-input"
            placeholder="Enter your email"
            aria-label="Email address"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            disabled={authStatus === 'sending' || authStatus === 'sent'}
          />
          <input
            type="password"
            className="strategy-email-input"
            placeholder="Password"
            aria-label="Password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            disabled={authStatus === 'sending' || authStatus === 'sent'}
          />
          <button
            type="submit"
            className="jaspen-btn jaspen-btn-primary strategy-email-btn"
            disabled={authStatus === 'sending' || authStatus === 'sent'}
          >
            {authStatus === 'sending' ? 'Sending...' : 'Continue with email'}
          </button>
        </form>
      </div>

      <div className={helperClassName}>
        <strong>{helperText}</strong>
        {helperDetail && <span>{helperDetail}</span>}
      </div>
    </div>
  );
}
