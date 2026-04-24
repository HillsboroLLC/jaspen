import React from 'react';
import { useLocation } from 'react-router-dom';
import { SectionHeader } from '../../homeSections/homeUi';
import InternalDrawerMenu from './InternalDrawerMenu';

const INTERNAL_ROUTE_PREFIXES = [
  '/dashboard',
  '/projects',
  '/scores',
  '/insights',
  '/reports',
  '/activity',
  '/connectors-manage',
  '/account',
  '/team',
  '/enterprise-admin',
  '/knowledge',
  '/jaspen-admin',
  '/payment',
];

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
  const location = useLocation();
  const pathname = location?.pathname || '';
  const useInternalDrawer = INTERNAL_ROUTE_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
  const containerClass = fullBleed ? '' : 'container';
  const contentStyle = noPadding ? {} : { padding: '24px 0 40px' };

  return (
    <div className={className}>
      {useInternalDrawer && <InternalDrawerMenu />}
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
