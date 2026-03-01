import React from 'react';

const Input = React.forwardRef(function Input(
  { as: Comp = 'input', className = '', style = {}, ...props },
  ref
) {
  return (
    <Comp
      ref={ref}
      className={className}
      style={{
        width: '100%',
        padding: '10px 12px',
        border: '1px solid #e2e8f0',
        borderRadius: 8,
        fontSize: '0.95rem',
        fontFamily: 'inherit',
        color: '#161f3b',
        background: '#ffffff',
        ...style,
      }}
      {...props}
    />
  );
});

export default Input;
