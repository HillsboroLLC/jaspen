import React from 'react';

export default function EmptyState({
  title = 'Nothing here yet',
  description,
  action,
  icon,
  className = '',
  style = {},
}) {
  return (
    <div
      className={className}
      style={{
        textAlign: 'center',
        padding: '32px 20px',
        border: '1px dashed var(--int-border)',
        borderRadius: 'var(--int-radius-md)',
        background: 'var(--int-bg)',
        color: 'var(--int-eyebrow)',
        ...style,
      }}
    >
      {icon && <div style={{ fontSize: 28, marginBottom: 10 }}>{icon}</div>}
      <h3 style={{ margin: 0, color: 'var(--int-text)', fontSize: '1.25rem' }}>{title}</h3>
      {description && <p style={{ marginTop: 8 }}>{description}</p>}
      {action && <div style={{ marginTop: 16 }}>{action}</div>}
    </div>
  );
}
