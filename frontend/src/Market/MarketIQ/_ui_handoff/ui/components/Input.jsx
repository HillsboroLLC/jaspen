/**
 * Input.jsx — Presentational input / textarea / select component
 *
 * Types: text (default), textarea, select
 *
 * Usage:
 *   <Input label="Project name" placeholder="Enter name..." />
 *   <Input type="textarea" placeholder="Describe your project..." rows={3} />
 *   <Input type="select" label="AI context" hint="Choose an adopted analysis." options={[...]} />
 */
import React from 'react';

const labelStyle = {
  display: 'block',
  fontSize: 'var(--miq-text-base)',
  fontWeight: 600,
  color: 'var(--miq-navy)',
  marginBottom: '6px',
};

const inputStyle = {
  width: '100%',
  padding: '10px 14px',
  border: '1px solid var(--miq-gray-300)',
  borderRadius: 'var(--miq-radius-sm)',
  fontSize: 'var(--miq-text-md)',
  fontFamily: 'var(--miq-font)',
  color: 'var(--miq-navy)',
  outline: 'none',
  background: 'var(--miq-white)',
};

const hintStyle = {
  fontSize: 'var(--miq-text-sm)',
  color: 'var(--miq-gray-500)',
  marginTop: '6px',
  lineHeight: 1.4,
};

export default function Input({
  type = 'text',
  label,
  hint,
  options = [],
  className = '',
  style: customStyle = {},
  ...props
}) {
  const wrapStyle = { marginBottom: 'var(--miq-space-4)', ...customStyle };

  const renderField = () => {
    if (type === 'textarea') {
      return (
        <textarea
          className="miq-form-input"
          style={{ ...inputStyle, resize: 'none', minHeight: '36px' }}
          {...props}
        />
      );
    }

    if (type === 'select') {
      return (
        <select
          className="miq-form-select"
          style={{ ...inputStyle, appearance: 'auto', cursor: 'pointer' }}
          {...props}
        >
          {options.map((opt, i) => {
            const val = typeof opt === 'string' ? opt : opt.value;
            const lbl = typeof opt === 'string' ? opt : opt.label;
            return (
              <option key={i} value={val}>
                {lbl}
              </option>
            );
          })}
        </select>
      );
    }

    return <input className="miq-form-input" style={inputStyle} type={type} {...props} />;
  };

  return (
    <div className={`miq-form-group ${className}`} style={wrapStyle}>
      {label && <label style={labelStyle}>{label}</label>}
      {renderField()}
      {hint && <div style={hintStyle}>{hint}</div>}
    </div>
  );
}
