import React, { useEffect, useMemo, useState } from 'react';
import { useAuth } from '../../shared/auth/AuthContext';
import { API_BASE } from '../../config/apiBase';
import { readAuthQueryNotice } from './authStatus';

export default function AuthModal({ isOpen, mode = 'email', onClose, onModeChange }) {
  const { login, signup } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [status, setStatus] = useState('idle');
  const [error, setError] = useState('');
  const [errorDetail, setErrorDetail] = useState('');

  const isEmailMode = mode === 'email';
  const isForgotMode = mode === 'forgot';

  const resetState = () => {
    setStatus('idle');
    setError('');
    setErrorDetail('');
    setPassword('');
  };

  useEffect(() => {
    if (!isOpen) return undefined;

    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        onClose?.();
      }
    };

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [isOpen, onClose]);

  useEffect(() => {
    resetState();
  }, [mode]);

  const statusMessage = useMemo(() => {
    if (status === 'sent') {
      return 'Authenticated. Redirecting...';
    }
    if (status === 'reset_sent') {
      return 'If that account exists, we’ll send a password reset link shortly.';
    }
    return '';
  }, [status]);

  const authNotice = useMemo(() => {
    if (typeof window === 'undefined') return null;
    return readAuthQueryNotice(window.location.search || '');
  }, []);

  if (!isOpen) return null;

  const handleBackdropClick = (event) => {
    if (event.target === event.currentTarget) {
      onClose?.();
    }
  };

  const handleGoogle = async () => {
    setError('');
    setErrorDetail('');
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
      setError('Please enter a valid email address.');
      setErrorDetail('');
      return;
    }
    if (!password || String(password).length < 8) {
      setError('Password must be at least 8 characters.');
      setErrorDetail('');
      return;
    }

    setStatus('sending');
    setError('');
    try {
      const loginAttempt = await login(normalizedEmail, password);
      if (loginAttempt?.success) {
        setStatus('sent');
        window.location.href = '/new';
        return;
      }

      const inferredName = normalizedEmail.split('@')[0] || 'Jaspen User';
      const signupAttempt = await signup(normalizedEmail, password, inferredName);
      if (signupAttempt?.success) {
        setStatus('sent');
        window.location.href = '/new';
        return;
      }

      setError(
        loginAttempt?.error
        || signupAttempt?.error
        || 'Unable to sign in with email right now.'
      );
      setErrorDetail(loginAttempt?.detail || signupAttempt?.detail || '');
      setStatus('idle');
    } catch (authError) {
      setError(authError?.message || 'Unable to sign in with email right now.');
      setErrorDetail(authError?.detail || '');
      setStatus('idle');
    }
  };

  const handleForgotSubmit = async (event) => {
    event.preventDefault();

    const normalizedEmail = String(email || '').trim().toLowerCase();
    if (!normalizedEmail) {
      setError('Please enter a valid email address.');
      setErrorDetail('');
      return;
    }

    setStatus('sending');
    setError('');
    setErrorDetail('');
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
      setStatus('reset_sent');
    } catch (authError) {
      setError(authError?.message || 'Unable to send a reset link right now.');
      setErrorDetail('');
      setStatus('idle');
    }
  };

  return (
    <div className="auth-modal-backdrop" onMouseDown={handleBackdropClick}>
      <div className="auth-modal" role="dialog" aria-modal="true" aria-label="Authentication">
        <button type="button" className="auth-modal-close" onClick={onClose} aria-label="Close">
          ×
        </button>

        <div className="auth-modal-header">
          <div className="auth-modal-eyebrow">STRATEGY ACCESS</div>
          <h2>{isForgotMode ? 'Reset your password' : (isEmailMode ? 'Continue with email' : 'Continue with Google')}</h2>
          <p>
            {isForgotMode
              ? 'Enter your email and we’ll send you a link to reset your password.'
              : isEmailMode
              ? 'Use your email and password to sign in. New email users are auto-created.'
              : 'Use your Google account to access Jaspen instantly.'}
          </p>
        </div>

        {(error || authNotice) && (
          <div className={`auth-modal-alert is-${error ? 'error' : authNotice?.tone || 'info'}`}>
            <strong>{error || authNotice?.message}</strong>
            {(errorDetail || authNotice?.detail) && <p>{errorDetail || authNotice?.detail}</p>}
          </div>
        )}
        {statusMessage && <div className="auth-modal-success">{statusMessage}</div>}

        {isEmailMode || isForgotMode ? (
          <form className="auth-modal-form" onSubmit={isForgotMode ? handleForgotSubmit : handleEmailSubmit}>
            <label className="auth-modal-label" htmlFor="auth-email">Email</label>
            <input
              id="auth-email"
              type="email"
              className="auth-modal-input"
              placeholder="Enter your email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              disabled={status === 'sending' || status === 'sent'}
            />
            {!isForgotMode && (
              <>
                <label className="auth-modal-label" htmlFor="auth-password">Password</label>
                <input
                  id="auth-password"
                  type="password"
                  className="auth-modal-input"
                  placeholder="Enter your password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  disabled={status === 'sending' || status === 'sent'}
                />
              </>
            )}
            <button
              type="submit"
              className="jaspen-btn jaspen-btn-primary auth-modal-submit"
              disabled={status === 'sending' || status === 'sent'}
            >
              {status === 'sending'
                ? (isForgotMode ? 'Sending reset link…' : 'Signing in…')
                : (isForgotMode ? 'Send reset link' : 'Continue with email')}
            </button>
          </form>
        ) : (
          <button type="button" className="jaspen-btn jaspen-btn-primary auth-modal-submit" onClick={handleGoogle}>
            Continue with Google
          </button>
        )}

        <div className="auth-modal-footer">
          {isForgotMode ? (
            <button type="button" className="auth-modal-switch" onClick={() => onModeChange?.('email')}>
              Back to sign in
            </button>
          ) : isEmailMode ? (
            <>
              <button type="button" className="auth-modal-switch" onClick={() => onModeChange?.('forgot')}>
                Forgot password?
              </button>
              <button type="button" className="auth-modal-switch" onClick={() => onModeChange?.('google')}>
                Prefer Google instead?
              </button>
            </>
          ) : (
            <button type="button" className="auth-modal-switch" onClick={() => onModeChange?.('email')}>
              Prefer email instead?
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
