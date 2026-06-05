import React, { useEffect } from 'react';
import { SectionHeader } from '../../homeSections/homeUi';
import BackToJaspen from '../../shared/components/BackToJaspen';

export default function AppShell({
  title,
  subtitle,
  actions,
  header,
  showHeader = true,
  fullBleed = false,
  noPadding = false,
  // When true, render ONE consistent "Back to Jaspen" link at the top of the page,
  // in the same place on every page, regardless of each page's own header. This is
  // the single back-to-Jaspen system for non-primary app pages.
  backToJaspen = false,
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
      {backToJaspen && (
        <div style={{ padding: '14px 16px 0' }}>
          <BackToJaspen />
        </div>
      )}
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
