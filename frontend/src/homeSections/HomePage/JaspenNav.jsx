import React, { useState, useRef, useEffect } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import './HomePage.css';

const NAV_MENUS = [
  {
    label: "I'm Jaspen",
    columns: [
      {
        title: 'Products',
        items: [
          { label: 'Jaspen', path: '/pages/jaspen' },
          { label: 'Jaspen Score', path: '/pages/jaspen-score' },
          { label: 'Project Management', path: '/pages/project-management' },
        ],
      },
      {
        title: 'Features',
        items: [
          { label: 'Jaspen in Jira', path: '/pages/jaspen-in-jira' },
          { label: 'Jaspen in Smartsheets', path: '/pages/jaspen-in-smartsheets' },
        ],
      },
    ],
  },
  {
    label: 'Pricing',
    columns: [
      {
        title: 'Overview',
        items: [
          { label: 'Overview', path: '/pages/pricing' },
          { label: 'API', path: '/pages/api' },
        ],
      },
      {
        title: 'Plans',
        items: [
          { label: 'Free', path: '/pages/pricing#free' },
          { label: 'Starter ($7)', path: '/pages/pricing#starter' },
          { label: 'Essential ($39)', path: '/pages/pricing#essential' },
          { label: 'Team', path: '/pages/pricing#team' },
          { label: 'Enterprise', path: '/pages/pricing#enterprise' },
        ],
      },
    ],
  },
  {
    label: 'Resources',
    columns: [
      {
        title: 'Learn',
        items: [
          { label: 'Docs', path: '/pages/resources/tutorials' },
          { label: 'Demos', path: '/pages/resources/demos' },
          { label: 'Tutorials', path: '/pages/resources/tutorials' },
        ],
      },
      {
        title: 'Tools',
        items: [
          { label: 'Free Calculators', path: '/calculators' },
          { label: 'Connectors', path: '/pages/resources/connectors' },
          { label: 'Plugins', path: '/pages/resources/plugins' },
        ],
      },
    ],
  },
];

