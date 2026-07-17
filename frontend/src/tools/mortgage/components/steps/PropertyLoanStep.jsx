import React, { useId } from 'react';
import ProvenanceBadge from '../../../shared/components/ProvenanceBadge';
import { LOAN_TERMS } from '../../config/questions';
import { PMMS } from '../../data/benchmarks';
import { formatCurrency, formatRate } from '../../../shared/formatting';

// Step 1 — property & loan. Rate is prefilled from the Freddie Mac PMMS
// benchmark and fully editable.
export default function PropertyLoanStep({
  inputs,
  setInput,
  assumptionValue,
  overrideAssumption,
  restoreAssumption,
  isAssumptionOverridden,
}) {
  const uid = useId();
  const rate = assumptionValue('interestRate');
  const rateOverridden = isAssumptionOverridden('interestRate');
  const downPayment = (Number(inputs.homePrice) || 0) * (Number(inputs.downPaymentPct) || 0);
  const loanAmount = Math.max(0, (Number(inputs.homePrice) || 0) - downPayment);

  return (
    <section className="tool-card" aria-labelledby={`${uid}-title`}>
      <h2 id={`${uid}-title`}>Property & loan</h2>
      <p className="tool-card-lead">
        Just the loan basics. Every other assumption is prefilled with a researched default you can
        review and adjust on the next step.
      </p>

      <div className="tool-field-grid">
        <div className="tool-field">
          <label className="tool-label" htmlFor={`${uid}-price`}>Home price</label>
          <div className="tool-input-affix">
            <span className="tool-prefix" aria-hidden="true">$</span>
            <input
              id={`${uid}-price`} className="tool-input" type="number" min={0} step={5000} inputMode="numeric"
              value={inputs.homePrice}
              onChange={(e) => setInput('homePrice', e.target.value === '' ? '' : Number(e.target.value))}
            />
          </div>
        </div>

        <div className="tool-field">
          <label className="tool-label" htmlFor={`${uid}-down`}>Down payment</label>
          <div className="tool-number-with-unit">
            <div className="tool-input-affix" style={{ width: 160 }}>
              <input
                id={`${uid}-down`} className="tool-input" type="number" min={0} max={100} step={1} inputMode="decimal"
                value={Number((Number(inputs.downPaymentPct) * 100).toFixed(2))}
                onChange={(e) => setInput('downPaymentPct', e.target.value === '' ? 0 : Number(e.target.value) / 100)}
                aria-label="Down payment percent"
              />
            </div>
            <span className="tool-unit-label">%</span>
          </div>
          <p className="tool-help">{formatCurrency(downPayment)} down · {formatCurrency(loanAmount)} financed</p>
        </div>

        <div className="tool-field">
          <div className="tool-assumption-head" style={{ marginBottom: 8 }}>
            <label className="tool-label" htmlFor={`${uid}-rate`} style={{ margin: 0 }}>Mortgage interest rate</label>
            <ProvenanceBadge type="published" overridden={rateOverridden} />
          </div>
          <div className="tool-number-with-unit">
            <div className="tool-input-affix" style={{ width: 160 }}>
              <input
                id={`${uid}-rate`} className="tool-input" type="number" min={0} max={25} step={0.01} inputMode="decimal"
                value={Number((rate * 100).toFixed(3))}
                onChange={(e) => overrideAssumption('interestRate', e.target.value === '' ? 0 : Number(e.target.value) / 100)}
                aria-label="Mortgage interest rate percent"
              />
            </div>
            <span className="tool-unit-label">%</span>
          </div>
          {rateOverridden ? (
            <div className="tool-inline-toggle">
              <button type="button" className="tool-chip-toggle" onClick={() => restoreAssumption('interestRate')}>
                Reset to PMMS benchmark ({formatRate(PMMS.rate30)})
              </button>
            </div>
          ) : (
            <p className="tool-help">
              Prefilled from the Freddie Mac PMMS 30-yr average ({formatRate(PMMS.rate30)}, as of {PMMS.asOf}). Reference
              only — confirm your rate with a lender.
            </p>
          )}
        </div>

        <div className="tool-field">
          <label className="tool-label" htmlFor={`${uid}-term`}>Loan term</label>
          <select id={`${uid}-term`} className="tool-select" value={inputs.loanTerm} onChange={(e) => setInput('loanTerm', Number(e.target.value))}>
            {LOAN_TERMS.map((t) => (
              <option key={t.id} value={t.id}>{t.label}</option>
            ))}
          </select>
        </div>

        <div className="tool-field">
          <label className="tool-label" htmlFor={`${uid}-zip`}>
            ZIP / state <span className="tool-help" style={{ display: 'inline' }}>(optional)</span>
          </label>
          <input
            id={`${uid}-zip`} className="tool-input" type="text" inputMode="numeric" maxLength={10}
            placeholder="e.g. 98101"
            value={inputs.zip}
            onChange={(e) => setInput('zip', e.target.value)}
          />
          <p className="tool-help">Used only to note local tax/insurance refinement is a future enhancement.</p>
        </div>
      </div>
    </section>
  );
}
