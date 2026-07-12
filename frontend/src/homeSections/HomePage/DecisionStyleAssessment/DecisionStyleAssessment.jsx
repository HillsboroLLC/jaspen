import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { API_BASE } from '../../../config/apiBase';
import { QUESTIONS, QUESTION_COUNT, LEAD_SOURCE, FULL_PROFILE_INCLUDES } from './assessmentData';
import { deriveProvisionalStyle } from './provisionalResult';
import './DecisionStyleAssessment.css';

// Homepage section: an inline Jaspen Decision Style Assessment. Replaces the
// Excel Decision Scorecard download that used to live in this slot.
//
// Intent (product philosophy): help the user RECOGNIZE patterns in how they
// decide — not evaluate, grade, rank, or compare them to Jaspen. There is no
// score. Style labels are provisional placeholders (see assessmentData.js) and
// the result mapping is a clearly-separated mock (see provisionalResult.js) so
// the real Decision Profile framework can drop in later without UI changes.
//
// Patterns follow the existing homepage sections (e.g. HowScoreWorks):
// functional component, site palette only (navy #161f3b, magenta #a0036c,
// cream #f8f5f0), Font Awesome solid icons, no gradients, no emojis. Animation
// is CSS-only (the homepage does not use framer-motion), keeping the section
// light and preserving page performance.

const LEADS_ENDPOINT = `${API_BASE}/api/v1/public/leads`;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const STORAGE_KEY = 'jaspen_dsa_v1'; // lightweight refresh-recovery only

// Steps: 'intro' -> 'question' -> 'result' -> 'confirmed'.
function loadSaved() {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return null;
    const answers = parsed.answers && typeof parsed.answers === 'object' ? parsed.answers : {};
    const step = ['intro', 'question', 'result'].includes(parsed.step) ? parsed.step : 'intro';
    const qIndex =
      Number.isInteger(parsed.qIndex) && parsed.qIndex >= 0 && parsed.qIndex < QUESTION_COUNT
        ? parsed.qIndex
        : 0;
    return { answers, step, qIndex };
  } catch {
    return null; // never let storage issues break the experience
  }
}

