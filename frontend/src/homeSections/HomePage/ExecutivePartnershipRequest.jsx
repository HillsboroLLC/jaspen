import React, { useCallback, useEffect, useRef, useState } from 'react';
import { API_BASE } from '../../config/apiBase';
import './ExecutivePartnershipRequest.css';

// Values mirror the backend's accepted sets exactly. Anything outside them is
// rejected server-side rather than coerced, so these must not drift.
export const ENGAGEMENT_OPTIONS = [
  { value: 'executive_decision_intensive', label: 'Executive Decision Intensive ($25,000)' },
  { value: 'strategic_advisor_partnership', label: 'Strategic Advisor Partnership ($100,000)' },
  { value: 'undecided', label: "I'm not sure yet" },
];

const IMPACT_OPTIONS = [
  { value: 'under_250k', label: 'Under $250K' },
  { value: '250k_1m', label: '$250K–$1M' },
  { value: '1m_5m', label: '$1M–$5M' },
  { value: '5m_25m', label: '$5M–$25M' },
  { value: '25m_plus', label: '$25M+' },
  { value: 'unsure', label: 'Unsure' },
];

const TIMELINE_OPTIONS = [
  { value: 'within_30_days', label: 'Within 30 days' },
  { value: '1_3_months', label: '1–3 months' },
  { value: '3_6_months', label: '3–6 months' },
  { value: '6_months_plus', label: 'More than 6 months' },
];

const PARTICIPANT_OPTIONS = [
  { value: 'ceo', label: 'CEO' },
  { value: 'founder', label: 'Founder' },
  { value: 'coo', label: 'COO' },
  { value: 'cfo', label: 'CFO' },
  { value: 'cio', label: 'CIO' },
  { value: 'business_unit_leader', label: 'Business Unit Leader' },
  { value: 'pmo', label: 'PMO' },
  { value: 'strategy_team', label: 'Strategy Team' },
  { value: 'other', label: 'Other' },
];

const AUTHORITY_OPTIONS = [
  { value: 'primary', label: 'Yes' },
  { value: 'shared', label: 'I share the decision' },
  { value: 'influencer', label: 'No, but I influence the decision' },
];

const OUTCOME_EXAMPLES = [
  'Prioritize competing initiatives',
  'Allocate capital',
  'Reduce costs',
  'Increase revenue',
  'Improve EBITDA',
  'Decide between strategic options',
];

// Matches the server's per-field caps, which exist so a thorough answer never
// trips the 8KB request limit.
const LIMITS = { decision_description: 2000, desired_outcome: 1000, additional_notes: 2000 };

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])';

/** A labelled field whose hint is associated by aria-describedby rather than
 *  nested inside the <label>. Nesting it would fold the whole hint into the
 *  control's accessible name, so a screen reader would announce the email
 *  field as "Work email Use your company email address; personal email
 *  providers are not accepted." */
function Field({ id, label, hint, required = false, className = '', children }) {
  const hintId = hint ? `${id}-hint` : undefined;
  return (
    <div className={`epr-field ${className}`.trim()}>
      <label htmlFor={id}>
        {label}
        {required && <span aria-hidden="true">*</span>}
      </label>
      {children({ id, 'aria-describedby': hintId, required })}
      {hint && <small id={hintId}>{hint}</small>}
    </div>
  );
}

function splitName(fullName) {
  const parts = String(fullName || '').trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return { first_name: '', last_name: '' };
  if (parts.length === 1) return { first_name: parts[0], last_name: '' };
  return { first_name: parts[0], last_name: parts.slice(1).join(' ') };
}

