import React, { useMemo, useState } from 'react';
import { API_BASE } from '../../config/apiBase';
import { createAnalytics } from '../../tools/shared/createAnalytics';
import './EnterpriseInvestmentCalculator.css';

const analytics = createAnalytics('enterprise_investment_calculator');
const REQUIREMENTS = [
  ['multiple_workspaces', 'Multiple workspaces'],
  ['sso_saml', 'SSO / SAML'],
  ['scim', 'SCIM'],
  ['audit_logs', 'Audit logs'],
  ['custom_permissions', 'Custom permissions'],
  ['enterprise_integrations', 'Enterprise integrations'],
  ['custom_retention', 'Custom data retention'],
  ['security_review', 'Security or compliance review'],
  ['procurement', 'Invoicing or procurement support'],
  ['negotiated_support', 'Negotiated SLA or dedicated support'],
];

const USAGE_OPTIONS = [
  { value: 'light', label: 'Light', range: '< 2 hours / person / month' },
  { value: 'standard', label: 'Standard', range: '2–5 hours / person / month' },
  { value: 'high', label: 'High', range: '> 5 hours / person / month' },
  { value: 'unsure', label: 'Unsure', range: 'Not estimated yet' },
];

const PERSONAL_EMAIL_DOMAINS = new Set([
  'gmail.com', 'googlemail.com', 'yahoo.com', 'ymail.com', 'hotmail.com',
  'outlook.com', 'live.com', 'msn.com', 'icloud.com', 'me.com', 'mac.com',
  'aol.com', 'proton.me', 'protonmail.com', 'mail.com', 'gmx.com',
  'fastmail.com', 'hey.com', 'zoho.com',
]);

const isBusinessEmail = (value) => {
  const parts = String(value || '').trim().toLowerCase().split('@');
  return parts.length === 2 && parts[0] && parts[1] && !PERSONAL_EMAIL_DOMAINS.has(parts[1]);
};

const money = (value) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(value);

const REQUIREMENT_WEIGHTS = {
  multiple_workspaces: 2, sso_saml: 1, scim: 1, audit_logs: 1,
  custom_permissions: 1, enterprise_integrations: 2, custom_retention: 1,
  security_review: 2, procurement: 1, negotiated_support: 2,
};
const USAGE_WEIGHTS = { light: 0, standard: 1, high: 2, unsure: 1 };

export function calculateEstimate(inputs) {
  const participants = Math.max(1, Number(inputs.participants) || 1);
  const teams = Math.max(1, Number(inputs.teams) || 1);
  const selected = inputs.requirements;
  const enterpriseRequired = participants > 10 || teams > 1 || selected.length > 0;

  if (!enterpriseRequired) {
    const additionalSeats = Math.max(0, participants - 5);
    const monthly = 299 + (additionalSeats * 30);
    const annual = 2988 + (additionalSeats * 360);
    return {
      fit: 'Business',
      band: 'Business',
      annualLow: annual,
      annualHigh: annual,
      price: inputs.billing === 'annual' ? `${money(annual)} billed annually` : `${money(monthly)} monthly`,
      reasons: [
        `${participants} active participant${participants === 1 ? '' : 's'}`,
        'One team or workspace',
        'No enterprise-level requirements selected',
      ],
      scope: ['One shared workspace', '5 seats included', 'Standard permissions and support', 'Shared AI usage pool'],
      equivalentInvestment: inputs.billing === 'annual' ? annual : monthly * 12,
    };
  }

  const teamScore = teams >= 4 ? 4 : teams === 3 ? 3 : teams === 2 ? 2 : 0;
  const complexityScore = (USAGE_WEIGHTS[inputs.usage] ?? 1)
    + teamScore
    + selected.reduce((sum, key) => sum + (REQUIREMENT_WEIGHTS[key] || 0), 0);
  const participantTier = participants > 50 ? 2 : participants > 20 ? 1 : 0;
  const complexityTier = complexityScore > 9 ? 2 : complexityScore > 4 ? 1 : 0;
  const tier = Math.max(participantTier, complexityTier);
  let band = 'Enterprise Core';
  let annualLow = 24000;
  let annualHigh = 36000;
  if (tier === 2) {
    band = 'Enterprise Strategic';
    annualLow = 72000;
    annualHigh = null;
  } else if (tier === 1) {
    band = 'Enterprise Scale';
    annualLow = 48000;
    annualHigh = 72000;
  }
  return {
    fit: band,
    band,
    annualLow,
    annualHigh,
    price: annualHigh ? `${money(annualLow)}–${money(annualHigh)} annually` : `Starting around ${money(annualLow)} annually`,
    reasons: [
      participants > 10 ? `${participants} active participants exceeds the Business limit` : `${participants} active participants`,
      teams > 1 ? `${teams} teams or business units require a multi-team deployment` : 'One primary business unit',
      selected.length ? `${selected.length} enterprise requirement${selected.length === 1 ? '' : 's'} selected` : `${inputs.usage} expected usage`,
    ],
    scope: [
      band === 'Enterprise Core' ? 'Focused deployment' : 'Multi-team or organization deployment',
      'Shared or negotiated AI capacity',
      selected.length ? 'Requirements scoped with Sales' : 'Limited enterprise configuration',
      'Annual agreement and structured deployment',
    ],
    equivalentInvestment: annualHigh ? Math.round((annualLow + annualHigh) / 2) : annualLow,
    complexityScore,
  };
}

