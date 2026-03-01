import React from 'react';

export default function SectionHeader({
  title,
  subtitle,
  actions,
  eyebrow,
  className = '',
  style = {},
}) {
  return (
    <div
      className={className}
      style={{
        display: 'flex',
        alignItems: 'flex-end',
        justifyContent: 'space-between',
        gap: 16,
        marginBottom: 16,
        ...style,
      }}
    >
      <div style={{ minWidth: 0 }}>
        {eyebrow && (
          <div style={{ fontSize: 12, fontWeight: 600, color: '#64748b', marginBottom: 6 }}>
            {eyebrow}
          </div>
        )}
        {title && (
          <h2 style={{ fontSize: '1.75rem', fontWeight: 700, margin: 0, color: '#161f3b' }}>
            {title}
          </h2>
        )}
        {subtitle && (
          <p style={{ marginTop: 6, marginBottom: 0, color: '#64748b' }}>
            {subtitle}
          </p>
        )}
      </div>
      {actions && <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>{actions}</div>}
    </div>
  );
}
