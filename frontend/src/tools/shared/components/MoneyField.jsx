import React, { useId } from 'react';

// Labeled currency (or plain number) input for direct user facts.
export default function MoneyField({ label, help, optional, value, onChange, prefix = '$', suffix, step = 10, min = 0, max }) {
  const id = useId();
  return (
    <div className="tool-field">
      <label className="tool-label" htmlFor={id}>
        {label}
        {optional ? <span className="tool-help" style={{ display: 'inline' }}> (optional)</span> : null}
      </label>
      <div className="tool-number-with-unit" style={{ maxWidth: 260 }}>
        <div className="tool-input-affix" style={{ width: 220, maxWidth: '100%' }}>
          {prefix ? <span className="tool-prefix" aria-hidden="true">{prefix}</span> : null}
          <input
          id={id}
          className="tool-input"
          type="number"
          inputMode="decimal"
          step={step}
          min={min}
          max={max}
          value={value}
          onChange={(e) => onChange(e.target.value === '' ? '' : Number(e.target.value))}
          />
        </div>
        {suffix ? <span className="tool-unit-label">{suffix}</span> : null}
      </div>
      {help ? <p className="tool-help">{help}</p> : null}
    </div>
  );
}
