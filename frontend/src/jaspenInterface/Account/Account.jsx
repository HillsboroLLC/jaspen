import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { API_BASE } from '../../config/apiBase';
import { getPlanConnectorSentence } from '../../shared/billing/planConnectors';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faBookOpen,
  faBolt,
  faChevronLeft,
  faChevronRight,
  faChartLine,
  faGear,
  faLayerGroup,
  faPlug,
} from '@fortawesome/free-solid-svg-icons';
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
const DEFAULT_SYNC_MODES = ['import', 'push', 'two_way'];
const DEFAULT_CONFLICT_POLICIES = ['latest_wins', 'prefer_external', 'prefer_jaspen', 'manual_review'];
const SYNC_MODE_LABELS = {
  import: 'External -> Jaspen',
  push: 'Jaspen -> External',
  two_way: 'Two-way',
};
const CONFLICT_POLICY_LABELS = {
  latest_wins: 'Most recent update wins',
  prefer_external: 'Prefer external system',
  prefer_jaspen: 'Prefer Jaspen',
  manual_review: 'Manual review required',
};
const CONFLICT_POLICY_HELP = {
  latest_wins: 'When both systems update the same field, the newest timestamp wins.',
  prefer_external: 'If values conflict, keep the external system value.',
  prefer_jaspen: 'If values conflict, keep the Jaspen value.',
  manual_review: 'Flag the conflict for manual review before applying.',
};
const DEFAULT_JIRA_ISSUE_TYPE = 'Task';

function emptyJiraModalState() {
  return {
    open: false,
    connectorId: '',
    intentEnable: false,
    revertStatus: 'disconnected',
    hasStoredToken: false,
    data: {
      jira_base_url: '',
      jira_project_key: '',
      jira_email: '',
      jira_api_token: '',
      jira_issue_type: DEFAULT_JIRA_ISSUE_TYPE,
    },
  };
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
    external_workspace: String(connector?.external_workspace || ''),
    jira_base_url: String(connector?.jira?.base_url || ''),
    jira_project_key: String(connector?.jira?.project_key || ''),
    jira_email: String(connector?.jira?.email || ''),
    jira_issue_type: String(connector?.jira?.issue_type || DEFAULT_JIRA_ISSUE_TYPE),
    jira_api_token: '',
  };
}

function buildConnectorDraftMap(items) {
  const result = {};
  (Array.isArray(items) ? items : []).forEach((connector) => {
    if (!connector?.id) return;
    result[connector.id] = buildConnectorDraft(connector);
  });
  return result;
}

function connectorDraftIsDirty(connector, draft) {
  const base = buildConnectorDraft(connector);
  const current = { ...base, ...(draft || {}) };
  const trim = (value) => String(value || '').trim();
  const fields = [
    'connection_status',
    'sync_mode',
    'conflict_policy',
    'external_workspace',
    'jira_base_url',
    'jira_project_key',
    'jira_email',
    'jira_issue_type',
  ];
  const hasFieldDiff = fields.some((field) => trim(base[field]) !== trim(current[field]));
  const hasNewToken = trim(current.jira_api_token).length > 0;
  return hasFieldDiff || hasNewToken;
}

