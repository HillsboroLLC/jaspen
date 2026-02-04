// File: frontend/src/All/pages/Home/Home.jsx
import React, { useState, useEffect, useRef, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../shared/auth/AuthContext';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faSalesforce } from '@fortawesome/free-brands-svg-icons';
import {
  faCheckCircle,
  faTimes,
  faBolt,
  faLightbulb,
  faUser,
  faCog,
  faHome,
  faQuestionCircle,
  faExternalLinkAlt,
  faSignOutAlt,
  faCreditCard,
  faChartBar,
  faCalendarAlt,
  faEnvelope,
  faDatabase,
  faCloud,
  faPlug,
  faPuzzlePiece,
  faKey,
  faEllipsisV,
  faSync,
  faFileAlt,
  faUnlink,
  faSpinner,
  faExclamationCircle,
  faFileExcel,
  faPlusCircle,
  faLock,
  faInfoCircle,
  faChevronRight,
  faArrowUp,
  faBook,
  faHeartbeat,
  faHeadset,
  faDownload,
  faEdit,
  faPlay,
  faLink,
  faFolder,
  faFolderOpen,
} from '@fortawesome/free-solid-svg-icons';

import './Home.css';

// API base: use NGINX proxy (/api) by default; can point to :4000 via REACT_APP_API_BASE
const API_BASE = 'https://api.sekki.io/api-node';
/* --- small UI helpers (no deps) --- */
const Badge = ({ tone = 'info', children }) => (
  <span className={`badge badge-${tone}`}>{children}</span>
);

const IconBtn = ({ title, onClick, children }) => (
  <button className="icon-btn" title={title} onClick={onClick} type="button">
    {children}
  </button>
);

const ToggleSwitch = ({ checked, onChange, label, id }) => (
  <div className="toggle-row">
    <span className="toggle-label">{label}</span>
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={checked}
      className={`toggle-switch ${checked ? 'active' : ''}`}
      onClick={() => onChange(!checked)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onChange(!checked);
        }
      }}
    />
  </div>
);

const StatCard = ({ value, label, sublabel }) => (
  <div className="stat-card">
    <div className="stat-value">{value}</div>
    <div className="stat-label">
      {label}
      {sublabel ? (
        <>
          <br />
          <small style={{ fontSize: 10 }}>{sublabel}</small>
        </>
      ) : null}
    </div>
  </div>
);

const Home = () => {
  const navigate = useNavigate();
  const { user } = useAuth();

  // ----- Top-level page -----
  const [showProfileDropdown, setShowProfileDropdown] = useState(false);
  const [showAccountModal, setShowAccountModal] = useState(false);
  const [activeAccountTab, setActiveAccountTab] = useState('account');
  const dropdownRef = useRef(null);
  const modalRef = useRef(null);

  const handleMarketIQClick = () => navigate('/market-iq');
  const handleActivitiesClick = () => navigate('/ops/activities');

  const firstName = (user?.name || user?.email || 'User').split(' ')[0];
  const userEmail = user?.email || 'user@example.com';
// Safari-safe date formatter (accepts 'YYYY-MM-DD' or full ISO)
const formatISODate = (s) => {
  if (!s) return '—';
  // If it's plain YYYY-MM-DD, make it ISO so Safari won’t complain
  const iso = /^\d{4}-\d{2}-\d{2}$/.test(s) ? `${s}T00:00:00Z` : s;
  const d = new Date(iso);
  return isNaN(d) ? '—' : d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
};

  const getInitials = (name) => {
    if (!name) return 'U';
    const parts = name.split(' ');
    if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
    return name.substring(0, 2).toUpperCase();
  };
  const initials = getInitials(user?.name || user?.email || 'User');

  // For now always show admin menu items
  const isAdmin = true;

  useEffect(() => {
    const onDocClick = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setShowProfileDropdown(false);
      }
    };
    if (showProfileDropdown) document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, [showProfileDropdown]);

  useEffect(() => {
    const onDocClick = (e) => {
      if (modalRef.current && e.target === modalRef.current) {
        setShowAccountModal(false);
        setActiveAccountTab('account');
      }
    };
    if (showAccountModal) document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, [showAccountModal]);

  const handleAccountClick = () => {
    setShowProfileDropdown(false);
    setShowAccountModal(true);
    setActiveAccountTab('account');
  };
  // Invite User (Account tab)
  async function handleInviteClick() {
    try {
      const email = window.prompt('Enter email to invite:');
      if (!email) return;

      const res = await fetch(`${API_BASE}/api/invite`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
        credentials: 'include',
      });

      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const msg = data.error || `Invite failed (HTTP ${res.status})`;
        alert(msg);
        return;
      }

      alert(data.message || 'Invitation sent!');
    } catch (err) {
      console.error(err);
      alert('Network or server error sending invite.');
    }
  }

  // ====== Integrations state (Account → Integrations tab) ======
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerTitle, setDrawerTitle] = useState('Connect Salesforce');
  const [wizardStep, setWizardStep] = useState(2); // show Step 2 by default per mock
  const [requestOpen, setRequestOpen] = useState(false);
  const [logOpen, setLogOpen] = useState(false);

  // Context menus: which tile has its menu open
  const [menuOpenFor, setMenuOpenFor] = useState(null);

  const tiles = useMemo(
    () => [
      {
        key: 'salesforce',
        name: 'Salesforce',
        state: 'connected',
        badge: 'live',
        icon: <FontAwesomeIcon icon={faSalesforce} />,
        tooltip: 'Connected • GridPoint-Sales Cloud\nLast sync 2h ago • 12k rows',
        microcopy: 'Read-only: Accounts, Opps, Products (configurable)',
        onClick: () => {
          setDrawerTitle('Connect Salesforce');
          setWizardStep(2);
          setDrawerOpen(true);
        },
        hasMenu: true,
      },
      {
        key: 'oracle',
        name: 'Oracle',
        state: 'syncing',
        badge: 'beta',
        icon: <FontAwesomeIcon icon={faDatabase} />,
        tooltip: 'Syncing • 45% complete\nStarted 5 minutes ago',
        microcopy: 'Costs, GL, Projects (read-only)',
        onClick: () => {
          setDrawerTitle('Connect Oracle Fusion');
          setWizardStep(2);
          setDrawerOpen(true);
        },
        hasMenu: true,
      },
      {
        key: 'csv',
        name: 'CSV/XLS',
        state: 'down',
        badge: 'down',
        icon: <FontAwesomeIcon icon={faFileExcel} />,
        tooltip: 'Auth expired • Click to reconnect',
        microcopy: 'Drag & drop. Column auto-detect.',
        onClick: () => {
          setDrawerTitle('Connect CSV / Excel');
          setWizardStep(2);
          setDrawerOpen(true);
        },
        hasMenu: true,
      },
      {
        key: 'spaces',
        name: 'Spaces (S3)',
        state: 'not-connected',
        badge: 'soon',
        icon: <FontAwesomeIcon icon={faCloud} />,
        tooltip: 'Not connected • Click to set up',
        microcopy: 'Secure file store for uploads & exports.',
        onClick: () => {
          setDrawerTitle('Connect Spaces (S3)');
          setWizardStep(2);
          setDrawerOpen(true);
        },
      },
      {
        key: 'airbyte',
        name: 'Airbyte',
        state: 'locked',
        badge: 'soon',
        icon: <FontAwesomeIcon icon={faPlug} />,
        tooltip: 'Upgrade to Premium for Airbyte Managed',
        microcopy: '',
        onClick: null,
      },
      {
        key: 'request',
        name: 'Request',
        state: 'request',
        badge: null,
        icon: <FontAwesomeIcon icon={faPlusCircle} />,
        tooltip: 'Need a specific connector? Let us know!',
        microcopy: '',
        onClick: () => setRequestOpen(true),
      },
    ],
    []
  );

  const badgeClass = (b) =>
    b === 'live' ? 'live' : b === 'beta' ? 'beta' : b === 'soon' ? 'soon' : b === 'down' ? 'down' : '';

  const stateClass = (s) =>
    s === 'connected'
      ? 'connected'
      : s === 'syncing'
      ? 'syncing'
      : s === 'down'
      ? 'down'
      : s === 'not-connected'
      ? 'not-connected'
      : s === 'locked'
      ? 'locked'
      : s === 'request'
      ? 'request'
      : '';

  const renderStatusIcon = (s) => {
    if (s === 'connected') return <FontAwesomeIcon icon={faCheckCircle} />;
    if (s === 'syncing') return <FontAwesomeIcon icon={faSpinner} spin />;
    if (s === 'error') return <FontAwesomeIcon icon={faExclamationCircle} />;
    if (s === 'not-connected') return <i className="far fa-circle" />;
    return null;
  };

  const closeAllMenus = () => setMenuOpenFor(null);

  useEffect(() => {
    const onDocClick = () => closeAllMenus();
    document.addEventListener('click', onDocClick);
    return () => document.removeEventListener('click', onDocClick);
  }, []);

  /* --- stub handlers (wiring later) --- */
  const [orgSettings, setOrgSettings] = useState({
    allowListOn: true,
    allowedDomains: 'acme.com, acme.io',
    defaultDraft: false,
    defaultFreq: 'Hourly',
  });
  const [personal, setPersonal] = useState({
    displayName: user?.name || firstName,
    timezone: 'UTC-05:00 (Eastern Time)',
    locale: 'English (US)',
  });
  const [notif, setNotif] = useState({
    emailSync: true,
    inappSync: true,
    emailSeats: true,
    inappSeats: false,
  });
  const [dataControls, setDataControls] = useState({
    retentionDays: 90,
    downloadFullLog: true,
    piiMin: false,
  });
