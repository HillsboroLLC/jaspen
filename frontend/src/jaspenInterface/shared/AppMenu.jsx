// =============================================================================
// AppMenu.jsx
// Shared MENU tab + sidebar for all internal pages.
// Renders the exact same element as JaspenWorkspace's settings sidebar.
// =============================================================================

import React, { useState, useCallback, useEffect, useMemo, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faBars, faTimes, faListCheck, faPlus, faLayerGroup, faChartLine,
  faDownload, faClockRotateLeft, faUser, faGaugeHigh, faQuestionCircle,
  faBolt, faBell, faLock, faArrowUpRightFromSquare,
} from '@fortawesome/free-solid-svg-icons';

import { useAuth } from '../../shared/auth/AuthContext';
import { buildAuthHeaders } from '../../shared/auth/http';
import { API_BASE } from '../../config/apiBase';
import { buildInviteLink, buildInviteDisplay } from '../../shared/inviteLink';
import { getPlanConnectorSentence } from '../../shared/billing/planConnectors';
import { PLAN_ORDER, PLAN_RANK } from '../../shared/constants/appConstants';
import SidebarIdentityFooter from '../Workspace/components/SidebarIdentityFooter';
import './AppMenu.css';

// ---------------------------------------------------------------------------
// Constants (mirrors JaspenWorkspace)
// ---------------------------------------------------------------------------
function highestPlanKey(...plans) {
  return plans
    .filter((plan) => Object.prototype.hasOwnProperty.call(PLAN_RANK, plan))
    .sort((a, b) => PLAN_RANK[b] - PLAN_RANK[a])[0] || 'free';
}

