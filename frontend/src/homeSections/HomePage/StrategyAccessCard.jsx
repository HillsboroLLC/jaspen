import React, { useEffect, useMemo, useState } from 'react';

const TARGET_SCORE = 87;
const ANIMATION_DURATION_MS = 1200;

export default function StrategyAccessCard() {
  const [score, setScore] = useState(0);
  const [status, setStatus] = useState('Pending');
  const [email, setEmail] = useState('');
  const [authStatus, setAuthStatus] = useState('idle');
  const [authError, setAuthError] = useState('');

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
    if (authStatus === 'sent') return 'Check your inbox for a secure magic link.';
    return 'By continuing, you agree to receive product updates.';
  }, [authError, authStatus]);

  const helperClassName = authError
    ? 'strategy-card-disclaimer is-error'
    : authStatus === 'sent'
      ? 'strategy-card-disclaimer is-success'
      : 'strategy-card-disclaimer';

  const handleGoogleClick = () => {
    setAuthError(null);
    window.location.href = "https://api.jaspen.ai/api/auth/google/start";
  };

  const handleEmailSubmit = async (event) => {
    event.preventDefault();

    if (!email.trim()) {
      setAuthError('Please enter a valid email address.');
      return;
    }

    setAuthError('Email authentication is not currently available. Please use Google sign-in.');
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
          <button
            type="submit"
            className="jaspen-btn jaspen-btn-primary strategy-email-btn"
            disabled={authStatus === 'sending' || authStatus === 'sent'}
          >
            {authStatus === 'sending' ? 'Sending...' : 'Continue with email'}
          </button>
        </form>
      </div>

      <div className={helperClassName}>{helperText}</div>
    </div>
  );
}
