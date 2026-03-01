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
        border: '1px dashed #e2e8f0',
        borderRadius: 12,
        background: '#f8fafc',
        color: '#64748b',
        ...style,
      }}
    >
      {icon && <div style={{ fontSize: 28, marginBottom: 10 }}>{icon}</div>}
      <h3 style={{ margin: 0, color: '#161f3b', fontSize: '1.25rem' }}>{title}</h3>
      {description && <p style={{ marginTop: 8 }}>{description}</p>}
      {action && <div style={{ marginTop: 16 }}>{action}</div>}
    </div>
  );
}
