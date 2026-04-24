import React, { useEffect, useMemo, useState } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faBars,
  faBookOpen,
  faClockRotateLeft,
  faChartLine,
  faGear,
  faLayerGroup,
  faListCheck,
  faPlug,
  faUserShield,
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
      { to: '/dashboard', label: 'Dashboard', icon: faListCheck },
      { to: '/projects', label: 'Projects', icon: faLayerGroup },
      { to: '/scores', label: 'Scores', icon: faChartLine },
      { to: '/insights', label: 'Insights', icon: faLayerGroup },
      { to: '/reports', label: 'Reports', icon: faChartLine },
      { to: '/activity', label: 'Activity', icon: faClockRotateLeft },
      { to: '/connectors-manage', label: 'Data Sources', icon: faPlug },
      { to: '/team', label: 'Team', icon: faLayerGroup },
      { to: '/knowledge', label: 'Knowledge', icon: faBookOpen },
      { to: '/account', label: 'Account', icon: faUserShield },
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
          className="jas-drawer-tab jas-drawer-tab-settings"
          onClick={() => setOpen(true)}
          aria-label="Open main menu"
          aria-expanded="false"
        >
          <FontAwesomeIcon icon={faBars} />
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
          <aside className={`jas-left-sidebar jas-settings-sidebar ${open ? 'sidebar-open' : ''}`} aria-label="Main menu">
            <div className="jas-sidebar-header">
              <h3>User Settings</h3>
              <button
                type="button"
                className="jas-close-btn"
                onClick={() => setOpen(false)}
                aria-label="Close main menu"
              >
                <FontAwesomeIcon icon={faTimes} />
              </button>
            </div>
            <div className="jas-sidebar-content">
              <div className="jas-ud-layout">
                <div className="jas-ud-scroll">
                  <div className="jas-ud-section">
                    <div className="jas-ud-section-label">Navigate</div>
                    <nav>
                      {items.map((item) => (
                        <NavLink
                          key={item.to}
                          to={item.to}
                          className={`jas-ud-item ${isRouteActive(location.pathname, item.to) ? 'is-active' : ''}`}
                        >
                          <FontAwesomeIcon icon={item.icon} />
                          <span className="jas-ud-item-label">{item.label}</span>
                        </NavLink>
                      ))}
                    </nav>
                  </div>
                </div>
              </div>
            </div>
          </aside>
        </>
      )}
    </>
  );
}
