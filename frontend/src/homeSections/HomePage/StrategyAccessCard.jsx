import React, { useEffect, useMemo, useState } from 'react';
import { useAuth } from '../../shared/auth/AuthContext';
import { authFetch } from '../../shared/auth/http';
import { API_BASE } from '../../config/apiBase';
import { readAuthQueryNotice } from './authStatus';
import AuthModal from './AuthModal';
import StripeCheckout from '../../jaspenInterface/Account/StripeCheckout';
import {
  readPendingIntakeContext,
  writePendingIntakeContext,
  clearPendingIntakeContext,
  getOrCreatePendingThreadId,
  clearPendingIntakeThreadId,
  runExclusiveHandoff,
} from '../../shared/auth/pendingIntakeContext';

// Carries pasted homepage context into the authenticated workspace by
// continuing the SAME intake conversation the workspace itself uses
// (conversation/start) — never a mismatched endpoint, never a bearer token
// (auth here is cookie-based; authFetch sends credentials + CSRF).
// Returns true if it navigated the browser away (caller should stop), false
// if there was no context to carry (caller proceeds with its normal redirect).
//
// Wrapped in runExclusiveHandoff + a reused thread_id so a double-click, a
// retried login, or a race between this and the Google OAuth callback path
// converges on ONE thread instead of creating duplicates.
function continueWithPendingContext(heroContext) {
  return runExclusiveHandoff(async () => {
    const pending = readPendingIntakeContext();
    const context = (pending || heroContext || '').trim();
    if (!context) return false;

    const threadId = getOrCreatePendingThreadId();
    try {
      const res = await authFetch('/api/v1/ai-agent/conversation/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        // strategy_objective is sent explicitly — and must stay 'balanced' —
        // because the homepage computed its readiness promise under
        // 'balanced' (public_intake.py). Omitting it lets conversation/start
        // re-INFER an objective from the text (e.g. cost-heavy briefs flip
        // to Cost Optimization), so the workspace would open under a
        // different profile than the one the visitor was just shown. Same
        // contract as the workspace composer, which always sends its pill.
        body: JSON.stringify({ message: context, thread_id: threadId, strategy_objective: 'balanced' }),
      });
      const data = await res.json().catch(() => ({}));
      const sid = data?.thread_id || data?.session_id;
      if (res.ok && sid) {
        // Clear only on confirmed success — "nothing you've shared will be lost"
        // is a promise the UI makes in writing. On any failure both keys stay
        // in sessionStorage: /new recovers the context as a composer prefill,
        // and the same thread_id is reused if the user retries.
        clearPendingIntakeContext();
        clearPendingIntakeThreadId();
        window.location.href = `/new?sid=${encodeURIComponent(sid)}`;
        return true;
      }
    } catch { /* fall through to normal redirect; pending keys intentionally kept */ }
    // Keep the key for the /new fallback, and make sure it's populated even when
    // the context only existed in React state (in-page modal flow).
    if (!pending) writePendingIntakeContext(context);
    return false;
  });
}

const TARGET_SCORE = 87;
const ANIMATION_DURATION_MS = 1200;

const SELECTABLE_PLANS = [
  { key: 'free',       label: 'Free',       priceLabel: 'Free',     paid: false, salesOnly: false },
  { key: 'essential',  label: 'Essential',  priceLabel: '$39/mo',   paid: true,  salesOnly: false },
  { key: 'team',       label: 'Team',       priceLabel: '$129/mo',  paid: true,  salesOnly: false },
  { key: 'enterprise', label: 'Enterprise', priceLabel: '$299/mo',  paid: true,  salesOnly: true  },
];

