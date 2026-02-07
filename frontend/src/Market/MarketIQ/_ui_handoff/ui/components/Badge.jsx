/**
 * Badge.jsx — Presentational badge / pill component
 *
 * Variants: navy (default), success, warning, danger, info, magenta, outline
 *
 * Usage:
 *   <Badge variant="navy">Fair</Badge>
 *   <Badge variant="success">Strong</Badge>
 *   <Badge variant="warning" icon="fa-solid fa-triangle-exclamation">At Risk</Badge>
 */
import React from 'react';

const variantStyles = {
  navy:    { background: 'var(--miq-navy)',    color: 'var(--miq-white)' },
  magenta: { background: 'var(--miq-magenta)', color: 'var(--miq-white)' },
  success: { background: '#e6f9ee',            color: '#0d7a3e' },
  warning: { background: '#fff8e1',            color: '#b8860b' },
  danger:  { background: '#fde8e8',            color: '#c0392b' },
  info:    { background: '#e8f4fd',            color: '#1a73e8' },
  outline: { background: 'transparent',        color: 'var(--miq-navy)', border: '1px solid var(--miq-gray-300)' },
};

const baseStyle = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: '4px',
  padding: '3px 10px',
  fontSize: 'var(--miq-text-sm)',
  fontWeight: 600,
  borderRadius: 'var(--miq-radius-full)',
  textTransform: 'uppercase',
  letterSpacing: '0.03em',
  lineHeight: 1.4,
  border: '1px solid transparent',
};

export default function Badge({
  variant = 'navy',
  icon,
  children,
  className = '',
  style: customStyle = {},
  ...props
}) {
  const merged = {
    ...baseStyle,
    ...variantStyles[variant],
    ...customStyle,
  };

  return (
    <span className={`miq-badge ${className}`} style={merged} {...props}>
      {icon && <i className={icon} style={{ fontSize: '0.6rem' }} />}
      {children}
    </span>
  );
}
