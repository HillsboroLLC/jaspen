import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { API_BASE } from '../../config/apiBase';
import { getPlanConnectorSentence } from '../../shared/billing/planConnectors';
import './Account.css';

function getToken() {
  return localStorage.getItem('access_token') || localStorage.getItem('token');
}

const PLAN_ORDER = ['free', 'essential', 'team', 'enterprise'];
const PACK_ORDER = ['pack_1000', 'pack_5000', 'pack_20000'];
const MODEL_ORDER = ['pluto', 'orbit', 'titan'];
const PLAN_RANK = {
  free: 0,
  essential: 1,
  team: 2,
  enterprise: 3,
};
const FALLBACK_MODEL_TYPES = {
  pluto: {
    model_type: 'pluto',
    label: 'Pluto',
    version: '1.0',
    description: 'Fastest model for core intake and scorecard workflows.',
    min_plan: 'free',
  },
  orbit: {
    model_type: 'orbit',
    label: 'Orbit',
    version: '1.0',
    description: 'Balanced depth and speed for broader cross-functional synthesis.',
    min_plan: 'team',
  },
  titan: {
    model_type: 'titan',
    label: 'Titan',
    version: '1.0',
    description: 'Highest-depth reasoning for complex multi-team initiatives.',
    min_plan: 'enterprise',
  },
};
const CONNECTOR_GROUP_ORDER = ['execution', 'data'];
const DEFAULT_SYNC_MODES = ['import', 'push', 'two_way'];
const DEFAULT_CONFLICT_POLICIES = ['latest_wins', 'prefer_external', 'prefer_jaspen', 'manual_review'];
const SYNC_MODE_LABELS = {
  import: 'External -> Jaspen',
  push: 'Jaspen -> External',
  two_way: 'Two-way sync',
};
const CONNECTOR_TOGGLE_COPY = {
  jira_sync: {
    on: 'Jaspen can sync WBS tasks, statuses, owners, and sprint progress with Jira.',
    off: 'Jaspen keeps internal plans only and does not sync Jira issues.',
    config: 'Configuration required: Jira URL, project key, service account email, and API token.',
  },
  workfront_sync: {
    on: 'Jaspen can sync project milestones and ownership updates with Workfront.',
    off: 'Workfront milestones and ownership changes stay out of Jaspen sync.',
    config: 'Configuration required: external workspace or account key.',
  },
  smartsheet_sync: {
    on: 'Jaspen can sync timeline rows and delivery status updates with Smartsheet.',
    off: 'Smartsheet plan updates are not synced into Jaspen.',
    config: 'Configuration required: external workspace or account key.',
  },
  salesforce_insights: {
    on: 'Jaspen can use Salesforce customer and pipeline signals in recommendations.',
    off: 'Salesforce objects are not used in prioritization or insight generation.',
    config: 'Configuration required: external workspace or account key.',
  },
  snowflake_insights: {
    on: 'Jaspen can read governed KPI and trend tables from Snowflake.',
    off: 'Snowflake data stays excluded from analysis context.',
    config: 'Configuration required: external workspace or account key.',
  },
  oracle_fusion_insights: {
    on: 'Jaspen can use Oracle Fusion finance and operating signals in planning.',
    off: 'Oracle Fusion metrics are not included in recommendations.',
    config: 'Configuration required: external workspace or account key.',
  },
  servicenow_insights: {
    on: 'Jaspen can ingest service and change metrics for execution risk signals.',
    off: 'ServiceNow records are excluded from risk and blocker insights.',
    config: 'Configuration required: external workspace or account key.',
  },
  netsuite_insights: {
    on: 'Jaspen can incorporate NetSuite operating and finance trends into decisions.',
    off: 'NetSuite trends are excluded from execution tradeoff analysis.',
    config: 'Configuration required: external workspace or account key.',
  },
};

function normalizeConnectorGroup(value) {
  return String(value || '').trim().toLowerCase() || 'data';
}

