/**
 * Card.jsx — Presentational card component
 *
 * Variants: default (white + border), flat (gray-50, no border), kpi
 *
 * Usage:
 *   <Card>Content here</Card>
 *   <Card variant="flat">Flat card</Card>
 *   <Card variant="kpi" label="Score" value="46" sub="Fair" icon="fa-solid fa-chart-line" />
 */
import React from 'react';

const styles = {
  default: {
    background: 'var(--miq-white)',
    border: '1px solid var(--miq-border)',
    borderRadius: 'var(--miq-radius-md)',
    padding: 'var(--miq-space-6)',
    transition: 'box-shadow var(--miq-transition)',
  },
  flat: {
    background: 'var(--miq-gray-50)',
    border: 'none',
    borderRadius: 'var(--miq-radius-md)',
    padding: 'var(--miq-space-6)',
  },
  kpi: {
    background: 'var(--miq-white)',
    border: '1px solid var(--miq-border)',
    borderRadius: 'var(--miq-radius-md)',
    padding: '20px 24px',
  },
};

export default function Card({
  variant = 'default',
  label,
  value,
  sub,
  icon,
  children,
  className = '',
  style: customStyle = {},
  ...props
}) {
  const cardStyle = { ...styles[variant], ...customStyle };

  if (variant === 'kpi') {
    return (
      <div className={`miq-kpi ${className}`} style={cardStyle} {...props}>
        {icon && (
          <div style={{ marginBottom: '8px' }}>
            <i
              className={icon}
              style={{ fontSize: 'var(--miq-text-lg)', color: 'var(--miq-magenta)' }}
            />
          </div>
        )}
        {label && (
          <div
            style={{
              fontSize: 'var(--miq-text-sm)',
              fontWeight: 500,
              textTransform: 'uppercase',
              letterSpacing: '0.05em',
              color: 'var(--miq-text-muted)',
              marginBottom: '4px',
            }}
          >
            {label}
          </div>
        )}
        {value && (
          <div
            style={{
              fontSize: 'var(--miq-text-3xl)',
              fontWeight: 700,
              color: 'var(--miq-navy)',
            }}
          >
            {value}
          </div>
        )}
        {sub && (
          <div
            style={{
              fontSize: 'var(--miq-text-sm)',
              color: 'var(--miq-text-muted)',
              marginTop: '2px',
            }}
          >
            {sub}
          </div>
        )}
        {children}
      </div>
    );
  }

  return (
    <div className={`miq-card ${className}`} style={cardStyle} {...props}>
      {children}
    </div>
  );
}
