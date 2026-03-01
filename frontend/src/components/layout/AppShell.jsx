import React from 'react';
import { SectionHeader } from '../ui';

export default function AppShell({
  title,
  subtitle,
  actions,
  header,
  showHeader = true,
  fullBleed = false,
  noPadding = false,
  className = '',
  contentClassName = '',
  children,
}) {
  const containerClass = fullBleed ? '' : 'container';
  const contentStyle = noPadding ? {} : { padding: '24px 0 40px' };

  return (
    <div className={className}>
      {showHeader && header !== null && (
        <div style={{ padding: '24px 0 8px' }}>
          <div className={containerClass}>
            {header || (
              <SectionHeader title={title} subtitle={subtitle} actions={actions} />
            )}
          </div>
        </div>
      )}
      <div style={contentStyle}>
        <div className={`${containerClass} ${contentClassName}`.trim()}>
          {children}
        </div>
      </div>
    </div>
  );
}
