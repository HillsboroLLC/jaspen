import React from 'react';
import styles from './Card.module.css';

const Card = ({
  children,
  title,
  subtitle,
  headerActions,
  variant = 'default',
  padding = 'medium',
  shadow = 'small',
  border = true,
  className = '',
  headerClassName = '',
  bodyClassName = '',
  ...props
}) => {
  const cardClasses = [
    styles.card,
    styles[variant],
    styles[`padding-${padding}`],
    styles[`shadow-${shadow}`],
    !border && styles.noBorder,
    className
  ].filter(Boolean).join(' ');

  const hasHeader = title || subtitle || headerActions;

  return (
    <div className={cardClasses} {...props}>
      {hasHeader && (
        <div className={`${styles.cardHeader} ${headerClassName}`}>
          <div className={styles.headerContent}>
            {title && <h2 className={styles.cardTitle}>{title}</h2>}
            {subtitle && <p className={styles.cardSubtitle}>{subtitle}</p>}
          </div>
          {headerActions && (
            <div className={styles.headerActions}>
              {headerActions}
            </div>
          )}
        </div>
      )}
      <div className={`${styles.cardBody} ${bodyClassName}`}>
        {children}
      </div>
    </div>
  );
};

// Card Section Component for organizing content within cards
const CardSection = ({ 
  children, 
  title, 
  className = '',
  ...props 
}) => {
  return (
    <div className={`${styles.cardSection} ${className}`} {...props}>
      {title && <h3 className={styles.sectionTitle}>{title}</h3>}
      <div className={styles.sectionContent}>
        {children}
      </div>
    </div>
  );
};

// Card Grid Component for laying out multiple cards
const CardGrid = ({ 
  children, 
  columns = 'auto',
  gap = 'medium',
  className = '',
  ...props 
}) => {
  const gridClasses = [
    styles.cardGrid,
    styles[`columns-${columns}`],
    styles[`gap-${gap}`],
    className
  ].filter(Boolean).join(' ');

  return (
    <div className={gridClasses} {...props}>
      {children}
    </div>
  );
};

Card.Section = CardSection;
Card.Grid = CardGrid;

export default Card;

