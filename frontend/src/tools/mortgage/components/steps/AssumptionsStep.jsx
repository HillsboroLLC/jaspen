import React, { useId } from 'react';
import AssumptionField from '../../../shared/components/AssumptionField';
import AdvancedOptions from '../../../shared/components/AdvancedOptions';
import { REVIEW_ASSUMPTIONS, PMI_ASSUMPTIONS } from '../../config/questions';
import { getBenchmark } from '../../data/benchmarks';
import { analytics } from '../../services/analytics';

export default function AssumptionsStep({
  defaults,
  assumptionValue,
  isAssumptionOverridden,
  overrideAssumption,
  restoreAssumption,
  restoreAll,
  overriddenKeys,
  inputs,
  setInput,
}) {
  const uid = useId();
  const pmiRelevant = (Number(inputs.downPaymentPct) || 0) < 0.2;

  const renderAssumption = (field) => (
    <AssumptionField
      key={field.key}
      field={field}
      benchmark={getBenchmark(defaults[field.key]?.benchmarkId)}
      value={assumptionValue(field.key)}
      overridden={isAssumptionOverridden(field.key)}
      onChange={(v) => {
        if (v === '' || v == null) return;
        overrideAssumption(field.key, v);
      }}
      onRestore={() => restoreAssumption(field.key)}
      onOpenSource={() => analytics.methodologyViewed()}
    />
  );

  return (
    <section className="tool-card" aria-labelledby={`${uid}-title`}>
      <div className="tool-assumption-head" style={{ marginBottom: 6 }}>
        <h2 id={`${uid}-title`} style={{ margin: 0 }}>Review the assumptions</h2>
        {overriddenKeys.length > 0 ? (
          <button type="button" className="tool-link" onClick={restoreAll}>Restore all defaults</button>
        ) : null}
      </div>
      <p className="tool-card-lead">
        We&apos;ve prefilled researched defaults with their sources. Review and adjust anything that
        differs from your property — you don&apos;t need to change a thing to see your result.
      </p>

      {REVIEW_ASSUMPTIONS.map(renderAssumption)}

      <hr className="tool-divider" />

      <div className="tool-field-grid">
        <div className="tool-field">
          <label className="tool-label" htmlFor={`${uid}-hoa`}>Monthly HOA / assessments</label>
          <div className="tool-input-affix" style={{ maxWidth: 180 }}>
            <span className="tool-prefix" aria-hidden="true">$</span>
            <input id={`${uid}-hoa`} className="tool-input" type="number" min={0} step={10} inputMode="numeric"
              value={inputs.hoaMonthly}
              onChange={(e) => setInput('hoaMonthly', e.target.value === '' ? 0 : Number(e.target.value))} />
          </div>
        </div>
        <div className="tool-field">
          <label className="tool-label" htmlFor={`${uid}-util`}>
            Monthly utilities <span className="tool-help" style={{ display: 'inline' }}>(optional)</span>
          </label>
          <div className="tool-input-affix" style={{ maxWidth: 180 }}>
            <span className="tool-prefix" aria-hidden="true">$</span>
            <input id={`${uid}-util`} className="tool-input" type="number" min={0} step={10} inputMode="numeric"
              value={inputs.utilitiesMonthly}
              onChange={(e) => setInput('utilitiesMonthly', e.target.value === '' ? 0 : Number(e.target.value))} />
          </div>
          <p className="tool-help">Included in the true carrying cost, not the required lender payment.</p>
        </div>
      </div>

      <AdvancedOptions label="Advanced options (PMI)">
        <p className="tool-help" style={{ marginTop: 0, marginBottom: 14 }}>
          {pmiRelevant
            ? 'Your down payment is under 20%, so PMI applies. Adjust the rate and the modeled removal point below.'
            : 'Your down payment is 20% or more, so PMI does not apply. These settings are shown for reference.'}
        </p>
        {PMI_ASSUMPTIONS.map(renderAssumption)}
      </AdvancedOptions>
    </section>
  );
}
