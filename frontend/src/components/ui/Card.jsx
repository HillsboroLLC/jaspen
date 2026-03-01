import React from 'react';

export default function Card({
  as: Comp = 'div',
  className = '',
  style = {},
  children,
  ...props
}) {
  return (
    <Comp
      className={className}
      style={{
        background: '#ffffff',
        border: '1px solid #e2e8f0',
        borderRadius: 12,
        padding: 16,
        boxShadow: '0 1px 2px rgba(15, 23, 42, 0.06)',
        ...style,
      }}
      {...props}
    >
      {children}
    </Comp>
  );
}