const [plan, setPlan] = useState(null);
const [planLoading, setPlanLoading] = useState(false);
const [planError, setPlanError] = useState(null);

  function onSaveSettings() {
    console.log('SAVE settings', { orgSettings, personal, notif });
  }
  function onExportUsage() {
    console.log('EXPORT usage csv');
  }
  function onOpenRun(id) {
    console.log('OPEN run', id);
  }
// Replace existing onUpgrade with this:
async function onUpgrade(planName) {
  try {
    const res = await fetch(`${API_BASE}/billing/checkout-session`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      // no credentials/cookies needed for this stub
      body: JSON.stringify({ plan: (planName || 'premium').toLowerCase() }),
    });

    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data?.ok || !data?.url) {
      throw new Error(data?.error || `Checkout failed (HTTP ${res.status})`);
    }

    // Redirect to the returned URL
    window.location.href = data.url;
  } catch (err) {
    console.error('Checkout error:', err);
    alert(err.message || 'Could not start checkout.');
  }
}
  function onUpdatePayment() {
    console.log('UPDATE payment');
  }

  async function startCheckout(planKey) {
  try {
const res = await fetch(`${API_BASE}/billing/checkout-session`, {
        method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ plan: planKey }), // 'standard' | 'premium' | 'enterprise'
    });
    const text = await res.text();
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${text.slice(0,200)}`);
    const data = JSON.parse(text);
    if (!data?.url) throw new Error('No checkout URL from server');
    window.location.href = data.url;
  } catch (err) {
    console.error('Checkout error:', err);
    alert(`Checkout failed (${err.message || 'unknown'})`);
  }
}

  function onDownloadInvoice(id) {
    console.log('DL invoice', id);
  }
  function onPurchaseAddOn(payload) {
    console.log('BUY addon', payload);
  }
  function onUpdateSchedule(id, freq) {
    console.log('UPDATE schedule', id, freq);
  }
  function onRunNow(id) {
    console.log('RUN now', id);
  }
  function onSendSupport(payload) {
    console.log('SEND support', payload);
  }
  function onNavigatePrefix(prefix) {
    console.log('NAV prefix', prefix);
  }
  function onCopyLink(key) {
    console.log('COPY link', key);
  }
  function onDownload(key) {
    console.log('DOWNLOAD', key);
  }
  function onOpenConnector(provider) {
    console.log('OPEN connector', provider);
  }
async function startBillingPortal() {
  try {
const res = await fetch(`${API_BASE}/billing/portal-session`, {
        method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
    });

    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.url) {
      const text = await res.text().catch(() => '');
      throw new Error(data.error || `Portal error (HTTP ${res.status}) ${text.slice(0,120)}`);
    }
    window.location.href = data.url;
  } catch (err) {
    console.error(err);
    alert(err.message || 'Could not open billing portal.');
  }
}


async function openBilling() {
  setActiveAccountTab('billing');
  setPlanLoading(true);
  setPlanError(null);
  try {
const res = await fetch('https://api.sekki.io/api-node/account/plan', {
  method: 'GET',
  mode: 'cors',
  credentials: 'include',
  headers: { 'Accept': 'application/json' },
});
    const contentType = res.headers.get('content-type') || '';
    const text = await res.text();

    if (!res.ok) {
      throw new Error(`HTTP ${res.status}: ${text.slice(0,120)}`);
    }
    if (!contentType.includes('application/json')) {
      throw new Error(`Unexpected response (not JSON): ${text.slice(0,120)}`);
    }

    const data = JSON.parse(text);
    setPlan(data);
    console.log('Plan from backend:', data);
  } catch (err) {
    console.error('Failed to load plan', err);
    setPlanError(err.message || 'Failed to load plan');
  } finally {
    setPlanLoading(false);
  }
}

  // ====== JSX ======
  return (
    <div className="home-container">
      {/* Background decoration */}
      <div className="bg-decoration bg-pattern-1" />
      <div className="bg-decoration bg-square-1" />
      <div className="bg-decoration bg-pattern-2" />
      <div className="bg-decoration bg-square-2" />

      {/* Branding */}
      <div className="home-branding">SEKKI</div>

      {/* Profile (top-right) */}
      <div className="profile-container" ref={dropdownRef}>
        <button
          className="profile-trigger"
          onClick={() => setShowProfileDropdown((v) => !v)}
          aria-haspopup="menu"
          aria-expanded={showProfileDropdown}
        >
          <div className="profile-avatar">{initials}</div>
        </button>

        {showProfileDropdown && (
          <div className="profile-dropdown" role="menu">
            <div className="profile-header">
              <div className="profile-avatar-large">{initials}</div>
              <div className="profile-info">
                <div className="profile-name">{user?.name || firstName}</div>
                <div className="profile-email">{userEmail}</div>
              </div>
            </div>

            <div className="profile-divider" />

            {/* keep Credits row read-only (can swap later to seats meter) */}
            <button className="profile-menu-item profile-credits">
              <FontAwesomeIcon icon={faBolt} className="profile-menu-icon" />
              <span>Credits</span>
              <span className="profile-credits-count">0</span>
              <FontAwesomeIcon icon={faChevronRight} className="profile-menu-arrow" />
            </button>

            <div className="profile-divider" />

            <button className="profile-menu-item">
              <FontAwesomeIcon icon={faLightbulb} className="profile-menu-icon" />
              <span>Knowledge</span>
            </button>

            <button className="profile-menu-item" onClick={handleAccountClick}>
              <FontAwesomeIcon icon={faUser} className="profile-menu-icon" />
              <span>Account</span>
            </button>

            <button className="profile-menu-item">
              <FontAwesomeIcon icon={faCog} className="profile-menu-icon" />
              <span>Settings</span>
            </button>

            <button className="profile-menu-item">
              <FontAwesomeIcon icon={faHome} className="profile-menu-icon" />
              <span>Homepage</span>
              <FontAwesomeIcon icon={faExternalLinkAlt} className="profile-menu-external" />
            </button>

            <button className="profile-menu-item">
              <FontAwesomeIcon icon={faQuestionCircle} className="profile-menu-icon" />
              <span>Get help</span>
              <FontAwesomeIcon icon={faExternalLinkAlt} className="profile-menu-external" />
            </button>

            <div className="profile-divider" />

            <button className="profile-menu-item profile-logout">
              <FontAwesomeIcon icon={faSignOutAlt} className="profile-menu-icon" />
              <span>Sign out</span>
            </button>
          </div>
        )}
      </div>

      {/* Account Modal */}
      {showAccountModal && (
        <div className="modal-overlay" ref={modalRef}>
          <div className="modal-container">
            <button
              className="modal-close"
              onClick={() => {
                setShowAccountModal(false);
                setActiveAccountTab('account');
              }}
              aria-label="Close"
            >
              <FontAwesomeIcon icon={faTimes} />
            </button>

            {/* Sidebar */}
            <div className="modal-sidebar">
              <div className="modal-sidebar-header">
                <i className="fas fa-cog modal-logo" />
                <span className="modal-sidebar-title">SEKKI</span>
              </div>

              <nav className="modal-sidebar-nav">
                <button
                  className={`modal-sidebar-item ${activeAccountTab === 'account' ? 'active' : ''}`}
                  onClick={() => setActiveAccountTab('account')}
                >
                  <FontAwesomeIcon icon={faUser} />
                  <span>Account</span>
                </button>

                <button
                  className={`modal-sidebar-item ${activeAccountTab === 'settings' ? 'active' : ''}`}
                  onClick={() => setActiveAccountTab('settings')}
                >
                  <FontAwesomeIcon icon={faCog} />
                  <span>Settings</span>
                </button>

                <button
                  className={`modal-sidebar-item ${activeAccountTab === 'usage' ? 'active' : ''}`}
                  onClick={() => setActiveAccountTab('usage')}
                >
                  <FontAwesomeIcon icon={faChartBar} />
                  <span>Usage</span>
                </button>

                <button
                  className={`modal-sidebar-item ${activeAccountTab === 'billing' ? 'active' : ''}`}
                  onClick={() => setActiveAccountTab('billing')}
                >
                  <FontAwesomeIcon icon={faCreditCard} />
                  <span>Billing</span>
                </button>

                {isAdmin && (
                  <>
                    <button
                      className={`modal-sidebar-item ${activeAccountTab === 'scheduled' ? 'active' : ''}`}
                      onClick={() => setActiveAccountTab('scheduled')}
                    >
                      <FontAwesomeIcon icon={faCalendarAlt} />
                      <span>Scheduled tasks</span>
                    </button>

                    <button
                      className={`modal-sidebar-item ${activeAccountTab === 'mail' ? 'active' : ''}`}
                      onClick={() => setActiveAccountTab('mail')}
                    >
                      <FontAwesomeIcon icon={faEnvelope} />
                      <span>Mail SEKKI</span>
                    </button>

                    <button
                      className={`modal-sidebar-item ${activeAccountTab === 'data' ? 'active' : ''}`}
                      onClick={() => setActiveAccountTab('data')}
                    >
                      <FontAwesomeIcon icon={faDatabase} />
                      <span>Data controls</span>
                    </button>

                    <button
                      className={`modal-sidebar-item ${activeAccountTab === 'cloud' ? 'active' : ''}`}
                      onClick={() => setActiveAccountTab('cloud')}
                    >
                      <FontAwesomeIcon icon={faCloud} />
                      <span>Cloud browser</span>
                    </button>

                    <button
                      className={`modal-sidebar-item ${activeAccountTab === 'connectors' ? 'active' : ''}`}
                      onClick={() => setActiveAccountTab('connectors')}
                    >
                      <FontAwesomeIcon icon={faPlug} />
                      <span>Connectors</span>
                    </button>

                    <button
                      className={`modal-sidebar-item ${activeAccountTab === 'integrations' ? 'active' : ''}`}
                      onClick={() => setActiveAccountTab('integrations')}
                    >
                      <FontAwesomeIcon icon={faPuzzlePiece} />
                      <span>Integrations</span>
                    </button>
                  </>
                )}

                <div className="modal-sidebar-divider" />

                <button
                  className={`modal-sidebar-item ${activeAccountTab === 'help' ? 'active' : ''}`}
                  onClick={() => setActiveAccountTab('help')}
                >
                  <FontAwesomeIcon icon={faQuestionCircle} />
                  <span>Get help</span>
                  <FontAwesomeIcon icon={faExternalLinkAlt} className="modal-sidebar-external" />
                </button>
              </nav>
            </div>

            {/* Modal Content */}
            <div className="account-modal-content compact">
              {/* ACCOUNT (Seats+) */}
              {activeAccountTab === 'account' && (
                <>
                  <h2 className="account-modal-title">ACCOUNT</h2>

                  <div className="section">
                    <div className="section-title">Organization</div>
                    <div className="info-row">
                      <span className="info-label">Organization name</span>
                      <span className="info-value">Acme Corp</span>
                    </div>
                    <div className="info-row">
                      <span className="info-label">Your role</span>
                      <span className="info-value">{isAdmin ? 'Administrator' : 'Member'}</span>
                    </div>
                  </div>

                  <div className="section">
                    <div className="section-title">Seat Summary</div>
                    <div className="info-row">
                      <span className="info-label">Creators</span>
                      <span className="info-value">3 / 5</span>
                    </div>
                    <div className="info-row">
                      <span className="info-label">Viewers</span>
                      <span className="info-value">7 / 15</span>
                    </div>
                    <div className="info-row">
                      <span className="info-label">Cap</span>
                      <span className="info-value">5 Creators, 15 Viewers (3 per Creator)</span>
                    </div>
                    <div className="microcopy">
                      <FontAwesomeIcon icon={faInfoCircle} /> Licensing is seats-based. Viewers capped at 3 per Creator.
                    </div>
                  </div>

                  <div className="section">
                    <div className="section-title">Actions</div>
                    <div className="btn-group">
<button className="btn btn-primary" type="button" onClick={handleInviteClick}>
  <FontAwesomeIcon icon={faUser} /> Invite User
</button>
<button
  className="btn btn-secondary"
  type="button"
  onClick={openBilling}
>
  <FontAwesomeIcon icon={faCreditCard} /> Manage Plan
</button>
                      <button
                        className="btn btn-secondary"
                        type="button"
                        onClick={() => setActiveAccountTab('usage')}
                      >
                        <FontAwesomeIcon icon={faChartBar} /> View Seat Usage
                      </button>
                    </div>
                  </div>
                </>
              )}

              {/* INTEGRATIONS */}
              {activeAccountTab === 'integrations' && (
                <>
                  <h2 className="account-modal-title">INTEGRATIONS</h2>

                  <div className="helper-text">
                    <strong>Get started:</strong> Connect your data sources to unlock powerful insights. Start with
                    CSV/Excel or Spaces for quick setup.
                  </div>

                  <div className="integrations-grid">
                    {tiles.map((t) => (
                      <div
                        key={t.key}
                        className={`integration-tile ${stateClass(t.state)}`}
                        role="button"
                        tabIndex={0}
                        aria-label={`${t.name} tile`}
                        onClick={(e) => {
                          e.stopPropagation();
                          if (t.state === 'locked') return;
                          if (t.onClick) t.onClick();
                        }}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault();
                            if (t.state !== 'locked' && t.onClick) t.onClick();
                          }
                        }}
                      >
                        {t.hasMenu && (t.state === 'connected' || t.state === 'syncing' || t.state === 'error') && (
                          <>
                            <button
                              className="integration-menu-btn"
                              aria-label="Options"
                              onClick={(e) => {
                                e.stopPropagation();
                                setMenuOpenFor((prev) => (prev === t.key ? null : t.key));
                              }}
                            >
                              <FontAwesomeIcon icon={faEllipsisV} />
                            </button>
                            <div className={`context-menu ${menuOpenFor === t.key ? 'active' : ''}`}>
                              <div className="context-menu-item" onClick={() => setDrawerOpen(true)}>
                                <i className="fas fa-cog" />
                                <span>Manage</span>
                              </div>
                              <div className="context-menu-item">
                                <FontAwesomeIcon icon={faSync} />
                                <span>Reconnect</span>
                              </div>
                              <div className="context-menu-item" onClick={() => setLogOpen(true)}>
                                <FontAwesomeIcon icon={faFileAlt} />
                                <span>View log</span>
                              </div>
                              <div className="context-menu-item">
                                <FontAwesomeIcon icon={faUnlink} />
                                <span>Disconnect</span>
                              </div>
                            </div>
                          </>
                        )}

                        <div className="integration-icon">{t.icon}</div>
                        <div className="integration-name">{t.name}</div>

                        {t.badge && (
                          <span className={`integration-badge ${badgeClass(t.badge)}`}>{t.badge}</span>
                        )}

                        {t.state === 'locked' ? (
                          <div className="integration-lock">
                            <FontAwesomeIcon icon={faLock} />
                          </div>
                        ) : (
                          <div className="integration-status">{renderStatusIcon(t.state)}</div>
                        )}

                        {t.tooltip && (
                          <div className="tooltip">
                            {t.tooltip.split('\n').map((line, i) => (
                              <div key={i}>{line}</div>
                            ))}
                          </div>
                        )}
                        {t.microcopy && <div className="integration-microcopy">{t.microcopy}</div>}
                      </div>
                    ))}
                  </div>
                </>
              )}

              {/* SETTINGS */}
              {activeAccountTab === 'settings' && (
                <>
                  <h2 className="account-modal-title">SETTINGS</h2>

                  <div className="section">
                    <div className="section-title">Organization Settings</div>

                    <ToggleSwitch
                      id="allowlist"
                      label="Domain allow-list"
                      checked={orgSettings.allowListOn}
                      onChange={(v) => setOrgSettings({ ...orgSettings, allowListOn: v })}
                    />

                    <div className="form-group">
                      <label className="form-label">Allowed domains</label>
                      <input
                        className="form-input"
                        value={orgSettings.allowedDomains}
                        placeholder="Enter domains separated by commas"
                        onChange={(e) => setOrgSettings({ ...orgSettings, allowedDomains: e.target.value })}
                      />
                    </div>

                    <ToggleSwitch
                      id="defaultdraft"
                      label="Default Draft Mode"
                      checked={orgSettings.defaultDraft}
                      onChange={(v) => setOrgSettings({ ...orgSettings, defaultDraft: v })}
                    />

                    <div className="form-group">
                      <label className="form-label">Default sync frequency</label>
                      <select
                        className="form-select"
                        value={orgSettings.defaultFreq}
                        onChange={(e) => setOrgSettings({ ...orgSettings, defaultFreq: e.target.value })}
                      >
                        <option>Manual</option>
                        <option>Hourly</option>
                        <option>Daily</option>
                        <option>Weekly</option>
                      </select>
                    </div>
                  </div>

                  <div className="section">
                    <div className="section-title">Personal Settings</div>

                    <div className="form-group">
                      <label className="form-label">Display name</label>
                      <input
                        className="form-input"
                        value={personal.displayName}
                        onChange={(e) => setPersonal({ ...personal, displayName: e.target.value })}
                      />
                    </div>

                    <div className="form-group">
                      <label className="form-label">Timezone</label>
                      <select
                        className="form-select"
                        value={personal.timezone}
                        onChange={(e) => setPersonal({ ...personal, timezone: e.target.value })}
                      >
                        <option>UTC-08:00 (Pacific Time)</option>
                        <option>UTC-07:00 (Mountain Time)</option>
                        <option>UTC-06:00 (Central Time)</option>
                        <option>UTC-05:00 (Eastern Time)</option>
                      </select>
                    </div>

                    <div className="form-group">
                      <label className="form-label">Locale</label>
                      <select
                        className="form-select"
                        value={personal.locale}
                        onChange={(e) => setPersonal({ ...personal, locale: e.target.value })}
                      >
                        <option>English (US)</option>
                        <option>English (UK)</option>
                        <option>Spanish</option>
                        <option>French</option>
                      </select>
                    </div>
                  </div>

                  <div className="section">
                    <div className="section-title">Notifications</div>

                    <ToggleSwitch
                      id="n-email-sync"
                      label="Sync success/failure (email)"
                      checked={notif.emailSync}
                      onChange={(v) => setNotif({ ...notif, emailSync: v })}
                    />
                    <ToggleSwitch
                      id="n-inapp-sync"
                      label="Sync success/failure (in-app)"
                      checked={notif.inappSync}
                      onChange={(v) => setNotif({ ...notif, inappSync: v })}
                    />
                    <ToggleSwitch
                      id="n-email-seats"
                      label="Seat soft-limit alerts (email)"
                      checked={notif.emailSeats}
                      onChange={(v) => setNotif({ ...notif, emailSeats: v })}
                    />
                    <ToggleSwitch
                      id="n-inapp-seats"
                      label="Seat soft-limit alerts (in-app)"
                      checked={notif.inappSeats}
                      onChange={(v) => setNotif({ ...notif, inappSeats: v })}
                    />
                  </div>

                  <button className="btn btn-primary" type="button" onClick={onSaveSettings}>
                    Save Settings
                  </button>
                </>
              )}

              {/* USAGE */}
              {activeAccountTab === 'usage' && (
                <>
                  <h2 className="account-modal-title">USAGE</h2>

                  <div className="section">
                    <div className="section-title">Overview</div>

                    <div className="stats-grid">
                      <StatCard value="3 / 5" label="Creators" />
                      <StatCard value="7 / 15" label="Viewers" />
                      <StatCard value="4 / 2 / 1" label="Integrations" sublabel="Connected / Draft / Errors" />
                      <StatCard value="2.4 GB" label="Parquet Storage" />
                      <StatCard value="1.8 GB" label="Raw Storage" />
                    </div>

                    <div className="btn-group">
                      <button className="btn btn-secondary" type="button" onClick={onExportUsage}>
                        <FontAwesomeIcon icon={faDownload} /> Export CSV
                      </button>
                      <button className="btn btn-secondary" type="button" onClick={() => onOpenRun('latest')}>
                        <FontAwesomeIcon icon={faFileAlt} /> Open Log
                      </button>
                    </div>
                  </div>

                  <div className="section">
                    <div className="section-title">Recent Sync Runs (Last 10)</div>

                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>Provider</th>
                          <th>Owner</th>
                          <th>Started</th>
                          <th>Rows</th>
                          <th>Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr>
                          <td>Salesforce</td>
                          <td>demo@sekki.io</td>
                          <td>2 hours ago</td>
                          <td>12,450</td>
                          <td>
                            <Badge tone="success">Success</Badge>
                          </td>
                        </tr>
                        <tr>
                          <td>Oracle Fusion</td>
                          <td>admin@sekki.io</td>
                          <td>4 hours ago</td>
                          <td>8,230</td>
                          <td>
                            <Badge tone="success">Success</Badge>
                          </td>
                        </tr>
                        <tr>
                          <td>CSV Upload</td>
                          <td>creator@sekki.io</td>
                          <td>6 hours ago</td>
                          <td>1,540</td>
                          <td>
                            <Badge tone="danger">Error</Badge>
                          </td>
                        </tr>
                      </tbody>
                    </table>
                  </div>

                  <div className="section">
                    <div className="section-title">Top Datasets by Size</div>

                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>Dataset</th>
                          <th>Provider</th>
                          <th>Size</th>
                          <th>Rows</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr>
                          <td>Accounts</td>
                          <td>Salesforce</td>
                          <td>1.2 GB</td>
                          <td>45,230</td>
                        </tr>
                        <tr>
                          <td>GL Transactions</td>
                          <td>Oracle Fusion</td>
                          <td>890 MB</td>
                          <td>128,450</td>
                        </tr>
                        <tr>
                          <td>Products</td>
                          <td>Salesforce</td>
                          <td>340 MB</td>
                          <td>12,890</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </>
              )}

              {/* BILLING */}
              {activeAccountTab === 'billing' && (
                <>
                  <h2 className="account-modal-title">BILLING</h2>
{planLoading && <div className="microcopy">Loading plan…</div>}
{planError && <div className="microcopy" style={{ color: '#b00020' }}>Error: {planError}</div>}
{plan && (
  <div className="microcopy">
    Loaded: {plan.plan} • Creators {plan.creatorsUsed}/{plan.creatorsCap} • Viewers {plan.viewersUsed}/{plan.viewersCap}
  </div>
)}

                  <div className="section">
                    <div className="section-title">Current Plan</div>

                    <div className="info-row">
                      <span className="info-label">Plan</span>
                      <span className="info-value">Premium</span>
                    </div>
                    <div className="info-row">
<span className="info-label">Renewal date</span>
<span className="info-value">{formatISODate(plan?.renewalDate)}</span>
                    </div>
                    <div className="info-row">
                      <span className="info-label">Creators</span>
                      <span className="info-value">3 / 5</span>
                    </div>
                    <div className="info-row">
                      <span className="info-label">Viewers</span>
                      <span className="info-value">7 / 15</span>
                    </div>
                    <div className="info-row">
                      <span className="info-label">Remaining viewer capacity</span>
                      <span className="info-value">8</span>
                    </div>

                    <div className="btn-group" style={{ marginTop: 16 }}>
<button className="btn btn-primary" type="button" onClick={() => startCheckout('premium')}>
  <FontAwesomeIcon icon={faArrowUp} /> Change Plan
</button>
<button className="btn btn-secondary" type="button" onClick={startBillingPortal}>
  <FontAwesomeIcon icon={faCreditCard} /> Update Payment
</button>
                    </div>
                  </div>

                  <div className="section">
                    <div className="section-title">Payment Method</div>

                    <div className="info-row">
                      <span className="info-label">Card</span>
                      <span className="info-value">
                        <span style={{ color: '#1a1f71', marginRight: 8 }}>●</span> •••• 4242
                      </span>
                    </div>
                  </div>

                  <div className="section">
                    <div className="section-title">Recent Invoices</div>

                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>Invoice</th>
                          <th>Date</th>
                          <th>Amount</th>
                          <th>Status</th>
                          <th>Action</th>
                        </tr>
                      </thead>
                      <tbody>
                        {[
                          { id: 'INV-2024-11', date: 'Nov 1, 2024', amt: '$199.00' },
                          { id: 'INV-2024-10', date: 'Oct 1, 2024', amt: '$199.00' },
                          { id: 'INV-2024-09', date: 'Sep 1, 2024', amt: '$199.00' },
                        ].map((row) => (
                          <tr key={row.id}>
                            <td>#{row.id}</td>
                            <td>{row.date}</td>
                            <td>{row.amt}</td>
                            <td>
                              <Badge tone="success">Paid</Badge>
                            </td>
                            <td>
                              <IconBtn title="Download" onClick={() => onDownloadInvoice(row.id)}>
                                <FontAwesomeIcon icon={faDownload} />
                              </IconBtn>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  <div className="section">
                    <div className="section-title">Add-ons</div>

                    <div className="list-item">
                      <div style={{ flex: 1 }}>
                        <div style={{ fontWeight: 600, color: '#161f3b', marginBottom: 4 }}>Extra Seats</div>
                        <div style={{ fontSize: 12, color: '#666' }}>Add more Creator or Viewer seats</div>
                      </div>
                      <button
                        className="btn btn-secondary"
                        type="button"
                        onClick={() => onPurchaseAddOn({ type: 'seats' })}
                      >
                        Purchase
                      </button>
                    </div>

                    <div className="list-item">
                      <div style={{ flex: 1 }}>
                        <div style={{ fontWeight: 600, color: '#161f3b', marginBottom: 4 }}>Airbyte Managed</div>
                        <div style={{ fontSize: 12, color: '#666' }}>
                          <Badge tone="warning">Enterprise</Badge> Managed Airbyte integration
                        </div>
                      </div>
                      <button
                        className="btn btn-secondary"
                        type="button"
                        onClick={() => onPurchaseAddOn({ type: 'airbyte' })}
                      >
                        Contact Sales
                      </button>
                    </div>
                  </div>
                </>
              )}

              {/* SCHEDULED TASKS */}
              {activeAccountTab === 'scheduled' && (
                <>
                  <h2 className="account-modal-title">SCHEDULED TASKS</h2>

                  <div className="section">
                    <div className="section-title">Default Frequency (Org-level)</div>

                    <div className="form-group">
                      <label className="form-label">Default for new connections</label>
                      <select
                        className="form-select"
                        value={orgSettings.defaultFreq}
                        onChange={(e) => setOrgSettings({ ...orgSettings, defaultFreq: e.target.value })}
                      >
                        <option>Manual</option>
                        <option>Hourly</option>
                        <option>Daily</option>
                        <option>Weekly</option>
                      </select>
                    </div>
                  </div>

                  <div className="section">
                    <div className="section-title">All Connections</div>

                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>Provider</th>
                          <th>Owner</th>
                          <th>Frequency</th>
                          <th>Next Run</th>
                          <th>Draft</th>
                          <th>Enabled</th>
                          <th>Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {[
                          {
                            id: 'conn-sfdc',
                            p: 'Salesforce',
                            owner: 'demo@sekki.io',
                            freq: 'Hourly',
                            next: 'In 23 min',
                            draft: false,
                            enabled: true,
                          },
                          {
                            id: 'conn-orcl',
                            p: 'Oracle Fusion',
                            owner: 'admin@sekki.io',
                            freq: 'Daily',
                            next: 'Tomorrow 6am',
                            draft: true,
                            enabled: true,
                          },
                          {
                            id: 'conn-csv1',
                            p: 'CSV Upload',
                            owner: 'creator@sekki.io',
                            freq: 'Manual',
                            next: '—',
                            draft: false,
                            enabled: false,
                          },
                        ].map((r) => (
                          <tr key={r.id}>
                            <td>{r.p}</td>
                            <td>{r.owner}</td>
                            <td>{r.freq}</td>
                            <td>{r.next}</td>
                            <td>{r.draft ? <Badge tone="warning">Draft</Badge> : <Badge tone="info">Live</Badge>}</td>
                            <td>{r.enabled ? <Badge tone="success">Yes</Badge> : <Badge tone="danger">No</Badge>}</td>
                            <td>
                              <IconBtn title="Run now" onClick={() => onRunNow(r.id)}>
                                <FontAwesomeIcon icon={faPlay} />
                              </IconBtn>
                              <IconBtn title="Edit" onClick={() => onUpdateSchedule(r.id, r.freq)}>
                                <FontAwesomeIcon icon={faEdit} />
                              </IconBtn>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )}

              {/* MAIL SEKKI */}
              {activeAccountTab === 'mail' && (
                <>
                  <h2 className="account-modal-title">MAIL SEKKI</h2>

                  <div className="section">
                    <div className="section-title">Contact Support</div>

                    <div className="form-group">
                      <label className="form-label">Subject</label>
                      <input
                        className="form-input"
                        placeholder="Brief description of your issue"
                        style={{ maxWidth: 600 }}
                      />
                    </div>

                    <div className="form-group">
                      <label className="form-label">Category</label>
                      <select className="form-select">
                        <option>Billing</option>
                        <option>Integration</option>
                        <option>Bug</option>
                        <option>Question</option>
                      </select>
                    </div>

                    <div className="form-group">
                      <label className="form-label">Details</label>
                      <textarea
                        className="form-textarea"
                        placeholder="Provide details about your issue..."
                        style={{ maxWidth: 600 }}
                      />
                    </div>

                    <div className="form-group">
                      <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
                        <input type="checkbox" defaultChecked />
                        <span className="form-label" style={{ margin: 0 }}>
                          Attach logs
                        </span>
                      </label>
                    </div>

                    <button className="btn btn-primary" type="button" onClick={() => onSendSupport({})}>
                      <i className="fas fa-paper-plane" /> Send
                    </button>

                    <div className="microcopy" style={{ maxWidth: 600 }}>
                      <FontAwesomeIcon icon={faInfoCircle} /> Your role ({isAdmin ? 'Administrator' : 'Member'}) and
                      current page context will be included automatically.
                    </div>
                  </div>
                </>
              )}

              {/* DATA CONTROLS */}
              {activeAccountTab === 'data' && (
                <>
                  <h2 className="account-modal-title">DATA CONTROLS</h2>

                  <div className="section">
                    <div className="section-title">Retention & Privacy</div>

                    <div className="form-group">
                      <label className="form-label">Raw sync logs retention (days)</label>
                      <input
                        type="number"
                        className="form-input"
                        value={dataControls.retentionDays}
                        min={1}
                        max={365}
                        onChange={(e) =>
                          setDataControls({ ...dataControls, retentionDays: Number(e.target.value || 0) })
                        }
                      />
                    </div>

                    <ToggleSwitch
                      id="dl-full-log"
                      label="Download full log"
                      checked={dataControls.downloadFullLog}
                      onChange={(v) => setDataControls({ ...dataControls, downloadFullLog: v })}
                    />
                    <ToggleSwitch
                      id="pii-min"
                      label="PII minimization"
                      checked={dataControls.piiMin}
                      onChange={(v) => setDataControls({ ...dataControls, piiMin: v })}
                    />

                    <button
                      className="btn btn-primary"
                      type="button"
                      onClick={() => console.log('SAVE data controls', dataControls)}
                    >
                      Save Controls
                    </button>
                  </div>
                </>
              )}

              {/* CLOUD BROWSER */}
              {activeAccountTab === 'cloud' && (
                <>
                  <h2 className="account-modal-title">CLOUD BROWSER</h2>

                  <div className="section">
                    <div className="section-title">Spaces (S3)</div>

                    <div style={{ fontSize: 13, color: '#666', marginBottom: 16 }}>
                      <FontAwesomeIcon icon={faFolder} /> sekki-bucket / org-acme / data
                    </div>

                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>Name</th>
                          <th>Type</th>
                          <th>Size</th>
                          <th>Modified</th>
                          <th>Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr>
                          <td>salesforce_accounts.parquet</td>
                          <td>Parquet</td>
                          <td>1.2 GB</td>
                          <td>2 hours ago</td>
                          <td>
                            <IconBtn title="Copy URL" onClick={() => onCopyLink('salesforce_accounts.parquet')}>
                              <FontAwesomeIcon icon={faLink} />
                            </IconBtn>
                            <IconBtn title="Download" onClick={() => onDownload('salesforce_accounts.parquet')}>
                              <FontAwesomeIcon icon={faDownload} />
                            </IconBtn>
                          </td>
                        </tr>
                        <tr>
                          <td>oracle_gl.parquet</td>
                          <td>Parquet</td>
                          <td>890 MB</td>
                          <td>4 hours ago</td>
                          <td>
                            <IconBtn title="Copy URL" onClick={() => onCopyLink('oracle_gl.parquet')}>
                              <FontAwesomeIcon icon={faLink} />
                            </IconBtn>
                            <IconBtn title="Download" onClick={() => onDownload('oracle_gl.parquet')}>
                              <FontAwesomeIcon icon={faDownload} />
                            </IconBtn>
                          </td>
                        </tr>
                        <tr>
                          <td>raw/</td>
                          <td>Folder</td>
                          <td>—</td>
                          <td>1 day ago</td>
                          <td>
                            <IconBtn title="Open" onClick={() => onNavigatePrefix('raw/')}>
                              <FontAwesomeIcon icon={faFolderOpen} />
                            </IconBtn>
                          </td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </>
              )}

              {/* CONNECTORS */}
              {activeAccountTab === 'connectors' && (
                <>
                  <h2 className="account-modal-title">CONNECTORS</h2>

                  <div className="section">
                    <div className="section-title">Available Connectors</div>

                    <div className="list-item">
                      <div style={{ flex: 1 }}>
                        <div style={{ fontWeight: 600, color: '#161f3b', marginBottom: 4 }}>Salesforce</div>
                        <div style={{ fontSize: 12, color: '#666' }}>
                          <Badge tone="info">Premium+</Badge> CRM data integration
                        </div>
                      </div>
                      <button className="btn btn-primary" type="button" onClick={() => onOpenConnector('salesforce')}>
                        Connect
                      </button>
                    </div>

                    <div className="list-item">
                      <div style={{ flex: 1 }}>
                        <div style={{ fontWeight: 600, color: '#161f3b', marginBottom: 4 }}>Oracle Fusion</div>
                        <div style={{ fontSize: 12, color: '#666' }}>
                          <Badge tone="warning">Enterprise</Badge> ERP &amp; financial data
                        </div>
                      </div>
                      <button className="btn btn-primary" type="button" onClick={() => onOpenConnector('oracle')}>
                        Connect
                      </button>
                    </div>

                    <div className="list-item">
                      <div style={{ flex: 1 }}>
                        <div style={{ fontWeight: 600, color: '#161f3b', marginBottom: 4 }}>CSV / Excel</div>
                        <div style={{ fontSize: 12, color: '#666' }}>Upload spreadsheets</div>
                      </div>
                      <button className="btn btn-primary" type="button" onClick={() => onOpenConnector('csv')}>
                        Connect
                      </button>
                    </div>

                    <div className="list-item">
                      <div style={{ flex: 1 }}>
                        <div style={{ fontWeight: 600, color: '#161f3b', marginBottom: 4 }}>Airbyte Managed</div>
                        <div style={{ fontSize: 12, color: '#666' }}>
                          <Badge tone="warning">Enterprise Add-on</Badge> 200+ connectors
                        </div>
                      </div>
                      <button
                        className="btn btn-secondary"
                        type="button"
                        onClick={() => console.log('REQUEST airbyte')}
                      >
                        Request
                      </button>
                    </div>
                  </div>
                </>
              )}

              {/* GET HELP */}
              {activeAccountTab === 'help' && (
                <>
                  <h2 className="account-modal-title">GET HELP</h2>

                  <div className="section">
                    <div className="section-title">Resources</div>

                    <div className="list-item">
                      <div style={{ flex: 1 }}>
                        <div style={{ fontWeight: 600, color: '#161f3b', marginBottom: 4 }}>Documentation</div>
                        <div style={{ fontSize: 12, color: '#666' }}>Browse guides and tutorials</div>
                      </div>
                      <IconBtn title="Open docs" onClick={() => window.open('#', '_blank')}>
                        <FontAwesomeIcon icon={faExternalLinkAlt} />
                      </IconBtn>
                    </div>

                    <div className="list-item">
                      <div style={{ flex: 1 }}>
                        <div style={{ fontWeight: 600, color: '#161f3b', marginBottom: 4 }}>Status Page</div>
                        <div style={{ fontSize: 12, color: '#666' }}>Check system status</div>
                      </div>
                      <IconBtn title="Open status" onClick={() => window.open('#', '_blank')}>
                        <FontAwesomeIcon icon={faExternalLinkAlt} />
                      </IconBtn>
                    </div>

                    <div className="list-item">
                      <div style={{ flex: 1 }}>
                        <div style={{ fontWeight: 600, color: '#161f3b', marginBottom: 4 }}>Contact Support</div>
                        <div style={{ fontSize: 12, color: '#666' }}>Pre-fills Mail SEKKI form</div>
                      </div>
                      <button className="btn btn-primary" type="button" onClick={() => setActiveAccountTab('mail')}>
                        Contact
                      </button>
                    </div>
                  </div>
                </>
              )}
            </div>

            {/* Right-side drawer (Connection wizard) */}
            <div className={`drawer-overlay ${drawerOpen ? 'active' : ''}`} onClick={() => setDrawerOpen(false)} />
            <div className={`drawer ${drawerOpen ? 'active' : ''}`} role="dialog" aria-modal="true">
              <div className="drawer-header">
                <div className="drawer-title">{drawerTitle}</div>
                <button className="drawer-close" onClick={() => setDrawerOpen(false)}>
                  <FontAwesomeIcon icon={faTimes} />
                </button>
              </div>

              <div className="drawer-content">
                {/* Progress bars */}
                <div className="wizard-steps">
                  <div className={`wizard-step ${wizardStep > 1 ? 'completed' : 'active'}`} />
                  <div className={`wizard-step ${wizardStep === 2 ? 'active' : wizardStep > 2 ? 'completed' : ''}`} />
                  <div className={`wizard-step ${wizardStep === 3 ? 'active' : wizardStep > 3 ? 'completed' : ''}`} />
                  <div className={`wizard-step ${wizardStep === 4 ? 'active' : wizardStep > 4 ? 'completed' : ''}`} />
                  <div className={`wizard-step ${wizardStep === 5 ? 'active' : ''}`} />
                </div>

                {/* Step 1 */}
                <div className={`step-content ${wizardStep === 1 ? 'active' : ''}`}>
                  <div className="step-title">Step 1: Choose Scope</div>
                  <div className="step-description">
                    Decide whether this connection is for your personal use or shared across your organization.
                  </div>

                  <div className="form-group">
                    <div className="form-radio-group">
                      <label className="form-radio-option">
                        <input type="radio" name="scope" defaultChecked />
                        <div className="form-radio-label">
                          <div className="form-radio-title">Organization-wide</div>
                          <div className="form-radio-description">
                            All team members can use this connection. Requires admin approval.
                          </div>
                        </div>
                      </label>
                      <label className="form-radio-option">
                        <input type="radio" name="scope" />
                        <div className="form-radio-label">
                          <div className="form-radio-title">Personal</div>
                          <div className="form-radio-description">
                            Only you can access this connection. No approval needed.
                          </div>
                        </div>
                      </label>
                    </div>
                  </div>
                </div>

                {/* Step 2 */}
                <div className={`step-content ${wizardStep === 2 ? 'active' : ''}`}>
                  <div className="step-title">Step 2: Authentication</div>
                  <div className="step-description">Connect securely using OAuth or API key.</div>

                  <div className="form-group">
                    <label className="form-label">Connection Name</label>
                    <input
                      type="text"
                      className="form-input"
                      placeholder="e.g., GridPoint-Sales Cloud"
                      defaultValue="GridPoint-Sales Cloud"
                    />
                  </div>

                  <div className="form-group">
                    <label className="form-label">Authentication Method</label>
                    <select className="form-select" defaultValue="oauth">
                      <option value="oauth">OAuth 2.0 (Recommended)</option>
                      <option value="apikey">API Key</option>
                    </select>
                  </div>

                  <div className="form-group">
                    <button className="btn btn-primary" style={{ width: '100%' }}>
                      <FontAwesomeIcon icon={faSalesforce} style={{ marginRight: 8 }} />
                      Authorize with Salesforce
                    </button>
                  </div>
                </div>

                {/* Step 3 */}
                <div className={`step-content ${wizardStep === 3 ? 'active' : ''}`}>
                  <div className="step-title">Step 3: Select Objects</div>
                  <div className="step-description">Choose which objects to sync. We’ve pre-selected common ones.</div>

                  <div className="form-group">
                    <label className="form-label">Preset Templates</label>
                    <select className="form-select" defaultValue="sales">
                      <option value="sales">Sales &amp; Opportunity Tracking</option>
                      <option value="support">Customer Service &amp; Cases</option>
                      <option value="mktg">Marketing &amp; Campaigns</option>
                      <option value="custom">Custom Selection</option>
                    </select>
                  </div>

                  <div className="form-group">
                    <label className="form-label">Objects to Sync</label>
                    <div className="form-checkbox-group">
                      {['Accounts', 'Opportunities', 'Products', 'Contacts', 'Cases', 'Leads'].map((label, idx) => (
                        <label key={label} className="form-checkbox-option">
                          <input type="checkbox" defaultChecked={idx < 3} />
                          <span className="form-checkbox-label">{label}</span>
                        </label>
                      ))}
                    </div>
                  </div>
                </div>

                {/* Step 4 */}
                <div className={`step-content ${wizardStep === 4 ? 'active' : ''}`}>
                  <div className="step-title">Step 4: Map &amp; Validate</div>
                  <div className="step-description">
                    Review field mappings and preview a sample of your data.
                  </div>

                  <div className="form-group">
                    <label className="form-label">Field Mapping</label>
                    <div style={{ fontSize: 12, color: '#666', marginBottom: 12 }}>
                      Auto-detected based on standard Salesforce schema. Click to customize.
                    </div>
                    <button className="btn btn-secondary" style={{ width: '100%' }}>
                      <i className="fas fa-edit" style={{ marginRight: 8 }} />
                      Customize Field Mapping
                    </button>
                  </div>

                  <div className="form-group">
                    <label className="form-label">Sample Data Preview</label>
                    <table className="preview-table">
                      <thead>
                        <tr>
                          <th>Account Name</th>
                          <th>Opportunity</th>
                          <th>Amount</th>
                          <th>Stage</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr>
                          <td>Acme Corp</td>
                          <td>Q4 Enterprise Deal</td>
                          <td>$125,000</td>
                          <td>Negotiation</td>
                        </tr>
                        <tr>
                          <td>GlobalTech Inc</td>
                          <td>Platform Upgrade</td>
                          <td>$85,000</td>
                          <td>Proposal</td>
                        </tr>
                        <tr>
                          <td>Innovate LLC</td>
                          <td>New Implementation</td>
                          <td>$200,000</td>
                          <td>Closed Won</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* Step 5 */}
                <div className={`step-content ${wizardStep === 5 ? 'active' : ''}`}>
                  <div className="step-title">Step 5: Schedule &amp; Save</div>
                  <div className="step-description">Set up automatic sync or run manually.</div>

                  <div className="form-group">
                    <label className="form-label">Sync Frequency</label>
                    <select className="form-select" defaultValue="6h">
                      <option value="manual">Manual only</option>
                      <option value="hourly">Every hour</option>
                      <option value="6h">Every 6 hours</option>
                      <option value="daily">Daily at 6:00 AM</option>
                      <option value="weekly">Weekly on Monday</option>
                    </select>
                  </div>

                  <div className="form-group">
                    <label className="form-label">Draft Mode</label>
                    <div style={{ fontSize: 12, color: '#666', marginBottom: 12 }}>
                      Test your connection without affecting live data pipelines.
                    </div>
                    <label className="form-checkbox-option">
                      <input type="checkbox" defaultChecked />
                      <span className="form-checkbox-label">Save as draft (publish when ready)</span>
                    </label>
                  </div>

                  <div className="helper-text">
                    <FontAwesomeIcon icon={faInfoCircle} style={{ marginRight: 8 }} />
                    Your connection will be saved as a draft. You can test and refine it before publishing to make it
                    live.
                  </div>
                </div>
              </div>

              <div className="drawer-footer">
                <button
                  className="btn btn-secondary"
                  onClick={() => setWizardStep((s) => Math.max(1, s - 1))}
                  disabled={wizardStep <= 1}
                >
                  Back
                </button>
                <button className="btn btn-primary" onClick={() => setWizardStep((s) => Math.min(5, s + 1))}>
                  Next
                </button>
              </div>
            </div>

            {/* Request Integration Modal */}
            <div
              className={`integrations-modal-overlay ${requestOpen ? 'active' : ''}`}
              onClick={() => setRequestOpen(false)}
            >
              <div className="integrations-modal" onClick={(e) => e.stopPropagation()}>
                <div className="integrations-modal-header">
                  <div className="integrations-modal-title">Request an Integration</div>
                  <button className="integrations-modal-close" onClick={() => setRequestOpen(false)}>
                    <FontAwesomeIcon icon={faTimes} />
                  </button>
                </div>
                <div className="integrations-modal-body">
                  <div className="form-group">
                    <label className="form-label">Integration Name</label>
                    <input type="text" className="form-input" placeholder="e.g., HubSpot, Workday, SAP" />
                  </div>
                  <div className="form-group">
                    <label className="form-label">Documentation Link (optional)</label>
                    <input type="text" className="form-input" placeholder="https://..." />
                  </div>
                  <div className="form-group">
                    <label className="form-label">Priority</label>
                    <select className="form-select" defaultValue="medium">
                      <option value="low">Low - Nice to have</option>
                      <option value="medium">Medium - Needed soon</option>
                      <option value="high">High - Blocking our workflow</option>
                    </select>
                  </div>
                  <div className="form-group">
                    <label className="form-label">Additional Details</label>
                    <textarea className="form-textarea" rows={4} placeholder="Tell us more about your use case..." />
                  </div>
                </div>
                <div className="integrations-modal-footer">
                  <button className="btn btn-secondary" onClick={() => setRequestOpen(false)}>
                    Cancel
                  </button>
                  <button className="btn btn-primary">Submit Request</button>
                </div>
              </div>
            </div>

            {/* Log Viewer Modal */}
            <div className={`integrations-modal-overlay ${logOpen ? 'active' : ''}`} onClick={() => setLogOpen(false)}>
              <div className="integrations-modal" onClick={(e) => e.stopPropagation()}>
                <div className="integrations-modal-header">
                  <div className="integrations-modal-title">Sync Log - Salesforce</div>
                  <button className="integrations-modal-close" onClick={() => setLogOpen(false)}>
                    <FontAwesomeIcon icon={faTimes} />
                  </button>
                </div>
                <div className="integrations-modal-body">
                  <div className="log-viewer">
                    {[
                      '[2024-11-22 14:32:15] [INFO] Starting sync for connection: GridPoint-Sales Cloud',
                      '[2024-11-22 14:32:16] [INFO] Authenticating with Salesforce API...',
                      '[2024-11-22 14:32:17] [SUCCESS] Authentication successful',
                      '[2024-11-22 14:32:18] [INFO] Fetching Accounts object...',
                      '[2024-11-22 14:32:22] [SUCCESS] Retrieved 4,523 records from Accounts',
                      '[2024-11-22 14:32:23] [INFO] Fetching Opportunities object...',
                      '[2024-11-22 14:32:28] [SUCCESS] Retrieved 7,891 records from Opportunities',
                      '[2024-11-22 14:32:29] [INFO] Fetching Products object...',
                      '[2024-11-22 14:32:31] [SUCCESS] Retrieved 342 records from Products',
                      '[2024-11-22 14:32:32] [INFO] Validating data integrity...',
                      '[2024-11-22 14:32:35] [SUCCESS] Validation complete - no errors found',
                      '[2024-11-22 14:32:36] [INFO] Writing to data warehouse...',
                      '[2024-11-22 14:32:42] [SUCCESS] Sync completed successfully - 12,756 total rows',
                    ].map((line, idx) => {
                      const ts = line.slice(0, 21);
                      const level = line.includes('[SUCCESS]')
                        ? 'success'
                        : line.includes('[INFO]')
                        ? 'info'
                        : 'error';
                      const message = line.replace(ts + ' ', '');
                      return (
                        <div className="log-line" key={idx}>
                          <span className="log-timestamp">{ts}</span>{' '}
                          <span className={`log-level-${level}`}>
                            {message.match(/\[(INFO|SUCCESS|ERROR)\]/)?.[0]}
                          </span>{' '}
                          {message.replace(/\[(INFO|SUCCESS|ERROR)\]\s?/, '')}
                        </div>
                      );
                    })}
                  </div>
                </div>
                <div className="integrations-modal-footer">
                  <button className="btn btn-secondary">Download Full Log</button>
                  <button className="btn btn-primary" onClick={() => setLogOpen(false)}>
                    Done
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Main content */}
      <div className="home-content">
        <div className="home-welcome">Welcome, {firstName}</div>
        <h1 className="home-title">Choose Your Path</h1>

        <div className="options-container">
          {/* MarketIQ */}
          <div className="option">
            <button
              onClick={handleMarketIQClick}
              className="option-button primary"
              aria-label="MarketIQ — Market Analysis"
            >
              <span className="button-title">MarketIQ</span>
              <span className="button-subtitle">Market Analysis</span>
            </button>
            <div className="option-description">Market Analysis</div>
          </div>

          <div className="divider" />

          {/* In Queue */}
          <div className="option">
            <button
              onClick={handleActivitiesClick}
              className="option-button secondary"
              aria-label="In Queue — Project Bundles"
            >
              <span className="button-title">In Queue</span>
              <span className="button-subtitle">Project Bundles</span>
            </button>
            <div className="option-description">Projects in Flight</div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Home;
