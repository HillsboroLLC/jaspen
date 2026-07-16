import React, { useId } from 'react';
import ProvenanceBadge from './ProvenanceBadge';
import SourceDetail from './SourceDetail';
import { getBenchmark } from '../data/benchmarks';
import { analytics } from '../services/analytics';

// One editable assumption: label, provenance badge, current value (default or
// override), a restore-default control, and expandable source detail.
//
// `kind` controls the display unit: 'percent' shows a 0-100 field but stores a
// 0-1 fraction; 'currency' and 'number' store raw numbers.
export default function AssumptionField({
  field,
  benchmark,
  value, // resolved numeric value (fraction for percent)
  defaultValue,
  overridden,
  onChange,
  onRestore,
}) {
  const id = useId();
  const bench = benchmark || getBenchmark(field.benchmarkId);
  const isPercent = field.kind === 'percent';
  const isCurrency = field.kind === 'currency';

  const displayValue = isPercent ? Math.round(value * 1000) / 10 : value;

  const handleInput = (raw) => {
    if (raw === '') {
      onChange('');
      return;
    }
    const n = Number(raw);
    if (!Number.isFinite(n)) return;
    onChange(isPercent ? n / 100 : n);
  };

  const suffix = isPercent ? '%' : field.unit && field.unit !== 'USD' ? field.unit : '';

  return (
    <div className="cot-assumption" data-overridden={overridden ? 'true' : 'false'}>
      <div className="cot-assumption-head">
        <p className="cot-assumption-title">{field.label}</p>
        <ProvenanceBadge type={bench?.type} overridden={overridden} />
      </div>
      {field.help ? <p className="cot-help">{field.help}</p> : null}

      <div className="cot-assumption-controls">
        <div className={`cot-input-affix cot-assumption-input`}>
          {isCurrency ? <span className="cot-prefix" aria-hidden="true">$</span> : null}
          <input
            id={id}
            className="cot-input"
            type="number"
            inputMode="decimal"
            step={field.step || (isPercent ? 1 : isCurrency ? 100 : 'any')}
            min={0}
            value={displayValue}
            aria-label={`${field.label}${suffix ? ` in ${suffix}` : ''}`}
            onChange={(e) => handleInput(e.target.value)}
          />
          {suffix ? <span className="cot-input-suffix">{suffix}</span> : null}
        </div>

        {overridden ? (
          <button
            type="button"
            className="cot-link"
            onClick={() => {
              onRestore();
            }}
          >
            Restore recommended default
          </button>
        ) : (
          <span className="cot-help" style={{ margin: 0 }}>
            Recommended default
          </span>
        )}
      </div>

      <SourceDetail
        benchmark={bench}
        onOpen={() => analytics.methodologyViewed()}
      />
    </div>
  );
}