export default function StrategyAccessCard({ initialFlowMode = 'signin', initialPlan = 'free', heroContext = '' }) {
  const { login, signup, mfaEnforcement, setMfaEnforcement } = useAuth();
  const [score, setScore] = useState(0);
  const [status, setStatus] = useState('Pending');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [authStatus, setAuthStatus] = useState('idle');
  const [authMode, setAuthMode] = useState('email');
  const [flowMode, setFlowMode] = useState(initialFlowMode);
  const [authError, setAuthError] = useState('');
  const [authErrorDetail, setAuthErrorDetail] = useState('');
  const [showAuthModal, setShowAuthModal] = useState(false);
  const [authModalMode, setAuthModalMode] = useState('email');
  const [mfaData, setMfaData] = useState(null);
  const [selectedPlan, setSelectedPlan] = useState(initialPlan);
  const [showStripe, setShowStripe] = useState(false);
  const [stripeToken, setStripeToken] = useState(null);
  const selectedPlanMeta = SELECTABLE_PLANS.find(p => p.key === selectedPlan) || SELECTABLE_PLANS[0];

  // Capture the URL auth notice ONCE at component creation time (lazy initializer).
  // This runs before any effects fire, so it always sees the original URL params
  // even after HomePage cleans them via setSearchParams. Subsequent re-renders
  // don't re-read window.location.search, eliminating the message flash.
  const [initialAuthNotice] = useState(() => {
    if (typeof window === 'undefined') return null;
    try { return readAuthQueryNotice(window.location.search || ''); } catch { return null; }
  });

  // Clean transient auth query params from the address bar after we've captured
  // the notice. Keep any unrelated params (plan/ref/etc.) intact.
  useEffect(() => {
    if (typeof window === 'undefined') return;
    try {
      const url = new URL(window.location.href);
      const hadTransientAuthParams = (
        url.searchParams.has('auth')
        || url.searchParams.has('error')
        || url.searchParams.has('signed_out')
      );
      if (!hadTransientAuthParams) return;
      url.searchParams.delete('auth');
      url.searchParams.delete('error');
      url.searchParams.delete('signed_out');
      const cleaned = `${url.pathname}${url.search}${url.hash}`;
      window.history.replaceState({}, '', cleaned);
    } catch (_err) {
      // Ignore URL parsing failures and leave current URL unchanged.
    }
  }, []);

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
    if (authStatus === 'reset_sent') return "If that account exists, we'll send a password reset link shortly.";
    if (authStatus === 'sent') return 'Authenticated. Redirecting...';
    if (initialAuthNotice?.message) return initialAuthNotice.message;
    return 'By continuing, you agree to receive product updates.';
  }, [authError, authStatus, initialAuthNotice]);

  const helperDetail = useMemo(() => {
    if (authErrorDetail) return authErrorDetail;
    return initialAuthNotice?.detail || '';
  }, [authErrorDetail, initialAuthNotice]);

  const queryNoticeTone = initialAuthNotice?.tone || '';

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
    if (flowMode === 'signup' && !String(name || '').trim()) {
      setAuthError('Please enter your name.');
      setAuthErrorDetail('');
      return;
    }

    setAuthStatus('sending');
    setAuthError('');
    try {
      if (flowMode === 'signup') {
        const signupAttempt = await signup(normalizedEmail, password, String(name).trim());
        if (signupAttempt?.success) {
          if (selectedPlanMeta.paid) {
            setStripeToken(signupAttempt.token || null);
            setShowStripe(true);
            setAuthStatus('idle');
            return;
          }
          // If the visitor analyzed context on the homepage, continue that same
          // conversation in the workspace instead of losing it at the auth wall.
          setAuthStatus('sent');
          if (await continueWithPendingContext(heroContext)) return;
          window.location.href = getPostAuthRedirect();
          return;
        }
        setAuthError(signupAttempt?.error || 'Unable to create account right now.');
        setAuthErrorDetail(signupAttempt?.detail || '');
        setAuthStatus('idle');
        return;
      }

      const loginAttempt = await login(normalizedEmail, password);

      if (loginAttempt?.mfaRequired) {
        setAuthStatus('idle');
        setMfaData(loginAttempt);
        setShowAuthModal(true);
        setAuthModalMode('email');
        return;
      }

      if (loginAttempt?.success) {
        setAuthStatus('sent');
        // Existing users deserve the same context handoff as new signups.
        if (await continueWithPendingContext(heroContext)) return;
        window.location.href = getPostAuthRedirect();
        return;
      }

      setAuthError(loginAttempt?.error || 'Incorrect email or password.');
      setAuthErrorDetail(loginAttempt?.detail || '');
      setAuthStatus('idle');
    } catch (error) {
      setAuthError(error?.message || 'Unable to sign in right now.');
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
            <div className="strategy-auth-tabs">
              <button
                type="button"
                className={`strategy-auth-tab ${flowMode === 'signin' ? 'is-active' : ''}`}
                onClick={() => { setFlowMode('signin'); setAuthError(''); setAuthErrorDetail(''); setAuthStatus('idle'); }}
              >
                Sign in
              </button>
              <button
                type="button"
                className={`strategy-auth-tab ${flowMode === 'signup' ? 'is-active' : ''}`}
                onClick={() => { setFlowMode('signup'); setAuthError(''); setAuthErrorDetail(''); setAuthStatus('idle'); }}
              >
                Create account
              </button>
            </div>
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
        {flowMode === 'signup' && authMode !== 'forgot' && (
          <div className="strategy-plan-selector">
            {SELECTABLE_PLANS.map(p => (
              <button
                key={p.key}
                type="button"
                className={`strategy-plan-option${p.key === 'enterprise' ? ' is-enterprise' : ''}${selectedPlan === p.key ? ' is-active' : ''}`}
                onClick={() => setSelectedPlan(p.key)}
              >
                <span className="strategy-plan-option-label">{p.label}</span>
                <span className="strategy-plan-option-price">{p.priceLabel}</span>
              </button>
            ))}
          </div>
        )}

        <form className="strategy-card-form" onSubmit={authMode === 'forgot' ? handleForgotPassword : handleEmailSubmit}>
          {flowMode === 'signup' && authMode !== 'forgot' && (
            <input
              type="text"
              className="strategy-email-input"
              placeholder="Your name"
              aria-label="Full name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              disabled={authStatus === 'sending' || authStatus === 'sent'}
            />
          )}
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
            disabled={authStatus === 'sending' || authStatus === 'sent'}
            aria-disabled={authStatus === 'sending' || authStatus === 'sent'}
          >
            {authStatus === 'sending'
              ? (authMode === 'forgot' ? 'Sending reset link…' : 'One moment…')
              : authMode === 'forgot'
                ? 'Send reset link'
                : flowMode === 'signup'
                  ? selectedPlanMeta.paid
                    ? `Continue to payment · ${selectedPlanMeta.priceLabel}`
                    : 'Create free account'
                  : 'Sign in'}
          </button>
        </form>
        <div className="strategy-card-meta">
          {authMode === 'forgot' ? (
            <button
              type="button"
              className="strategy-meta-link"
              onClick={() => { setAuthMode('email'); setAuthStatus('idle'); setAuthError(''); setAuthErrorDetail(''); }}
            >
              Back to sign in
            </button>
          ) : (
            <button
              type="button"
              className="strategy-meta-link"
              onClick={() => { setAuthMode('forgot'); setAuthStatus('idle'); setAuthError(''); setAuthErrorDetail(''); }}
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

      {showStripe && (
        <StripeCheckout
          mode="subscribe"
          planKey={selectedPlan}
          planLabel={selectedPlanMeta.label}
          priceLabel={selectedPlanMeta.priceLabel}
          onSuccess={() => { setShowStripe(false); window.location.href = '/new'; }}
          onClose={() => setShowStripe(false)}
        />
      )}
    </div>
  );
}
