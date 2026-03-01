import React from 'react';

const VARIANT_CLASS = {
  primary: 'btn-primary',
  secondary: 'btn-secondary',
  ghost: 'btn-secondary',
  default: '',
};

const SIZE_CLASS = {
  lg: 'btn-large',
  md: '',
  sm: '',
};

export default function Button({
  as: Comp = 'button',
  variant = 'primary',
  size = 'md',
  className = '',
  children,
  ...props
}) {
  const classes = ['btn', VARIANT_CLASS[variant] || VARIANT_CLASS.default, SIZE_CLASS[size] || '', className]
    .filter(Boolean)
    .join(' ');

  const finalProps = { ...props };
  if (Comp === 'button' && !('type' in finalProps)) {
    finalProps.type = 'button';
  }

  return (
    <Comp className={classes} {...finalProps}>
      {children}
    </Comp>
  );
}
