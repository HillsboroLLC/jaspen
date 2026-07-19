import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Check, ChevronDown, RotateCcw } from 'lucide-react';
import MarketingPageLayout from '../../../pages/Marketing/MarketingPageLayout';
import Seo from '../../../shared/components/Seo';
import CalculatorSeoFooter from '../../../shared/components/CalculatorSeoFooter';
import { createAnalytics } from '../../shared/createAnalytics';
import { calculateReworkCost, REWORK_DEFAULTS } from '../engine/calculator';
import { SEO, seoJsonLd, FAQS } from '../config/seo';
import '../ReworkCostCalculator.css';

const analytics = createAnalytics('rework_cost_calculator');
const STEPS = ['Team', 'Rework', 'Known costs', 'Results'];
const INDUSTRIES = [
  ['knowledge', 'Knowledge work'], ['software', 'Software / technology'],
  ['construction', 'Construction'], ['manufacturing', 'Manufacturing'], ['other', 'Other'],
];
const BENCHMARK_CONTEXT = {
  knowledge: {
    finding: 'PMI reported 9.4% of investment was wasted because of poor project performance in its 2021 survey.',
    caution: 'That measure is broader than rework and is not used as your rework rate.',
    source: 'https://www.pmi.org/-/media/pmi/documents/public/pdf/learning/thought-leadership/pulse/pmi_pulse_2021.pdf',
    sourceLabel: 'PMI Pulse of the Profession 2021',
  },
  software: {
    finding: 'Older software-project literature cited by PMI placed rework effort in a wide 30%–50% range.',
    caution: 'The evidence is older and definitions vary, so it is context only—not a default or comparison target.',
    source: 'https://www.pmi.org/learning/library/project-managers-business-analysts-requirements-6971',
    sourceLabel: 'PMI professional library',
  },
  construction: {
    finding: 'A 2022 peer-reviewed review reported direct construction rework costs ranging from 2.4% to 12.4%.',
    caution: 'Construction definitions and measurement boundaries vary sharply, so the range is not applied to your estimate.',
    source: 'https://www.sciencedirect.com/science/article/pii/S209580992200426X',
    sourceLabel: 'Engineering: State of Science review',
  },
  manufacturing: {
    finding: 'NIST separates direct labor and materials, downtime, lost sales, and rework or defect costs when examining manufacturing maintenance impacts.',
    caution: 'It does not provide a universal company-level rework rate, so your own inputs remain the basis of the calculation.',
    source: 'https://nvlpubs.nist.gov/nistpubs/ams/NIST.AMS.100-18.pdf',
    sourceLabel: 'NIST manufacturing report',
  },
  other: {
    finding: 'Published rework findings vary substantially by industry, definition, and whether indirect consequences are included.',
    caution: 'No external percentage is applied. Use your own defensible estimate of time and known costs.',
    source: 'https://www.gao.gov/assets/gao-20-195g.pdf',
    sourceLabel: 'GAO Cost Estimating and Assessment Guide',
  },
};

const currency = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
const whole = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });
const percent = (value) => `${Math.round(value * 100)}%`;

function NumericField({ label, value, onChange, min = 0, max, step = 1, prefix, hint, required = false }) {
  return (
    <label className="rwc-field">
      <span className="rwc-label">{label}{required ? <span aria-hidden="true"> *</span> : null}</span>
      <span className="rwc-input-wrap">
        {prefix ? <span className="rwc-input-prefix" aria-hidden="true">{prefix}</span> : null}
        <input type="number" value={value} min={min} max={max} step={step} required={required}
          onChange={(event) => onChange(event.target.value)} className={prefix ? 'rwc-input--prefixed' : ''} />
      </span>
      {hint ? <span className="rwc-field-hint">{hint}</span> : null}
    </label>
  );
}

function Stepper({ current, onSelect }) {
  return (
    <ol className="rwc-stepper" aria-label="Calculator progress">
      {STEPS.map((step, index) => (
        <li key={step} className={index === current ? 'is-active' : index < current ? 'is-complete' : ''}>
          <button type="button" onClick={() => index <= current && onSelect(index)} disabled={index > current}>
            <span>{index < current ? <Check size={14} /> : index + 1}</span>{step}
          </button>
        </li>
      ))}
    </ol>
  );
}