export default function JaspenNav({ onOpenModal } = {}) {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [activeDesktopMenu, setActiveDesktopMenu] = useState(null);
  const closeMenuTimer = useRef(null);
  const location = useLocation();
  const navigate = useNavigate();
  const isHomePage = location.pathname === '/';

  useEffect(() => {
    return () => {
      if (closeMenuTimer.current) clearTimeout(closeMenuTimer.current);
    };
  }, []);

  const openDesktopMenu = (label) => {
    if (closeMenuTimer.current) {
      clearTimeout(closeMenuTimer.current);
      closeMenuTimer.current = null;
    }
    setActiveDesktopMenu(label);
  };

  const closeDesktopMenu = () => {
    if (closeMenuTimer.current) clearTimeout(closeMenuTimer.current);
    closeMenuTimer.current = setTimeout(() => setActiveDesktopMenu(null), 180);
  };

  const closeNavMenus = () => {
    setMobileNavOpen(false);
    setActiveDesktopMenu(null);
    if (closeMenuTimer.current) {
      clearTimeout(closeMenuTimer.current);
      closeMenuTimer.current = null;
    }
  };

  const handleRequestAccess = (e) => {
    e.preventDefault();
    closeNavMenus();
    if (isHomePage) {
      const el = document.getElementById('request-access');
      if (el) el.scrollIntoView({ behavior: 'smooth' });
    } else {
      navigate('/#request-access');
    }
  };

  return (
    <header className="jaspen-header">
      <div className="jaspen-header-inner">
        <Link to="/" className="jaspen-logo">Jaspen</Link>

        <nav className="jaspen-nav-desktop">
          {NAV_MENUS.map((menu) => (
            <div
              key={menu.label}
              className={`jaspen-nav-item ${activeDesktopMenu === menu.label ? 'is-open' : ''}`}
              onMouseEnter={() => openDesktopMenu(menu.label)}
              onMouseLeave={closeDesktopMenu}
            >
              <button
                type="button"
                className="jaspen-nav-trigger"
                aria-haspopup="true"
                aria-expanded={activeDesktopMenu === menu.label}
                onClick={() => setActiveDesktopMenu(activeDesktopMenu === menu.label ? null : menu.label)}
              >
                {menu.label}
                <i className="fa-solid fa-chevron-down"></i>
              </button>

              <div
                className={`jaspen-mega-menu ${menu.label === "I'm Jaspen" ? 'is-im-jaspen' : ''}`}
                style={{ '--menu-columns': menu.columns.length }}
              >
                <div className="jaspen-mega-menu-grid">
                  {menu.columns.map((column) => (
                    <div
                      key={`${menu.label}-${column.title}`}
                      className={`mega-menu-column ${menu.label === 'Solutions' && column.title === 'Industries' ? 'is-industries' : ''}`}
                    >
                      <p className="mega-menu-heading">{column.title}</p>
                      <ul>
                        {column.items.map((item) => (
                          <li key={`${menu.label}-${column.title}-${item.label}`}>
                            {item.path && !item.path.startsWith('http') ? (
                              <Link
                                to={item.path}
                                className="mega-menu-link"
                                onClick={closeNavMenus}
                              >
                                {item.label}
                              </Link>
                            ) : (
                              <a
                                href={item.path}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="mega-menu-link has-external"
                                onClick={closeNavMenus}
                              >
                                {item.label}
                                <i className="fa-solid fa-arrow-up-right-from-square mega-menu-external-icon" aria-hidden="true"></i>
                              </a>
                            )}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ))}
        </nav>

        <div className="jaspen-header-actions">
          <button type="button" className="jaspen-login-link" onClick={() => onOpenModal?.('signin')}>Log in</button>
          <button type="button" className="jaspen-btn jaspen-btn-primary" onClick={() => onOpenModal?.('signup')}>Create account</button>
        </div>

        <button
          className={`jaspen-hamburger ${mobileNavOpen ? 'is-open' : ''}`}
          onClick={() => setMobileNavOpen(!mobileNavOpen)}
          aria-label="Toggle menu"
          aria-expanded={mobileNavOpen}
        >
          <span /><span /><span />
        </button>
      </div>

      {mobileNavOpen && (
        <div className="jaspen-mobile-menu">
          <div className="jaspen-mobile-menu-inner">
            {NAV_MENUS.map((menu) => (
              <div key={`mobile-${menu.label}`} className="mobile-menu-group">
                <p className="mobile-menu-group-title">{menu.label}</p>
                <div className="mobile-menu-columns">
                  {menu.columns.map((column) => (
                    <div key={`mobile-${menu.label}-${column.title}`} className="mobile-menu-column">
                      <p className="mobile-menu-heading">{column.title}</p>
                      <ul>
                        {column.items.map((item) => (
                          <li key={`mobile-${menu.label}-${column.title}-${item.label}`}>
                            {item.path && !item.path.startsWith('http') ? (
                              <Link to={item.path} onClick={closeNavMenus}>{item.label}</Link>
                            ) : (
                              <a href={item.path} target="_blank" rel="noopener noreferrer" onClick={closeNavMenus} className="mobile-link-external">
                                {item.label}
                                <i className="fa-solid fa-arrow-up-right-from-square mega-menu-external-icon" aria-hidden="true"></i>
                              </a>
                            )}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
              </div>
            ))}
            <div className="mobile-menu-actions">
              <button type="button" className="jaspen-login-link" onClick={() => { setMobileNavOpen(false); onOpenModal?.('signin'); }}>Log in</button>
              <button type="button" className="jaspen-btn jaspen-btn-primary" onClick={() => { setMobileNavOpen(false); onOpenModal?.('signup'); }}>Create account</button>
            </div>
          </div>
        </div>
      )}
    </header>
  );
}
