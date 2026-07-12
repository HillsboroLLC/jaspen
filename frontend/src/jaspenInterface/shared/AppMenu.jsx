// =============================================================================
// AppMenu.jsx
// Shared MENU tab + sidebar for all internal pages.
// Renders the exact same element as JaspenWorkspace's settings sidebar.
// =============================================================================

import React, { useState, useCallback, useEffect, useMemo, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faBars, faTimes, faListCheck, faPlus, faLayerGroup, faChartLine,
  faDownload, faClockRotateLeft, faUser, faGaugeHigh, faQuestionCircle,
  faBolt, faBell, faLock, faArrowUpRightFromSquare, faAddressBook,
} from '@fortawesome/free-solid-svg-icons';

import { useAuth } from '../../shared/auth/AuthContext';
import { AUTH_EVENTS, buildAuthHeaders } from '../../shared/auth/http';
import { API_BASE } from '../../config/apiBase';
import { buildInviteLink, buildInviteDisplay } from '../../shared/inviteLink';
import { getPlanConnectorSentence } from '../../shared/billing/planConnectors';
import { PLAN_ORDER, PLAN_RANK } from '../../shared/constants/appConstants';
import { formatNextResetDate } from '../../shared/utils/dateUtils';
import { isMasterAdminUser } from '../../shared/auth/masterAdmin';
import SidebarIdentityFooter from '../Workspace/components/SidebarIdentityFooter';
import StripeCheckout from '../Account/StripeCheckout';
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