function normalizeTierLabel(value) {
  const text = String(value || '').trim();
  if (!text) return 'Team';
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function buildConnectorDraft(connector) {
  const syncModes = Array.isArray(connector?.available_sync_modes) && connector.available_sync_modes.length
    ? connector.available_sync_modes
    : DEFAULT_SYNC_MODES;
  const conflictPolicies =
    Array.isArray(connector?.available_conflict_policies) && connector.available_conflict_policies.length
      ? connector.available_conflict_policies
      : DEFAULT_CONFLICT_POLICIES;

  return {
    connection_status: connector?.connected ? 'connected' : 'disconnected',
    sync_mode: connector?.sync_mode || (syncModes.includes('import') ? 'import' : syncModes[0] || ''),
    conflict_policy: connector?.conflict_policy || conflictPolicies[0] || 'prefer_external',
    auto_sync: connector?.auto_sync !== false,
    external_workspace: String(connector?.external_workspace || ''),
    jira_base_url: String(connector?.jira?.base_url || ''),
    jira_project_key: String(connector?.jira?.project_key || ''),
    jira_email: String(connector?.jira?.email || ''),
    jira_issue_type: String(connector?.jira?.issue_type || ''),
    jira_api_token: '',
  };
}

function buildConnectorDraftMap(items) {
  const map = {};
  (Array.isArray(items) ? items : []).forEach((connector) => {
    if (!connector?.id) return;
    map[connector.id] = buildConnectorDraft(connector);
  });
  return map;
}

function connectorDraftHasChanges(connector, draft) {
  const base = buildConnectorDraft(connector);
  const current = { ...base, ...(draft || {}) };
  const trim = (value) => String(value || '').trim();
  const keySet = [
    'connection_status',
    'sync_mode',
    'conflict_policy',
    'auto_sync',
    'external_workspace',
    'jira_base_url',
    'jira_project_key',
    'jira_email',
    'jira_issue_type',
  ];
  const hasFieldDiff = keySet.some((key) => {
    if (key === 'auto_sync') return Boolean(base[key]) !== Boolean(current[key]);
    return trim(base[key]) !== trim(current[key]);
  });
  const hasNewJiraToken = connector?.id === 'jira_sync' && trim(current.jira_api_token).length > 0;
  return hasFieldDiff || hasNewJiraToken;
}

function getConnectorCopy(connectorId, fallbackGroup) {
  const copy = CONNECTOR_TOGGLE_COPY[String(connectorId || '').trim().toLowerCase()];
  if (copy) return copy;
  if (normalizeConnectorGroup(fallbackGroup) === 'execution') {
    return {
      on: 'Jaspen can exchange plan and status updates with this execution tool.',
      off: 'Jaspen keeps this execution tool disconnected from plan sync flows.',
      config: 'Configuration required: external workspace or account key.',
    };
  }
  return {
    on: 'Jaspen can use this system for insight and recommendation context.',
    off: 'This system is excluded from connector-based analysis context.',
    config: 'Configuration required: external workspace or account key.',
  };
}

export default function Account() {
  const navigate = useNavigate();
  const [status, setStatus] = useState(null);
  const [catalog, setCatalog] = useState({ plans: {}, overage_packs: {}, model_types: FALLBACK_MODEL_TYPES });
  const [connectorState, setConnectorState] = useState({
    loading: true,
    items: [],
  });
  const [connectorDrafts, setConnectorDrafts] = useState({});
  const [loading, setLoading] = useState(true);
  const [pendingAction, setPendingAction] = useState('');
  const [connectorPendingId, setConnectorPendingId] = useState('');
  const [message, setMessage] = useState('');
  const [adminState, setAdminState] = useState({
    checked: false,
    isAdmin: false,
    loading: false,
    users: [],
    query: '',
    selectedUserId: '',
    draft: null,
    pending: false,
  });

  useEffect(() => {
    let mounted = true;

    const load = async () => {
      const token = getToken();

      try {
        const [statusRes, catalogRes, connectorsRes, adminCapsRes] = await Promise.all([
          fetch(`${API_BASE}/api/billing/status`, {
            headers: token ? { Authorization: `Bearer ${token}` } : {},
            credentials: 'include',
          }),
          fetch(`${API_BASE}/api/billing/catalog`, { credentials: 'include' }),
          fetch(`${API_BASE}/api/connectors/status`, {
            headers: token ? { Authorization: `Bearer ${token}` } : {},
            credentials: 'include',
          }),
          fetch(`${API_BASE}/api/admin/capabilities`, {
            headers: token ? { Authorization: `Bearer ${token}` } : {},
            credentials: 'include',
          }),
        ]);

        const statusData = await statusRes.json();
        const catalogData = await catalogRes.json();
        const connectorsData = await connectorsRes.json().catch(() => ({}));
        const adminCapsData = await adminCapsRes.json().catch(() => ({}));

        if (!statusRes.ok) {
          if (statusRes.status === 401) {
            navigate('/?auth=1', { replace: true });
            return;
          }
          throw new Error(statusData?.msg || 'Unable to load billing status.');
        }
        if (!connectorsRes.ok && connectorsRes.status === 401) {
          navigate('/?auth=1', { replace: true });
          return;
        }
        if (!adminCapsRes.ok && adminCapsRes.status === 401) {
          navigate('/?auth=1', { replace: true });
          return;
        }
        if (mounted) {
          const connectorItems = Array.isArray(connectorsData?.connectors) ? connectorsData.connectors : [];
          setStatus(statusData);
          setCatalog(catalogData || { plans: {}, overage_packs: {}, model_types: FALLBACK_MODEL_TYPES });
          setConnectorState({
            loading: false,
            items: connectorItems,
          });
          setConnectorDrafts(buildConnectorDraftMap(connectorItems));
          const isAdmin = Boolean(adminCapsRes.ok && adminCapsData?.is_admin);
          setAdminState((prev) => ({
            ...prev,
            checked: true,
            isAdmin,
          }));
          if (isAdmin) {
            const usersRes = await fetch(`${API_BASE}/api/admin/users?limit=100`, {
              headers: token ? { Authorization: `Bearer ${token}` } : {},
              credentials: 'include',
            });
            const usersData = await usersRes.json().catch(() => ({}));
            if (mounted && usersRes.ok) {
              setAdminState((prev) => ({
                ...prev,
                checked: true,
                isAdmin: true,
                users: Array.isArray(usersData?.users) ? usersData.users : [],
              }));
            }
          }
        }
      } catch (error) {
        if (mounted) {
          setMessage(error.message || 'Unable to load account details.');
          setConnectorState((prev) => ({ ...prev, loading: false }));
          setAdminState((prev) => ({ ...prev, checked: true }));
        }
      } finally {
        if (mounted) setLoading(false);
      }
    };

    load();
    return () => {
      mounted = false;
    };
  }, [navigate]);

  const refreshStatus = async () => {
    const token = getToken();
    const res = await fetch(`${API_BASE}/api/billing/status`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      credentials: 'include',
    });
    const data = await res.json();
    if (res.ok) setStatus(data);
  };

  const refreshConnectors = async () => {
    const token = getToken();
    const res = await fetch(`${API_BASE}/api/connectors/status`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      credentials: 'include',
    });
    const data = await res.json();
    if (res.ok) {
      const connectorItems = Array.isArray(data?.connectors) ? data.connectors : [];
      setConnectorState({
        loading: false,
        items: connectorItems,
      });
      setConnectorDrafts(buildConnectorDraftMap(connectorItems));
    } else if (res.status === 401) {
      navigate('/?auth=1', { replace: true });
    }
  };

  const startPlanChange = async (planKey) => {
    const token = getToken();

    setPendingAction(planKey);
    setMessage('');

    try {
      const response = await fetch(`${API_BASE}/api/billing/create-checkout-session`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        credentials: 'include',
        body: JSON.stringify({ plan_key: planKey }),
      });
      const data = await response.json();

      if (!response.ok) {
        if (response.status === 401) {
          navigate('/?auth=1', { replace: true });
          return;
        }
        throw new Error(data?.msg || 'Unable to start plan change.');
      }

      if (data?.url) {
        window.location.href = data.url;
        return;
      }

      setMessage('Plan updated successfully.');
      await refreshStatus();
    } catch (error) {
      setMessage(error.message || 'Unable to start plan change.');
    } finally {
      setPendingAction('');
    }
  };

  const openBillingPortal = async () => {
    const token = getToken();

    setPendingAction('portal');
    setMessage('');

    try {
      const response = await fetch(`${API_BASE}/api/billing/create-portal-session`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        credentials: 'include',
        body: JSON.stringify({ return_url: `${window.location.origin}/account` }),
      });
      const data = await response.json();
      if (!response.ok || !data?.url) {
        if (response.status === 401) {
          navigate('/?auth=1', { replace: true });
          return;
        }
        throw new Error(data?.msg || 'Online billing management is not available for this account yet.');
      }
      window.location.href = data.url;
    } catch (error) {
      setMessage(error.message || 'Unable to open billing settings.');
    } finally {
      setPendingAction('');
    }
  };

  const cancelAtPeriodEnd = async () => {
    const token = getToken();

    setPendingAction('cancel');
    setMessage('');

    try {
      const response = await fetch(`${API_BASE}/api/billing/cancel-subscription`, {
        method: 'POST',
        headers: {
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        credentials: 'include',
      });
      const data = await response.json();
      if (!response.ok) {
        if (response.status === 401) {
          navigate('/?auth=1', { replace: true });
          return;
        }
        throw new Error(data?.msg || 'Unable to cancel subscription.');
      }
      setMessage('Subscription will cancel at period end.');
      await refreshStatus();
    } catch (error) {
      setMessage(error.message || 'Unable to cancel subscription.');
    } finally {
      setPendingAction('');
    }
  };

  const buyPack = async (packKey) => {
    const token = getToken();

    setPendingAction(packKey);
    setMessage('');

    try {
      const response = await fetch(`${API_BASE}/api/billing/create-overage-checkout-session`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        credentials: 'include',
        body: JSON.stringify({ pack_key: packKey }),
      });
      const data = await response.json();
      if (!response.ok || !data?.url) {
        if (response.status === 401) {
          navigate('/?auth=1', { replace: true });
          return;
        }
        throw new Error(data?.msg || 'Unable to start overage checkout.');
      }
      window.location.href = data.url;
    } catch (error) {
      setMessage(error.message || 'Unable to start overage checkout.');
    } finally {
      setPendingAction('');
    }
  };

  const updateConnector = async (connectorId, updates) => {
    const token = getToken();
    setConnectorPendingId(connectorId);
    setMessage('');

    try {
      const response = await fetch(`${API_BASE}/api/connectors/${encodeURIComponent(connectorId)}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        credentials: 'include',
        body: JSON.stringify(updates || {}),
      });
      const data = await response.json();
      if (!response.ok) {
        if (response.status === 401) {
          navigate('/?auth=1', { replace: true });
          return;
        }
        throw new Error(data?.error || 'Unable to update connector.');
      }

      const updatedConnector = data?.connector;
      if (updatedConnector?.id) {
        setConnectorState((prev) => ({
          ...prev,
          items: (prev.items || []).map((item) => (item.id === updatedConnector.id ? updatedConnector : item)),
        }));
        setConnectorDrafts((prev) => ({
          ...prev,
          [updatedConnector.id]: buildConnectorDraft(updatedConnector),
        }));
        setMessage(`${updatedConnector.label || 'Connector'} settings saved.`);
      } else {
        await refreshConnectors();
        setMessage('Connector settings saved.');
      }
    } catch (error) {
      setMessage(error.message || 'Unable to update connector.');
    } finally {
      setConnectorPendingId('');
    }
  };

  const updateConnectorDraft = (connectorId, updates) => {
    if (!connectorId) return;
    setConnectorDrafts((prev) => ({
      ...prev,
      [connectorId]: {
        ...(prev[connectorId] || {}),
        ...(updates || {}),
      },
    }));
  };

  const saveConnectorDraft = async (connector) => {
    if (!connector?.id) return;
    const draft = connectorDrafts[connector.id] || buildConnectorDraft(connector);
    const payload = {
      connection_status: draft.connection_status === 'connected' ? 'connected' : 'disconnected',
      sync_mode: String(draft.sync_mode || '').trim(),
      conflict_policy: String(draft.conflict_policy || '').trim(),
      auto_sync: Boolean(draft.auto_sync),
      external_workspace: String(draft.external_workspace || '').trim(),
    };

    if (connector.id === 'jira_sync') {
      payload.jira_base_url = String(draft.jira_base_url || '').trim();
      payload.jira_project_key = String(draft.jira_project_key || '').trim();
      payload.jira_email = String(draft.jira_email || '').trim();
      payload.jira_issue_type = String(draft.jira_issue_type || '').trim();
      if (String(draft.jira_api_token || '').trim()) {
        payload.jira_api_token = String(draft.jira_api_token || '').trim();
      }
    }

    await updateConnector(connector.id, payload);
  };

  const toAdminDraft = (user) => {
    if (!user || !user.id) return null;
    return {
      id: user.id,
      email: user.email || '',
      name: user.name || '',
      subscription_plan: user.subscription_plan || 'free',
      credits_remaining: user.credits_remaining == null ? '' : String(user.credits_remaining),
      seat_limit: user.seat_limit == null ? '' : String(user.seat_limit),
      max_seats: user.max_seats == null ? '' : String(user.max_seats),
      unlimited_analysis: Boolean(user.unlimited_analysis),
      max_concurrent_sessions: user.max_concurrent_sessions == null ? '' : String(user.max_concurrent_sessions),
      stripe_customer_id: user.stripe_customer_id || '',
      stripe_subscription_id: user.stripe_subscription_id || '',
    };
  };

  const refreshAdminUsers = async (nextQuery = adminState.query || '') => {
    if (!adminState.isAdmin) return;
    const token = getToken();
    setAdminState((prev) => ({ ...prev, loading: true, query: nextQuery }));
    try {
      const response = await fetch(`${API_BASE}/api/admin/users?limit=100&q=${encodeURIComponent(nextQuery)}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        credentials: 'include',
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        if (response.status === 401) {
          navigate('/?auth=1', { replace: true });
          return;
        }
        if (response.status === 403) {
          setAdminState((prev) => ({ ...prev, loading: false, isAdmin: false, checked: true }));
          return;
        }
        throw new Error(data?.error || 'Unable to load users.');
      }

      const users = Array.isArray(data?.users) ? data.users : [];
      setAdminState((prev) => {
        let draft = prev.draft;
        if (draft?.id) {
          const replacement = users.find((item) => item.id === draft.id);
          draft = replacement ? toAdminDraft(replacement) : null;
        }
        return {
          ...prev,
          loading: false,
          users,
          draft,
          selectedUserId: draft?.id || '',
        };
      });
    } catch (error) {
      setAdminState((prev) => ({ ...prev, loading: false }));
      setMessage(error.message || 'Unable to load users.');
    }
  };

  const saveAdminUser = async () => {
    if (!adminState.isAdmin || !adminState.draft?.id) return;
    const token = getToken();
    setAdminState((prev) => ({ ...prev, pending: true }));
    setMessage('');
    try {
      const draft = adminState.draft;
      const payload = {
        name: String(draft.name || '').trim(),
        subscription_plan: String(draft.subscription_plan || '').trim().toLowerCase(),
        credits_remaining: draft.credits_remaining === '' ? null : Number(draft.credits_remaining),
        seat_limit: draft.seat_limit === '' ? 0 : Number(draft.seat_limit),
        max_seats: draft.max_seats === '' ? 0 : Number(draft.max_seats),
        unlimited_analysis: Boolean(draft.unlimited_analysis),
        max_concurrent_sessions: draft.max_concurrent_sessions === '' ? null : Number(draft.max_concurrent_sessions),
        stripe_customer_id: String(draft.stripe_customer_id || '').trim(),
        stripe_subscription_id: String(draft.stripe_subscription_id || '').trim(),
      };
      const response = await fetch(`${API_BASE}/api/admin/users/${encodeURIComponent(draft.id)}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        credentials: 'include',
        body: JSON.stringify(payload),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data?.error || 'Unable to save user.');
      }
      const saved = data?.user;
      if (saved?.id) {
        setAdminState((prev) => ({
          ...prev,
          pending: false,
          users: (prev.users || []).map((item) => (item.id === saved.id ? saved : item)),
          draft: toAdminDraft(saved),
          selectedUserId: saved.id,
        }));
      } else {
        setAdminState((prev) => ({ ...prev, pending: false }));
      }
      setMessage(`Saved user ${saved?.email || ''}.`);
      await refreshStatus();
    } catch (error) {
      setAdminState((prev) => ({ ...prev, pending: false }));
      setMessage(error.message || 'Unable to save user.');
    }
  };

  const forceEssential = async () => {
    if (!adminState.isAdmin || !adminState.draft?.id) return;
    const token = getToken();
    setAdminState((prev) => ({ ...prev, pending: true }));
    setMessage('');
    try {
      const response = await fetch(`${API_BASE}/api/admin/users/${encodeURIComponent(adminState.draft.id)}/force-plan`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        credentials: 'include',
        body: JSON.stringify({ plan_key: 'essential', reset_credits: true }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data?.error || 'Unable to force plan.');
      }
      const saved = data?.user;
      if (saved?.id) {
        setAdminState((prev) => ({
          ...prev,
          pending: false,
          users: (prev.users || []).map((item) => (item.id === saved.id ? saved : item)),
          draft: toAdminDraft(saved),
          selectedUserId: saved.id,
        }));
      } else {
        setAdminState((prev) => ({ ...prev, pending: false }));
      }
      setMessage(`Forced Essential for ${saved?.email || ''}.`);
      await refreshStatus();
    } catch (error) {
      setAdminState((prev) => ({ ...prev, pending: false }));
      setMessage(error.message || 'Unable to force Essential.');
    }
  };

  if (loading) {
    return (
      <div className="account-page">
        <div className="account-panel">Loading account details...</div>
      </div>
    );
  }

  const currentPlan = status?.plan_key || 'free';
  const plans = catalog?.plans || {};
  const packs = catalog?.overage_packs || {};
  const creditsRemainingLabel = status?.credits_remaining == null
    ? 'Contracted'
    : Number(status?.credits_remaining || 0).toLocaleString();
  const monthlyLimitLabel = status?.monthly_credit_limit == null
    ? 'Contracted'
    : Number(status?.monthly_credit_limit || 0).toLocaleString();
  const modelTypes = catalog?.model_types || FALLBACK_MODEL_TYPES;
  const orderedModelTypes = MODEL_ORDER.map((key) => modelTypes?.[key]).filter(Boolean);
  const connectorsByGroup = (connectorState.items || []).reduce((grouped, connector) => {
    const groupKey = normalizeConnectorGroup(connector?.group);
    if (!grouped[groupKey]) grouped[groupKey] = [];
    grouped[groupKey].push(connector);
    return grouped;
  }, {});
  const formatModelDisplayName = (model) => {
    const label = model?.label || model?.model_type || 'Model';
    const version = String(model?.version || '1.0').trim();
    return `${label}-${version}`;
  };
  const isModelAvailableForPlan = (minPlan, planKey) => {
    const requiredRank = PLAN_RANK[String(minPlan || 'free').toLowerCase()] ?? 0;
    const planRank = PLAN_RANK[String(planKey || 'free').toLowerCase()] ?? 0;
    return planRank >= requiredRank;
  };

  return (
    <div className="account-page">
      <div className="account-panel">
        <div className="account-header-row">
          <div className="account-title-wrap">
            <p className="account-eyebrow">Account</p>
            <h1>Billing & Usage</h1>
            <p className="account-subtext">
              Manage plan access, credit usage, and available connectors for your workspace.
            </p>
          </div>
          <div className="account-header-actions">
            {adminState.checked && adminState.isAdmin && (
              <button type="button" onClick={() => navigate('/jaspen-admin')} className="account-secondary-btn">
                Jaspen Admin
              </button>
            )}
            <button type="button" onClick={() => navigate('/new')} className="account-secondary-btn">
              Back to Jaspen
            </button>
          </div>
        </div>

        <div className="account-inline-status">
          <span className="account-status-chip">
            <span className="label">Current plan</span>
            <strong>{(plans[currentPlan]?.label || currentPlan).toString()}</strong>
          </span>
          <span className="account-status-chip">
            <span className="label">Credits remaining</span>
            <strong>{creditsRemainingLabel}</strong>
          </span>
          <span className="account-status-chip">
            <span className="label">Monthly limit</span>
            <strong>{monthlyLimitLabel}</strong>
          </span>
        </div>

        {message && <p className="account-message">{message}</p>}

        <section className="account-section">
          <h2>Plans</h2>
          <div className="account-plan-grid">
            {PLAN_ORDER.map((key) => {
              const plan = plans[key];
              if (!plan) return null;
              const isCurrent = currentPlan === key;
              const isSalesOnly = !!plan.sales_only;
              const isPending = pendingAction === key;
              const hasPrice = Number.isFinite(plan.monthly_price_usd);

              return (
                <article className={`account-plan-card ${isCurrent ? 'is-current' : ''}`} key={key}>
                  <h3>{plan.label}</h3>
                  <p className="account-plan-price">
                    {hasPrice ? (plan.monthly_price_usd === 0 ? '$0' : `$${plan.monthly_price_usd}/mo`) : 'Contact sales'}
                  </p>
                  <p>
                    {plan.monthly_credits == null
                      ? 'Contracted pooled usage'
                      : `${Number(plan.monthly_credits).toLocaleString()} credits/month`}
                  </p>
                  <p className="account-plan-connectors">
                    Connectors: {getPlanConnectorSentence(key)}
                  </p>

                  {isCurrent ? (
                    <span className="account-pill">Current</span>
                  ) : isSalesOnly ? (
                    <a href="/login" className="account-primary-btn">Talk to sales</a>
                  ) : (
                    <button
                      type="button"
                      className="account-primary-btn"
                      onClick={() => startPlanChange(key)}
                      disabled={isPending}
                    >
                      {isPending ? 'Redirecting...' : key === 'essential' ? 'Upgrade' : 'Switch'}
                    </button>
                  )}
                </article>
              );
            })}
          </div>
        </section>

        <section className="account-section" id="connectors">
          <h2>Connectors & PM Sync</h2>
          <p className="account-connectors-subtext">
            Use the organized list below to control connector access. Toggle on/off, review what that unlocks, adjust
            configuration, then save.
          </p>
          {connectorState.loading ? (
            <p className="account-connectors-loading">Loading connector settings...</p>
          ) : (
            <div className="account-connector-list-wrap">
              {CONNECTOR_GROUP_ORDER.map((groupKey) => {
                const groupItems = connectorsByGroup[groupKey] || [];
                if (!groupItems.length) return null;
                const groupLabel = groupKey === 'execution' ? 'Execution connectors' : 'Data connectors';

                return (
                  <div className="account-connector-group-block" key={groupKey}>
                    <h3>{groupLabel}</h3>
                    <div className="account-connector-list">
                      {groupItems.map((connector) => {
                        const locked = connector?.status === 'locked' || !connector?.enabled;
                        const pending = connectorPendingId === connector?.id;
                        const syncModes =
                          Array.isArray(connector?.available_sync_modes) && connector.available_sync_modes.length
                            ? connector.available_sync_modes
                            : DEFAULT_SYNC_MODES;
                        const conflictPolicies =
                          Array.isArray(connector?.available_conflict_policies) && connector.available_conflict_policies.length
                            ? connector.available_conflict_policies
                            : DEFAULT_CONFLICT_POLICIES;
                        const draft = connectorDrafts[connector.id] || buildConnectorDraft(connector);
                        const isOn = draft.connection_status === 'connected';
                        const tierLabel = normalizeTierLabel(connector?.required_min_tier || 'team');
                        const copy = getConnectorCopy(connector?.id, connector?.group);
                        const hasChanges = connectorDraftHasChanges(connector, draft);

                        return (
                          <article className={`account-connector-row ${isOn ? 'is-on' : ''}`} key={connector.id}>
                            <div className="account-connector-row-top">
                              <div className="account-connector-title-wrap">
                                <h4>{connector.label}</h4>
                                <p className="account-connector-group">{normalizeConnectorGroup(connector.group)}</p>
                              </div>
                              <div className="account-connector-status-wrap">
                                <span className={`account-connector-badge ${locked ? 'is-locked' : isOn ? 'is-connected' : 'is-available'}`}>
                                  {locked ? `${tierLabel}+` : isOn ? 'On' : 'Off'}
                                </span>
                                <label className={`account-connector-toggle ${locked ? 'is-disabled' : ''}`}>
                                  <input
                                    type="checkbox"
                                    checked={isOn}
                                    disabled={locked || pending}
                                    onChange={(e) =>
                                      updateConnectorDraft(connector.id, {
                                        connection_status: e.target.checked ? 'connected' : 'disconnected',
                                      })}
                                  />
                                  <span className="account-connector-toggle-track" />
                                  <span className="account-connector-toggle-label">{isOn ? 'Enabled' : 'Disabled'}</span>
                                </label>
                              </div>
                            </div>

                            <p className="account-connector-description">{connector.description}</p>
                            <p className="account-connector-impact">
                              <strong>When on:</strong> {copy.on} <strong>When off:</strong> {copy.off}
                            </p>
                            <p className="account-connector-config-note">{copy.config}</p>

                            {locked ? (
                              <div className="account-connector-row-actions">
                                <button
                                  type="button"
                                  className="account-secondary-btn"
                                  onClick={() => setMessage(`Upgrade to ${tierLabel} or above to unlock ${connector.label}.`)}
                                >
                                  Upgrade to unlock
                                </button>
                              </div>
                            ) : (
                              <>
                                <div className="account-connector-controls">
                                  <label>
                                    Sync direction
                                    <select
                                      value={draft.sync_mode || ''}
                                      disabled={pending}
                                      onChange={(e) => updateConnectorDraft(connector.id, { sync_mode: e.target.value })}
                                    >
                                      {syncModes.map((mode) => (
                                        <option key={mode} value={mode}>
                                          {SYNC_MODE_LABELS[mode] || mode}
                                        </option>
                                      ))}
                                    </select>
                                  </label>
                                  <label>
                                    Conflict policy
                                    <select
                                      value={draft.conflict_policy || ''}
                                      disabled={pending}
                                      onChange={(e) => updateConnectorDraft(connector.id, { conflict_policy: e.target.value })}
                                    >
                                      {conflictPolicies.map((policy) => (
                                        <option key={policy} value={policy}>
                                          {policy.replace(/_/g, ' ')}
                                        </option>
                                      ))}
                                    </select>
                                  </label>
                                  <label>
                                    External workspace / account key
                                    <input
                                      type="text"
                                      value={draft.external_workspace || ''}
                                      placeholder="Project key, workspace id, or account id"
                                      disabled={pending}
                                      onChange={(e) => updateConnectorDraft(connector.id, { external_workspace: e.target.value })}
                                    />
                                  </label>
                                  <label className="account-connector-checkbox">
                                    <input
                                      type="checkbox"
                                      checked={Boolean(draft.auto_sync)}
                                      disabled={pending}
                                      onChange={(e) => updateConnectorDraft(connector.id, { auto_sync: e.target.checked })}
                                    />
                                    Auto-sync when updates are available
                                  </label>
                                </div>

                                {connector.id === 'jira_sync' && (
                                  <>
                                    <div className="account-connector-controls account-jira-config">
                                      <label>
                                        Jira URL
                                        <input
                                          type="text"
                                          value={draft.jira_base_url || ''}
                                          placeholder="https://your-company.atlassian.net"
                                          disabled={pending}
                                          onChange={(e) => updateConnectorDraft(connector.id, { jira_base_url: e.target.value })}
                                        />
                                      </label>
                                      <label>
                                        Jira project key
                                        <input
                                          type="text"
                                          value={draft.jira_project_key || ''}
                                          placeholder="PROJ"
                                          disabled={pending}
                                          onChange={(e) => updateConnectorDraft(connector.id, {
                                            jira_project_key: e.target.value,
                                            external_workspace: e.target.value,
                                          })}
                                        />
                                      </label>
                                      <label>
                                        Jira service account email
                                        <input
                                          type="email"
                                          value={draft.jira_email || ''}
                                          placeholder="service-account@company.com"
                                          disabled={pending}
                                          onChange={(e) => updateConnectorDraft(connector.id, { jira_email: e.target.value })}
                                        />
                                      </label>
                                      <label>
                                        Jira issue type
                                        <input
                                          type="text"
                                          value={draft.jira_issue_type || ''}
                                          placeholder="Story"
                                          disabled={pending}
                                          onChange={(e) => updateConnectorDraft(connector.id, { jira_issue_type: e.target.value })}
                                        />
                                      </label>
                                      <label>
                                        Jira API token
                                        <input
                                          type="password"
                                          value={draft.jira_api_token || ''}
                                          placeholder={
                                            connector?.jira?.has_api_token
                                              ? 'Stored token found. Enter a new token to rotate.'
                                              : 'Enter Jira API token'
                                          }
                                          disabled={pending}
                                          onChange={(e) => updateConnectorDraft(connector.id, { jira_api_token: e.target.value })}
                                        />
                                      </label>
                                    </div>
                                    {connector?.jira?.has_api_token && !String(draft.jira_api_token || '').trim() && (
                                      <p className="account-connector-note">
                                        Jira API token already stored. Leave blank to keep the existing token.
                                      </p>
                                    )}
                                  </>
                                )}

                                <div className="account-connector-row-actions">
                                  <button
                                    type="button"
                                    className="account-secondary-btn"
                                    onClick={() => updateConnectorDraft(connector.id, buildConnectorDraft(connector))}
                                    disabled={pending || !hasChanges}
                                  >
                                    Reset
                                  </button>
                                  <button
                                    type="button"
                                    className="account-primary-btn"
                                    onClick={() => saveConnectorDraft(connector)}
                                    disabled={pending || !hasChanges}
                                  >
                                    {pending ? 'Saving...' : 'Save changes'}
                                  </button>
                                </div>
                              </>
                            )}
                          </article>
                        );
                      })}
                    </div>
                  </div>
                );
              })}

            </div>
          )}
        </section>

        <section className="account-section" id="connectors-api">
          <h2>Connector API setup</h2>
          <p className="account-connectors-subtext">
            Connector controls in this page use the same API you can automate against with your authenticated bearer token.
          </p>
          <div className="account-api-guide">
            <article className="account-api-step">
              <h3>1. Read connector state</h3>
              <p><code>GET /api/connectors/status</code> returns enabled/locked status, sync modes, and current config.</p>
            </article>
            <article className="account-api-step">
              <h3>2. Toggle and configure</h3>
              <p><code>PATCH /api/connectors/:connector_id</code> with <code>connection_status</code>, sync settings, and connector-specific fields.</p>
            </article>
            <article className="account-api-step">
              <h3>3. Set thread-level PM sync</h3>
              <p><code>PUT /api/connectors/threads/:thread_id/sync</code> selects connected execution connectors for thread sync.</p>
            </article>
          </div>
          <pre className="account-api-snippet">
{`PATCH /api/connectors/jira_sync
{
  "connection_status": "connected",
  "sync_mode": "two_way",
  "conflict_policy": "prefer_external",
  "external_workspace": "PROJ",
  "jira_base_url": "https://your-company.atlassian.net",
  "jira_project_key": "PROJ"
}`}
          </pre>
        </section>

        <section className="account-section">
          <h2>One-time credit packs</h2>
          <div className="account-pack-grid">
            {PACK_ORDER.map((key) => {
              const pack = packs[key];
              if (!pack) return null;
              const isPending = pendingAction === key;
              return (
                <article className="account-pack-card" key={key}>
                  <h3>{pack.label}</h3>
                  <p>{Number(pack.credits || 0).toLocaleString()} one-time credits</p>
                  <button
                    type="button"
                    className="account-primary-btn"
                    onClick={() => buyPack(key)}
                    disabled={isPending}
                  >
                    {isPending ? 'Redirecting...' : `Purchase for $${pack.price_usd}`}
                  </button>
                </article>
              );
            })}
          </div>
        </section>

        <section className="account-section">
          <h2>Model access by plan</h2>
          <div className="account-model-table-wrap">
            <table className="account-model-table">
              <thead>
                <tr>
                  <th scope="col">Model</th>
                  {PLAN_ORDER.map((key) => (
                    <th scope="col" key={key}>{plans[key]?.label || key}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {orderedModelTypes.map((model) => (
                  <tr key={model.model_type || model.label}>
                    <th scope="row">
                      <div className="account-model-name">{formatModelDisplayName(model)}</div>
                      <div className="account-model-desc">{model.description || ''}</div>
                    </th>
                    {PLAN_ORDER.map((key) => (
                      <td
                        key={`${model.model_type}-${key}`}
                        className={key === currentPlan ? 'is-current-plan' : ''}
                      >
                        {isModelAvailableForPlan(model.min_plan, key) ? 'Included' : 'Upgrade'}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="account-section account-actions-row">
          <button
            type="button"
            className="account-secondary-btn"
            onClick={openBillingPortal}
            disabled={pendingAction === 'portal'}
          >
            {pendingAction === 'portal' ? 'Opening...' : 'Manage billing'}
          </button>
          <button
            type="button"
            className="account-danger-btn"
            onClick={cancelAtPeriodEnd}
            disabled={pendingAction === 'cancel' || !status?.stripe_subscription_id}
          >
            {pendingAction === 'cancel' ? 'Canceling...' : 'Cancel at period end'}
          </button>
        </section>

        {adminState.checked && adminState.isAdmin && (
          <section className="account-section" id="admin">
            <div className="account-admin-header">
              <h2>System admin</h2>
              <p>Search users, adjust plan, credits, and account controls without billing flow.</p>
            </div>
            <div className="account-admin-search">
              <input
                type="text"
                placeholder="Search by email or name"
                value={adminState.query}
                onChange={(e) => setAdminState((prev) => ({ ...prev, query: e.target.value }))}
              />
              <button
                type="button"
                className="account-secondary-btn"
                onClick={() => refreshAdminUsers(adminState.query)}
                disabled={adminState.loading}
              >
                {adminState.loading ? 'Searching...' : 'Search'}
              </button>
            </div>
            <div className="account-admin-layout">
              <div className="account-admin-user-list">
                {(adminState.users || []).map((user) => {
                  const selected = adminState.selectedUserId === user.id;
                  return (
                    <button
                      type="button"
                      key={user.id}
                      className={`account-admin-user ${selected ? 'is-selected' : ''}`}
                      onClick={() => setAdminState((prev) => ({
                        ...prev,
                        selectedUserId: user.id,
                        draft: toAdminDraft(user),
                      }))}
                    >
                      <strong>{user.email}</strong>
                      <span>{user.name}</span>
                      <span>{user.subscription_plan}</span>
                    </button>
                  );
                })}
              </div>
              <div className="account-admin-editor">
                {adminState.draft ? (
                  <>
                    <div className="account-admin-grid">
                      <label>
                        Email
                        <input type="text" value={adminState.draft.email} disabled />
                      </label>
                      <label>
                        Name
                        <input
                          type="text"
                          value={adminState.draft.name}
                          onChange={(e) => setAdminState((prev) => ({
                            ...prev,
                            draft: { ...prev.draft, name: e.target.value },
                          }))}
                        />
                      </label>
                      <label>
                        Plan
                        <select
                          value={adminState.draft.subscription_plan}
                          onChange={(e) => setAdminState((prev) => ({
                            ...prev,
                            draft: { ...prev.draft, subscription_plan: e.target.value },
                          }))}
                        >
                          {PLAN_ORDER.map((key) => <option key={key} value={key}>{key}</option>)}
                        </select>
                      </label>
                      <label>
                        Credits
                        <input
                          type="number"
                          value={adminState.draft.credits_remaining}
                          onChange={(e) => setAdminState((prev) => ({
                            ...prev,
                            draft: { ...prev.draft, credits_remaining: e.target.value },
                          }))}
                        />
                      </label>
                      <label>
                        Seat limit
                        <input
                          type="number"
                          value={adminState.draft.seat_limit}
                          onChange={(e) => setAdminState((prev) => ({
                            ...prev,
                            draft: { ...prev.draft, seat_limit: e.target.value },
                          }))}
                        />
                      </label>
                      <label>
                        Max seats
                        <input
                          type="number"
                          value={adminState.draft.max_seats}
                          onChange={(e) => setAdminState((prev) => ({
                            ...prev,
                            draft: { ...prev.draft, max_seats: e.target.value },
                          }))}
                        />
                      </label>
                      <label>
                        Max concurrent sessions
                        <input
                          type="number"
                          value={adminState.draft.max_concurrent_sessions}
                          onChange={(e) => setAdminState((prev) => ({
                            ...prev,
                            draft: { ...prev.draft, max_concurrent_sessions: e.target.value },
                          }))}
                        />
                      </label>
                      <label>
                        Stripe customer id
                        <input
                          type="text"
                          value={adminState.draft.stripe_customer_id}
                          onChange={(e) => setAdminState((prev) => ({
                            ...prev,
                            draft: { ...prev.draft, stripe_customer_id: e.target.value },
                          }))}
                        />
                      </label>
                      <label>
                        Stripe subscription id
                        <input
                          type="text"
                          value={adminState.draft.stripe_subscription_id}
                          onChange={(e) => setAdminState((prev) => ({
                            ...prev,
                            draft: { ...prev.draft, stripe_subscription_id: e.target.value },
                          }))}
                        />
                      </label>
                      <label className="account-admin-checkbox">
                        <input
                          type="checkbox"
                          checked={Boolean(adminState.draft.unlimited_analysis)}
                          onChange={(e) => setAdminState((prev) => ({
                            ...prev,
                            draft: { ...prev.draft, unlimited_analysis: e.target.checked },
                          }))}
                        />
                        Unlimited analysis
                      </label>
                    </div>
                    <div className="account-admin-actions">
                      <button
                        type="button"
                        className="account-primary-btn"
                        onClick={saveAdminUser}
                        disabled={adminState.pending}
                      >
                        {adminState.pending ? 'Saving...' : 'Save user settings'}
                      </button>
                      <button
                        type="button"
                        className="account-secondary-btn"
                        onClick={forceEssential}
                        disabled={adminState.pending}
                      >
                        Force Essential + reset credits
                      </button>
                    </div>
                  </>
                ) : (
                  <p>Select a user to edit.</p>
                )}
              </div>
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
