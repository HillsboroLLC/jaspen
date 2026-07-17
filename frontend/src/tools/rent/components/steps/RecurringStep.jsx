import React, { useId } from 'react';
import MoneyField from '../../../shared/components/MoneyField';
import { RECURRING_FIELDS } from '../../config/questions';
import { formatCurrency } from '../../../shared/formatting';

export default function RecurringStep({ inputs, setInput, result }) {
  const uid = useId();
  return (
    <section className="tool-card" aria-labelledby={`${uid}-title`}>
      <h2 id={`${uid}-title`}>Recurring monthly costs</h2>
      <p className="tool-card-lead">
        These recurring charges rarely appear in the advertised rent, but you pay them every month.
        Add only the ones that apply.
      </p>

      <div className="tool-field-grid">
        {RECURRING_FIELDS.map((f) => (
          <MoneyField key={f.key} label={f.label} value={inputs[f.key]} onChange={(v) => setInput(f.key, v)} />
        ))}
      </div>

      <div className="tool-line" style={{ borderTop: '1px solid var(--tool-card-border)', marginTop: 8 }}>
        <span>
          <span className="tool-line-label">True monthly rent cost</span>
          <span className="tool-line-sub">Effective rent + fees + utilities + insurance</span>
        </span>
        <span className="tool-line-value">{formatCurrency(result.trueMonthlyRentCost)}</span>
      </div>
    </section>
  );
}