function ContextPanel({ inputs, result }) {
  const industry = INDUSTRIES.find(([id]) => id === inputs.industry)?.[1] || 'Selected work';
  return (
    <aside className="rwc-context" aria-label="Live estimate context">
      <p className="rwc-eyebrow">Live estimate</p>
      <h2>{currency.format(result.grossAnnualCost)}</h2>
      <p className="rwc-context-range">Planning range {currency.format(result.low)}–{currency.format(result.high)}</p>
      <div className="rwc-context-rule" />
      <dl>
        <div><dt>Work type</dt><dd>{industry}</dd></div>
        <div><dt>People affected</dt><dd>{whole.format(Number(inputs.people) || 0)}</dd></div>
        <div><dt>Rework share</dt><dd>{Number(inputs.reworkShare) || 0}%</dd></div>
        <div><dt>Potentially addressable</dt><dd>{currency.format(result.addressableCost)}</dd></div>
      </dl>
      <p className="rwc-context-note">Industry changes benchmark context only. It never changes your calculation.</p>
    </aside>
  );
}

function Results({ inputs, result, onRevise, onRestart }) {
  const benchmark = BENCHMARK_CONTEXT[inputs.industry] || BENCHMARK_CONTEXT.other;
  return (
    <div className="rwc-results">
      <section className="rwc-result-hero">
        <p className="rwc-eyebrow rwc-eyebrow--light">Your estimated annual rework cost</p>
        <h1>{currency.format(result.grossAnnualCost)}</h1>
        <p className="rwc-result-range">Estimated range <strong>{currency.format(result.low)} to {currency.format(result.high)}</strong></p>
        <p>Based on the information you entered, this is the estimated value of labor and other known resources spent redoing work that had already been completed or was expected to move forward.</p>
      </section>

      <div className="rwc-metric-grid">
        <article><span>Monthly cost</span><strong>{currency.format(result.monthlyCost)}</strong></article>
        <article><span>Rework hours</span><strong>{whole.format(result.reworkHours)}</strong></article>
        <article><span>Equivalent capacity</span><strong>{result.equivalentFte.toFixed(2)} FTE</strong></article>
        <article><span>Potentially addressable</span><strong>{currency.format(result.addressableCost)}</strong></article>
      </div>

      <section className="rwc-result-section">
        <p className="rwc-eyebrow">Where the estimate comes from</p>
        <h2>Cost composition</h2>
        <div className="rwc-composition-bar" aria-label="Estimated cost composition">
          {result.categories.filter((item) => item.value > 0).map((item) => (
            <span key={item.id} className={`rwc-segment rwc-segment--${item.id}`} style={{ width: `${item.share * 100}%` }} title={`${item.label}: ${percent(item.share)}`} />
          ))}
        </div>
        <div className="rwc-composition-list">
          {result.categories.filter((item) => item.value > 0).map((item) => (
            <div key={item.id}><span className={`rwc-dot rwc-dot--${item.id}`} /><span>{item.label}</span><strong>{currency.format(item.value)} · {percent(item.share)}</strong></div>
          ))}
        </div>
      </section>

      <section className="rwc-result-section">
        <p className="rwc-eyebrow">Illustrative scenarios</p>
        <h2>What different reductions could be worth</h2>
        <p className="rwc-section-copy">These scenarios apply only to the portion you identified as potentially avoidable. They are planning illustrations, not predicted savings.</p>
        <div className="rwc-scenario-grid">
          {result.recoveryScenarios.map((scenario) => (
            <article key={scenario.rate}><span>{percent(scenario.rate)} reduction</span><strong>{currency.format(scenario.annualValue)}</strong><small>{currency.format(scenario.monthlyValue)} monthly equivalent</small></article>
          ))}
        </div>
      </section>

      <details className="rwc-benchmark">
        <summary>Published benchmark context <ChevronDown size={19} /></summary>
        <div>
          <p>{benchmark.finding}</p>
          <p><strong>How to use this:</strong> {benchmark.caution}</p>
          <a href={benchmark.source} target="_blank" rel="noreferrer">Read the source: {benchmark.sourceLabel} →</a>
        </div>
      </details>

      <section className="rwc-disclosure">
        <strong>Planning estimate only.</strong> This estimate uses the inputs and assumptions shown. Published rework findings vary by industry and by what researchers count as rework. Recovery scenarios do not predict or guarantee cost savings, productivity gains, or business outcomes.
      </section>

      <section className="rwc-cta">
        <div><p className="rwc-eyebrow rwc-eyebrow--light">Beyond the number</p><h2>Make the work behind the estimate easier to examine.</h2><p>Jaspen helps teams surface assumptions, preserve decision context, and make execution clearer.</p></div>
        <Link to="/" onClick={() => window.scrollTo({ top: 0 })}>See how Jaspen works →</Link>
      </section>

      <div className="rwc-result-actions"><button type="button" className="rwc-btn rwc-btn--ghost" onClick={onRevise}>← Revise inputs</button><button type="button" className="rwc-reset" onClick={onRestart}><RotateCcw size={15} /> Start a new estimate</button></div>
    </div>
  );
}

