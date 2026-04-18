import React, { useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { useAuth } from '../../shared/auth/AuthContext';
import { API_BASE } from '../../config/apiBase';
import { authFetch } from '../../shared/auth/http';
import { readAuthQueryNotice } from './authStatus';

export default function AuthModal({ isOpen, mode = 'email', onClose, onModeChange, initialMfaData }) {
  const { login, signup, setUser } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [status, setStatus] = useState('idle');
  const [error, setError] = useState('');
  const [errorDetail, setErrorDetail] = useState('');

  // MFA state
  const [mfaStep, setMfaStep] = useState(null); // null | 'challenge' | 'setup' | 'setup-verify' | 'backup-codes'
  const [mfaPendingToken, setMfaPendingToken] = useState('');
  const [mfaCode, setMfaCode] = useState('');
  const [mfaQrCode, setMfaQrCode] = useState('');
  const [mfaSecret, setMfaSecret] = useState('');
  const [mfaBackupCodes, setMfaBackupCodes] = useState([]);
  const [mfaOrgName, setMfaOrgName] = useState('');

  const isEmailMode = mode === 'email';
  const isForgotMode = mode === 'forgot';

  const resetState = () => {
    setStatus('idle');
    setError('');
    setErrorDetail('');
    setPassword('');
    setMfaStep(null);
    setMfaPendingToken('');
    setMfaCode('');
    setMfaQrCode('');
    setMfaSecret('');
    setMfaBackupCodes([]);
    setMfaOrgName('');
  };

  useEffect(() => {
    if (!isOpen) return undefined;
    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        if (mfaStep) {
          resetState();
        } else {
          onClose?.();
        }
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [isOpen, onClose, mfaStep]);

  useEffect(() => {
    resetState();
  }, [mode]);

  // Auto-trigger MFA flow when opened with initial MFA data
  useEffect(() => {
    if (!isOpen || !initialMfaData?.mfaRequired) return;
    setMfaOrgName(initialMfaData.organizationName || '');
    setMfaPendingToken(initialMfaData.pendingToken || '');
    if (initialMfaData.mfaSetupRequired) {
      startMfaSetup(initialMfaData.pendingToken);
    } else {
      setMfaStep('challenge');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, initialMfaData]);

  const statusMessage = useMemo(() => {
    if (status === 'sent') return 'Authenticated. Redirecting...';
    if (status === 'reset_sent') return 'If that account exists, we\'ll send a password reset link shortly.';
    return '';
  }, [status]);

  const authNotice = useMemo(() => {
    if (typeof window === 'undefined') return null;
    return readAuthQueryNotice(window.location.search || '');
  }, []);

  if (!isOpen) return null;

  const handleBackdropClick = (event) => {
    if (event.target === event.currentTarget) onClose?.();
  };

  const handleGoogle = async () => {
    setError('');
    setErrorDetail('');
    const params = new URLSearchParams({ next: '/new' });
    try {
      const current = new URLSearchParams(window.location.search || '');
      const referralCode = current.get('referral_code') || current.get('invite_code') || current.get('ref') || current.get('invite');
      if (referralCode) params.set('referral_code', referralCode);
    } catch (err) {
      console.debug('Unable to preserve referral code for Google auth:', err);
    }
    window.location.href = `${API_BASE}/api/v1/auth/google/start?${params.toString()}`;
  };

  const handleEmailSubmit = async (event) => {
    event.preventDefault();
    const normalizedEmail = String(email || '').trim().toLowerCase();
    if (!normalizedEmail) { setError('Please enter a valid email address.'); return; }
    if (!password || String(password).length < 8) { setError('Password must be at least 8 characters.'); return; }

    setStatus('sending');
    setError('');
    try {
      const loginAttempt = await login(normalizedEmail, password);

      // MFA required — switch to challenge or setup
      if (loginAttempt?.mfaRequired) {
        setMfaOrgName(loginAttempt.organizationName || '');
        if (loginAttempt.mfaSetupRequired) {
          // User needs to set up MFA first — initiate setup with pending token
          setMfaPendingToken(loginAttempt.pendingToken || '');
          await startMfaSetup(loginAttempt.pendingToken);
          return;
        }
        // User has MFA enabled — show code input
        setMfaPendingToken(loginAttempt.pendingToken || '');
        setMfaStep('challenge');
        setStatus('idle');
        return;
      }

      if (loginAttempt?.success) {
        setStatus('sent');
        window.location.href = '/new';
        return;
      }

      // Login failed — try signup
      const inferredName = normalizedEmail.split('@')[0] || 'Jaspen User';
      const signupAttempt = await signup(normalizedEmail, password, inferredName);
      if (signupAttempt?.success) {
        setStatus('sent');
        window.location.href = '/new';
        return;
      }

      setError(loginAttempt?.error || signupAttempt?.error || 'Unable to sign in with email right now.');
      setErrorDetail(loginAttempt?.detail || signupAttempt?.detail || '');
      setStatus('idle');
    } catch (authError) {
      setError(authError?.message || 'Unable to sign in with email right now.');
      setStatus('idle');
    }
  };

  // ---- MFA Setup Flow ----

  const startMfaSetup = async (pendingToken) => {
    setError('');
    setStatus('sending');
    try {
      const res = await fetch(`${API_BASE}/api/v1/auth/mfa/setup`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${pendingToken}`,
        },
        credentials: 'include',
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.message || 'Unable to start MFA setup.');
      setMfaQrCode(data.qr_code || '');
      setMfaSecret(data.secret || '');
      setMfaStep('setup');
      setStatus('idle');
    } catch (err) {
      setError(err?.message || 'Unable to start MFA setup.');
      setMfaStep('setup');
      setStatus('idle');
    }
  };

  const handleMfaSetupVerify = async (event) => {
    event.preventDefault();
    const code = String(mfaCode || '').trim();
    if (!code || code.length < 6) { setError('Enter the 6-digit code from your authenticator app.'); return; }

    setError('');
    setStatus('sending');
    try {
      const res = await fetch(`${API_BASE}/api/v1/auth/mfa/verify`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${mfaPendingToken}`,
        },
        credentials: 'include',
        body: JSON.stringify({ code }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.message || 'Invalid code. Please try again.');

      setMfaBackupCodes(data.backup_codes || []);
      setMfaStep('backup-codes');
      setStatus('idle');
    } catch (err) {
      setError(err?.message || 'Verification failed.');
      setStatus('idle');
    }
  };

  const handleBackupCodesContinue = async () => {
    // After viewing backup codes, complete login via challenge
    setMfaStep('challenge');
    setMfaCode('');
    setError('');
  };

  // ---- MFA Challenge (enter code after login) ----

  const handleMfaChallenge = async (event) => {
    event.preventDefault();
    const code = String(mfaCode || '').trim();
    if (!code) { setError('Enter your authenticator code or a backup code.'); return; }

    setError('');
    setStatus('sending');
    try {
      const res = await fetch(`${API_BASE}/api/v1/auth/mfa/challenge`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ pending_token: mfaPendingToken, code }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.message || 'Invalid code.');

      // Successful MFA — we're logged in
      localStorage.removeItem('access_token');
      localStorage.removeItem('token');
      localStorage.removeItem('refresh_token');
      if (data?.user && typeof setUser === 'function') {
        setUser(data.user);
      }
      setStatus('sent');
      window.location.href = '/new';
    } catch (err) {
      setError(err?.message || 'Invalid code. Please try again.');
      setStatus('idle');
    }
  };

  // ---- Forgot Password ----

  const handleForgotSubmit = async (event) => {
    event.preventDefault();
    const normalizedEmail = String(email || '').trim().toLowerCase();
    if (!normalizedEmail) { setError('Please enter a valid email address.'); return; }

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
      if (!response.ok) throw new Error(data?.message || 'Unable to send a reset link right now.');
      setStatus('reset_sent');
    } catch (authError) {
      setError(authError?.message || 'Unable to send a reset link right now.');
      setStatus('idle');
    }
  };

  // ---- Render ----

  const renderMfaChallenge = () => (
    <>
      <div className="auth-modal-header">
        <div className="auth-modal-eyebrow">TWO-FACTOR AUTHENTICATION</div>
        <h2>Enter your code</h2>
        <p>Open your authenticator app and enter the 6-digit code, or use a backup code.</p>
      </div>
      {error && <div className="auth-modal-alert is-error"><strong>{error}</strong></div>}
      {statusMessage && <div className="auth-modal-success">{statusMessage}</div>}
      <form className="auth-modal-form" onSubmit={handleMfaChallenge}>
        <label className="auth-modal-label" htmlFor="mfa-code">Authentication code</label>
        <input
          id="mfa-code"
          type="text"
          inputMode="numeric"
          autoComplete="one-time-code"
          className="auth-modal-input"
          placeholder="000000"
          value={mfaCode}
          onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, '').slice(0, 8))}
          disabled={status === 'sending' || status === 'sent'}
          autoFocus
          style={{ letterSpacing: '0.25em', fontSize: '1.25rem', textAlign: 'center' }}
        />
        <button
          type="submit"
          className="jaspen-btn jaspen-btn-primary auth-modal-submit"
          disabled={status === 'sending' || status === 'sent' || !mfaCode.trim()}
        >
          {status === 'sending' ? 'Verifying...' : 'Verify'}
        </button>
      </form>
      <div className="auth-modal-footer">
        <button type="button" className="auth-modal-switch" onClick={resetState}>
          Back to sign in
        </button>
      </div>
    </>
  );

  const renderMfaSetup = () => (
    <>
      <div className="auth-modal-header">
        <div className="auth-modal-eyebrow">MFA SETUP REQUIRED</div>
        <h2>Set up two-factor authentication</h2>
        <p>
          {mfaOrgName
            ? `${mfaOrgName} requires two-factor authentication. `
            : 'Your organization requires two-factor authentication. '}
          This QR code opens your browser or device default authenticator. If you prefer another authenticator app,
          adjust browser settings or use the manual secret entry key below.
        </p>
      </div>
      {error && <div className="auth-modal-alert is-error"><strong>{error}</strong></div>}
      {mfaQrCode && (
        <div style={{ textAlign: 'center', margin: '16px 0' }}>
          <img src={mfaQrCode} alt="MFA QR Code" style={{ width: 180, height: 180, borderRadius: 8 }} />
        </div>
      )}
      {mfaSecret && (
        <div style={{ textAlign: 'center', margin: '0 0 16px', fontSize: '0.85rem', color: '#64748b' }}>
          Manual entry key: <code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: 4, fontWeight: 600, letterSpacing: '0.05em' }}>{mfaSecret}</code>
        </div>
      )}
      <details className="auth-modal-help">
        <summary>Info: authenticator app options</summary>
        <p>
          QR scanning typically opens your default browser/device authenticator.
          To use Microsoft Authenticator, Google Authenticator, Authy, or another app, add a new account in that app
          and enter the manual key.
        </p>
      </details>
      <form className="auth-modal-form" onSubmit={handleMfaSetupVerify}>
        <label className="auth-modal-label" htmlFor="mfa-setup-code">Enter the 6-digit code from your app</label>
        <input
          id="mfa-setup-code"
          type="text"
          inputMode="numeric"
          autoComplete="one-time-code"
          className="auth-modal-input"
          placeholder="000000"
          value={mfaCode}
          onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
          disabled={status === 'sending'}
          autoFocus
          style={{ letterSpacing: '0.25em', fontSize: '1.25rem', textAlign: 'center' }}
        />
        <button
          type="submit"
          className="jaspen-btn jaspen-btn-primary auth-modal-submit"
          disabled={status === 'sending' || mfaCode.trim().length < 6}
        >
          {status === 'sending' ? 'Verifying...' : 'Verify and enable MFA'}
        </button>
      </form>
      <div className="auth-modal-footer">
        <button type="button" className="auth-modal-switch" onClick={resetState}>
          Back to sign in
        </button>
      </div>
    </>
  );

  const renderBackupCodes = () => (
    <>
      <div className="auth-modal-header">
        <div className="auth-modal-eyebrow">SAVE YOUR BACKUP CODES</div>
        <h2>MFA enabled successfully</h2>
        <p>
          Save these backup codes in a secure location. Each code can only be used once.
          If you lose access to your authenticator app, you can use these codes to sign in.
        </p>
      </div>
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(2, 1fr)',
        gap: '8px',
        margin: '16px 0',
        padding: '16px',
        background: '#f8fafc',
        borderRadius: 8,
        border: '1px solid #e2e8f0',
      }}>
        {mfaBackupCodes.map((code, idx) => (
          <code key={idx} style={{
            display: 'block',
            textAlign: 'center',
            padding: '6px',
            background: '#fff',
            borderRadius: 4,
            fontWeight: 600,
            fontSize: '0.9rem',
            letterSpacing: '0.1em',
            border: '1px solid #e2e8f0',
          }}>{code}</code>
        ))}
      </div>
      <button
        type="button"
        className="jaspen-btn jaspen-btn-primary auth-modal-submit"
        onClick={handleBackupCodesContinue}
      >
        I've saved my codes — continue to sign in
      </button>
    </>
  );

  const renderLoginForm = () => (
    <>
      <div className="auth-modal-header">
        <div className="auth-modal-eyebrow">STRATEGY ACCESS</div>
        <h2>{isForgotMode ? 'Reset your password' : (isEmailMode ? 'Continue with email' : 'Continue with Google')}</h2>
        <p>
          {isForgotMode
            ? 'Enter your email and we\'ll send you a link to reset your password.'
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
              ? (isForgotMode ? 'Sending reset link...' : 'Signing in...')
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
    </>
  );

  const modalContent = (
    <div className="auth-modal-backdrop" onMouseDown={handleBackdropClick}>
      <div className="auth-modal" role="dialog" aria-modal="true" aria-label="Authentication">
        <button type="button" className="auth-modal-close" onClick={() => { resetState(); onClose?.(); }} aria-label="Close">
          x
        </button>
        {mfaStep === 'challenge' && renderMfaChallenge()}
        {mfaStep === 'setup' && renderMfaSetup()}
        {mfaStep === 'backup-codes' && renderBackupCodes()}
        {!mfaStep && renderLoginForm()}
      </div>
    </div>
  );

  if (typeof document === 'undefined') return modalContent;
  return createPortal(modalContent, document.body);
}
