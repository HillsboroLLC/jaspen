import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { submitLead } from '../../../shared/lead/leadClient';
import LeadsMockNotice from '../LeadsMockNotice';
import { QUESTIONS, QUESTION_COUNT, LEAD_SOURCE, FULL_PROFILE_INCLUDES, STYLES, STYLE_ORDER } from './assessmentData';
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

    try {
      const res = await submitLead({
        email: value.toLowerCase(),
        source: LEAD_SOURCE,
        assessmentAnswers: answers,
        decisionStyle: result?.style?.key,
      });
      if (!res || !res.ok) {
        throw new Error('Decision Profile request was not accepted.');
      }
    } catch {
      setSubmitStatus('idle');
      setEmailError(
        'We could not email your Decision Profile right now. Your result is still here, so you can try again in a moment.'
      );
      return;
    }

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
      <div className={`dsa-inner${step === 'intro' ? ' dsa-inner--wide' : ''}`}>
        {/* ── Intro ───────────────────────────────────────────── */}
        {step === 'intro' && (
          <div className="dsa-hero dsa-fade">
            {/* Left: the value proposition */}
            <div className="dsa-hero-copy">
              <p className="dsa-hero-eyebrow">
                <i className="fa-solid fa-wand-magic-sparkles" aria-hidden="true" />
                Free decision-style assessment
              </p>
              <h2 className="dsa-hero-title" id="dsa-title">
                What kind of decision‑maker are{' '}
                <span className="dsa-hero-title-accent">you</span>?
              </h2>
              <p className="dsa-hero-sub">
                Everyone has a natural way of making the big calls. Answer seven quick questions
                and uncover yours — the strengths it gives you, the blind spots to watch, and how
                to make decisions you can defend. No score. No grade. Just a sharper picture of you.
              </p>
              <ul className="dsa-hero-facts">
                <li>
                  <i className="fa-solid fa-list-check" aria-hidden="true" />7 quick questions
                </li>
                <li>
                  <i className="fa-solid fa-clock" aria-hidden="true" />About 2 minutes
                </li>
                <li>
                  <i className="fa-solid fa-lock-open" aria-hidden="true" />No sign‑up to start
                </li>
              </ul>
            </div>

            {/* Right: animated stage + the call to action */}
            <div className="dsa-hero-stage">
              <div className="dsa-stage" aria-hidden="true">
                <span className="dsa-stage-ring" />
                <span className="dsa-stage-ring dsa-stage-ring--inner" />
                <div className="dsa-stage-core">
                  <i className="fa-solid fa-fingerprint" />
                </div>
                {STYLE_ORDER.map((key, i) => (
                  <span className={`dsa-chip dsa-chip--${i + 1}`} key={key}>
                    {STYLES[key].name}
                  </span>
                ))}
              </div>

              <button
                type="button"
                className="dsa-btn dsa-btn-primary dsa-hero-cta"
                onClick={start}
              >
                Reveal my decision style
                <i className="fa-solid fa-arrow-right dsa-btn-icon" aria-hidden="true" />
              </button>
              <p className="dsa-hero-microcopy">
                {answeredCount > 0
                  ? 'Pick up right where you left off.'
                  : 'Takes about two minutes — see your result instantly.'}
              </p>
            </div>
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
                  <LeadsMockNotice />
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
                    {submitStatus === 'sending' ? 'Sending your results...' : 'Email my full Decision Profile'}
                  </button>
                  <p className="dsa-email-fine" id="dsa-email-fine">
                    One email with your profile. You will not be added to a marketing list from
                    this request.
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
            <h2 className="dsa-confirm-title">Your Decision Profile is on its way.</h2>
            <p className="dsa-confirm-body">
              Check your inbox in the next few minutes for a closer look at your decision style.
            </p>
            <button type="button" className="dsa-link" onClick={restart}>
              Take the reflection again
            </button>
          </div>
        )}
      </div>
    </section>
  );
}