export default function ExecutivePartnershipRequest({ initialEngagement = 'undecided', onClose }) {
  const [values, setValues] = useState({
    fullName: '', company: '', title: '', email: '', phone: '',
    engagement: initialEngagement,
    decisionDescription: '', desiredOutcome: '',
    financialImpact: '', timeline: '',
    participants: [],
    authority: '',
    additionalNotes: '',
    website: '',
  });
  const [status, setStatus] = useState({ state: 'idle', message: '' });
  const dialogRef = useRef(null);
  const headingRef = useRef(null);
  const returnFocusRef = useRef(null);

  const set = (field) => (event) => {
    const value = event.target.type === 'checkbox' ? event.target.checked : event.target.value;
    setValues(current => ({ ...current, [field]: value }));
  };

  const toggleParticipant = (role) => setValues(current => ({
    ...current,
    participants: current.participants.includes(role)
      ? current.participants.filter(item => item !== role)
      : [...current.participants, role],
  }));

  const close = useCallback(() => {
    onClose?.();
    // Send focus back where it came from rather than dropping the user at the
    // top of the document.
    returnFocusRef.current?.focus?.();
  }, [onClose]);

  useEffect(() => {
    returnFocusRef.current = document.activeElement;
    headingRef.current?.focus();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        close();
        return;
      }
      if (event.key !== 'Tab') return;
      const focusable = dialogRef.current?.querySelectorAll(FOCUSABLE);
      if (!focusable?.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [close]);

  const submit = async (event) => {
    event.preventDefault();
    if (status.state === 'submitting') return;

    if (values.participants.length === 0) {
      setStatus({ state: 'error', message: 'Select at least one participant.' });
      return;
    }

    setStatus({ state: 'submitting', message: '' });
    const params = new URLSearchParams(window.location.search);
    const { first_name, last_name } = splitName(values.fullName);

    try {
      const response = await fetch(`${API_BASE}/api/v1/public/leads/advisory-inquiry`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source: 'advisory-partnerships',
          first_name,
          last_name,
          email: values.email,
          company: values.company,
          title: values.title,
          phone: values.phone,
          engagement: values.engagement,
          decision_description: values.decisionDescription,
          desired_outcome: values.desiredOutcome,
          financial_impact_band: values.financialImpact || null,
          decision_timeline: values.timeline,
          participants: values.participants,
          decision_authority: values.authority,
          additional_notes: values.additionalNotes,
          website: values.website,
          source_url: window.location.href,
          utm_source: params.get('utm_source') || '',
          utm_medium: params.get('utm_medium') || '',
          utm_campaign: params.get('utm_campaign') || '',
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || 'We could not submit your request.');
      setStatus({ state: 'success', message: '', acknowledged: data.acknowledged !== false });
    } catch (error) {
      setStatus({ state: 'error', message: error.message });
    }
  };

  const succeeded = status.state === 'success';

  return (
    <div
      className="epr-backdrop"
      onMouseDown={(event) => { if (event.target === event.currentTarget) close(); }}
    >
      <div
        className="epr-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="epr-title"
        ref={dialogRef}
      >
        <div className="epr-header">
          <div>
            <p className="epr-eyebrow">Jaspen Advisory</p>
            <h2 id="epr-title" tabIndex={-1} ref={headingRef}>Executive Partnership Request</h2>
          </div>
          <button type="button" className="epr-close" onClick={close} aria-label="Close request form">×</button>
        </div>

        {succeeded ? (
          <div className="epr-body">
            <div className="epr-success" role="status">
              <h3>Your request has been received.</h3>
              <p>Thank you for your interest in Jaspen Executive Partnerships.</p>
              <p>
                We review every request personally to ensure the engagement is the right fit for
                both your organization and Jaspen.
              </p>
              {status.acknowledged
                ? <p>A confirmation is on its way to {values.email}.</p>
                : <p>We have your request. If a confirmation email does not arrive, it does not affect it.</p>}
              <p className="epr-success-note">
                If your request aligns with our current capacity and expertise, we&apos;ll contact
                you to schedule an executive consultation.
              </p>
              <button type="button" className="jaspen-btn jaspen-btn-primary" onClick={close}>Close</button>
            </div>
          </div>
        ) : (
          <form className="epr-body" onSubmit={submit} noValidate={false}>
            <fieldset className="epr-fieldset">
              <legend>Contact information</legend>
              <div className="epr-grid">
                <Field id="epr-name" label="Full name" required>
                  {(props) => <input {...props} value={values.fullName} onChange={set('fullName')} autoComplete="name" />}
                </Field>
                <Field id="epr-company" label="Company" required>
                  {(props) => <input {...props} value={values.company} onChange={set('company')} autoComplete="organization" />}
                </Field>
                {/* Not "epr-title" — that id belongs to the dialog heading
                    the dialog is labelled by, and a duplicate would silently
                    bind this label to the heading instead of the input. */}
                <Field id="epr-job-title" label="Job title" required>
                  {(props) => <input {...props} value={values.title} onChange={set('title')} autoComplete="organization-title" />}
                </Field>
                <Field
                  id="epr-email"
                  label="Work email"
                  required
                  hint="Use your company email address; personal email providers are not accepted."
                >
                  {(props) => <input {...props} type="email" inputMode="email" value={values.email} onChange={set('email')} autoComplete="email" />}
                </Field>
                <Field id="epr-phone" label="Phone number (optional)">
                  {(props) => <input {...props} type="tel" value={values.phone} onChange={set('phone')} autoComplete="tel" />}
                </Field>
              </div>
            </fieldset>

            <fieldset className="epr-fieldset">
              <legend>Which engagement are you interested in?<span aria-hidden="true">*</span></legend>
              <div className="epr-options">
                {ENGAGEMENT_OPTIONS.map(option => (
                  <label key={option.value} className="epr-choice">
                    <input
                      type="radio"
                      name="engagement"
                      value={option.value}
                      checked={values.engagement === option.value}
                      onChange={set('engagement')}
                    />
                    <span>{option.label}</span>
                  </label>
                ))}
              </div>
            </fieldset>

            <fieldset className="epr-fieldset">
              <legend>About the decision</legend>
              <Field
                id="epr-decision"
                className="epr-block"
                label="Briefly describe the decision, opportunity, or challenge."
                required
                hint="3–5 sentences."
              >
                {(props) => (
                  <textarea
                    {...props} rows="5" maxLength={LIMITS.decision_description}
                    value={values.decisionDescription} onChange={set('decisionDescription')}
                  />
                )}
              </Field>
              <Field
                id="epr-outcome"
                className="epr-block"
                label="What outcome are you hoping to achieve?"
                required
                hint={`For example: ${OUTCOME_EXAMPLES.join(' · ')}.`}
              >
                {(props) => (
                  <textarea
                    {...props} rows="3" maxLength={LIMITS.desired_outcome}
                    value={values.desiredOutcome} onChange={set('desiredOutcome')}
                  />
                )}
              </Field>
            </fieldset>

            <fieldset className="epr-fieldset">
              <legend>Approximately what is the financial impact of this decision? <span className="epr-optional">(optional)</span></legend>
              <div className="epr-options epr-options--inline">
                {IMPACT_OPTIONS.map(option => (
                  <label key={option.value} className="epr-choice">
                    <input
                      type="radio"
                      name="financialImpact"
                      value={option.value}
                      checked={values.financialImpact === option.value}
                      onChange={set('financialImpact')}
                    />
                    <span>{option.label}</span>
                  </label>
                ))}
              </div>
            </fieldset>

            <fieldset className="epr-fieldset">
              <legend>When do you need to make this decision?<span aria-hidden="true">*</span></legend>
              <div className="epr-options epr-options--inline">
                {TIMELINE_OPTIONS.map(option => (
                  <label key={option.value} className="epr-choice">
                    <input
                      type="radio"
                      name="timeline"
                      required
                      value={option.value}
                      checked={values.timeline === option.value}
                      onChange={set('timeline')}
                    />
                    <span>{option.label}</span>
                  </label>
                ))}
              </div>
            </fieldset>

            <fieldset className="epr-fieldset">
              <legend>Who will participate in the Executive Decision Intensive?<span aria-hidden="true">*</span></legend>
              <div className="epr-options epr-options--inline">
                {PARTICIPANT_OPTIONS.map(option => (
                  <label key={option.value} className="epr-choice">
                    <input
                      type="checkbox"
                      checked={values.participants.includes(option.value)}
                      onChange={() => toggleParticipant(option.value)}
                    />
                    <span>{option.label}</span>
                  </label>
                ))}
              </div>
            </fieldset>

            <fieldset className="epr-fieldset">
              <legend>Are you the primary decision-maker for engaging Jaspen?<span aria-hidden="true">*</span></legend>
              <div className="epr-options">
                {AUTHORITY_OPTIONS.map(option => (
                  <label key={option.value} className="epr-choice">
                    <input
                      type="radio"
                      name="authority"
                      required
                      value={option.value}
                      checked={values.authority === option.value}
                      onChange={set('authority')}
                    />
                    <span>{option.label}</span>
                  </label>
                ))}
              </div>
            </fieldset>

            <Field id="epr-notes" className="epr-block" label="Anything else you'd like us to know? (optional)">
              {(props) => (
                <textarea
                  {...props} rows="4" maxLength={LIMITS.additional_notes}
                  value={values.additionalNotes} onChange={set('additionalNotes')}
                />
              )}
            </Field>

            <label className="epr-honeypot" aria-hidden="true">
              Website
              <input tabIndex={-1} autoComplete="off" value={values.website} onChange={set('website')} />
            </label>

            {status.state === 'error' && <p className="epr-error" role="alert">{status.message}</p>}

            <button
              type="submit"
              className="jaspen-btn jaspen-btn-primary epr-submit"
              disabled={status.state === 'submitting'}
            >
              {status.state === 'submitting' ? 'Sending…' : 'Request Consultation'}
            </button>
            <p className="epr-footnote">
              Engagements are accepted based on fit, capacity, and decision readiness. Submitting
              this request does not create an engagement or a charge.
            </p>
          </form>
        )}
      </div>
    </div>
  );
}
