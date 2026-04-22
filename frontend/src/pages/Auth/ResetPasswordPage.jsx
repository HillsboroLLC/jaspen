import React, { useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { API_BASE } from '../../config/apiBase';
import './ResetPasswordPage.css';

export default function ResetPasswordPage() {
  const [searchParams] = useSearchParams();
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [status, setStatus] = useState('idle');
  const [error, setError] = useState('');

  const token = useMemo(() => String(searchParams.get('token') || '').trim(), [searchParams]);

  const submitDisabled = status === 'sending' || status === 'sent';

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (!token) {
      setError('That reset link could not be verified. Request a new one and try again.');
      return;
    }
    if (!password || password.length < 8) {
      setError('Password must be at least 8 characters.');
      return;
    }
    if (password !== confirmPassword) {
      setError('Passwords do not match.');
      return;
    }

    setStatus('sending');
    setError('');
    try {
      const response = await fetch(`${API_BASE}/api/v1/auth/reset-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ token, new_password: password }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data?.message || 'Unable to reset your password right now.');
      }
      setStatus('sent');
      setPassword('');
      setConfirmPassword('');
    } catch (requestError) {
      setError(requestError?.message || 'Unable to reset your password right now.');
      setStatus('idle');
    }
  };

  return (
    <div className="reset-password-page">
      <div className="reset-password-card">
        <div className="reset-password-eyebrow">ACCOUNT RECOVERY</div>
        <h1>Choose a new password</h1>
        <p className="reset-password-subtitle">
          Set a new password for your Jaspen account and we’ll get you back in.
        </p>

        {!token && (
          <div className="reset-password-alert is-error">
            <strong>That reset link could not be verified.</strong>
            <p>Request a new one from the sign-in screen and try again.</p>
          </div>
        )}

        {error && (
          <div className="reset-password-alert is-error">
            <strong>{error}</strong>
          </div>
        )}

        {status === 'sent' && (
          <div className="reset-password-alert is-success">
            <strong>Your password has been updated.</strong>
            <p>You can sign in now.</p>
          </div>
        )}

        <form className="reset-password-form" onSubmit={handleSubmit}>
          <label htmlFor="reset-password-new">New password</label>
          <input
            id="reset-password-new"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            disabled={submitDisabled || !token}
            placeholder="Enter a new password"
          />

          <label htmlFor="reset-password-confirm">Confirm password</label>
          <input
            id="reset-password-confirm"
            type="password"
            value={confirmPassword}
            onChange={(event) => setConfirmPassword(event.target.value)}
            disabled={submitDisabled || !token}
            placeholder="Confirm your new password"
          />

          <button type="submit" className="reset-password-submit" disabled={submitDisabled || !token} aria-disabled={submitDisabled || !token}>
            {status === 'sending' ? 'Updating password…' : 'Update password'}
          </button>
        </form>

        <div className="reset-password-footer">
          <Link to="/?auth=1">Back to sign in</Link>
        </div>
      </div>
    </div>
  );
}