export default function EnterpriseInvestmentCalculator({ billing = 'monthly', onOpenModal }) {
  const [step, setStep] = useState(0);
  const [inputs, setInputs] = useState({ participants: 10, teams: 1, usage: 'standard', requirements: [], hourlyCost: 112.5, billing });
  const [contact, setContact] = useState({ firstName: '', lastName: '', email: '', company: '', title: '', phone: '', preferredContact: '', comments: '', emailCopy: false, website: '' });
  const [submitState, setSubmitState] = useState({ status: 'idle', message: '' });
  const estimate = useMemo(() => calculateEstimate({ ...inputs, billing }), [inputs, billing]);
  const isEnterpriseQualified = estimate.band !== 'Business';
  const steps = ['Deployment', 'Requirements', 'Estimate'];

  const toggleRequirement = (key) => setInputs(current => ({
    ...current,
    requirements: current.requirements.includes(key)
      ? current.requirements.filter(item => item !== key)
      : [...current.requirements, key],
  }));

  const next = () => {
    if (step === 0) analytics.calculatorStarted();
    analytics.stepCompleted(steps[step].toLowerCase(), step);
    setStep(current => Math.min(2, current + 1));
    if (step === 1) analytics.calculatorCompleted({ recommended_fit: estimate.fit, participant_band: inputs.participants > 50 ? '51_plus' : inputs.participants > 20 ? '21_50' : inputs.participants > 10 ? '11_20' : '1_10' });
  };

  const submit = async (event) => {
    event.preventDefault();
    if (!isBusinessEmail(contact.email)) {
      setSubmitState({ status: 'error', message: 'Please use your business email address. Personal email providers are not accepted for Enterprise inquiries.' });
      return;
    }
    setSubmitState({ status: 'submitting', message: '' });
    const params = new URLSearchParams(window.location.search);
    try {
      const response = await fetch(`${API_BASE}/api/v1/public/leads/enterprise-inquiry`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source: 'enterprise-investment-calculator',
          first_name: contact.firstName,
          last_name: contact.lastName,
          email: contact.email,
          company: contact.company,
          title: contact.title,
          phone: contact.phone,
          preferred_contact: contact.preferredContact,
          comments: contact.comments,
          email_copy: contact.emailCopy,
          website: contact.website,
          participants: Number(inputs.participants),
          teams: Number(inputs.teams),
          usage: inputs.usage,
          requirements: inputs.requirements,
          hourly_cost: Number(inputs.hourlyCost) || null,
          recommendation: estimate.fit,
          annual_low: estimate.annualLow,
          annual_high: estimate.annualHigh,
          source_url: window.location.href,
          utm_source: params.get('utm_source') || '',
          utm_medium: params.get('utm_medium') || '',
          utm_campaign: params.get('utm_campaign') || '',
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || 'We could not submit your inquiry.');
      analytics.track('enterprise_inquiry_submitted', { recommended_fit: estimate.fit });
      setSubmitState({ status: 'success', message: contact.emailCopy && data.copy_sent
        ? 'Thank you. Your estimate was sent to Jaspen Sales, and a copy was emailed to you.'
        : contact.emailCopy
        ? 'Your estimate was sent to Jaspen Sales, but we could not email your copy. Sales still received your inquiry.'
        : 'Thank you. Your estimate and deployment context have been sent to Jaspen Sales.' });
    } catch (error) {
      setSubmitState({ status: 'error', message: error.message });
    }
  };

  const minutes = inputs.hourlyCost > 0
    ? Math.round((estimate.equivalentInvestment / Number(inputs.hourlyCost) / Math.max(1, Number(inputs.participants)) / 12) * 60)
    : null;

  return (
    <section className="eic" aria-labelledby="eic-title">
      <header className="eic-head">
        <div><p className="eic-eyebrow">Indicative planning tool</p><h3 id="eic-title">Enterprise Investment Calculator</h3></div>
        <span>Step {step + 1} of 3</span>
      </header>
      <div className="eic-progress" aria-hidden="true"><span style={{ width: `${((step + 1) / 3) * 100}%` }} /></div>

      {step === 0 && <div className="eic-step">
        <p className="eic-lead">Tell us about the people and teams that would actively use Jaspen.</p>
        <div className="eic-grid">
          <label>Active participants<input type="number" min="1" value={inputs.participants} onChange={e => setInputs({ ...inputs, participants: e.target.value })} /></label>
          <label>Teams or business units<input type="number" min="1" value={inputs.teams} onChange={e => setInputs({ ...inputs, teams: e.target.value })} /></label>
        </div>
        <fieldset><legend>Expected usage</legend><div className="eic-options">{USAGE_OPTIONS.map(option => <div className="eic-usage-option" key={option.value}><label><input type="radio" name="usage" checked={inputs.usage === option.value} onChange={() => setInputs({ ...inputs, usage: option.value })} /><span>{option.label}</span></label><small>{option.range}</small></div>)}</div></fieldset>
      </div>}

      {step === 1 && <div className="eic-step">
        <p className="eic-lead">Select anything your deployment may require. These needs generally move a team into Enterprise scoping.</p>
        <fieldset><legend>Organization requirements</legend><div className="eic-checks">{REQUIREMENTS.map(([key, label]) => <label key={key}><input type="checkbox" checked={inputs.requirements.includes(key)} onChange={() => toggleRequirement(key)} />{label}</label>)}</div></fieldset>
        <label className="eic-hourly">Fully loaded leadership hourly cost <span>(optional planning assumption)</span><div><span>$</span><input type="number" min="0" step="0.5" value={inputs.hourlyCost} onChange={e => setInputs({ ...inputs, hourlyCost: e.target.value })} /></div><small>The $112.50 default is editable and is used only to express the investment in leadership-time terms.</small></label>
      </div>}

      {step === 2 && <div className="eic-step" aria-live="polite">
        <div className="eic-result">
          <p className="eic-eyebrow">Recommended fit</p><h4>{estimate.fit}</h4><strong>{estimate.price}</strong>
          <div className="eic-result-grid"><div><h5>Why this fit</h5><ul>{estimate.reasons.map(item => <li key={item}>{item}</li>)}</ul></div><div><h5>Expected scope</h5><ul>{estimate.scope.map(item => <li key={item}>{item}</li>)}</ul></div></div>
          {minutes != null && <div className="eic-equivalent">At {money(Number(inputs.hourlyCost))} per hour, the indicative annual investment is equivalent to approximately <strong>{minutes} minutes of leadership time per participant each month.</strong></div>}
          <p className="eic-disclaimer">This comparison puts the investment into organizational terms. It does not predict or guarantee time savings, financial savings, or business outcomes. Enterprise estimates are indicative, not final quotes.</p>
        </div>

        {isEnterpriseQualified ? <div className="eic-contact">
          <h4>Discuss your Enterprise fit</h4><p>Your estimate is visible above. Contact information is only needed if you want Sales to follow up.</p>
          {submitState.status === 'success' ? <div className="eic-success" role="status">{submitState.message}</div> : <form onSubmit={submit}>
            <div className="eic-grid"><label>First name<input required value={contact.firstName} onChange={e => setContact({ ...contact, firstName: e.target.value })} /></label><label>Last name<input required value={contact.lastName} onChange={e => setContact({ ...contact, lastName: e.target.value })} /></label><label>Work email<input required type="email" inputMode="email" autoComplete="email" value={contact.email} onChange={e => { setContact({ ...contact, email: e.target.value }); if (submitState.status === 'error') setSubmitState({ status: 'idle', message: '' }); }} /><small>Use your company email address; personal email providers are not accepted.</small></label><label>Company<input required value={contact.company} onChange={e => setContact({ ...contact, company: e.target.value })} /></label></div>
            <div className="eic-grid eic-grid-three"><label>Job title <span>(optional)</span><input value={contact.title} onChange={e => setContact({ ...contact, title: e.target.value })} /></label><label>Phone <span>(optional)</span><input type="tel" value={contact.phone} onChange={e => setContact({ ...contact, phone: e.target.value })} /></label><label>Preferred contact <span>(optional)</span><select value={contact.preferredContact} onChange={e => setContact({ ...contact, preferredContact: e.target.value })}><option value="">No preference</option><option value="email">Email</option><option value="phone">Phone</option></select></label></div>
            <label>Anything else we should know? <span>(optional)</span><textarea rows="3" value={contact.comments} onChange={e => setContact({ ...contact, comments: e.target.value })} /></label>
            <label className="eic-copy-option"><input type="checkbox" checked={contact.emailCopy} onChange={e => setContact({ ...contact, emailCopy: e.target.checked })} /><span><strong>Email me a copy of this estimate</strong><small>This is an indicative planning estimate, not a quote.</small></span></label>
            <label className="eic-honeypot" aria-hidden="true">Website<input tabIndex="-1" autoComplete="off" value={contact.website} onChange={e => setContact({ ...contact, website: e.target.value })} /></label>
            {submitState.message && <p className="eic-error" role="alert">{submitState.message}</p>}
            <button className="jaspen-btn jaspen-btn-primary" disabled={submitState.status === 'submitting'}>{submitState.status === 'submitting' ? 'Sending…' : 'Send to Sales'}</button>
            <small>No newsletter signup is included with this request.</small>
          </form>}
        </div> : <div className="eic-contact">
          <h4>Business looks like the right fit</h4>
          <p>You can start with Business directly. Contact Sales is reserved for deployments that require Enterprise scoping.</p>
          <button type="button" className="jaspen-btn jaspen-btn-primary" onClick={() => { analytics.track('business_recommendation_cta_clicked'); onOpenModal?.('signup', 'free'); }}>Start with Business</button>
        </div>}
      </div>}

      <footer className="eic-actions">{step > 0 && <button type="button" className="jaspen-btn jaspen-btn-outline" onClick={() => setStep(current => current - 1)}>Back</button>}{step < 2 && <button type="button" className="jaspen-btn jaspen-btn-primary" onClick={next}>Continue</button>}</footer>
    </section>
  );
}
