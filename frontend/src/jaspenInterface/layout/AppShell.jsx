import React, { useEffect } from 'react';
import { SectionHeader } from '../../homeSections/homeUi';

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

  useEffect(() => {
    const brand = 'Jaspen';
    const pageTitle = String(title || '').trim();
    if (!pageTitle) {
      document.title = brand;
      return;
    }
    document.title = pageTitle.toLowerCase() === brand.toLowerCase() ? brand : `${pageTitle} | ${brand}`;
  }, [title]);

  return (
    <div className={className}>
      <a href="#app-main-content" className="app-skip-link">Skip to main content</a>
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
        <div id="app-main-content" tabIndex={-1} className={`${containerClass} ${contentClassName}`.trim()}>
          {children}
        </div>
      </div>
    </div>
  );
}
