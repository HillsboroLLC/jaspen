import React, { useId } from 'react';
import AssumptionField from '../../../shared/components/AssumptionField';
import AdvancedOptions from '../../../shared/components/AdvancedOptions';
import { GROWTH_ASSUMPTIONS } from '../../config/questions';
import { getBenchmark } from '../../data/benchmarks';
import { formatCurrency } from '../../../shared/formatting';
import { analytics } from '../../services/analytics';

export default function CashStep({
  defaults,
  assumptionValue,
  isAssumptionOverridden,
  overrideAssumption,
  restoreAssumption,
  inputs,
  setInput,
  result,
}) {
  const uid = useId();

  const closingField = { key: 'closingCostPct', label: 'Closing costs', kind: 'rate', unit: '% of price', decimals: 2 };

  return (
    <section className="tool-card" aria-labelledby={`${uid}-title`}>
      <h2 id={`${uid}-title`}>Cash to close & future outlook</h2>
      <p className="tool-card-lead">
        Estimate the upfront cash you&apos;ll need, then see how ownership costs could grow over time.
        Your lender Loan Estimate controls the real closing figure.
      </p>

      <AssumptionField
        field={closingField}
        benchmark={getBenchmark('M004')}
        value={assumptionValue('closingCostPct')}
        overridden={isAssumptionOverridden('closingCostPct')}
        onChange={(v) => { if (v !== '' && v != null) overrideAssumption('closingCostPct', v); }}
        onRestore={() => restoreAssumption('closingCostPct')}
        onOpenSource={() => analytics.methodologyViewed()}
      />

      <div className="tool-field-grid" style={{ marginTop: 20 }}>
        <div className="tool-field">
          <label className="tool-label" htmlFor={`${uid}-points`}>Points / prepaids − lender credits</label>
          <div className="tool-input-affix" style={{ maxWidth: 200 }}>
            <span className="tool-prefix" aria-hidden="true">$</span>
            <input id={`${uid}-points`} className="tool-input" type="number" step={100} inputMode="numeric"
              value={inputs.pointsCreditsNet}
              onChange={(e) => setInput('pointsCreditsNet', e.target.value === '' ? 0 : Number(e.target.value))} />
          </div>
          <p className="tool-help">Net additional cash at closing (enter a negative number for net credits).</p>
        </div>
        <div className="tool-field">
          <label className="tool-label" htmlFor={`${uid}-income`}>
            Gross monthly income <span className="tool-help" style={{ display: 'inline' }}>(optional)</span>
          </label>
          <div className="tool-input-affix" style={{ maxWidth: 200 }}>
            <span className="tool-prefix" aria-hidden="true">$</span>
            <input id={`${uid}-income`} className="tool-input" type="number" min={0} step={500} inputMode="numeric"
              placeholder="for a housing-cost ratio"
              value={inputs.grossMonthlyIncome}
              onChange={(e) => setInput('grossMonthlyIncome', e.target.value === '' ? '' : Number(e.target.value))} />
          </div>
          <p className="tool-help">Only used to show your housing-cost ratio, never an approval decision.</p>
        </div>
      </div>

      <div className="tool-line" style={{ borderTop: '1px solid var(--tool-card-border)', marginTop: 8 }}>
        <span className="tool-line-label">Estimated cash to close</span>
        <span className="tool-line-value">{formatCurrency(result.cashToClose.mid)}</span>
      </div>

      <AdvancedOptions label="Future cost growth (optional)">
        <p className="tool-help" style={{ marginTop: 0, marginBottom: 14 }}>
          Editable scenarios — not forecasts. These drive the payment-change exposure on your
          results, showing how a fixed-rate loan still has a rising total housing cost.
        </p>
        {GROWTH_ASSUMPTIONS.map((field) => (
          <AssumptionField
            key={field.key}
            field={field}
            benchmark={getBenchmark(defaults[field.key]?.benchmarkId)}
            value={assumptionValue(field.key)}
            overridden={isAssumptionOverridden(field.key)}
            onChange={(v) => { if (v !== '' && v != null) overrideAssumption(field.key, v); }}
            onRestore={() => restoreAssumption(field.key)}
            onOpenSource={() => analytics.methodologyViewed()}
          />
        ))}
      </AdvancedOptions>
    </section>
  );
}
