import React, { useId } from 'react';
import MoneyField from '../../../shared/components/MoneyField';
import AssumptionField from '../../../shared/components/AssumptionField';
import AdvancedOptions from '../../../shared/components/AdvancedOptions';
import { MOVEIN_FIELDS, GROWTH_ASSUMPTIONS } from '../../config/questions';
import { getBenchmark } from '../../data/benchmarks';
import { formatCurrency } from '../../../shared/formatting';

export default function MoveInStep({ inputs, setInput, defaults, assumptionValue, isAssumptionOverridden, overrideAssumption, restoreAssumption, result }) {
  const uid = useId();
  const renderAssumption = (field) => {
    const d = defaults[field.key];
    return (
      <AssumptionField key={field.key} field={field} benchmark={getBenchmark(d.benchmarkId)}
        value={assumptionValue(field.key)} overridden={isAssumptionOverridden(field.key)}
        onChange={(v) => overrideAssumption(field.key, v)} onRestore={() => restoreAssumption(field.key)} />
    );
  };

  return (
    <section className="tool-card" aria-labelledby={`${uid}-title`}>
      <h2 id={`${uid}-title`}>Move-in cash &amp; future costs</h2>
      <p className="tool-card-lead">Separate refundable cash held from costs you will not get back, then review the editable renewal assumptions.</p>

      {renderAssumption({ key: 'securityDeposit', label: 'Security deposit', kind: 'currency', help: 'Defaults to one month of entered rent. Replace it with the lease amount when known.' })}

      <div className="tool-field-grid" style={{ marginTop: 22 }}>
        {MOVEIN_FIELDS.map((f) => (
          <MoneyField key={f.key} label={f.label} help={f.help} value={inputs[f.key]} onChange={(v) => setInput(f.key, v)} />
        ))}
      </div>

      <div style={{ marginTop: 8 }}>
        <div className="tool-line"><span className="tool-line-label">Refundable cash held</span><span className="tool-line-value">{formatCurrency(result.refundableCashHeld)}</span></div>
        <div className="tool-line"><span className="tool-line-label">Nonrefundable move-in cost</span><span className="tool-line-value">{formatCurrency(result.nonrefundableMoveInCost)}</span></div>
        <div className="tool-line"><span className="tool-line-label">Total move-in cash required</span><span className="tool-line-value">{formatCurrency(result.moveInCashRequired)}</span></div>
      </div>

      <AdvancedOptions label="Future cost assumptions">
        <p className="tool-help" style={{ marginBottom: 14 }}>Planning scenarios, not forecasts. Change any rate to match your expectations.</p>
        {GROWTH_ASSUMPTIONS.map(renderAssumption)}
      </AdvancedOptions>
    </section>
  );
}
