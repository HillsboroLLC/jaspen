import React, { useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { API_BASE } from '../../config/apiBase';
import FieldError from '../../shared/components/FieldError';
import PublicJaspenHeader from '../../homeSections/HomePage/PublicJaspenHeader';
import './ResetPasswordPage.css';

export default function ResetPasswordPage() {
  const [searchParams] = useSearchParams();
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [status, setStatus] = useState('idle');
  const [error, setError] = useState('');
  const [fieldErrors, setFieldErrors] = useState({});

  const token = useMemo(() => String(searchParams.get('token') || '').trim(), [searchParams]);

  const submitDisabled = status === 'sending' || status === 'sent';
  const requiredLabel = (text) => (
    <>
      {text} <span className="reset-required-marker" aria-hidden="true">*</span>
    </>
  );

  const validatePassword = (value) => {
    if (!String(value || '').trim()) return 'Please enter a new password.';
    if (String(value || '').length < 8) return 'Password must be at least 8 characters.';
    return '';
  };

  const validateConfirmPassword = (value, basePassword) => {
    if (!String(value || '').trim()) return 'Please confirm your password.';
    if (value !== basePassword) return 'Passwords do not match.';
    return '';
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (!token) {
      setError('That reset link could not be verified. Request a new one and try again.');
      return;
    }
    const nextFieldErrors = {};
    const passwordError = validatePassword(password);
    if (passwordError) nextFieldErrors.password = passwordError;
    const confirmPasswordError = validateConfirmPassword(confirmPassword, password);
    if (confirmPasswordError) nextFieldErrors.confirmPassword = confirmPasswordError;
    if (Object.keys(nextFieldErrors).length > 0) {
      setFieldErrors(nextFieldErrors);
      setError('Please fix the highlighted fields.');
      return;
    }

    setStatus('sending');
    setError('');
    setFieldErrors({});
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
      setFieldErrors({});
    } catch (requestError) {
      setError(requestError?.message || 'Unable to reset your password right now.');
      setStatus('idle');
    }
  };

  return (
    <div className="reset-password-page">
      <PublicJaspenHeader />
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
          <p className="reset-required-legend"><span aria-hidden="true">*</span> Required</p>
          <label htmlFor="reset-password-new">{requiredLabel('New password')}</label>
          <input
            id="reset-password-new"
            type="password"
            value={password}
            onChange={(event) => {
              const value = event.target.value;
              setPassword(value);
              setFieldErrors((prev) => ({ ...prev, password: '' }));
              if (String(confirmPassword || '').trim()) {
                const confirmErr = validateConfirmPassword(confirmPassword, value);
                setFieldErrors((prev) => ({ ...prev, confirmPassword: confirmErr }));
              }
            }}
            onBlur={() => {
              const passwordError = validatePassword(password);
              setFieldErrors((prev) => ({ ...prev, password: passwordError }));
            }}
            disabled={submitDisabled || !token}
            aria-required="true"
            placeholder="Enter a new password"
            className={fieldErrors.password ? 'is-invalid' : ''}
            aria-invalid={Boolean(fieldErrors.password)}
            aria-describedby={fieldErrors.password ? 'reset-password-new-error' : undefined}
          />
          <FieldError id="reset-password-new-error" message={fieldErrors.password} />

          <label htmlFor="reset-password-confirm">{requiredLabel('Confirm password')}</label>
          <input
            id="reset-password-confirm"
            type="password"
            value={confirmPassword}
            onChange={(event) => {
              const value = event.target.value;
              setConfirmPassword(value);
              setFieldErrors((prev) => ({ ...prev, confirmPassword: '' }));
            }}
            onBlur={() => {
              const confirmError = validateConfirmPassword(confirmPassword, password);
              setFieldErrors((prev) => ({ ...prev, confirmPassword: confirmError }));
            }}
            disabled={submitDisabled || !token}
            aria-required="true"
            placeholder="Confirm your new password"
            className={fieldErrors.confirmPassword ? 'is-invalid' : ''}
            aria-invalid={Boolean(fieldErrors.confirmPassword)}
            aria-describedby={fieldErrors.confirmPassword ? 'reset-password-confirm-error' : undefined}
          />
          <FieldError id="reset-password-confirm-error" message={fieldErrors.confirmPassword} />

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
