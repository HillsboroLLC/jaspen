import React, { useEffect, useMemo, useState } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faBookOpen,
  faChartLine,
  faGear,
  faLayerGroup,
  faPlug,
  faShieldHalved,
  faTimes,
} from '@fortawesome/free-solid-svg-icons';
import { useAuth } from '../../shared/auth/AuthContext';
import './InternalDrawerMenu.css';

function isRouteActive(pathname, to) {
  if (to === '/new') return pathname === '/new' || pathname === '/strategy';
  return pathname === to || pathname.startsWith(`${to}/`);
}

export default function InternalDrawerMenu() {
  const location = useLocation();
  const { user } = useAuth();
  const [open, setOpen] = useState(false);

  const items = useMemo(() => {
    const base = [
      { to: '/new', label: 'Jaspen', icon: faChartLine },
      { to: '/scores', label: 'Scores', icon: faChartLine },
      { to: '/insights', label: 'Insights', icon: faLayerGroup },
      { to: '/projects', label: 'Projects', icon: faLayerGroup },
      { to: '/reports', label: 'Reports', icon: faChartLine },
      { to: '/activity', label: 'Activity', icon: faChartLine },
      { to: '/connectors-manage', label: 'Connectors', icon: faPlug },
      { to: '/team', label: 'Team', icon: faLayerGroup },
      { to: '/account', label: 'Account', icon: faShieldHalved },
      { to: '/knowledge', label: 'Knowledge', icon: faBookOpen },
    ];
    if (user?.is_platform_admin || user?.can_access_enterprise_admin) {
      base.push({ to: '/jaspen-admin', label: 'Jaspen Admin', icon: faGear });
    }
    return base;
  }, [user?.can_access_enterprise_admin, user?.is_platform_admin]);

  useEffect(() => {
    setOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (!open) return undefined;
    const onKeyDown = (event) => {
      if (event.key === 'Escape') setOpen(false);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [open]);

  return (
    <>
      {!open && (
        <button
          type="button"
          className="jas-main-drawer-tab"
          onClick={() => setOpen(true)}
          aria-label="Open main menu"
          aria-expanded="false"
        >
          MENU
        </button>
      )}
      {open && (
        <>
          <button
            type="button"
            className="jas-main-drawer-backdrop"
            onClick={() => setOpen(false)}
            aria-label="Close main menu"
          />
          <aside className="jas-main-drawer" aria-label="Main menu">
            <div className="jas-main-drawer-head">
              <p>Main menu</p>
              <button
                type="button"
                className="jas-main-drawer-close"
                onClick={() => setOpen(false)}
                aria-label="Close main menu"
              >
                <FontAwesomeIcon icon={faTimes} />
              </button>
            </div>
            <nav className="jas-main-drawer-nav">
              {items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={`jas-main-drawer-link ${isRouteActive(location.pathname, item.to) ? 'is-active' : ''}`}
                >
                  <span className="jas-main-drawer-icon">
                    <FontAwesomeIcon icon={item.icon} />
                  </span>
                  <span>{item.label}</span>
                </NavLink>
              ))}
            </nav>
          </aside>
        </>
      )}
    </>
  );
}
