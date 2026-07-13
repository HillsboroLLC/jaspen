import React, { useEffect, useMemo, useState } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faArrowLeft,
  faArrowRotateRight,
  faCheck,
  faFingerprint,
  faTableList,
  faXmark,
} from '@fortawesome/free-solid-svg-icons';

import { authFetch } from '../../shared/auth/http';
import AppMenu from '../shared/AppMenu';
import { QUESTIONS } from '../../homeSections/HomePage/DecisionStyleAssessment/assessmentData';
import '../shared/internal.css';
import './DecisionProfile.css';

const SECTION_LABELS = {
  shows_up: 'How this style tends to show up',
  natural_strength: 'Natural strengths',
  watch: 'Patterns worth watching',
  decision_tendencies: 'Decision tendencies',
  jaspen_support: 'How Jaspen supports your style',
  questions: 'Questions Jaspen may emphasize',
  history: 'Decision history and emerging patterns',
  additional_context: 'Additional context',
};

function formatDate(value) {
  if (!value) return 'Not available yet';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Not available yet';
  return date.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

function ProfileSection({ title, children }) {
  return (
    <section className="decision-profile-section int-card">
      <h2>{title}</h2>
      {children}
    </section>
  );
}

function DecisionProfileModal({ open, mode, onClose, onSaved }) {
  const [index, setIndex] = useState(0);
  const [answers, setAnswers] = useState({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const question = QUESTIONS[index];
  const selected = question ? answers[question.id] : '';
  const progress = Math.round(((index + 1) / QUESTIONS.length) * 100);
  const canContinue = Boolean(selected);
  const isLast = index === QUESTIONS.length - 1;

  useEffect(() => {
    if (!open) return;
    setIndex(0);
    setAnswers({});
    setSaving(false);
    setError('');
  }, [open]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (event) => {
      if (event.key === 'Escape' && !saving) onClose?.();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose, saving]);

  if (!open || !question) return null;

  const selectAnswer = (answerId) => {
    setError('');
    setAnswers((prev) => ({ ...prev, [question.id]: answerId }));
  };

  const submit = async () => {
    if (!canContinue) return;
    if (!isLast) {
      setIndex((value) => value + 1);
      return;
    }
    setSaving(true);
    setError('');
    try {
      const response = await authFetch('/api/v1/decision-profile', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ assessment_answers: answers }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data?.error || 'Unable to save your Decision Profile right now.');
      }
      onSaved?.(data);
    } catch (err) {
      setError(err?.message || 'Unable to save your Decision Profile right now.');
      setSaving(false);
    }
  };

  const startOver = () => {
    setIndex(0);
    setAnswers({});
    setError('');
  };

  return (
    <div
      className="decision-profile-modal-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !saving) onClose?.();
      }}
    >
      <div
        className="decision-profile-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="decision-profile-modal-title"
      >
        <div className="decision-profile-modal-head">
          <div>
            <p className="int-eyebrow">{mode === 'retake' ? 'Retake assessment' : 'Decision Profile'}</p>
            <h2 id="decision-profile-modal-title">
              {mode === 'retake' ? 'Update your Decision Profile' : 'Find your Decision Profile'}
            </h2>
          </div>
          <button className="decision-profile-icon-btn" type="button" onClick={onClose} disabled={saving} aria-label="Close">
            <FontAwesomeIcon icon={faXmark} />
          </button>
        </div>

        {mode === 'retake' && (
          <p className="decision-profile-retake-note">
            Retaking updates your current profile and keeps the earlier completion as part of your profile history.
          </p>
        )}

        <div className="decision-profile-progress" aria-label={`Question ${index + 1} of ${QUESTIONS.length}`}>
          <span style={{ width: `${progress}%` }} />
        </div>

        <div className="decision-profile-question">
          <p className="decision-profile-step">Question {index + 1} of {QUESTIONS.length}</p>
          <h3>{question.prompt}</h3>
          {question.help && <p>{question.help}</p>}
        </div>

        <div className="decision-profile-options" role="radiogroup" aria-label={question.prompt}>
          {question.options.map((option) => {
            const active = selected === option.id;
            return (
              <button
                key={option.id}
                type="button"
                className={`decision-profile-option ${active ? 'is-selected' : ''}`}
                onClick={() => selectAnswer(option.id)}
                aria-checked={active}
                role="radio"
              >
                <span className="decision-profile-option-mark" aria-hidden="true">
                  {active && <FontAwesomeIcon icon={faCheck} />}
                </span>
                <span>{option.label}</span>
              </button>
            );
          })}
        </div>

        {error && <div className="decision-profile-error" role="alert">{error}</div>}

        <div className="decision-profile-modal-actions">
          <button
            className="int-btn int-btn-ghost"
            type="button"
            onClick={() => setIndex((value) => Math.max(0, value - 1))}
            disabled={saving || index === 0}
          >
            <FontAwesomeIcon icon={faArrowLeft} />
            Back
          </button>
          <button className="int-btn int-btn-ghost" type="button" onClick={startOver} disabled={saving}>
            <FontAwesomeIcon icon={faArrowRotateRight} />
            Start over
          </button>
          <button className="int-btn int-btn-primary" type="button" onClick={submit} disabled={!canContinue || saving}>
            {saving ? 'Saving your profile...' : isLast ? 'Save profile' : 'Next'}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function DecisionProfile() {
  const [state, setState] = useState({ loading: true, error: '', data: null });
  const [modalOpen, setModalOpen] = useState(false);
  const [modalMode, setModalMode] = useState('new');

  const profile = state.data?.profile || null;
  const sections = profile?.sections || {};

  const loadProfile = async () => {
    setState((prev) => ({ ...prev, loading: true, error: '' }));
    try {
      const response = await authFetch('/api/v1/decision-profile');
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data?.error || 'Unable to load your Decision Profile.');
      setState({ loading: false, error: '', data });
    } catch (err) {
      setState({ loading: false, error: err?.message || 'Unable to load your Decision Profile.', data: null });
    }
  };

  useEffect(() => {
    loadProfile();
  }, []);

  const summaryMeta = useMemo(() => {
    if (!profile) return [];
    return [
      { label: 'Completed', value: formatDate(profile.completed_at) },
      { label: 'Last updated', value: formatDate(profile.last_updated_at) },
      { label: 'Version', value: `Profile ${profile.version || 1}` },
    ];
  }, [profile]);

  const openAssessment = (mode = 'new') => {
    setModalMode(mode);
    setModalOpen(true);
  };

  const onSaved = (data) => {
    setState({ loading: false, error: '', data });
    setModalOpen(false);
  };

  return (
    <div className="decision-profile-page int-page">
      <AppMenu />
      <div className="decision-profile-inner int-page-inner">
        <header className="int-page-head decision-profile-head">
          <div>
            <p className="int-eyebrow">Decision Profile</p>
            <h1>Understand how you naturally decide.</h1>
            <p>
              Your profile turns the assessment into a practical reference you can use while framing,
              testing, and explaining real decisions in Jaspen.
            </p>
          </div>
          {profile && (
            <button className="int-btn int-btn-primary" type="button" onClick={() => openAssessment('retake')}>
              Retake assessment
            </button>
          )}
        </header>

        {state.loading && <div className="master-admin-state">Loading your Decision Profile...</div>}
        {!state.loading && state.error && <div className="master-admin-state is-error">{state.error}</div>}

        {!state.loading && !state.error && !profile && (
          <section className="decision-profile-empty int-card">
            <div className="decision-profile-empty-icon" aria-hidden="true">
              <FontAwesomeIcon icon={faFingerprint} />
            </div>
            <h2>Your Decision Profile is ready when you are.</h2>
            <p>
              Take the short assessment to see your decision style, response patterns, and where Jaspen can support the way you already think.
            </p>
            <button className="int-btn int-btn-primary" type="button" onClick={() => openAssessment('new')}>
              Take the assessment
            </button>
          </section>
        )}

        {!state.loading && !state.error && profile && (
          <>
            <section className="decision-profile-summary int-card">
              <div className="decision-profile-summary-main">
                <p className="int-eyebrow">Decision Style</p>
                <h2>{profile.style_name}</h2>
                <p>{profile.interpretation}</p>
              </div>
              <div className="decision-profile-summary-meta" aria-label="Profile dates">
                {summaryMeta.map((item) => (
                  <div key={item.label}>
                    <span>{item.label}</span>
                    <strong>{item.value}</strong>
                  </div>
                ))}
              </div>
            </section>

            <section className="decision-profile-table-card int-card">
              <div className="int-card-head">
                <div>
                  <h2>Response profile</h2>
                  <p>Your answers are interpreted row by row so the profile stays explainable.</p>
                </div>
                <FontAwesomeIcon icon={faTableList} aria-hidden="true" />
              </div>
              <div className="decision-profile-table-wrap">
                <table className="decision-profile-table">
                  <thead>
                    <tr>
                      <th>Question</th>
                      <th>Decision tendency</th>
                      <th>Your response</th>
                      <th>What it may mean</th>
                    </tr>
                  </thead>
                  <tbody>
                    {profile.responses.map((row) => (
                      <tr key={row.question_id}>
                        <td>{row.question}</td>
                        <td>{row.tendency}</td>
                        <td><span className="decision-profile-response-pill">{row.answer_label}</span></td>
                        <td>{row.meaning}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="decision-profile-mobile-rows">
                {profile.responses.map((row) => (
                  <article className="decision-profile-response-card" key={row.question_id}>
                    <h3>{row.question}</h3>
                    <dl>
                      <div>
                        <dt>Decision tendency</dt>
                        <dd>{row.tendency}</dd>
                      </div>
                      <div>
                        <dt>Your response</dt>
                        <dd><span className="decision-profile-response-pill">{row.answer_label}</span></dd>
                      </div>
                      <div>
                        <dt>What it may mean</dt>
                        <dd>{row.meaning}</dd>
                      </div>
                    </dl>
                  </article>
                ))}
              </div>
            </section>

            <div className="decision-profile-section-grid">
              <ProfileSection title={SECTION_LABELS.shows_up}>
                <p>{sections.shows_up}</p>
              </ProfileSection>
              <ProfileSection title={SECTION_LABELS.natural_strength}>
                <p>{sections.natural_strength}</p>
              </ProfileSection>
              <ProfileSection title={SECTION_LABELS.watch}>
                <p>{sections.watch}</p>
              </ProfileSection>
              <ProfileSection title={SECTION_LABELS.decision_tendencies}>
                <div className="decision-profile-tendencies">
                  {(sections.decision_tendencies || []).map((item, idx) => (
                    <div key={`${item.label}-${idx}`}>
                      <span>{item.label}</span>
                      <strong>{item.value}</strong>
                    </div>
                  ))}
                </div>
              </ProfileSection>
              <ProfileSection title={SECTION_LABELS.jaspen_support}>
                <p>{sections.jaspen_support}</p>
              </ProfileSection>
              <ProfileSection title={SECTION_LABELS.questions}>
                <ul className="decision-profile-list">
                  {(sections.questions || []).map((item) => <li key={item}>{item}</li>)}
                </ul>
              </ProfileSection>
              <ProfileSection title={SECTION_LABELS.history}>
                <p>{sections.history}</p>
              </ProfileSection>
              <ProfileSection title={SECTION_LABELS.additional_context}>
                <p>{sections.additional_context}</p>
              </ProfileSection>
            </div>
          </>
        )}
      </div>

      <DecisionProfileModal
        open={modalOpen}
        mode={modalMode}
        onClose={() => setModalOpen(false)}
        onSaved={onSaved}
      />
    </div>
  );
}
