import React, { useEffect, useMemo, useState } from 'react';
import { useAuth } from '../../shared/auth/AuthContext';
import { API_BASE } from '../../config/apiBase';

export default function AuthModal({ isOpen, mode = 'email', onClose, onModeChange }) {
  const { login, signup } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [status, setStatus] = useState('idle');
  const [error, setError] = useState('');

  const isEmailMode = mode === 'email';

  const resetState = () => {
    setStatus('idle');
    setError('');
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
    return '';
  }, [status]);

  if (!isOpen) return null;

  const handleBackdropClick = (event) => {
    if (event.target === event.currentTarget) {
      onClose?.();
    }
  };

  const handleGoogle = async () => {
    setError('');
    window.location.href = `${API_BASE}/api/auth/google/start?next=${encodeURIComponent('/new')}`;
  };

  const handleEmailSubmit = async (event) => {
    event.preventDefault();

    const normalizedEmail = String(email || '').trim().toLowerCase();
    if (!normalizedEmail) {
      setError('Please enter a valid email address.');
      return;
    }
    if (!password || String(password).length < 8) {
      setError('Password must be at least 8 characters.');
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
      setStatus('idle');
    } catch (authError) {
      setError(authError?.message || 'Unable to sign in with email right now.');
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
          <h2>{isEmailMode ? 'Continue with email' : 'Continue with Google'}</h2>
          <p>
            {isEmailMode
              ? 'Use your email and password to sign in. New email users are auto-created.'
              : 'Use your Google account to access Jaspen instantly.'}
          </p>
        </div>

        {error && <div className="auth-modal-alert">{error}</div>}
        {statusMessage && <div className="auth-modal-success">{statusMessage}</div>}

        {isEmailMode ? (
          <form className="auth-modal-form" onSubmit={handleEmailSubmit}>
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
            <button
              type="submit"
              className="jaspen-btn jaspen-btn-primary auth-modal-submit"
              disabled={status === 'sending' || status === 'sent'}
            >
              {status === 'sending' ? 'Signing in…' : 'Continue with email'}
            </button>
          </form>
        ) : (
          <button type="button" className="jaspen-btn jaspen-btn-primary auth-modal-submit" onClick={handleGoogle}>
            Continue with Google
          </button>
        )}

        <div className="auth-modal-footer">
          {isEmailMode ? (
            <button type="button" className="auth-modal-switch" onClick={() => onModeChange?.('google')}>
              Prefer Google instead?
            </button>
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
