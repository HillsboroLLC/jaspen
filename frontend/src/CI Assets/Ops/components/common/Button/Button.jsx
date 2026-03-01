import React from 'react';
import styles from './Button.module.css';

const Button = ({
  children,
  variant = 'primary',
  size = 'medium',
  icon = null,
  iconPosition = 'left',
  disabled = false,
  loading = false,
  onClick,
  type = 'button',
  className = '',
  ...props
}) => {
  const buttonClasses = [
    styles.button,
    styles[variant],
    styles[size],
    disabled && styles.disabled,
    loading && styles.loading,
    className
  ].filter(Boolean).join(' ');

  const handleClick = (e) => {
    if (!disabled && !loading && onClick) {
      onClick(e);
    }
  };

  const renderIcon = () => {
    if (loading) {
      return <span className={styles.spinner}></span>;
    }
    if (icon) {
      return <i className={icon}></i>;
    }
    return null;
  };

  return (
    <button
      type={type}
      className={buttonClasses}
      onClick={handleClick}
      disabled={disabled || loading}
      {...props}
    >
      {iconPosition === 'left' && renderIcon()}
      {children && <span className={styles.text}>{children}</span>}
      {iconPosition === 'right' && renderIcon()}
    </button>
  );
};

export default Button;

