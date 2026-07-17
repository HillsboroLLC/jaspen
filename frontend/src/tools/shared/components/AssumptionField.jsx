import React, { useId } from 'react';
import ProvenanceBadge from './ProvenanceBadge';
import SourceDetail from './SourceDetail';

// One editable assumption: label, provenance badge, current value (default or
// override), restore-default, and expandable source detail.
//
// field.kind: 'currency' | 'number' | 'percent' | 'rate'
//   'percent' / 'rate' store a 0–1 fraction but display 0–100 with `field.decimals`.
export default function AssumptionField({
  field,
  benchmark,
  value,
  overridden,
  onChange,
  onRestore,
  onOpenSource,
}) {
  const id = useId();
  const isFraction = field.kind === 'percent' || field.kind === 'rate';
  const isCurrency = field.kind === 'currency';
  const decimals = field.decimals ?? (field.kind === 'rate' ? 2 : field.kind === 'percent' ? 1 : 0);

  const displayValue = isFraction ? Number((Number(value) * 100).toFixed(decimals + 2)) : value;

  const handleInput = (raw) => {
    if (raw === '') {
      onChange('');
      return;
    }
    const n = Number(raw);
    if (!Number.isFinite(n)) return;
    onChange(isFraction ? n / 100 : n);
  };

  const suffix = isFraction ? '%' : field.unit && field.unit !== 'USD' ? field.unit : '';

  return (
    <div className="tool-assumption" data-overridden={overridden ? 'true' : 'false'}>
      <div className="tool-assumption-head">
        <p className="tool-assumption-title">{field.label}</p>
        <ProvenanceBadge type={benchmark?.type} overridden={overridden} />
      </div>
      {field.help ? <p className="tool-help">{field.help}</p> : null}

      <div className="tool-assumption-controls">
        <div className="tool-number-with-unit">
          <div className="tool-input-affix tool-assumption-input">
          {isCurrency ? <span className="tool-prefix" aria-hidden="true">$</span> : null}
          <input
            id={id}
            className="tool-input"
            type="number"
            inputMode="decimal"
            step={field.step || (isFraction ? 0.01 : isCurrency ? 100 : 1)}
            min={field.min ?? 0}
            value={displayValue}
            aria-label={`${field.label}${suffix ? ` in ${suffix}` : ''}`}
            onChange={(e) => handleInput(e.target.value)}
          />
          </div>
          {suffix ? <span className="tool-unit-label">{suffix}</span> : null}
        </div>

        {overridden ? (
          <button type="button" className="tool-link" onClick={onRestore}>
            Restore recommended default
          </button>
        ) : (
          <span className="tool-help" style={{ margin: 0 }}>
            Recommended default
          </span>
        )}
      </div>

      <SourceDetail benchmark={benchmark} onOpen={onOpenSource} />
    </div>
  );
}
