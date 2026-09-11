import React, { useMemo, useState } from 'react';
import './AdvisoryDecisionCalculator.css';

export const ADVISORY_ENGAGEMENTS = {
  intensive: { label: 'Executive Decision Intensive', fee: 25000, unit: 'decision' },
  partnership: { label: 'Strategic Advisor Partnership', fee: 100000, unit: 'portfolio' },
};

const asAmount = (value) => {
  const parsed = Number(String(value ?? '').replace(/[^0-9.]/g, ''));
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
};

export function calculateDecisionInvestment(fee, decisionValues) {
  const values = (Array.isArray(decisionValues) ? decisionValues : [decisionValues])
    .map(asAmount)
    .filter((value) => value > 0);
  const total = values.reduce((sum, value) => sum + value, 0);
  if (!total || !Number.isFinite(fee) || fee <= 0) return null;
  const percentage = (fee / total) * 100;
  return { total, fee, percentage, remainderPercentage: 100 - percentage, decisionCount: values.length };
}

const money = (value) => new Intl.NumberFormat('en-US', {
  style: 'currency', currency: 'USD', maximumFractionDigits: 0,
}).format(value);

const percent = (value) => (value < 0.1 ? value.toFixed(3) : value.toFixed(2));

export default function AdvisoryDecisionCalculator() {
  const [engagementKey, setEngagementKey] = useState('intensive');
  const [values, setValues] = useState(['10000000']);
  const engagement = ADVISORY_ENGAGEMENTS[engagementKey];
  const result = useMemo(
    () => calculateDecisionInvestment(engagement.fee, values),
    [engagement, values],
  );

  const chooseEngagement = (key) => {
    setEngagementKey(key);
    setValues(key === 'intensive' ? ['10000000'] : ['25000000', '25000000']);
  };
  const updateValue = (index, value) => setValues((current) => (
    current.map((item, itemIndex) => (itemIndex === index ? value : item))
  ));

  return (
    <section className="adc" aria-labelledby="adc-title">
      <div className="adc-intro">
        <p className="adc-eyebrow">Put the engagement in context</p>
        <h4 id="adc-title">What share of the commitment would you invest in pressure-testing it?</h4>
        <p>
          Enter the approximate value of the decision or portfolio. This is a fee comparison,
          not a forecast of savings, avoided losses, or business outcomes.
        </p>
      </div>

      <div className="adc-body">
        <fieldset className="adc-engagements">
          <legend>Engagement</legend>
          {Object.entries(ADVISORY_ENGAGEMENTS).map(([key, item]) => (
            <label key={key} className={engagementKey === key ? 'is-selected' : ''}>
              <input
                type="radio"
                name="advisory-engagement"
                checked={engagementKey === key}
                onChange={() => chooseEngagement(key)}
              />
              <span><strong>{item.label}</strong><small>{money(item.fee)} flat fee</small></span>
            </label>
          ))}
        </fieldset>

        <div className="adc-values">
          <p className="adc-label">
            {engagementKey === 'intensive' ? 'Approximate decision value' : 'Decisions in the portfolio'}
          </p>
          {values.map((value, index) => (
            <label key={index}>
              <span>{engagementKey === 'partnership' ? `Decision ${index + 1}` : 'Decision value'}</span>
              <div><span aria-hidden="true">$</span><input
                aria-label={engagementKey === 'partnership' ? `Decision ${index + 1} value` : 'Decision value'}
                inputMode="decimal"
                value={value}
                onChange={(event) => updateValue(index, event.target.value)}
              /></div>
              {engagementKey === 'partnership' && values.length > 1 && (
                <button type="button" onClick={() => setValues((current) => current.filter((_, i) => i !== index))}>
                  Remove
                </button>
              )}
            </label>
          ))}
          {engagementKey === 'partnership' && (
            <button type="button" className="adc-add" onClick={() => setValues((current) => [...current, ''])}>
              Add another decision
            </button>
          )}
        </div>

        <div className="adc-result" aria-live="polite">
          {result ? (
            <>
              <p>{money(engagement.fee)} ÷ {money(result.total)}</p>
              <strong>{percent(result.percentage)}%</strong>
              <p>
                You would be investing {percent(result.percentage)}% of this {engagement.unit} to
                pressure-test the assumptions, evidence, tradeoffs, and vulnerabilities behind it.
              </p>
              <small>
                {result.remainderPercentage > 0
                  ? `The remaining ${percent(result.remainderPercentage)}% is the commitment being examined. `
                  : 'The engagement fee is greater than or equal to the commitment value entered; verify the amount before relying on this comparison. '}
                This comparison does not predict or guarantee any financial outcome.
              </small>
            </>
          ) : (
            <p>Enter a value greater than zero to calculate the percentage.</p>
          )}
        </div>
      </div>
    </section>
  );
}