function connectorToggleMeaning(connector) {
  const isExecution = String(connector?.group || '').toLowerCase() === 'execution';
  if (isExecution) {
    return 'On enables execution sync flows. Off blocks plan/status exchange.';
  }
  return 'On enables insight ingestion. Off excludes this system from analysis context.';
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
  const [connectorSettingsOpen, setConnectorSettingsOpen] = useState({});
  const [loading, setLoading] = useState(true);
  const [pendingAction, setPendingAction] = useState('');
  const [connectorPendingId, setConnectorPendingId] = useState('');
  const [jiraConfigModal, setJiraConfigModal] = useState(() => emptyJiraModalState());
  const [jiraConfigError, setJiraConfigError] = useState('');
  const [jiraConfigSaving, setJiraConfigSaving] = useState(false);
  const [message, setMessage] = useState('');
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [activeTab, setActiveTab] = useState('overview');
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
          setConnectorSettingsOpen((prev) => {
            const next = {};
            connectorItems.forEach((item) => {
              if (item?.id && prev[item.id]) next[item.id] = true;
            });
            return next;
          });
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

  useEffect(() => {
    if (activeTab === 'admin' && !(adminState.checked && adminState.isAdmin)) {
      setActiveTab('overview');
    }
  }, [activeTab, adminState.checked, adminState.isAdmin]);

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
      setConnectorSettingsOpen((prev) => {
        const next = {};
        connectorItems.forEach((item) => {
          if (item?.id && prev[item.id]) next[item.id] = true;
        });
        return next;
      });
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
          return false;
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
        setMessage(`${updatedConnector.label || 'Connector'} saved.`);
      } else {
        await refreshConnectors();
        setMessage('Connector saved.');
      }
      return true;
    } catch (error) {
      setMessage(error.message || 'Unable to update connector.');
      return false;
    } finally {
      setConnectorPendingId('');
    }
  };

  const updateConnectorDraft = (connectorId, updates = {}) => {
    if (!connectorId) return;
    setConnectorDrafts((prev) => ({
      ...prev,
      [connectorId]: {
        ...(prev[connectorId] || {}),
        ...(updates || {}),
      },
    }));
  };

  const toggleConnectorSettings = (connectorId) => {
    if (!connectorId) return;
    setConnectorSettingsOpen((prev) => ({
      ...prev,
      [connectorId]: !prev[connectorId],
    }));
  };

  const saveConnectorDraft = async (connector, draftOverride = null) => {
    if (!connector?.id) return;
    const draft = draftOverride || connectorDrafts[connector.id] || buildConnectorDraft(connector);
    const payload = {
      connection_status: draft.connection_status === 'connected' ? 'connected' : 'disconnected',
      sync_mode: String(draft.sync_mode || '').trim(),
      conflict_policy: String(draft.conflict_policy || '').trim(),
      external_workspace: String(draft.external_workspace || '').trim(),
    };
    if (connector.id === 'jira_sync') {
      payload.jira_base_url = String(draft.jira_base_url || '').trim();
      payload.jira_project_key = String(draft.jira_project_key || '').trim();
      payload.jira_email = String(draft.jira_email || '').trim();
      payload.jira_issue_type = String(draft.jira_issue_type || DEFAULT_JIRA_ISSUE_TYPE).trim();
      if (String(draft.jira_api_token || '').trim()) {
        payload.jira_api_token = String(draft.jira_api_token || '').trim();
      }
    }
    return updateConnector(connector.id, payload);
  };

  const openJiraConfigModal = (connector, options = {}) => {
    const baseDraft = connectorDrafts[connector.id] || buildConnectorDraft(connector);
    const intentEnable = Boolean(options?.intentEnable);
    const revertStatus = options?.revertStatus || baseDraft.connection_status || 'disconnected';
    const nextStatus = intentEnable ? 'connected' : (baseDraft.connection_status || 'disconnected');
    updateConnectorDraft(connector.id, { connection_status: nextStatus });
    setJiraConfigError('');
    setJiraConfigSaving(false);
    setJiraConfigModal({
      open: true,
      connectorId: connector.id,
      intentEnable,
      revertStatus,
      hasStoredToken: Boolean(connector?.jira?.has_api_token),
      data: {
        jira_base_url: String(baseDraft.jira_base_url || connector?.jira?.base_url || ''),
        jira_project_key: String(baseDraft.jira_project_key || connector?.jira?.project_key || ''),
        jira_email: String(baseDraft.jira_email || connector?.jira?.email || ''),
        jira_api_token: '',
        jira_issue_type: String(baseDraft.jira_issue_type || connector?.jira?.issue_type || DEFAULT_JIRA_ISSUE_TYPE),
      },
    });
  };

  const closeJiraConfigModal = (revertToPrevious = true) => {
    setJiraConfigModal((prev) => {
      if (revertToPrevious && prev?.open && prev.intentEnable && prev.connectorId) {
        updateConnectorDraft(prev.connectorId, { connection_status: prev.revertStatus || 'disconnected' });
      }
      return emptyJiraModalState();
    });
    setJiraConfigSaving(false);
    setJiraConfigError('');
  };

  const saveJiraConfigAndEnable = async () => {
    const modal = jiraConfigModal;
    if (!modal?.open || !modal.connectorId) return;
    const connector = (connectorState.items || []).find((item) => item.id === modal.connectorId);
    if (!connector) {
      setJiraConfigError('Unable to locate Jira connector state.');
      return;
    }

    const trimmed = {
      jira_base_url: String(modal.data.jira_base_url || '').trim(),
      jira_project_key: String(modal.data.jira_project_key || '').trim(),
      jira_email: String(modal.data.jira_email || '').trim(),
      jira_api_token: String(modal.data.jira_api_token || '').trim(),
      jira_issue_type: String(modal.data.jira_issue_type || DEFAULT_JIRA_ISSUE_TYPE).trim() || DEFAULT_JIRA_ISSUE_TYPE,
    };
    const tokenAvailable = modal.hasStoredToken || Boolean(trimmed.jira_api_token);

    if (!trimmed.jira_base_url || !trimmed.jira_project_key || !trimmed.jira_email) {
      setJiraConfigError('Jira URL, project key, and Jira email are required.');
      return;
    }
    if (!tokenAvailable) {
      setJiraConfigError('Jira API token is required before enabling Jira sync.');
      return;
    }

    const nextDraft = {
      ...(connectorDrafts[connector.id] || buildConnectorDraft(connector)),
      connection_status: modal.intentEnable ? 'connected' : (connectorDrafts[connector.id]?.connection_status || 'disconnected'),
      jira_base_url: trimmed.jira_base_url,
      jira_project_key: trimmed.jira_project_key,
      jira_email: trimmed.jira_email,
      jira_issue_type: trimmed.jira_issue_type,
      external_workspace: trimmed.jira_project_key,
    };
    if (trimmed.jira_api_token) {
      nextDraft.jira_api_token = trimmed.jira_api_token;
    }

    updateConnectorDraft(connector.id, nextDraft);
    setJiraConfigSaving(true);
    setJiraConfigError('');
    const success = await saveConnectorDraft(connector, nextDraft);
    setJiraConfigSaving(false);
    if (success) {
      setJiraConfigModal(emptyJiraModalState());
      setJiraConfigError('');
    }
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
  const isAdminUser = adminState.checked && adminState.isAdmin;
  const sidebarItems = [
    { key: 'overview', label: 'Overview', icon: faChartLine },
    { key: 'plans', label: 'Plans', icon: faLayerGroup },
    { key: 'connectors', label: 'Connectors', icon: faPlug },
    { key: 'packs', label: 'Credit packs', icon: faBolt },
    { key: 'models', label: 'Models', icon: faLayerGroup },
    ...(isAdminUser ? [{ key: 'admin', label: 'System admin', icon: faGear }] : []),
    { key: 'knowledge', label: 'Knowledge', icon: faBookOpen },
  ];

  return (
    <div className="account-page">
      <div className="account-panel">
        <div className="account-content-layout">
          <aside className={`account-sidebar ${sidebarCollapsed ? 'is-collapsed' : ''}`}>
            <div className="account-sidebar-head">
              {!sidebarCollapsed && <p className="account-sidebar-title">Billing menu</p>}
              <button
                type="button"
                className="account-sidebar-toggle"
                onClick={() => setSidebarCollapsed((prev) => !prev)}
                aria-expanded={!sidebarCollapsed}
                aria-label={sidebarCollapsed ? 'Expand billing menu' : 'Collapse billing menu'}
              >
                <FontAwesomeIcon icon={sidebarCollapsed ? faChevronRight : faChevronLeft} />
              </button>
            </div>
            <nav className="account-sidebar-nav" aria-label="Billing sections">
              {sidebarItems.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  className={`account-sidebar-item ${activeTab === item.key ? 'is-active' : ''}`}
                  onClick={() => setActiveTab(item.key)}
                  title={sidebarCollapsed ? item.label : undefined}
                >
                  <span className="account-sidebar-icon">
                    <FontAwesomeIcon icon={item.icon} />
                  </span>
                  {!sidebarCollapsed && <span className="account-sidebar-label">{item.label}</span>}
                </button>
              ))}
            </nav>
          </aside>

          <div className="account-main-content">
        <div className="account-header-row">
          <div className="account-title-wrap">
            <p className="account-eyebrow">Account</p>
            <h1>Billing & Usage</h1>
            <p className="account-subtext">
              Manage plan access, credit usage, and available connectors for your workspace.
            </p>
          </div>
          <div className="account-header-actions">
            {isAdminUser && (
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

        {activeTab === 'overview' && (
        <section className="account-section">
          <h2 className="account-tab-title">Overview</h2>
          <div className="account-overview-grid">
            <article className="account-overview-card">
              <h3>Current plan</h3>
              <p>{(plans[currentPlan]?.label || currentPlan).toString()}</p>
            </article>
            <article className="account-overview-card">
              <h3>Credits remaining</h3>
              <p>{creditsRemainingLabel}</p>
            </article>
            <article className="account-overview-card">
              <h3>Monthly limit</h3>
              <p>{monthlyLimitLabel}</p>
            </article>
          </div>
        </section>
        )}

        {activeTab === 'plans' && (
        <section className="account-section">
          <h2 className="account-tab-title">Plans</h2>
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
                  <div className="account-plan-head">
                    <h3>{plan.label}</h3>
                    {isCurrent && (
                      <span className="account-pill">Current</span>
                    )}
                  </div>
                  <p className="account-plan-price">
                    {hasPrice ? (plan.monthly_price_usd === 0 ? '$0' : `$${plan.monthly_price_usd}/mo`) : 'Contact sales'}
                  </p>
                  <p className="account-plan-meta">
                    {plan.monthly_credits == null
                      ? 'Contracted pooled usage'
                      : `${Number(plan.monthly_credits).toLocaleString()} credits/month`}
                  </p>
                  <div className="account-plan-features">
                    <p className="account-plan-connectors">
                      Connectors: {getPlanConnectorSentence(key)}
                    </p>
                  </div>

                  <div className="account-plan-action-row">
                    {isCurrent ? null : isSalesOnly ? (
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
                  </div>
                </article>
              );
            })}
          </div>
        </section>
        )}

        {activeTab === 'connectors' && (
        <section className="account-section">
          <h2 className="account-tab-title">Connectors & PM Sync</h2>
          <p className="account-connectors-subtext">
            Start connector setup here. Toggle on, open settings if needed, and save per connector.
          </p>
          {connectorState.loading ? (
            <p className="account-connectors-loading">Loading connector settings...</p>
          ) : (
            <div className="account-connector-stack">
              {(connectorState.items || []).map((connector) => {
                const locked = connector?.status === 'locked' || !connector?.enabled;
                const requiredTier = String(connector?.required_min_tier || 'team').trim().toLowerCase();
                const requiredTierLabel = requiredTier ? `${requiredTier.charAt(0).toUpperCase()}${requiredTier.slice(1)}` : 'Team';
                const pending = connectorPendingId === connector?.id;
                const syncModes =
                  Array.isArray(connector?.available_sync_modes) && connector.available_sync_modes.length
                    ? connector.available_sync_modes
                    : DEFAULT_SYNC_MODES;
                const conflictPolicies = Array.isArray(connector?.available_conflict_policies)
                  ? connector.available_conflict_policies
                  : DEFAULT_CONFLICT_POLICIES;
                const draft = connectorDrafts[connector.id] || buildConnectorDraft(connector);
                const isOn = draft.connection_status === 'connected';
                const isDirty = connectorDraftIsDirty(connector, draft);
                const jiraTokenConfigured =
                  Boolean(connector?.jira?.has_api_token) || Boolean(String(draft.jira_api_token || '').trim());
                const settingsOpen = Boolean(connectorSettingsOpen[connector.id]);

                return (
                  <article className={`account-connector-item ${isOn ? 'is-connected' : ''} ${locked ? 'is-locked' : ''}`} key={connector.id}>
                    <div className="account-connector-main-row">
                      <div className="account-connector-main-copy">
                        <div className="account-connector-title-row">
                          <h3>{connector.label}</h3>
                          <p className="account-connector-group">{connector.group}</p>
                        </div>
                        <p className="account-connector-description">{connector.description}</p>
                        <p className="account-connector-toggle-note">{connectorToggleMeaning(connector)}</p>
                      </div>
                      <div className="account-connector-actions">
                        <span className={`account-connector-badge ${locked ? 'is-locked' : isOn ? 'is-connected' : 'is-available'}`}>
                          {locked ? `${requiredTier}+` : isOn ? 'On' : 'Off'}
                        </span>
                        <label className={`account-connector-toggle ${locked ? 'is-disabled' : ''}`}>
                          <input
                            type="checkbox"
                            checked={isOn}
                            disabled={locked || pending}
                            onChange={(e) => {
                              if (connector.id === 'jira_sync' && e.target.checked) {
                                openJiraConfigModal(connector, {
                                  intentEnable: true,
                                  revertStatus: draft.connection_status,
                                });
                                return;
                              }
                              updateConnectorDraft(connector.id, {
                                connection_status: e.target.checked ? 'connected' : 'disconnected',
                              });
                            }}
                          />
                          <span className="account-connector-toggle-track" />
                        </label>
                        <button
                          type="button"
                          className="account-secondary-btn account-connector-settings-btn"
                          onClick={() => toggleConnectorSettings(connector.id)}
                          disabled={locked || pending}
                        >
                          {settingsOpen ? 'Hide settings' : 'Settings'}
                        </button>
                        <button
                          type="button"
                          className="account-primary-btn account-save-btn"
                          onClick={() => saveConnectorDraft(connector)}
                          disabled={locked || pending || !isDirty}
                        >
                          {pending ? 'Saving...' : 'Save'}
                        </button>
                      </div>
                    </div>

                    {settingsOpen && (
                      <div className="account-connector-settings-panel">
                        <div className="account-connector-controls account-connector-controls-compact">
                          <label>
                            Sync
                            <select
                              value={draft.sync_mode || ''}
                              disabled={locked || pending}
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
                            Conflict
                            <select
                              value={draft.conflict_policy || ''}
                              disabled={locked || pending}
                              onChange={(e) => updateConnectorDraft(connector.id, { conflict_policy: e.target.value })}
                            >
                              {conflictPolicies.map((policy) => (
                                <option key={policy} value={policy}>
                                  {CONFLICT_POLICY_LABELS[policy] || policy.replace(/_/g, ' ')}
                                </option>
                              ))}
                            </select>
                            <span className="account-field-help">
                              {CONFLICT_POLICY_HELP[draft.conflict_policy] || ''}
                            </span>
                          </label>
                          <label>
                            External workspace
                            <input
                              type="text"
                              value={draft.external_workspace || ''}
                              placeholder="Workspace or account id"
                              disabled={locked || pending}
                              onChange={(e) => updateConnectorDraft(connector.id, { external_workspace: e.target.value })}
                            />
                          </label>
                        </div>

                        {connector.id === 'jira_sync' && (
                          <div className="account-jira-settings-row">
                            <button
                              type="button"
                              className="account-secondary-btn account-jira-settings-btn"
                              onClick={() => openJiraConfigModal(connector, {
                                intentEnable: false,
                                revertStatus: draft.connection_status,
                              })}
                              disabled={locked || pending}
                            >
                              Jira API settings
                            </button>
                            <span className={`account-jira-settings-state ${jiraTokenConfigured ? 'is-ready' : 'is-missing'}`}>
                              {jiraTokenConfigured ? 'API token configured' : 'API token required'}
                            </span>
                          </div>
                        )}
                      </div>
                    )}

                    {!settingsOpen && connector.id === 'jira_sync' && !jiraTokenConfigured && !locked && (
                      <p className="account-connector-locked-note">Jira API token required before enabling.</p>
                    )}

                    {locked && (
                      <p className="account-connector-locked-note">
                        Upgrade to {requiredTierLabel}+ to enable this toggle and save settings.
                      </p>
                    )}
                  </article>
                );
              })}
            </div>
          )}
        </section>
        )}

        {jiraConfigModal.open && (
          <div className="account-jira-modal-backdrop" role="presentation" onClick={() => closeJiraConfigModal(true)}>
            <div
              className="account-jira-modal"
              role="dialog"
              aria-modal="true"
              aria-label="Jira API settings"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="account-jira-modal-header">
                <h3>Jira API settings</h3>
                <button type="button" className="account-jira-modal-close" onClick={() => closeJiraConfigModal(true)} aria-label="Close">
                  ×
                </button>
              </div>
              <p className="account-jira-modal-subtext">
                Enter Jira credentials and mapping details, then save. Required: URL, project key, Jira email, API token.
              </p>
              <div className="account-jira-modal-grid">
                <label>
                  Jira URL
                  <input
                    type="text"
                    value={jiraConfigModal.data.jira_base_url}
                    placeholder="https://your-company.atlassian.net"
                    onChange={(e) => setJiraConfigModal((prev) => ({
                      ...prev,
                      data: { ...prev.data, jira_base_url: e.target.value },
                    }))}
                    disabled={jiraConfigSaving}
                  />
                </label>
                <label>
                  Jira project key
                  <input
                    type="text"
                    value={jiraConfigModal.data.jira_project_key}
                    placeholder="PROJ"
                    onChange={(e) => setJiraConfigModal((prev) => ({
                      ...prev,
                      data: { ...prev.data, jira_project_key: e.target.value },
                    }))}
                    disabled={jiraConfigSaving}
                  />
                </label>
                <label>
                  Jira email
                  <input
                    type="email"
                    value={jiraConfigModal.data.jira_email}
                    placeholder="service-account@company.com"
                    onChange={(e) => setJiraConfigModal((prev) => ({
                      ...prev,
                      data: { ...prev.data, jira_email: e.target.value },
                    }))}
                    disabled={jiraConfigSaving}
                  />
                </label>
                <label>
                  Jira issue type
                  <input
                    type="text"
                    value={jiraConfigModal.data.jira_issue_type}
                    placeholder="Task"
                    onChange={(e) => setJiraConfigModal((prev) => ({
                      ...prev,
                      data: { ...prev.data, jira_issue_type: e.target.value },
                    }))}
                    disabled={jiraConfigSaving}
                  />
                </label>
                <label className="account-jira-modal-token-field">
                  Jira API token
                  <input
                    type="password"
                    value={jiraConfigModal.data.jira_api_token}
                    placeholder={jiraConfigModal.hasStoredToken ? 'Token exists. Enter to rotate token.' : 'Enter Jira API token'}
                    onChange={(e) => setJiraConfigModal((prev) => ({
                      ...prev,
                      data: { ...prev.data, jira_api_token: e.target.value },
                    }))}
                    disabled={jiraConfigSaving}
                  />
                </label>
              </div>
              {jiraConfigError && <p className="account-jira-modal-error">{jiraConfigError}</p>}
              <div className="account-jira-modal-actions">
                <button type="button" className="account-secondary-btn" onClick={() => closeJiraConfigModal(true)} disabled={jiraConfigSaving}>
                  Cancel
                </button>
                <button type="button" className="account-primary-btn" onClick={saveJiraConfigAndEnable} disabled={jiraConfigSaving}>
                  {jiraConfigSaving ? 'Saving...' : (jiraConfigModal.intentEnable ? 'Save & enable Jira' : 'Save Jira settings')}
                </button>
              </div>
            </div>
          </div>
        )}

        {activeTab === 'packs' && (
        <section className="account-section">
          <h2 className="account-tab-title">One-time credit packs</h2>
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
        )}

        {activeTab === 'models' && (
        <section className="account-section">
          <h2 className="account-tab-title">Model access by plan</h2>
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
        )}

        {activeTab === 'overview' && (
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
        )}

        {activeTab === 'admin' && isAdminUser && (
          <section className="account-section">
            <div className="account-admin-header">
              <h2 className="account-tab-title">System admin</h2>
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
        {activeTab === 'knowledge' && (
          <section className="account-section">
            <h2 className="account-tab-title">Knowledge</h2>
            <div className="account-section-card account-knowledge-panel">
              <p>Connector setup, API patterns, and agent component docs are available in your internal Knowledge hub.</p>
              <button type="button" className="account-primary-btn" onClick={() => navigate('/knowledge')}>
                Open Knowledge
              </button>
            </div>
          </section>
        )}
          </div>
        </div>
      </div>
    </div>
  );
}
