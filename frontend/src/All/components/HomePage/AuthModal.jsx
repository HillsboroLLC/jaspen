import React, { useEffect, useMemo, useState } from 'react';
import { supabase } from '../../shared/supabase/supabaseClient';

const getRedirectUrl = () =>
  typeof window !== 'undefined' ? `${window.location.origin}/auth/callback` : '';

export default function AuthModal({ isOpen, mode = 'email', onClose, onModeChange }) {
  const [email, setEmail] = useState('');
  const [status, setStatus] = useState('idle');
  const [error, setError] = useState('');

  const isEmailMode = mode === 'email';

  const resetState = () => {
    setEmail('');
    setStatus('idle');
    setError('');
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

  useEffect(() => {
    if (isOpen) {
      resetState();
    }
  }, [isOpen]);

  const statusMessage = useMemo(() => {
    if (status === 'sent') {
      return 'Check your inbox for a secure magic link.';
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
    if (!supabase) {
      setError('Supabase is not configured yet. Please try again shortly.');
      return;
    }

    setError('');
    const { error: signInError } = await supabase.auth.signInWithOAuth({
      provider: 'google',
      options: {
        redirectTo: getRedirectUrl(),
      },
    });

    if (signInError) {
      setError(signInError.message || 'Unable to start Google sign-in.');
    }
  };

  const handleEmailSubmit = async (event) => {
    event.preventDefault();

    if (!email.trim()) {
      setError('Please enter a valid email address.');
      return;
    }

    if (!supabase) {
      setError('Supabase is not configured yet. Please try again shortly.');
      return;
    }

    setStatus('sending');
    setError('');

    const { error: otpError } = await supabase.auth.signInWithOtp({
      email,
      options: {
        emailRedirectTo: getRedirectUrl(),
      },
    });

    if (otpError) {
      setError(otpError.message || 'Unable to send magic link.');
      setStatus('idle');
      return;
    }

    setStatus('sent');
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
              ? 'We will send a secure magic link to finish signing in.'
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
            <button
              type="submit"
              className="jaspen-btn jaspen-btn-primary auth-modal-submit"
              disabled={status === 'sending' || status === 'sent'}
            >
              {status === 'sending' ? 'Sending…' : 'Send magic link'}
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
