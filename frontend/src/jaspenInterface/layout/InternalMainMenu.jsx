import React from 'react';
import { NavLink } from 'react-router-dom';
import { useAuth } from '../../shared/auth/AuthContext';
import './InternalMainMenu.css';

const baseItems = [
  { to: '/new', label: 'Jaspen' },
  { to: '/scores', label: 'Scores' },
  { to: '/insights', label: 'Insights' },
  { to: '/projects', label: 'Projects' },
  { to: '/reports', label: 'Reports' },
  { to: '/activity', label: 'Activity' },
  { to: '/connectors-manage', label: 'Connectors' },
  { to: '/team', label: 'Team' },
  { to: '/account', label: 'Account' },
  { to: '/knowledge', label: 'Knowledge' },
];

function isRouteActive(pathname, to) {
  if (to === '/new') return pathname === '/new' || pathname === '/strategy';
  return pathname === to || pathname.startsWith(`${to}/`);
}

export default function InternalMainMenu({ pathname = '' }) {
  const { user } = useAuth();
  const canSeeAdmin = Boolean(user?.is_platform_admin || user?.can_access_enterprise_admin);
  const items = canSeeAdmin
    ? [...baseItems, { to: '/jaspen-admin', label: 'Jaspen Admin' }]
    : baseItems;

  return (
    <aside className="jas-main-menu" aria-label="Main menu">
      <div className="jas-main-menu-head">
        <p>Main menu</p>
      </div>
      <nav className="jas-main-menu-nav">
        {items.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={`jas-main-menu-link ${isRouteActive(pathname, item.to) ? 'is-active' : ''}`}
          >
            {item.label}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