async function copyText(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  // Fallback
  const el = document.createElement('textarea');
  el.value = text;
  el.setAttribute('readonly', '');
  el.style.position = 'absolute';
  el.style.left = '-9999px';
  document.body.appendChild(el);
  el.select();
  document.execCommand('copy');
  document.body.removeChild(el);
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export default function AppMenu() {
  const navigate = useNavigate();
  const {
    user,
    logout,
    updateDisplayName,
    isPlatformAdmin,
    isEnterpriseAdmin,
    canManageOrg,
    isOrgCreator,
    planCategory,
  } = useAuth();

  // Sidebar open state
  const [open, setOpen] = useState(false);

  // Billing
  const [billingStatus, setBillingStatus] = useState(null);
  const [billingCatalog, setBillingCatalog] = useState({ plans: {}, overage_packs: {}, model_types: {} });
  const [billingLoading, setBillingLoading] = useState(true);
  const [billingMessage, setBillingMessage] = useState('');
  const [billingModalOpen, setBillingModalOpen] = useState(false);
  const [billingActionLoading, setBillingActionLoading] = useState(null);

  // Notifications (simple badge only – no live feed on non-workspace pages)
  const [notificationsOpen, setNotificationsOpen] = useState(false);

  // Invite link copy state
  const [inviteCopied, setInviteCopied] = useState(false);
  const inviteCopyTimerRef = useRef(null);

  // Display name editor
  const [nameModalOpen, setNameModalOpen] = useState(false);
  const [nameInput, setNameInput] = useState('');
  const [nameError, setNameError] = useState('');
  const [nameSaving, setNameSaving] = useState(false);

  // Display name derived from auth
  const [displayName, setDisplayName] = useState(() => {
    try {
      const keys = user?.id
        ? [`jaspen_display_name_id_${user.id}`]
        : user?.email
        ? [`jaspen_display_name_email_${String(user.email).toLowerCase()}`]
        : [];
      for (const k of keys) {
        const v = localStorage.getItem(k);
        if (v) return v;
      }
    } catch {}
    return user?.name || user?.email?.split('@')[0] || '';
  });

  // Invite link
  const inviteCode = String(user?.referral_code || '').trim();
  const inviteLink = buildInviteLink(inviteCode);
  const inviteDisplay = buildInviteDisplay(inviteCode);

  // ---------------------------------------------------------------------------
  // Billing fetch
  // ---------------------------------------------------------------------------
  const loadBilling = useCallback(async () => {
    setBillingLoading(true);
    try {
      const [statusRes, catalogRes] = await Promise.all([
        fetch(`${API_BASE}/api/v1/billing/status`, {
          headers: buildAuthHeaders({}, 'GET'),
          credentials: 'include',
        }),
        fetch(`${API_BASE}/api/v1/billing/catalog`, { credentials: 'include' }),
      ]);
      const statusData = await statusRes.json().catch(() => ({}));
      const catalogData = await catalogRes.json().catch(() => ({}));
      if (statusRes.ok) {
        setBillingStatus(statusData || null);
        setBillingCatalog(catalogData || { plans: {}, overage_packs: {}, model_types: {} });
        setBillingMessage('');
      } else {
        setBillingMessage(statusData?.msg || 'Unable to load plan details.');
      }
    } catch (err) {
      setBillingMessage(err.message || 'Unable to load plan details.');
    } finally {
      setBillingLoading(false);
    }
  }, []);

  useEffect(() => {
    loadBilling();
  }, [loadBilling, user?.id, user?.email]);

  // Toggle body class so CSS can push page content when sidebar is open/closed
  useEffect(() => {
    document.body.classList.toggle('jaspen-sidebar-open', open);
    return () => document.body.classList.remove('jaspen-sidebar-open');
  }, [open]);

  // ---------------------------------------------------------------------------
  // Plan flags (mirrors JaspenWorkspace)
  // ---------------------------------------------------------------------------
  const plans = billingCatalog?.plans || {};
  const currentPlanKey = String(billingStatus?.plan_key || 'free').toLowerCase();
  const effectivePlanKey = highestPlanKey(
    currentPlanKey,
    user?.active_organization_plan_key,
    user?.subscription_plan,
  );
  const previewPlanCategory =
    effectivePlanKey === 'enterprise'
      ? 'enterprise'
      : effectivePlanKey === 'team'
      ? 'team'
      : 'individual';

  const currentPlanLabel =
    plans[currentPlanKey]?.label ||
    (currentPlanKey[0]?.toUpperCase() + currentPlanKey.slice(1));

  const footerPlanKey = highestPlanKey(
    user?.active_organization_plan_key,
    user?.subscription_plan,
    currentPlanKey,
  );
  const footerPlanLabel =
    plans[footerPlanKey]?.label ||
    (footerPlanKey[0]?.toUpperCase() + footerPlanKey.slice(1));

  const effectiveIsCreator = isOrgCreator;
  const effectiveCanManageOrg = canManageOrg;

  const canStartOrgProjects =
    previewPlanCategory === 'individual' ||
    effectiveIsCreator ||
    isPlatformAdmin;

  const showRealDashboard =
    previewPlanCategory !== 'individual' || isPlatformAdmin;
  const showLockedDashboard =
    previewPlanCategory === 'individual' && !isPlatformAdmin;
  const showRealInsights =
    isPlatformAdmin || PLAN_RANK[effectivePlanKey] >= PLAN_RANK.team;
  const showLockedInsights = !showRealInsights;
  const showRealReports =
    isPlatformAdmin || PLAN_RANK[effectivePlanKey] >= PLAN_RANK.team;
  const showLockedReports = !showRealReports;
  const showRealActivity =
    isPlatformAdmin || PLAN_RANK[effectivePlanKey] >= PLAN_RANK.essential;
  const showLockedActivity = !showRealActivity;
  const showRealTeam = !isPlatformAdmin && effectiveCanManageOrg;
  const showLockedTeam =
    previewPlanCategory === 'individual' && !isPlatformAdmin;
  const showRealConnectors =
    isPlatformAdmin || PLAN_RANK[effectivePlanKey] >= PLAN_RANK.essential;
  const showLockedConnectors = !showRealConnectors;

  const batchIdeasPlanUnlocked =
    isPlatformAdmin || PLAN_RANK[effectivePlanKey] >= PLAN_RANK.team;
  const batchIdeasRoleUnlocked =
    previewPlanCategory !== 'individual' &&
    (effectiveIsCreator || isPlatformAdmin);
  const canUseBatchIdeas = batchIdeasPlanUnlocked && batchIdeasRoleUnlocked;
  const batchIdeasLocked = !canUseBatchIdeas;
  const batchIdeasLockReason = !batchIdeasPlanUnlocked
    ? 'plan'
    : !batchIdeasRoleUnlocked
    ? 'role'
    : null;

  const monthlyCreditLimit = billingStatus?.monthly_credit_limit;
  const creditsRemaining = billingStatus?.credits_remaining;
  const monthlyCreditsUsed = billingStatus?.credits_used;

  const resolvedMonthlyCreditsUsed = useMemo(() => {
    const direct = Number(monthlyCreditsUsed);
    if (Number.isFinite(direct)) return Math.max(0, direct);
    const limitNum = Number(monthlyCreditLimit);
    const remainingNum = Number(creditsRemaining);
    if (Number.isFinite(limitNum) && Number.isFinite(remainingNum)) {
      return Math.max(0, limitNum - remainingNum);
    }
    return null;
  }, [monthlyCreditsUsed, monthlyCreditLimit, creditsRemaining]);

  const creditsBadge =
    creditsRemaining == null
      ? 'Contracted'
      : Number(creditsRemaining || 0).toLocaleString();

  // ---------------------------------------------------------------------------
  // Handlers
  // ---------------------------------------------------------------------------
  const close = useCallback(() => setOpen(false), []);

  const handleLogout = useCallback(async () => {
    await logout();
  }, [logout]);

  const handleCopyInviteLink = useCallback(async () => {
    if (!inviteLink) return;
    try {
      await copyText(inviteLink);
      setInviteCopied(true);
      if (inviteCopyTimerRef.current) clearTimeout(inviteCopyTimerRef.current);
      inviteCopyTimerRef.current = setTimeout(() => setInviteCopied(false), 1800);
    } catch {}
  }, [inviteLink]);

  useEffect(
    () => () => {
      if (inviteCopyTimerRef.current) clearTimeout(inviteCopyTimerRef.current);
    },
    [],
  );

  const startBillingPlanChange = useCallback(
    async (planKey) => {
      setBillingActionLoading(planKey);
      try {
        const res = await fetch(
          `${API_BASE}/api/v1/billing/create-checkout-session`,
          {
            method: 'POST',
            headers: {
              ...buildAuthHeaders({}, 'POST'),
              'Content-Type': 'application/json',
            },
            credentials: 'include',
            body: JSON.stringify({ plan_key: planKey }),
          },
        );
        const data = await res.json().catch(() => ({}));
        if (data?.checkout_url) {
          window.location.href = data.checkout_url;
        } else {
          setBillingMessage(data?.msg || 'Unable to start checkout.');
        }
      } catch (err) {
        setBillingMessage(err.message || 'Unable to start checkout.');
      } finally {
        setBillingActionLoading(null);
      }
    },
    [],
  );

  const openBillingPortal = useCallback(async () => {
    setBillingActionLoading('portal');
    try {
      const res = await fetch(
        `${API_BASE}/api/v1/billing/create-portal-session`,
        {
          method: 'POST',
          headers: buildAuthHeaders({}, 'POST'),
          credentials: 'include',
        },
      );
      const data = await res.json().catch(() => ({}));
      if (data?.portal_url) {
        window.location.href = data.portal_url;
      } else {
        setBillingMessage(data?.msg || 'Unable to open billing portal.');
      }
    } catch (err) {
      setBillingMessage(err.message || 'Unable to open billing portal.');
    } finally {
      setBillingActionLoading(null);
    }
  }, []);

  const openDisplayNameEditor = useCallback(() => {
    setNameError('');
    setNameInput(displayName || user?.name || user?.email?.split?.('@')[0] || '');
    setNameModalOpen(true);
  }, [displayName, user]);

  const persistDisplayName = useCallback(
    async (value) => {
      const trimmed = String(value || '').trim();
      if (!trimmed) return;
      setNameError('');
      setNameSaving(true);
      const result = await updateDisplayName(trimmed);
      if (!result?.success) {
        setNameError(result?.error || 'Unable to save name.');
        setNameSaving(false);
        return;
      }
      try {
        const keys = [];
        if (user?.id) keys.push(`jaspen_display_name_id_${user.id}`);
        if (user?.email) keys.push(`jaspen_display_name_email_${String(user.email).toLowerCase()}`);
        keys.forEach((k) => localStorage.setItem(k, trimmed));
      } catch {}
      setDisplayName(trimmed);
      setNameSaving(false);
      setNameModalOpen(false);
    },
    [updateDisplayName, user],
  );

  // ---------------------------------------------------------------------------
  // Menu content (mirrors renderUserMenuContent in JaspenWorkspace)
  // ---------------------------------------------------------------------------
  const renderMenuContent = () => (
    <div className="jas-ud-layout">
      <div className="jas-ud-scroll">
        {isPlatformAdmin && (
          <div className="jas-ud-section">
            <div className="jas-ud-section-label">Role Switcher</div>
            <div className="jas-ud-role-switcher">
              <label className="jas-ud-role-switcher-label">
                Admin — viewing full access
              </label>
            </div>
          </div>
        )}

        <div className="jas-ud-section">
          <div className="jas-ud-section-label">Navigate</div>

          {showRealDashboard && (
            <button className="jas-ud-item" onClick={() => { close(); navigate('/dashboard'); }}>
              <FontAwesomeIcon icon={faListCheck} />
              <span className="jas-ud-item-label">Dashboard</span>
            </button>
          )}
          {showLockedDashboard && (
            <button
              className="jas-ud-item is-locked"
              onClick={() => setBillingModalOpen(true)}
              title="Upgrade to Team to unlock shared dashboards"
            >
              <FontAwesomeIcon icon={faListCheck} />
              <span className="jas-ud-item-label">Dashboard</span>
              <span className="jas-ud-item-ext"><FontAwesomeIcon icon={faLock} /></span>
            </button>
          )}

          {canStartOrgProjects && (
            <button className="jas-ud-item" onClick={() => { close(); navigate('/new'); }}>
              <FontAwesomeIcon icon={faPlus} />
              <span className="jas-ud-item-label">New Project</span>
            </button>
          )}

          <button
            className={`jas-ud-item ${batchIdeasLocked ? 'is-locked' : ''}`}
            onClick={() => { close(); navigate('/new'); }}
            title={
              batchIdeasLockReason === 'plan'
                ? 'Upgrade to Team to unlock batch idea upload'
                : batchIdeasLockReason === 'role'
                ? 'Only creators and admins can upload and promote batch ideas'
                : 'Upload and rank a portfolio of ideas'
            }
          >
            <FontAwesomeIcon icon={faLayerGroup} />
            <span className="jas-ud-item-label">Batch Ideas</span>
            {batchIdeasLocked && (
              <span className="jas-ud-item-ext"><FontAwesomeIcon icon={faLock} /></span>
            )}
          </button>

          <button className="jas-ud-item" onClick={() => { close(); navigate('/projects'); }}>
            <FontAwesomeIcon icon={faLayerGroup} />
            <span className="jas-ud-item-label">Projects</span>
          </button>

          <button className="jas-ud-item" onClick={() => { close(); navigate('/scores'); }}>
            <FontAwesomeIcon icon={faChartLine} />
            <span className="jas-ud-item-label">Scores</span>
          </button>

          {showRealInsights && (
            <button className="jas-ud-item" onClick={() => { close(); navigate('/insights'); }}>
              <FontAwesomeIcon icon={faChartLine} />
              <span className="jas-ud-item-label">Insights</span>
            </button>
          )}
          {showLockedInsights && (
            <button
              className="jas-ud-item is-locked"
              onClick={() => setBillingModalOpen(true)}
              title="Upgrade to Team to unlock connected insights"
            >
              <FontAwesomeIcon icon={faChartLine} />
              <span className="jas-ud-item-label">Insights</span>
              <span className="jas-ud-item-ext"><FontAwesomeIcon icon={faLock} /></span>
            </button>
          )}

          {showRealReports && (
            <button className="jas-ud-item" onClick={() => { close(); navigate('/reports'); }}>
              <FontAwesomeIcon icon={faDownload} />
              <span className="jas-ud-item-label">Reports</span>
            </button>
          )}
          {showLockedReports && (
            <button
              className="jas-ud-item is-locked"
              onClick={() => setBillingModalOpen(true)}
              title="Upgrade to Team to unlock reports"
            >
              <FontAwesomeIcon icon={faDownload} />
              <span className="jas-ud-item-label">Reports</span>
              <span className="jas-ud-item-ext"><FontAwesomeIcon icon={faLock} /></span>
            </button>
          )}

          {showRealActivity && (
            <button className="jas-ud-item" onClick={() => { close(); navigate('/activity'); }}>
              <FontAwesomeIcon icon={faClockRotateLeft} />
              <span className="jas-ud-item-label">Activity</span>
            </button>
          )}
          {showLockedActivity && (
            <button
              className="jas-ud-item is-locked"
              onClick={() => setBillingModalOpen(true)}
              title="Upgrade to Essential to unlock activity history"
            >
              <FontAwesomeIcon icon={faClockRotateLeft} />
              <span className="jas-ud-item-label">Activity</span>
              <span className="jas-ud-item-ext"><FontAwesomeIcon icon={faLock} /></span>
            </button>
          )}

          {showRealTeam && (
            <button className="jas-ud-item" onClick={() => { close(); navigate('/team'); }}>
              <FontAwesomeIcon icon={faUser} />
              <span className="jas-ud-item-label">Team</span>
            </button>
          )}
          {showLockedTeam && (
            <button
              className="jas-ud-item is-locked"
              onClick={() => setBillingModalOpen(true)}
              title="Upgrade to Team to unlock shared members and settings"
            >
              <FontAwesomeIcon icon={faUser} />
              <span className="jas-ud-item-label">Team</span>
              <span className="jas-ud-item-ext"><FontAwesomeIcon icon={faLock} /></span>
            </button>
          )}

          {!isPlatformAdmin && isEnterpriseAdmin && (
            <button className="jas-ud-item" onClick={() => { close(); navigate('/enterprise-admin'); }}>
              <FontAwesomeIcon icon={faGaugeHigh} />
              <span className="jas-ud-item-label">Enterprise Admin</span>
            </button>
          )}

          {showRealConnectors && (
            <button className="jas-ud-item" onClick={() => { close(); navigate('/connectors-manage'); }}>
              <FontAwesomeIcon icon={faLayerGroup} />
              <span className="jas-ud-item-label">Data Sources</span>
            </button>
          )}
          {showLockedConnectors && (
            <button
              className="jas-ud-item is-locked"
              onClick={() => setBillingModalOpen(true)}
              title="Upgrade to Essential to unlock starter data sources"
            >
              <FontAwesomeIcon icon={faLayerGroup} />
              <span className="jas-ud-item-label">Data Sources</span>
              <span className="jas-ud-item-ext"><FontAwesomeIcon icon={faLock} /></span>
            </button>
          )}

          <button className="jas-ud-item" onClick={() => { close(); navigate('/knowledge'); }}>
            <FontAwesomeIcon icon={faQuestionCircle} />
            <span className="jas-ud-item-label">Knowledge</span>
          </button>

          <button className="jas-ud-item" onClick={() => { close(); navigate('/account'); }}>
            <FontAwesomeIcon icon={faUser} />
            <span className="jas-ud-item-label">Account</span>
          </button>

          {isPlatformAdmin && (
            <button className="jas-ud-item" onClick={() => { close(); navigate('/jaspen-admin'); }}>
              <FontAwesomeIcon icon={faUser} />
              <span className="jas-ud-item-label">Jaspen Admin</span>
            </button>
          )}
        </div>

        <div className="jas-ud-section">
          <div className="jas-ud-section-label">User Tools</div>
          <div className="jas-ud-role-switcher jas-ud-invite-card">
            <span className="jas-ud-role-switcher-label">Invite others</span>
            <p className="jas-ud-role-switcher-note">
              Share your invite link from here.
            </p>
            <div className="jas-ud-invite-row">
              <code>{inviteDisplay || 'Generating…'}</code>
              <button
                type="button"
                className="jas-ud-invite-btn"
                onClick={handleCopyInviteLink}
                disabled={!inviteLink}
              >
                {inviteCopied ? 'Copied!' : 'Copy link'}
              </button>
            </div>
          </div>
          <button
            className="jas-ud-item"
            onClick={() => setNotificationsOpen(true)}
          >
            <FontAwesomeIcon icon={faBell} />
            <span className="jas-ud-item-label">Notifications</span>
          </button>
          <button className="jas-ud-item" onClick={() => setBillingModalOpen(true)}>
            <FontAwesomeIcon icon={faBolt} />
            <span className="jas-ud-item-label">Credits</span>
            <span className="jas-ud-item-badge">
              {billingLoading ? '...' : creditsBadge}
            </span>
          </button>
        </div>

        <div className="jas-ud-section">
          <div className="jas-ud-section-label">Account Usage (This Month)</div>
          {billingLoading && (
            <p className="jas-ud-usage-empty">Loading usage...</p>
          )}
          {!billingLoading && monthlyCreditLimit == null && (
            <p className="jas-ud-usage-note">
              Monthly limit: Contracted pooled credits on {currentPlanLabel} plan.
            </p>
          )}
          {!billingLoading && monthlyCreditLimit != null && (
            <>
              <div className="jas-ud-usage-grid jas-ud-usage-grid-compact">
                <div className="jas-ud-usage-stat">
                  <span>Used</span>
                  <strong>
                    {Number(resolvedMonthlyCreditsUsed || 0).toLocaleString()}
                  </strong>
                </div>
                <div className="jas-ud-usage-stat">
                  <span>Remaining</span>
                  <strong>
                    {Number(creditsRemaining || 0).toLocaleString()}
                  </strong>
                </div>
              </div>
              <p className="jas-ud-usage-note">
                Monthly limit: {Number(monthlyCreditLimit || 0).toLocaleString()} credits
                on {currentPlanLabel}.
              </p>
            </>
          )}
        </div>

        <div className="jas-ud-section">
          <button
            className="jas-ud-item"
            onClick={() =>
              window.open('/pages/support', '_blank', 'noopener,noreferrer')
            }
          >
            <FontAwesomeIcon icon={faQuestionCircle} />
            <span className="jas-ud-item-label">Get help</span>
            <span className="jas-ud-item-ext">
              <FontAwesomeIcon icon={faArrowUpRightFromSquare} />
            </span>
          </button>
        </div>
      </div>

      <SidebarIdentityFooter
        displayName={displayName}
        planLabel={footerPlanLabel}
        onOpenDisplayNameEditor={openDisplayNameEditor}
        onOpenOnboardingEditor={() => { close(); navigate('/account'); }}
        onOpenBilling={() => setBillingModalOpen(true)}
        onLogout={handleLogout}
        onClose={close}
      />
    </div>
  );

  // ---------------------------------------------------------------------------
  // Billing modal
  // ---------------------------------------------------------------------------
  const renderBillingModal = () => {
    if (!billingModalOpen) return null;
    return (
      <div
        className="jas-modal-backdrop"
        role="presentation"
        onClick={() => setBillingModalOpen(false)}
      >
        <div
          className="jas-account-modal"
          role="dialog"
          aria-modal="true"
          aria-label="Account and billing"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="jas-account-modal-header">
            <h3>Account and billing</h3>
            <button
              type="button"
              className="jas-account-modal-close"
              onClick={() => setBillingModalOpen(false)}
              aria-label="Close"
            >
              <FontAwesomeIcon icon={faTimes} />
            </button>
          </div>

          <div className="jas-account-summary-grid">
            <article className="jas-account-summary-card">
              <p className="label">Current plan</p>
              <p className="value">{currentPlanLabel}</p>
            </article>
            <article className="jas-account-summary-card">
              <p className="label">Credits remaining</p>
              <p className="value">{creditsBadge}</p>
            </article>
            <article className="jas-account-summary-card">
              <p className="label">Monthly limit</p>
              <p className="value">
                {monthlyCreditLimit == null
                  ? 'Contracted'
                  : Number(monthlyCreditLimit).toLocaleString()}
              </p>
            </article>
          </div>

          <div className="jas-account-plan-grid">
            {PLAN_ORDER.map((key) => {
              const plan = plans[key];
              if (!plan) return null;
              const isCurrent = key === currentPlanKey;
              const isSalesOnly = !!plan.sales_only;
              return (
                <article
                  className={`jas-account-plan-card ${isCurrent ? 'is-current' : ''}`}
                  key={key}
                >
                  <h4>{plan.label}</h4>
                  <p className="price">
                    {Number.isFinite(plan.monthly_price_usd)
                      ? plan.monthly_price_usd === 0
                        ? '$0/mo'
                        : `$${plan.monthly_price_usd}/mo`
                      : 'Contact sales'}
                  </p>
                  <p className="detail">
                    {plan.monthly_credits == null
                      ? 'Contracted pooled credits'
                      : `${Number(plan.monthly_credits).toLocaleString()} credits/month`}
                  </p>
                  <p className="detail jas-account-plan-connectors">
                    Connectors: {getPlanConnectorSentence(key)}
                  </p>
                  {isCurrent ? (
                    <span className="jas-account-pill">Current</span>
                  ) : isSalesOnly ? (
                    <a
                      href="/pages/get-in-touch"
                      className="jas-account-action-link"
                      target="_blank"
                      rel="noreferrer"
                    >
                      Talk to sales
                    </a>
                  ) : (
                    <button
                      type="button"
                      className="jas-account-action-btn"
                      onClick={() => startBillingPlanChange(key)}
                      disabled={billingActionLoading === key}
                    >
                      {billingActionLoading === key
                        ? 'Redirecting...'
                        : 'Select plan'}
                    </button>
                  )}
                </article>
              );
            })}
          </div>

          {billingMessage && (
            <p className="jas-account-message">{billingMessage}</p>
          )}

          <div className="jas-account-modal-actions">
            <button
              type="button"
              className="jas-account-portal-btn"
              onClick={openBillingPortal}
              disabled={billingActionLoading === 'portal'}
            >
              {billingActionLoading === 'portal' ? 'Opening...' : 'Manage billing'}
            </button>
            <button
              type="button"
              className="jas-account-secondary-btn"
              onClick={() => { setBillingModalOpen(false); navigate('/account'); }}
            >
              Full account page
            </button>
          </div>
        </div>
      </div>
    );
  };

  // ---------------------------------------------------------------------------
  // Notifications modal (simplified — no live feed on non-workspace pages)
  // ---------------------------------------------------------------------------
  const renderNotificationsModal = () => {
    if (!notificationsOpen) return null;
    return (
      <div
        className="jas-notifications-backdrop"
        role="presentation"
        onClick={() => setNotificationsOpen(false)}
      >
        <div
          className="jas-notifications-modal"
          role="dialog"
          aria-modal="true"
          aria-label="Notifications"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="jas-notifications-header">
            <h3>Notifications</h3>
            <div className="jas-notifications-header-actions">
              <button
                type="button"
                className="jas-notifications-close"
                onClick={() => setNotificationsOpen(false)}
                aria-label="Close notifications"
              >
                <FontAwesomeIcon icon={faTimes} />
              </button>
            </div>
          </div>
          <div className="jas-notifications-list">
            <div className="jas-notification-empty">
              Open a project on the workspace to see activity notifications.
            </div>
          </div>
        </div>
      </div>
    );
  };

  // ---------------------------------------------------------------------------
  // Display name editor modal
  // ---------------------------------------------------------------------------
  const renderNameModal = () => {
    if (!nameModalOpen) return null;
    return (
      <div
        className="jas-modal-backdrop"
        role="presentation"
        onClick={() => setNameModalOpen(false)}
      >
        <div
          className="jas-account-modal"
          style={{ maxWidth: 420 }}
          role="dialog"
          aria-modal="true"
          aria-label="Edit display name"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="jas-account-modal-header">
            <h3>Edit display name</h3>
            <button
              type="button"
              className="jas-account-modal-close"
              onClick={() => setNameModalOpen(false)}
              aria-label="Close"
            >
              <FontAwesomeIcon icon={faTimes} />
            </button>
          </div>
          <div style={{ padding: '16px 20px 20px' }}>
            <input
              className="jas-ud-name-input"
              type="text"
              value={nameInput}
              onChange={(e) => setNameInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') persistDisplayName(nameInput);
              }}
              placeholder="Your display name"
              autoFocus
            />
            {nameError && (
              <p style={{ color: '#c0392b', fontSize: '0.75rem', marginTop: 6 }}>
                {nameError}
              </p>
            )}
            <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
              <button
                type="button"
                className="jas-ud-name-save"
                onClick={() => persistDisplayName(nameInput)}
                disabled={!nameInput.trim() || nameSaving}
              >
                {nameSaving ? 'Saving...' : 'Save'}
              </button>
              <button
                type="button"
                className="jas-ud-name-cancel"
                onClick={() => setNameModalOpen(false)}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  };

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------
  return (
    <div className={`app-menu-host${open ? ' is-open' : ''}`}>
      {/* Tab button — visible when sidebar is closed */}
      {!open && (
        <button
          type="button"
          className="jas-drawer-tab jas-drawer-tab-settings"
          style={{ top: 128 }}
          onClick={() => setOpen(true)}
          aria-label="Open menu"
          aria-expanded={false}
          aria-controls="app-menu-panel"
        >
          <FontAwesomeIcon icon={faBars} />
          MENU
        </button>
      )}

      {/* Sidebar */}
      <aside
        id="app-menu-panel"
        className={`jas-left-sidebar jas-settings-sidebar${open ? ' sidebar-open' : ''}`}
        aria-labelledby="app-menu-title"
      >
        <div className="jas-sidebar-header">
          <h3 id="app-menu-title">Menu</h3>
          <button
            className="jas-sidebar-close"
            onClick={close}
            aria-label="Close menu"
          >
            <FontAwesomeIcon icon={faTimes} />
          </button>
        </div>
        <div className="jas-sidebar-content">
          {renderMenuContent()}
        </div>
      </aside>

      {/* Modals */}
      {renderBillingModal()}
      {renderNotificationsModal()}
      {renderNameModal()}
    </div>
  );
}