export default function ReworkCostCalculatorPage() {
  const [inputs, setInputs] = useState({ ...REWORK_DEFAULTS });
  const [step, setStep] = useState(0);
  const [costsOpen, setCostsOpen] = useState(false);
  const [contextOpen, setContextOpen] = useState(false);
  const topRef = useRef(null);
  const result = useMemo(() => calculateReworkCost(inputs), [inputs]);
  const hasEdits = JSON.stringify(inputs) !== JSON.stringify(REWORK_DEFAULTS);
  const setInput = (key, value) => setInputs((current) => ({ ...current, [key]: value }));

  useEffect(() => { analytics.track('utility_viewed'); }, []);
  useEffect(() => {
    topRef.current?.focus({ preventScroll: true });
    if (step > 0) window.scrollTo({ top: 0, behavior: 'smooth' });
  }, [step]);

  const next = () => {
    analytics.track('step_completed', { step: STEPS[step].toLowerCase().replace(' ', '_') });
    setStep((current) => Math.min(3, current + 1));
  };
  const reset = () => { setInputs({ ...REWORK_DEFAULTS }); setStep(0); setCostsOpen(false); setContextOpen(false); };

  return (
    <MarketingPageLayout pageClass="page-tool-rwc">
      <Seo title={SEO.title} description={SEO.description} canonicalPath={SEO.canonicalPath} jsonLd={seoJsonLd()} />
      <main className="rwc">
        <div className="rwc-shell">
          <span ref={topRef} tabIndex={-1} className="rwc-sr-only">{STEPS[step]}</span>
          {step < 3 ? (
            <header className="rwc-hero">
              <p className="rwc-eyebrow">Free business calculator · No sign-up required</p>
              <h1>Calculate what rework may be costing your team.</h1>
              <p>Estimate the labor, coordination, materials, and documented delay costs absorbed when completed work has to be corrected, revised, rebuilt, or repeated.</p>
              <ul><li>Your inputs drive the estimate</li><li>Every assumption is editable</li><li>Benchmarks stay separate</li></ul>
            </header>
          ) : null}

          <Stepper current={step} onSelect={setStep} />

          {step === 3 ? <Results inputs={inputs} result={result} onRevise={() => setStep(0)} onRestart={reset} /> : (
            <div className="rwc-layout">
              <section className="rwc-card">
                {step === 0 ? <>
                  <h2>Start with the team</h2><p className="rwc-card-intro">Use the group whose completed work is regularly redone. You can refine every default.</p>
                  <div className="rwc-fields">
                    <label className="rwc-field"><span className="rwc-label">Industry / work type *</span><select value={inputs.industry} onChange={(e) => setInput('industry', e.target.value)}>{INDUSTRIES.map(([id, label]) => <option value={id} key={id}>{label}</option>)}</select><span className="rwc-field-hint">Used only to show relevant context.</span></label>
                    <NumericField label="People affected" value={inputs.people} onChange={(v) => setInput('people', v)} min={1} max={100000} required hint="People whose completed work is regularly redone." />
                    <NumericField label="Paid hours per person per week" value={inputs.hoursPerWeek} onChange={(v) => setInput('hoursPerWeek', v)} min={1} max={100} required />
                    <NumericField label="Working weeks per year" value={inputs.weeksPerYear} onChange={(v) => setInput('weeksPerYear', v)} min={1} max={52} required hint="Editable planning default." />
                  </div>
                </> : null}

                {step === 1 ? <>
                  <h2>Estimate the rework</h2><p className="rwc-card-intro">Include correction, revision, rebuilding, repeated approval, and other redo work.</p>
                  <div className="rwc-fields">
                    <NumericField label="Fully loaded hourly cost" value={inputs.hourlyCost} onChange={(v) => setInput('hourlyCost', v)} min={1} max={10000} prefix="$" required hint="Wages, benefits, payroll taxes, and overhead if known." />
                    <NumericField label="Share of time spent redoing completed work" value={inputs.reworkShare} onChange={(v) => setInput('reworkShare', v)} max={100} step={0.1} required hint="Percent of paid time." />
                    <NumericField label="Share of rework that may be avoidable" value={inputs.avoidableShare} onChange={(v) => setInput('avoidableShare', v)} max={100} step={0.1} required hint="Some iteration is necessary. Estimate only the portion that clearer context, decisions, or processes might reduce." />
                    <label className="rwc-field"><span className="rwc-label">Confidence in these inputs *</span><select value={inputs.confidence} onChange={(e) => setInput('confidence', e.target.value)}><option value="high">High · ±10%</option><option value="medium">Medium · ±25%</option><option value="low">Low · ±40%</option></select><span className="rwc-field-hint">Confidence changes the range, not the midpoint.</span></label>
                  </div>
                </> : null}

                {step === 2 ? <>
                  <h2>Add costs you already know</h2><p className="rwc-card-intro">These inputs are optional. Leave unknown costs at zero rather than guessing.</p>
                  <button className="rwc-optional-toggle" type="button" aria-expanded={costsOpen} onClick={() => setCostsOpen((open) => !open)}>Coordination and direct costs <ChevronDown className={costsOpen ? 'is-open' : ''} size={20} /></button>
                  {costsOpen ? <div className="rwc-fields rwc-fields--optional">
                    <NumericField label="Manager coordination hours per week" value={inputs.managerHours} onChange={(v) => setInput('managerHours', v)} max={168} step={0.5} hint="Triage, review, explanation, reassignment, or escalation." />
                    <NumericField label="Manager fully loaded hourly cost" value={inputs.managerHourlyCost} onChange={(v) => setInput('managerHourlyCost', v)} min={inputs.managerHours > 0 ? 1 : 0} max={10000} prefix="$" />
                    <NumericField label="Annual material, vendor, or remake cost" value={inputs.materialsCost} onChange={(v) => setInput('materialsCost', v)} prefix="$" hint="Discarded materials, outside services, refunds, credits, or repeat purchases." />
                    <NumericField label="Annual delay or opportunity cost" value={inputs.delayCost} onChange={(v) => setInput('delayCost', v)} prefix="$" hint="Enter only a documented or defensible amount." />
                  </div> : <p className="rwc-collapsed-summary">Current known costs: {currency.format(result.managerCost + result.materialsCost + result.delayCost)} annually.</p>}
                  <button className="rwc-optional-toggle" type="button" aria-expanded={contextOpen} onClick={() => setContextOpen((open) => !open)}>Optional business context <ChevronDown className={contextOpen ? 'is-open' : ''} size={20} /></button>
                  {contextOpen ? <div className="rwc-fields rwc-fields--optional"><NumericField label="Annual project / operating budget" value={inputs.annualBudget} onChange={(v) => setInput('annualBudget', v)} prefix="$" hint="Used only to contextualize the estimate." /><NumericField label="Annual revenue" value={inputs.annualRevenue} onChange={(v) => setInput('annualRevenue', v)} prefix="$" hint="Leave zero to display N/A." /></div> : null}
                </> : null}

                <div className="rwc-actions">
                  <div>{step > 0 ? <button type="button" className="rwc-btn rwc-btn--ghost" onClick={() => setStep(step - 1)}>← Back</button> : null}{hasEdits ? <button type="button" className="rwc-reset" onClick={reset}><RotateCcw size={14} /> Reset defaults</button> : null}</div>
                  <button type="button" className="rwc-btn rwc-btn--primary" onClick={next}>{step === 2 ? 'See my estimate' : 'Continue'} →</button>
                </div>
              </section>
              <ContextPanel inputs={inputs} result={result} />
            </div>
          )}
        </div>
      </main>

      <CalculatorSeoFooter faqs={FAQS} />
    </MarketingPageLayout>
  );
}