export default function DecisionStyleAssessment() {
  const saved = useMemo(() => loadSaved(), []);
  const [step, setStep] = useState(saved ? saved.step : 'intro');
  const [qIndex, setQIndex] = useState(saved ? saved.qIndex : 0);
  const [answers, setAnswers] = useState(saved ? saved.answers : {});
  const [direction, setDirection] = useState('forward'); // drives the swipe
  const [email, setEmail] = useState('');
  const [emailError, setEmailError] = useState('');
  const [submitStatus, setSubmitStatus] = useState('idle'); // idle | sending | done
  const [saveOk, setSaveOk] = useState(true);

  const liveRef = useRef(null);

  // Persist lightweight progress for accidental-refresh recovery. We never
  // persist the email or the confirmed state.
  useEffect(() => {
    try {
      if (step === 'confirmed') return;
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ step, qIndex, answers }));
    } catch {
      /* ignore storage failures */
    }
  }, [step, qIndex, answers]);

  const clearSaved = useCallback(() => {
    try {
      window.localStorage.removeItem(STORAGE_KEY);
    } catch {
      /* ignore */
    }
  }, []);

  const question = QUESTIONS[qIndex];
  const answeredCount = Object.keys(answers).length;
  const currentAnswer = question ? answers[question.id] : undefined;

  const start = () => {
    setDirection('forward');
    setStep('question');
    setQIndex(0);
  };

  const select = (optionId) => {
    setAnswers((prev) => ({ ...prev, [question.id]: optionId }));
    // Advance shortly after selection so the choice is visibly registered.
    setDirection('forward');
    window.setTimeout(() => {
      if (qIndex < QUESTION_COUNT - 1) {
        setQIndex((i) => i + 1);
      } else {
        setStep('result');
      }
    }, 180);
  };

  const goBack = () => {
    setDirection('back');
    if (step === 'result') {
      setStep('question');
      setQIndex(QUESTION_COUNT - 1);
    } else if (qIndex > 0) {
      setQIndex((i) => i - 1);
    } else {
      setStep('intro');
    }
  };

  const restart = () => {
    clearSaved();
    setAnswers({});
    setQIndex(0);
    setEmail('');
    setEmailError('');
    setSubmitStatus('idle');
    setSaveOk(true);
    setDirection('back');
    setStep('intro');
  };

  const result = useMemo(
    () => (step === 'result' || step === 'confirmed' ? deriveProvisionalStyle(answers) : null),
    [step, answers]
  );

  const handleSubmit = async (e) => {
    e.preventDefault();
    const value = email.trim();
    if (!EMAIL_RE.test(value)) {
      setEmailError('Please enter a valid email address.');
      return;
    }
    setEmailError('');
    setSubmitStatus('sending');

    // Best-effort capture. A backend hiccup must never trap the user on this
    // screen, so we always advance to a graceful confirmation; the copy adapts
    // to whether the save was actually confirmed. No email is sent yet (no
    // automation exists), so we never claim delivery.
    let ok = false;
    try {
      const res = await fetch(LEADS_ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: value, source: LEAD_SOURCE }),
      });
      ok = !!res && res.ok;
    } catch {
      ok = false;
    }

    setSaveOk(ok);
    setSubmitStatus('done');
    clearSaved();
    setStep('confirmed');
  };

  // Move focus/announce on step changes for screen-reader users.
  useEffect(() => {
    if (liveRef.current) liveRef.current.focus({ preventScroll: true });
  }, [step, qIndex]);

  const progressPct = Math.round(((qIndex + (currentAnswer ? 1 : 0)) / QUESTION_COUNT) * 100);

  return (
    <section className="dsa" id="decision-style-assessment" aria-labelledby="dsa-title">
      <div className="dsa-inner">
        {/* ── Intro ───────────────────────────────────────────── */}
        {step === 'intro' && (
          <div className="dsa-intro dsa-fade">
            <p className="dsa-eyebrow">A two-minute reflection</p>
            <h2 className="dsa-title" id="dsa-title">
              How do you make decisions?
            </h2>
            <p className="dsa-sub">
              From a quick gut call to a careful weighing of the options, everyone approaches
              important choices a little differently. Answer seven short questions and see the
              patterns that shape how you decide.
            </p>
            <button type="button" className="dsa-btn dsa-btn-primary" onClick={start}>
              Start the reflection
              <i className="fa-solid fa-arrow-right dsa-btn-icon" aria-hidden="true" />
            </button>
            <p className="dsa-reassure">
              <i className="fa-solid fa-circle-info dsa-reassure-icon" aria-hidden="true" />
              No score, no grade. Just a clearer picture of your natural approach.
            </p>
            {answeredCount > 0 && (
              <button type="button" className="dsa-link" onClick={start}>
                Resume where you left off
              </button>
            )}
          </div>
        )}

        {/* ── Questions ───────────────────────────────────────── */}
        {step === 'question' && question && (
          <div className="dsa-question-wrap">
            <div className="dsa-progress" aria-hidden="false">
              <div className="dsa-progress-meta">
                <span className="dsa-progress-count">
                  Question {qIndex + 1} of {QUESTION_COUNT}
                </span>
                <button type="button" className="dsa-link dsa-restart" onClick={restart}>
                  Start over
                </button>
              </div>
              <div
                className="dsa-progress-track"
                role="progressbar"
                aria-valuenow={progressPct}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-label="Assessment progress"
              >
                <span className="dsa-progress-fill" style={{ width: `${progressPct}%` }} />
              </div>
            </div>

            <div
              className={`dsa-card dsa-swipe dsa-swipe--${direction}`}
              key={question.id}
              ref={liveRef}
              tabIndex={-1}
            >
              <fieldset className="dsa-fieldset">
                <legend className="dsa-legend">{question.prompt}</legend>
                {question.help && <p className="dsa-help">{question.help}</p>}
                <div className="dsa-options" role="radiogroup" aria-label={question.prompt}>
                  {question.options.map((opt) => {
                    const checked = currentAnswer === opt.id;
                    return (
                      <label
                        key={opt.id}
                        className={`dsa-option${checked ? ' is-selected' : ''}`}
                      >
                        <input
                          type="radio"
                          className="dsa-option-input"
                          name={question.id}
                          value={opt.id}
                          checked={checked}
                          onChange={() => select(opt.id)}
                        />
                        <span className="dsa-option-mark" aria-hidden="true" />
                        <span className="dsa-option-label">{opt.label}</span>
                      </label>
                    );
                  })}
                </div>
              </fieldset>
            </div>

            <div className="dsa-nav">
              <button type="button" className="dsa-btn dsa-btn-ghost" onClick={goBack}>
                <i className="fa-solid fa-arrow-left dsa-btn-icon-left" aria-hidden="true" />
                Back
              </button>
              <span className="dsa-nav-hint">Pick the closest fit — you can change it.</span>
            </div>
          </div>
        )}

        {/* ── Partial result + email capture ──────────────────── */}
        {step === 'result' && result && (
          <div className="dsa-result dsa-fade" ref={liveRef} tabIndex={-1}>
            <div className="dsa-result-head">
              <p className="dsa-result-kicker">
                <i className="fa-solid fa-circle-check dsa-result-kicker-icon" aria-hidden="true" />
                Reflection complete
              </p>
              <p className="dsa-result-lead">Your decision style appears to be</p>
              <h2 className="dsa-result-style">{result.style.name}</h2>
              <p className="dsa-result-blurb">{result.style.blurb}</p>
              {result.isFallback && (
                <p className="dsa-result-note">
                  Your answers didn&apos;t point strongly in one direction yet — the full profile
                  will explore your mix in more detail.
                </p>
              )}
            </div>

            <div className="dsa-result-grid">
              <div className="dsa-includes">
                <p className="dsa-includes-title">Your full Decision Profile will include</p>
                <ul className="dsa-includes-list">
                  {FULL_PROFILE_INCLUDES.map((item) => (
                    <li key={item}>
                      <i className="fa-solid fa-check dsa-includes-check" aria-hidden="true" />
                      {item}
                    </li>
                  ))}
                </ul>
              </div>

              <div className="dsa-email-card">
                <form className="dsa-email-form" onSubmit={handleSubmit} noValidate>
                  <label className="dsa-email-label" htmlFor="dsa-email">
                    Where should we send your full profile?
                  </label>
                  <input
                    id="dsa-email"
                    type="email"
                    className="dsa-email-input"
                    placeholder="you@company.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    autoComplete="email"
                    aria-invalid={!!emailError}
                    aria-describedby={emailError ? 'dsa-email-error' : 'dsa-email-fine'}
                  />
                  {emailError && (
                    <p className="dsa-email-error" id="dsa-email-error" role="alert">
                      {emailError}
                    </p>
                  )}
                  <button
                    type="submit"
                    className="dsa-btn dsa-btn-primary dsa-email-submit"
                    disabled={submitStatus === 'sending'}
                  >
                    {submitStatus === 'sending' ? 'Saving…' : 'Email my full Decision Profile'}
                  </button>
                  <p className="dsa-email-fine" id="dsa-email-fine">
                    One email with your profile. We may share the occasional Jaspen update.
                    Unsubscribe anytime.
                  </p>
                </form>
              </div>
            </div>

            <div className="dsa-result-foot">
              <button type="button" className="dsa-link" onClick={goBack}>
                <i className="fa-solid fa-arrow-left dsa-btn-icon-left" aria-hidden="true" />
                Change my last answer
              </button>
              <button type="button" className="dsa-link" onClick={restart}>
                Start over
              </button>
            </div>
          </div>
        )}

        {/* ── Confirmation ────────────────────────────────────── */}
        {step === 'confirmed' && result && (
          <div className="dsa-confirm dsa-fade" ref={liveRef} tabIndex={-1} role="status">
            <i className="fa-solid fa-envelope-circle-check dsa-confirm-icon" aria-hidden="true" />
            {saveOk ? (
              <>
                <h2 className="dsa-confirm-title">You&apos;re on the list.</h2>
                <p className="dsa-confirm-body">
                  Your email is saved. As an <strong>{result.style.name}</strong>, your full
                  Decision Profile will be on its way the moment the results experience is live.
                </p>
              </>
            ) : (
              <>
                <h2 className="dsa-confirm-title">You&apos;re all set.</h2>
                <p className="dsa-confirm-body">
                  We couldn&apos;t confirm the save just now, but your reflection is safe here. As
                  an <strong>{result.style.name}</strong>, your full Decision Profile will follow
                  once the results experience is live.
                </p>
              </>
            )}
            <button type="button" className="dsa-link" onClick={restart}>
              Take the reflection again
            </button>
          </div>
        )}
      </div>
    </section>
  );
}