function priceDisplay(plan) {
  if (plan?.price_model === 'per_seat' && Number.isFinite(plan?.monthly_price_usd)) {
    return `$${plan.monthly_price_usd}/mo`;
  }
  if (plan?.price_model === 'custom') {
    return 'Contact sales';
  }
  if (Number.isFinite(plan?.monthly_price_usd)) {
    return plan.monthly_price_usd === 0 ? '$0' : `$${plan.monthly_price_usd}/mo`;
  }
  return 'Contact sales';
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export default function AppMenu() {
  const navigate = useNavigate();
  const location = useLocation();
  const {
    user,
    logout,
    updateDisplayName,
    updateUiPreferences,
    isPlatformAdmin,
    isEnterpriseAdmin,
    canManageOrg,
    isOrgCreator,
  } = useAuth();

  // Sidebar open state
  const [open, setOpen] = useState(false);
  const [gettingStartedLoading, setGettingStartedLoading] = useState(false);
  const [gettingStartedProgress, setGettingStartedProgress] = useState({
    hasProject: false,
    hasScore: false,
  });
  const [gettingStartedHidden, setGettingStartedHidden] = useState(false);

  // Billing
  const [billingStatus, setBillingStatus] = useState(null);
  const [billingCatalog, setBillingCatalog] = useState({ plans: {}, credit_packs: {}, overage_packs: {}, model_types: {} });
  const [billingLoading, setBillingLoading] = useState(true);
  const [billingMessage, setBillingMessage] = useState('');
  const [billingModalOpen, setBillingModalOpen] = useState(false);
  const [billingActionLoading, setBillingActionLoading] = useState(null);
  const [embeddedCheckout, setEmbeddedCheckout] = useState(null);

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
        setBillingCatalog(catalogData || { plans: {}, credit_packs: {}, overage_packs: {}, model_types: {} });
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

  useEffect(() => {
    const onCreditsExhausted = (event) => {
      const message = String(event?.detail?.message || "You've reached your monthly thinking power.").trim();
      setBillingMessage(message);
      setBillingModalOpen(true);
    };
    window.addEventListener(AUTH_EVENTS.CREDITS_EXHAUSTED_EVENT, onCreditsExhausted);
    return () => window.removeEventListener(AUTH_EVENTS.CREDITS_EXHAUSTED_EVENT, onCreditsExhausted);
  }, []);

  // Toggle body class so CSS can push page content when sidebar is open/closed
  useEffect(() => {
    document.body.classList.toggle('jaspen-sidebar-open', open);
    return () => document.body.classList.remove('jaspen-sidebar-open');
  }, [open]);

  // ---------------------------------------------------------------------------
  // Plan flags (mirrors JaspenWorkspace)
  // ---------------------------------------------------------------------------
  const plans = useMemo(() => billingCatalog?.plans || {}, [billingCatalog?.plans]);
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
  const isMasterAdmin = isMasterAdminUser(user);

  const canStartOrgProjects =
    previewPlanCategory === 'individual' ||
    effectiveIsCreator ||
    isPlatformAdmin;

  // Dashboard / Projects / Scores / Insights / Reports / Activity are shown as
  // disabled "Coming soon" menu items for launch — their plan-gating vars were
  // removed since the items render the same (disabled) for every plan.
  const showRealTeam =!isPlatformAdmin && effectiveCanManageOrg && PLAN_RANK[effectivePlanKey] >= PLAN_RANK.team;
  const showLockedTeam =
    !showRealTeam && previewPlanCategory === 'individual' && !isPlatformAdmin;
  const showRealConnectors = true;
  const showLockedConnectors = false;


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

  const thinkingPowerRemainingLabel =
    creditsRemaining == null ? 'Contracted' : Number(creditsRemaining || 0).toLocaleString();
  const usageResetLabel = useMemo(() => {
    const value = billingStatus?.cycle_reset_at;
    const label = formatNextResetDate(value);
    return label || 'Your next billing cycle';
  }, [billingStatus?.cycle_reset_at]);
  const creditsBadge =
    monthlyCreditLimit > 0
      ? `${Math.max(0, Math.round((Math.max(0, Number(creditsRemaining || 0)) / Number(monthlyCreditLimit || 1)) * 100))}% remaining`
      : 'Usage';

  const [meterHidden, setMeterHidden] = useState(Boolean(user?.ui_preferences?.hide_thinking_power_meter));
  useEffect(() => {
    setMeterHidden(Boolean(user?.ui_preferences?.hide_thinking_power_meter));
  }, [user?.ui_preferences?.hide_thinking_power_meter]);

  const toggleThinkingPowerMeter = useCallback(async () => {
    const next = !meterHidden;
    setMeterHidden(next);
    if (typeof updateUiPreferences !== 'function') return;
    await updateUiPreferences({ hide_thinking_power_meter: next });
  }, [meterHidden, updateUiPreferences]);

  const creditsTone = useMemo(() => {
    const level = String(billingStatus?.usage_warning_level || 'normal').toLowerCase();
    if (level === 'blocked' || level === 'exhausted') return 'critical';
    if (level === 'urgent' || level === 'critical') return 'critical';
    if (level === 'warning') return 'warning';
    return 'normal';
  }, [billingStatus?.usage_warning_level]);

  const currentPath = String(location?.pathname || '');
  const isActivePath = useCallback(
    (paths) => (Array.isArray(paths) ? paths : [paths]).some((path) => currentPath === String(path || '')),
    [currentPath],
  );
  const menuItemClass = useCallback(
    (paths, extra = '') => `jas-ud-item${isActivePath(paths) ? ' is-active' : ''}${extra ? ` ${extra}` : ''}`,
    [isActivePath],
  );
  const onboardingPrefs = user?.ui_preferences?.onboarding && typeof user.ui_preferences.onboarding === 'object'
    ? user.ui_preferences.onboarding
    : {};
  const onboardingCompleted = Boolean(onboardingPrefs.completed || user?.ui_preferences?.onboarding_complete);
  const gettingStartedDismissed = Boolean(onboardingPrefs.dismissed);
  const gettingStartedSteps = useMemo(() => ([
    {
      key: 'onboarding',
      label: 'Complete setup preferences',
      done: onboardingCompleted,
      href: '/new',
    },
    {
      key: 'first-project',
      label: 'Start your first project',
      done: Boolean(gettingStartedProgress.hasProject),
      href: '/new',
    },
    {
      key: 'first-score',
      label: 'Generate your first score',
      done: Boolean(gettingStartedProgress.hasScore),
      href: '/scores',
    },
  ]), [gettingStartedProgress.hasProject, gettingStartedProgress.hasScore, onboardingCompleted]);
  const gettingStartedDoneCount = gettingStartedSteps.filter((step) => step.done).length;
  useEffect(() => {
    setGettingStartedHidden(gettingStartedDismissed);
  }, [gettingStartedDismissed]);

  const showGettingStartedCard = !gettingStartedHidden && gettingStartedDoneCount < gettingStartedSteps.length;

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

  const loadGettingStartedProgress = useCallback(async () => {
    if (!open || !user) return;
    setGettingStartedLoading(true);
    try {
      const [projectsRes, scoresRes] = await Promise.all([
        fetch(`${API_BASE}/api/v1/ai-agent/threads`, {
          headers: buildAuthHeaders({}, 'GET'),
          credentials: 'include',
        }),
        fetch(`${API_BASE}/api/v1/strategy/scores?limit=1&offset=0`, {
          headers: buildAuthHeaders({}, 'GET'),
          credentials: 'include',
        }),
      ]);
      const projectsJson = await projectsRes.json().catch(() => ({}));
      const scoresJson = await scoresRes.json().catch(() => ({}));
      const sessions = Array.isArray(projectsJson?.sessions) ? projectsJson.sessions : [];
      const scores = Array.isArray(scoresJson?.scores) ? scoresJson.scores : [];
      const totalScores = Number(scoresJson?.total);
      setGettingStartedProgress({
        hasProject: sessions.length > 0,
        hasScore: scores.length > 0 || (Number.isFinite(totalScores) && totalScores > 0),
      });
    } catch {
      setGettingStartedProgress({ hasProject: false, hasScore: false });
    } finally {
      setGettingStartedLoading(false);
    }
  }, [open, user]);

  useEffect(() => {
    void loadGettingStartedProgress();
  }, [loadGettingStartedProgress]);

  const dismissGettingStarted = useCallback(async () => {
    setGettingStartedHidden(true);
    if (typeof updateUiPreferences !== 'function') return;
    const currentPrefs = user?.ui_preferences && typeof user.ui_preferences === 'object'
      ? user.ui_preferences
      : {};
    const currentOnboarding = currentPrefs?.onboarding && typeof currentPrefs.onboarding === 'object'
      ? currentPrefs.onboarding
      : {};
    await updateUiPreferences({
      onboarding: {
        ...currentOnboarding,
        dismissed: true,
      },
    });
  }, [updateUiPreferences, user?.ui_preferences]);

  const startBillingPlanChange = useCallback(
    async (planKey) => {
      setBillingActionLoading(planKey);
      setBillingMessage('');
      const plan = plans?.[planKey] || {};
      const currentPlan = plans?.[currentPlanKey] || {};
      const hasSubscription = Boolean(billingStatus?.stripe_subscription_id);
      try {
        if (planKey !== 'free' && (!hasSubscription || currentPlanKey === 'free')) {
          setBillingModalOpen(false);
          setEmbeddedCheckout({
            planKey,
            planLabel: plan?.label || planKey,
            priceLabel: priceDisplay(plan),
          });
          return;
        }

        if (planKey === 'free') {
          const res = await fetch(`${API_BASE}/api/v1/billing/cancel-subscription`, {
            method: 'POST',
            credentials: 'include',
            headers: buildAuthHeaders({}, 'POST'),
          });
          const data = await res.json().catch(() => ({}));
          if (!res.ok) {
            throw new Error(data?.msg || 'Unable to cancel subscription.');
          }
          const endDate = data?.current_period_end_iso
            ? new Date(data.current_period_end_iso).toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' })
            : 'your next billing date';
          setBillingMessage(`You'll keep ${currentPlan?.label || 'your current plan'} through ${endDate}, then move to Free.`);
          await loadBilling();
          return;
        }

        const res = await fetch(`${API_BASE}/api/v1/billing/modify-subscription`, {
          method: 'POST',
          headers: {
            ...buildAuthHeaders({}, 'POST'),
            'Content-Type': 'application/json',
          },
          credentials: 'include',
          body: JSON.stringify({ plan_key: planKey }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(data?.msg || 'Unable to update subscription.');
        }
        setBillingMessage(data?.message || `Your plan change to ${data?.plan_label || plan?.label || planKey} has been saved.`);
        await loadBilling();
      } catch (err) {
        setBillingMessage(err.message || 'Unable to update billing.');
      } finally {
        setBillingActionLoading(null);
      }
    },
    [billingStatus?.stripe_subscription_id, currentPlanKey, loadBilling, plans],
  );

  const openBillingPortal = useCallback(() => {
    setBillingMessage('');
    setBillingModalOpen(false);
    setEmbeddedCheckout({ mode: 'update_payment' });
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

          {/* Coming soon: disabled (not clickable), no lock. The page + its
              work stay in place; we just keep users out of it for launch. */}
          <button className="jas-ud-item is-coming-soon" disabled aria-disabled="true" title="Coming soon">
            <FontAwesomeIcon icon={faListCheck} />
            <span className="jas-ud-item-label">Dashboard</span>
            <span className="jas-ud-item-badge is-soon">Coming soon</span>
          </button>

          {canStartOrgProjects && (
            <button className={menuItemClass('/new')} onClick={() => { close(); navigate('/new'); }}>
              <FontAwesomeIcon icon={faPlus} />
              <span className="jas-ud-item-label">New Project</span>
            </button>
          )}

          <button className="jas-ud-item is-coming-soon" disabled aria-disabled="true" title="Coming soon">
            <FontAwesomeIcon icon={faLayerGroup} />
            <span className="jas-ud-item-label">Projects</span>
            <span className="jas-ud-item-badge is-soon">Coming soon</span>
          </button>

          <button className="jas-ud-item is-coming-soon" disabled aria-disabled="true" title="Coming soon">
            <FontAwesomeIcon icon={faChartLine} />
            <span className="jas-ud-item-label">Scores</span>
            <span className="jas-ud-item-badge is-soon">Coming soon</span>
          </button>

          <button className="jas-ud-item is-coming-soon" disabled aria-disabled="true" title="Coming soon">
            <FontAwesomeIcon icon={faChartLine} />
            <span className="jas-ud-item-label">Insights</span>
            <span className="jas-ud-item-badge is-soon">Coming soon</span>
          </button>

          <button className="jas-ud-item is-coming-soon" disabled aria-disabled="true" title="Coming soon">
            <FontAwesomeIcon icon={faDownload} />
            <span className="jas-ud-item-label">Reports</span>
            <span className="jas-ud-item-badge is-soon">Coming soon</span>
          </button>

          <button className="jas-ud-item is-coming-soon" disabled aria-disabled="true" title="Coming soon">
            <FontAwesomeIcon icon={faClockRotateLeft} />
            <span className="jas-ud-item-label">Activity</span>
            <span className="jas-ud-item-badge is-soon">Coming soon</span>
          </button>

          {showRealTeam && (
            <button className={menuItemClass('/team')} onClick={() => { close(); navigate('/team'); }}>
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
            <button className={menuItemClass('/enterprise-admin')} onClick={() => { close(); navigate('/enterprise-admin'); }}>
              <FontAwesomeIcon icon={faGaugeHigh} />
              <span className="jas-ud-item-label">Enterprise Admin</span>
            </button>
          )}

          {showRealConnectors && (
            <button className={menuItemClass('/connectors-manage')} onClick={() => { close(); navigate('/connectors-manage'); }}>
              <FontAwesomeIcon icon={faLayerGroup} />
              <span className="jas-ud-item-label">Data Sources</span>
            </button>
          )}
          {showLockedConnectors && (
            <button
              className="jas-ud-item is-locked"
              onClick={() => setBillingModalOpen(true)}
              title="Connect data sources from Account settings"
            >
              <FontAwesomeIcon icon={faLayerGroup} />
              <span className="jas-ud-item-label">Data Sources</span>
              <span className="jas-ud-item-ext"><FontAwesomeIcon icon={faLock} /></span>
            </button>
          )}

          <button className={menuItemClass('/knowledge')} onClick={() => { close(); navigate('/knowledge'); }}>
            <FontAwesomeIcon icon={faQuestionCircle} />
            <span className="jas-ud-item-label">Knowledge</span>
          </button>

          <button className={menuItemClass('/account')} onClick={() => { close(); navigate('/account'); }}>
            <FontAwesomeIcon icon={faUser} />
            <span className="jas-ud-item-label">Account</span>
          </button>

          {isPlatformAdmin && (
            <button className={menuItemClass('/jaspen-admin')} onClick={() => { close(); navigate('/jaspen-admin'); }}>
              <FontAwesomeIcon icon={faUser} />
              <span className="jas-ud-item-label">Jaspen Admin</span>
            </button>
          )}
          {isMasterAdmin && (
            <>
              <button className={menuItemClass('/admin/analytics')} onClick={() => { close(); navigate('/admin/analytics'); }}>
                <FontAwesomeIcon icon={faChartLine} />
                <span className="jas-ud-item-label">Analytics</span>
              </button>
              <button className={menuItemClass('/admin/leads')} onClick={() => { close(); navigate('/admin/leads'); }}>
                <FontAwesomeIcon icon={faAddressBook} />
                <span className="jas-ud-item-label">Leads</span>
              </button>
              <button className={menuItemClass('/admin/errors')} onClick={() => { close(); navigate('/admin/errors'); }}>
                <FontAwesomeIcon icon={faGaugeHigh} />
                <span className="jas-ud-item-label">Errors</span>
              </button>
            </>
          )}
        </div>

        {showGettingStartedCard && (
          <div className="jas-ud-section">
            <div className="jas-ud-section-label">Getting Started</div>
            <div className="jas-ud-role-switcher jas-ud-getting-started-card">
              <div className="jas-ud-getting-started-head">
                <strong>{gettingStartedDoneCount}/{gettingStartedSteps.length} completed</strong>
                <button
                  type="button"
                  className="jas-ud-getting-started-dismiss"
                  onClick={() => { void dismissGettingStarted(); }}
                >
                  Dismiss
                </button>
              </div>
              <div className="jas-ud-getting-started-list" aria-live="polite">
                {gettingStartedSteps.map((step) => (
                  <div key={step.key} className={`jas-ud-getting-started-row${step.done ? ' is-done' : ''}`}>
                    <span className="jas-ud-getting-started-state" aria-hidden="true">{step.done ? '✓' : '○'}</span>
                    <span className="jas-ud-getting-started-label">{step.label}</span>
                    {!step.done && (
                      <button
                        type="button"
                        className="jas-ud-getting-started-link"
                        onClick={() => { close(); navigate(step.href); }}
                      >
                        Go
                      </button>
                    )}
                  </div>
                ))}
              </div>
              {gettingStartedLoading && (
                <p className="jas-ud-getting-started-loading">Refreshing progress…</p>
              )}
            </div>
          </div>
        )}

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
            <span className="jas-ud-item-label">Thinking power</span>
            <span className="jas-ud-item-badge">
              {billingLoading ? '...' : creditsBadge}
            </span>
          </button>
          <button className="jas-ud-meter-toggle" onClick={toggleThinkingPowerMeter}>
            <FontAwesomeIcon icon={faGaugeHigh} />
            {meterHidden ? 'Show usage meter' : 'Hide usage meter'}
          </button>
        </div>

        {!meterHidden && (
          <div className="jas-ud-section">
            <div className="jas-ud-section-label">THINKING POWER</div>
            {billingLoading && (
              <p className="jas-ud-usage-empty">Loading usage...</p>
            )}
            {!billingLoading && monthlyCreditLimit == null && (
              <p className="jas-ud-usage-note">
                Thinking power is managed by your contract on {currentPlanLabel}.
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
                <p className="jas-ud-usage-note">Thinking power remaining: {creditsBadge}</p>
                <p className="jas-ud-usage-note">
                  Monthly limit: {Number(monthlyCreditLimit || 0).toLocaleString()} credits on {currentPlanLabel}.
                </p>
                <p className="jas-ud-usage-note">Resets: {usageResetLabel}</p>
                <p className="jas-ud-usage-note">Current plan: {currentPlanLabel}</p>
                {creditsTone !== 'normal' && (
                  <div className="jas-ud-usage-actions">
                    <button type="button" className="jas-account-action-link" onClick={() => navigate('/account?tab=packs')}>Add credits</button>
                    <button type="button" className="jas-account-action-link" onClick={() => navigate('/account?tab=plans')}>Upgrade plan</button>
                  </div>
                )}
              </>
            )}
          </div>
        )}

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
              <p className="label">Thinking power remaining</p>
              <p className="value">{thinkingPowerRemainingLabel}</p>
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
                      ? 'Contracted pooled thinking power'
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
                        ? 'Opening...'
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
            >
              Manage billing
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

  const renderEmbeddedCheckout = () => {
    if (!embeddedCheckout) return null;
    return (
      <StripeCheckout
        mode={embeddedCheckout.mode || 'subscribe'}
        planKey={embeddedCheckout.planKey}
        planLabel={embeddedCheckout.planLabel}
        priceLabel={embeddedCheckout.priceLabel}
        plans={PLAN_ORDER
          .filter((key) => key !== 'free' && plans[key] && !plans[key]?.sales_only)
          .map((key) => {
            const plan = plans[key];
            return {
            key,
            label: plan?.label || key,
            priceLabel: priceDisplay(plan),
          };
          })}
        onClose={() => setEmbeddedCheckout(null)}
        onSuccess={async () => {
          const wasUpdate = embeddedCheckout.mode === 'update_payment';
          setEmbeddedCheckout(null);
          setBillingMessage(
            wasUpdate
              ? 'Your payment method was updated.'
              : 'Subscription started. Your plan will update as soon as payment is confirmed.'
          );
          await loadBilling();
        }}
      />
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
      {renderEmbeddedCheckout()}
      {renderNotificationsModal()}
      {renderNameModal()}
    </div>
  );
}
