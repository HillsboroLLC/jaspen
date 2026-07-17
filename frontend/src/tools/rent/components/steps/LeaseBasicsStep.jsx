import React, { useId } from 'react';
import MoneyField from '../../../shared/components/MoneyField';
import { LEASE_TERMS } from '../../config/questions';
import { formatCurrency } from '../../../shared/formatting';

export default function LeaseBasicsStep({ inputs, setInput, result }) {
  const uid = useId();
  return (
    <section className="tool-card" aria-labelledby={`${uid}-title`}>
      <h2 id={`${uid}-title`}>Lease basics</h2>
      <p className="tool-card-lead">
        Start with the advertised rent and lease terms. You&apos;ll add fees, utilities, and move-in
        costs next — the parts the listing usually leaves out.
      </p>

      <div className="tool-field-grid">
        <MoneyField label="Advertised monthly rent" value={inputs.advertisedRent} onChange={(v) => setInput('advertisedRent', v)} step={50} />
        <div className="tool-field">
          <label className="tool-label" htmlFor={`${uid}-term`}>Lease term</label>
          <select id={`${uid}-term`} className="tool-select" value={inputs.leaseTermMonths} onChange={(e) => setInput('leaseTermMonths', Number(e.target.value))}>
            {LEASE_TERMS.map((t) => (
              <option key={t.id} value={t.id}>{t.label}</option>
            ))}
          </select>
        </div>
        <div className="tool-field">
          <label className="tool-label" htmlFor={`${uid}-free`}>Free-rent concession</label>
          <div className="tool-number-with-unit">
            <div className="tool-input-affix" style={{ width: 140 }}>
              <input id={`${uid}-free`} className="tool-input" type="number" min={0} max={12} step={0.5} inputMode="decimal"
                value={inputs.freeMonths} onChange={(e) => setInput('freeMonths', e.target.value === '' ? 0 : Number(e.target.value))} />
            </div>
            <span className="tool-unit-label">months free</span>
          </div>
          {Number(inputs.freeMonths) > 0 && result ? (
            <p className="tool-help">Effective rent after concession: {formatCurrency(result.effectiveFirstYearRent)}/mo</p>
          ) : (
            <p className="tool-help">e.g. &quot;1 month free&quot; — enter 1.</p>
          )}
        </div>
        <MoneyField label="Gross monthly income" optional value={inputs.grossMonthlyIncome} onChange={(v) => setInput('grossMonthlyIncome', v)} step={500} help="Only used to show your housing-cost ratio." />
        <div className="tool-field">
          <label className="tool-label" htmlFor={`${uid}-zip`}>
            ZIP / metro <span className="tool-help" style={{ display: 'inline' }}>(optional)</span>
          </label>
          <input id={`${uid}-zip`} className="tool-input" type="text" inputMode="numeric" maxLength={10} placeholder="e.g. 30303"
            value={inputs.zip} onChange={(e) => setInput('zip', e.target.value)} />
          <p className="tool-help">Local market-rent comparison is a future enhancement.</p>
        </div>
      </div>
    </section>
  );
}
