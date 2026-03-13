import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { API_BASE } from '../../config/apiBase';
import { getPlanConnectorSentence } from '../../shared/billing/planConnectors';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faBookOpen,
  faBars,
  faBolt,
  faChartLine,
  faGear,
  faLayerGroup,
  faPlug,
  faTimes,
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
const DEFAULT_WORKFRONT_BASE_URL = 'https://yourdomain.my.workfront.com';
const DEFAULT_SMARTSHEET_BASE_URL = 'https://api.smartsheet.com';
const DEFAULT_ORACLE_FUSION_BASE_URL = 'https://your-company.fa.us2.oraclecloud.com';
const DEFAULT_SERVICENOW_INSTANCE_URL = 'https://your-instance.service-now.com';
const DEFAULT_NETSUITE_REST_BASE_URL = 'https://<account>.suitetalk.api.netsuite.com';
const MODAL_CONNECTOR_IDS = [
  'jira_sync',
  'workfront_sync',
  'smartsheet_sync',
  'salesforce_insights',
  'snowflake_insights',
  'oracle_fusion_insights',
  'servicenow_insights',
  'netsuite_insights',
];

function connectorUsesApiModal(connectorId) {
  return MODAL_CONNECTOR_IDS.includes(String(connectorId || '').trim());
}

function connectorApiLabel(connectorId) {
  if (connectorId === 'jira_sync') return 'Jira';
  if (connectorId === 'workfront_sync') return 'Workfront';
  if (connectorId === 'smartsheet_sync') return 'Smartsheet';
  if (connectorId === 'salesforce_insights') return 'Salesforce';
  if (connectorId === 'snowflake_insights') return 'Snowflake';
  if (connectorId === 'oracle_fusion_insights') return 'Oracle Fusion';
  if (connectorId === 'servicenow_insights') return 'ServiceNow';
  if (connectorId === 'netsuite_insights') return 'NetSuite';
  return 'Connector';
}

function emptyJiraModalState() {
  return {
    open: false,
    connectorId: '',
    intentEnable: false,
    revertStatus: 'disconnected',
    hasStoredToken: false,
    storedFlags: {},
    data: {
      jira_base_url: '',
      jira_project_key: '',
      jira_email: '',
      jira_api_token: '',
      jira_issue_type: DEFAULT_JIRA_ISSUE_TYPE,
      workfront_base_url: '',
      workfront_project_id: '',
      workfront_api_token: '',
      smartsheet_base_url: DEFAULT_SMARTSHEET_BASE_URL,
      smartsheet_sheet_id: '',
      smartsheet_api_token: '',
      salesforce_auth_base_url: '',
      salesforce_instance_url: '',
      salesforce_client_id: '',
      salesforce_client_secret: '',
      salesforce_refresh_token: '',
      snowflake_account: '',
      snowflake_warehouse: '',
      snowflake_database: '',
      snowflake_schema: '',
      snowflake_role: '',
      snowflake_user: '',
      snowflake_password: '',
      snowflake_private_key: '',
      snowflake_table_allowlist: '',
      oracle_fusion_base_url: DEFAULT_ORACLE_FUSION_BASE_URL,
      oracle_fusion_username: '',
      oracle_fusion_password: '',
      oracle_fusion_business_unit: '',
      servicenow_instance_url: DEFAULT_SERVICENOW_INSTANCE_URL,
      servicenow_username: '',
      servicenow_password: '',
      servicenow_table_allowlist: '',
      netsuite_account_id: '',
      netsuite_consumer_key: '',
      netsuite_consumer_secret: '',
      netsuite_token_id: '',
      netsuite_token_secret: '',
      netsuite_rest_base_url: DEFAULT_NETSUITE_REST_BASE_URL,
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

    // Jira
    jira_base_url: String(connector?.jira?.base_url || ''),
    jira_project_key: String(connector?.jira?.project_key || ''),
    jira_email: String(connector?.jira?.email || ''),
    jira_issue_type: String(connector?.jira?.issue_type || DEFAULT_JIRA_ISSUE_TYPE),
    jira_api_token: '',

    // Workfront
    workfront_base_url: String(connector?.workfront?.base_url || ''),
    workfront_project_id: String(connector?.workfront?.project_id || ''),
    workfront_api_token: '',

    // Smartsheet
    smartsheet_base_url: String(connector?.smartsheet?.base_url || DEFAULT_SMARTSHEET_BASE_URL),
    smartsheet_sheet_id: String(connector?.smartsheet?.sheet_id || ''),
    smartsheet_api_token: '',

    // Salesforce
    salesforce_auth_base_url: String(connector?.salesforce?.auth_base_url || ''),
    salesforce_instance_url: String(connector?.salesforce?.instance_url || ''),
    salesforce_client_id: String(connector?.salesforce?.client_id || ''),
    salesforce_client_secret: '',
    salesforce_refresh_token: '',

    // Snowflake
    snowflake_account: String(connector?.snowflake?.account || ''),
    snowflake_warehouse: String(connector?.snowflake?.warehouse || ''),
    snowflake_database: String(connector?.snowflake?.database || ''),
    snowflake_schema: String(connector?.snowflake?.schema || ''),
    snowflake_role: String(connector?.snowflake?.role || ''),
    snowflake_user: String(connector?.snowflake?.user || ''),
    snowflake_password: '',
    snowflake_private_key: '',
    snowflake_table_allowlist: Array.isArray(connector?.snowflake?.table_allowlist)
      ? connector.snowflake.table_allowlist.join(', ')
      : '',

    // Oracle Fusion
    oracle_fusion_base_url: String(connector?.oracle_fusion?.base_url || DEFAULT_ORACLE_FUSION_BASE_URL),
    oracle_fusion_username: String(connector?.oracle_fusion?.username || ''),
    oracle_fusion_password: '',
    oracle_fusion_business_unit: String(connector?.oracle_fusion?.business_unit || ''),

    // ServiceNow
    servicenow_instance_url: String(connector?.servicenow?.instance_url || DEFAULT_SERVICENOW_INSTANCE_URL),
    servicenow_username: String(connector?.servicenow?.username || ''),
    servicenow_password: '',
    servicenow_table_allowlist: Array.isArray(connector?.servicenow?.table_allowlist)
      ? connector.servicenow.table_allowlist.join(', ')
      : '',

    // NetSuite
    netsuite_account_id: String(connector?.netsuite?.account_id || ''),
    netsuite_consumer_key: String(connector?.netsuite?.consumer_key || ''),
    netsuite_consumer_secret: '',
    netsuite_token_id: String(connector?.netsuite?.token_id || ''),
    netsuite_token_secret: '',
    netsuite_rest_base_url: String(connector?.netsuite?.rest_base_url || DEFAULT_NETSUITE_REST_BASE_URL),
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
    'workfront_base_url',
    'workfront_project_id',
    'smartsheet_base_url',
    'smartsheet_sheet_id',
    'salesforce_auth_base_url',
    'salesforce_instance_url',
    'salesforce_client_id',
    'snowflake_account',
    'snowflake_warehouse',
    'snowflake_database',
    'snowflake_schema',
    'snowflake_role',
    'snowflake_user',
    'snowflake_table_allowlist',
    'oracle_fusion_base_url',
    'oracle_fusion_username',
    'oracle_fusion_business_unit',
    'servicenow_instance_url',
    'servicenow_username',
    'servicenow_table_allowlist',
    'netsuite_account_id',
    'netsuite_consumer_key',
    'netsuite_token_id',
    'netsuite_rest_base_url',
  ];
  const hasFieldDiff = fields.some((field) => trim(base[field]) !== trim(current[field]));
  const hasNewToken = [
    'jira_api_token',
    'workfront_api_token',
    'smartsheet_api_token',
    'salesforce_client_secret',
    'salesforce_refresh_token',
    'snowflake_password',
    'snowflake_private_key',
    'oracle_fusion_password',
    'servicenow_password',
    'netsuite_consumer_secret',
    'netsuite_token_secret',
  ].some((field) => trim(current[field]).length > 0);
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

  useEffect(() => {
    const search = new URLSearchParams(window.location.search || '');
    const sfOauth = String(search.get('sf_oauth') || '').trim().toLowerCase();
    const reason = String(search.get('reason') || '').trim();
    if (!sfOauth) return;

    if (sfOauth === 'success') {
      setMessage('Salesforce OAuth connected successfully.');
    } else if (sfOauth === 'error') {
      setMessage(`Salesforce OAuth failed${reason ? ` (${reason})` : ''}.`);
    }

    search.delete('sf_oauth');
    search.delete('reason');
    const nextUrl = `${window.location.pathname}${search.toString() ? `?${search.toString()}` : ''}${window.location.hash || ''}`;
    window.history.replaceState({}, document.title, nextUrl);
  }, []);

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

  const startSalesforceOauth = async () => {
    const token = getToken();
    setConnectorPendingId('salesforce_insights');
    setMessage('');
    try {
      const next = encodeURIComponent('/account?tab=connectors');
      const response = await fetch(`${API_BASE}/api/connectors/salesforce/oauth/start?next=${next}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        credentials: 'include',
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data?.error || 'Unable to start Salesforce OAuth.');
      }
      if (!data?.auth_url) {
        throw new Error('Salesforce OAuth URL was not returned by the backend.');
      }
      window.location.href = data.auth_url;
    } catch (error) {
      setMessage(error.message || 'Unable to start Salesforce OAuth.');
    } finally {
      setConnectorPendingId('');
    }
  };

  const runSalesforcePipelinePreview = async () => {
    const token = getToken();
    setConnectorPendingId('salesforce_insights');
    setMessage('');
    try {
      const response = await fetch(`${API_BASE}/api/connectors/salesforce/pipeline/summary?days=90&limit=200`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        credentials: 'include',
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data?.error || 'Unable to load Salesforce pipeline summary.');
      }
      const summary = data?.summary || {};
      setMessage(
        `Salesforce pipeline: ${summary.opportunity_count || 0} opportunities, `
        + `$${Number(summary.total_amount || 0).toLocaleString()} total amount.`
      );
      refreshConnectors();
    } catch (error) {
      setMessage(error.message || 'Unable to load Salesforce pipeline summary.');
    } finally {
      setConnectorPendingId('');
    }
  };

  const runSnowflakeQueryCheck = async (draft) => {
    const token = getToken();
    setConnectorPendingId('snowflake_insights');
    setMessage('');
    try {
      const firstTable = String(draft?.snowflake_table_allowlist || '')
        .split(',')
        .map((item) => item.trim())
        .find(Boolean);
      if (!firstTable) {
        throw new Error('Add at least one Snowflake table in the allowlist before testing.');
      }
      const response = await fetch(`${API_BASE}/api/connectors/snowflake/query`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        credentials: 'include',
        body: JSON.stringify({
          table: firstTable,
          limit: 5,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data?.error || 'Unable to run Snowflake test query.');
      }
      const rowCount = Array.isArray(data?.rows) ? data.rows.length : 0;
      setMessage(`Snowflake test query returned ${rowCount} row(s) from ${firstTable}.`);
      refreshConnectors();
    } catch (error) {
      setMessage(error.message || 'Unable to run Snowflake test query.');
    } finally {
      setConnectorPendingId('');
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
    } else if (connector.id === 'workfront_sync') {
      payload.workfront_base_url = String(draft.workfront_base_url || '').trim();
      payload.workfront_project_id = String(draft.workfront_project_id || '').trim();
      if (String(draft.workfront_api_token || '').trim()) {
        payload.workfront_api_token = String(draft.workfront_api_token || '').trim();
      }
    } else if (connector.id === 'smartsheet_sync') {
      payload.smartsheet_base_url = String(draft.smartsheet_base_url || DEFAULT_SMARTSHEET_BASE_URL).trim();
      payload.smartsheet_sheet_id = String(draft.smartsheet_sheet_id || '').trim();
      if (String(draft.smartsheet_api_token || '').trim()) {
        payload.smartsheet_api_token = String(draft.smartsheet_api_token || '').trim();
      }
    } else if (connector.id === 'salesforce_insights') {
      payload.salesforce_auth_base_url = String(draft.salesforce_auth_base_url || '').trim();
      payload.salesforce_instance_url = String(draft.salesforce_instance_url || '').trim();
      payload.salesforce_client_id = String(draft.salesforce_client_id || '').trim();
      if (String(draft.salesforce_client_secret || '').trim()) {
        payload.salesforce_client_secret = String(draft.salesforce_client_secret || '').trim();
      }
      if (String(draft.salesforce_refresh_token || '').trim()) {
        payload.salesforce_refresh_token = String(draft.salesforce_refresh_token || '').trim();
      }
    } else if (connector.id === 'snowflake_insights') {
      payload.snowflake_account = String(draft.snowflake_account || '').trim();
      payload.snowflake_warehouse = String(draft.snowflake_warehouse || '').trim();
      payload.snowflake_database = String(draft.snowflake_database || '').trim();
      payload.snowflake_schema = String(draft.snowflake_schema || '').trim();
      payload.snowflake_role = String(draft.snowflake_role || '').trim();
      payload.snowflake_user = String(draft.snowflake_user || '').trim();
      if (String(draft.snowflake_password || '').trim()) {
        payload.snowflake_password = String(draft.snowflake_password || '').trim();
      }
      if (String(draft.snowflake_private_key || '').trim()) {
        payload.snowflake_private_key = String(draft.snowflake_private_key || '').trim();
      }
      payload.snowflake_table_allowlist = String(draft.snowflake_table_allowlist || '')
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean);
    } else if (connector.id === 'oracle_fusion_insights') {
      payload.oracle_fusion_base_url = String(draft.oracle_fusion_base_url || '').trim();
      payload.oracle_fusion_username = String(draft.oracle_fusion_username || '').trim();
      payload.oracle_fusion_business_unit = String(draft.oracle_fusion_business_unit || '').trim();
      if (String(draft.oracle_fusion_password || '').trim()) {
        payload.oracle_fusion_password = String(draft.oracle_fusion_password || '').trim();
      }
    } else if (connector.id === 'servicenow_insights') {
      payload.servicenow_instance_url = String(draft.servicenow_instance_url || '').trim();
      payload.servicenow_username = String(draft.servicenow_username || '').trim();
      if (String(draft.servicenow_password || '').trim()) {
        payload.servicenow_password = String(draft.servicenow_password || '').trim();
      }
      payload.servicenow_table_allowlist = String(draft.servicenow_table_allowlist || '')
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean);
    } else if (connector.id === 'netsuite_insights') {
      payload.netsuite_account_id = String(draft.netsuite_account_id || '').trim();
      payload.netsuite_consumer_key = String(draft.netsuite_consumer_key || '').trim();
      payload.netsuite_token_id = String(draft.netsuite_token_id || '').trim();
      payload.netsuite_rest_base_url = String(draft.netsuite_rest_base_url || '').trim();
      if (String(draft.netsuite_consumer_secret || '').trim()) {
        payload.netsuite_consumer_secret = String(draft.netsuite_consumer_secret || '').trim();
      }
      if (String(draft.netsuite_token_secret || '').trim()) {
        payload.netsuite_token_secret = String(draft.netsuite_token_secret || '').trim();
      }
    }
    return updateConnector(connector.id, payload);
  };

  const handleConnectorToggle = async (connector, checked) => {
    if (!connector?.id) return;
    const baseDraft = connectorDrafts[connector.id] || buildConnectorDraft(connector);

    if (checked && connectorUsesApiModal(connector.id)) {
      openJiraConfigModal(connector, {
        intentEnable: true,
        revertStatus: baseDraft.connection_status,
      });
      return;
    }

    const nextDraft = {
      ...baseDraft,
      connection_status: checked ? 'connected' : 'disconnected',
    };
    updateConnectorDraft(connector.id, nextDraft);
    await saveConnectorDraft(connector, nextDraft);
  };

  const openJiraConfigModal = (connector, options = {}) => {
    if (!connector?.id || !connectorUsesApiModal(connector.id)) return;
    const baseDraft = connectorDrafts[connector.id] || buildConnectorDraft(connector);
    const intentEnable = Boolean(options?.intentEnable);
    const revertStatus = options?.revertStatus || baseDraft.connection_status || 'disconnected';
    const nextStatus = intentEnable ? 'connected' : (baseDraft.connection_status || 'disconnected');
    const baseData = emptyJiraModalState().data;
    const modalData = {};
    const storedFlags = {};

    if (connector.id === 'jira_sync') {
      storedFlags.jira_api_token = Boolean(connector?.jira?.has_api_token);
      modalData.jira_base_url = String(baseDraft.jira_base_url || connector?.jira?.base_url || '');
      modalData.jira_project_key = String(baseDraft.jira_project_key || connector?.jira?.project_key || '');
      modalData.jira_email = String(baseDraft.jira_email || connector?.jira?.email || '');
      modalData.jira_api_token = '';
      modalData.jira_issue_type = String(baseDraft.jira_issue_type || connector?.jira?.issue_type || DEFAULT_JIRA_ISSUE_TYPE);
    } else if (connector.id === 'workfront_sync') {
      storedFlags.workfront_api_token = Boolean(connector?.workfront?.has_api_token);
      modalData.workfront_base_url = String(baseDraft.workfront_base_url || connector?.workfront?.base_url || '');
      modalData.workfront_project_id = String(baseDraft.workfront_project_id || connector?.workfront?.project_id || '');
      modalData.workfront_api_token = '';
    } else if (connector.id === 'smartsheet_sync') {
      storedFlags.smartsheet_api_token = Boolean(connector?.smartsheet?.has_api_token);
      modalData.smartsheet_base_url = String(baseDraft.smartsheet_base_url || connector?.smartsheet?.base_url || DEFAULT_SMARTSHEET_BASE_URL);
      modalData.smartsheet_sheet_id = String(baseDraft.smartsheet_sheet_id || connector?.smartsheet?.sheet_id || '');
      modalData.smartsheet_api_token = '';
    } else if (connector.id === 'salesforce_insights') {
      storedFlags.salesforce_client_secret = Boolean(connector?.salesforce?.has_client_secret);
      storedFlags.salesforce_refresh_token = Boolean(connector?.salesforce?.has_refresh_token);
      modalData.salesforce_auth_base_url = String(baseDraft.salesforce_auth_base_url || connector?.salesforce?.auth_base_url || '');
      modalData.salesforce_instance_url = String(baseDraft.salesforce_instance_url || connector?.salesforce?.instance_url || '');
      modalData.salesforce_client_id = String(baseDraft.salesforce_client_id || connector?.salesforce?.client_id || '');
      modalData.salesforce_client_secret = '';
      modalData.salesforce_refresh_token = '';
    } else if (connector.id === 'snowflake_insights') {
      storedFlags.snowflake_password = Boolean(connector?.snowflake?.has_password);
      storedFlags.snowflake_private_key = Boolean(connector?.snowflake?.has_private_key);
      modalData.snowflake_account = String(baseDraft.snowflake_account || connector?.snowflake?.account || '');
      modalData.snowflake_warehouse = String(baseDraft.snowflake_warehouse || connector?.snowflake?.warehouse || '');
      modalData.snowflake_database = String(baseDraft.snowflake_database || connector?.snowflake?.database || '');
      modalData.snowflake_schema = String(baseDraft.snowflake_schema || connector?.snowflake?.schema || '');
      modalData.snowflake_role = String(baseDraft.snowflake_role || connector?.snowflake?.role || '');
      modalData.snowflake_user = String(baseDraft.snowflake_user || connector?.snowflake?.user || '');
      modalData.snowflake_password = '';
      modalData.snowflake_private_key = '';
      modalData.snowflake_table_allowlist = String(baseDraft.snowflake_table_allowlist || '');
    } else if (connector.id === 'oracle_fusion_insights') {
      storedFlags.oracle_fusion_password = Boolean(connector?.oracle_fusion?.has_password);
      modalData.oracle_fusion_base_url = String(baseDraft.oracle_fusion_base_url || connector?.oracle_fusion?.base_url || DEFAULT_ORACLE_FUSION_BASE_URL);
      modalData.oracle_fusion_username = String(baseDraft.oracle_fusion_username || connector?.oracle_fusion?.username || '');
      modalData.oracle_fusion_password = '';
      modalData.oracle_fusion_business_unit = String(baseDraft.oracle_fusion_business_unit || connector?.oracle_fusion?.business_unit || '');
    } else if (connector.id === 'servicenow_insights') {
      storedFlags.servicenow_password = Boolean(connector?.servicenow?.has_password);
      modalData.servicenow_instance_url = String(baseDraft.servicenow_instance_url || connector?.servicenow?.instance_url || DEFAULT_SERVICENOW_INSTANCE_URL);
      modalData.servicenow_username = String(baseDraft.servicenow_username || connector?.servicenow?.username || '');
      modalData.servicenow_password = '';
      modalData.servicenow_table_allowlist = String(baseDraft.servicenow_table_allowlist || '');
    } else if (connector.id === 'netsuite_insights') {
      storedFlags.netsuite_consumer_secret = Boolean(connector?.netsuite?.has_consumer_secret);
      storedFlags.netsuite_token_secret = Boolean(connector?.netsuite?.has_token_secret);
      modalData.netsuite_account_id = String(baseDraft.netsuite_account_id || connector?.netsuite?.account_id || '');
      modalData.netsuite_consumer_key = String(baseDraft.netsuite_consumer_key || connector?.netsuite?.consumer_key || '');
      modalData.netsuite_consumer_secret = '';
      modalData.netsuite_token_id = String(baseDraft.netsuite_token_id || connector?.netsuite?.token_id || '');
      modalData.netsuite_token_secret = '';
      modalData.netsuite_rest_base_url = String(baseDraft.netsuite_rest_base_url || connector?.netsuite?.rest_base_url || DEFAULT_NETSUITE_REST_BASE_URL);
    }

    updateConnectorDraft(connector.id, { connection_status: nextStatus });
    setJiraConfigError('');
    setJiraConfigSaving(false);
    setJiraConfigModal({
      open: true,
      connectorId: connector.id,
      intentEnable,
      revertStatus,
      hasStoredToken: Object.values(storedFlags).some(Boolean),
      storedFlags,
      data: { ...baseData, ...modalData },
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
    const connectorLabel = connectorApiLabel(modal.connectorId);
    if (!connector) {
      setJiraConfigError(`Unable to locate ${connectorLabel} connector state.`);
      return;
    }
    const nextDraft = {
      ...(connectorDrafts[connector.id] || buildConnectorDraft(connector)),
      connection_status: modal.intentEnable ? 'connected' : (connectorDrafts[connector.id]?.connection_status || 'disconnected'),
    };

    if (modal.connectorId === 'jira_sync') {
      const trimmed = {
        jira_base_url: String(modal.data.jira_base_url || '').trim(),
        jira_project_key: String(modal.data.jira_project_key || '').trim(),
        jira_email: String(modal.data.jira_email || '').trim(),
        jira_api_token: String(modal.data.jira_api_token || '').trim(),
        jira_issue_type: String(modal.data.jira_issue_type || DEFAULT_JIRA_ISSUE_TYPE).trim() || DEFAULT_JIRA_ISSUE_TYPE,
      };
      const tokenAvailable = Boolean(modal.storedFlags?.jira_api_token) || Boolean(trimmed.jira_api_token);
      if (!trimmed.jira_base_url || !trimmed.jira_project_key || !trimmed.jira_email) {
        setJiraConfigError('Jira URL, project key, and Jira email are required.');
        return;
      }
      if (!tokenAvailable) {
        setJiraConfigError('Jira API token is required before enabling Jira sync.');
        return;
      }
      nextDraft.jira_base_url = trimmed.jira_base_url;
      nextDraft.jira_project_key = trimmed.jira_project_key;
      nextDraft.jira_email = trimmed.jira_email;
      nextDraft.jira_issue_type = trimmed.jira_issue_type;
      nextDraft.external_workspace = trimmed.jira_project_key;
      if (trimmed.jira_api_token) nextDraft.jira_api_token = trimmed.jira_api_token;
    } else if (modal.connectorId === 'workfront_sync') {
      const trimmed = {
        workfront_base_url: String(modal.data.workfront_base_url || '').trim(),
        workfront_project_id: String(modal.data.workfront_project_id || '').trim(),
        workfront_api_token: String(modal.data.workfront_api_token || '').trim(),
      };
      const tokenAvailable = Boolean(modal.storedFlags?.workfront_api_token) || Boolean(trimmed.workfront_api_token);
      if (!trimmed.workfront_base_url || !trimmed.workfront_project_id) {
        setJiraConfigError('Workfront URL and project id are required.');
        return;
      }
      if (!tokenAvailable) {
        setJiraConfigError('Workfront API token is required before enabling Workfront sync.');
        return;
      }
      nextDraft.workfront_base_url = trimmed.workfront_base_url;
      nextDraft.workfront_project_id = trimmed.workfront_project_id;
      nextDraft.external_workspace = trimmed.workfront_project_id;
      if (trimmed.workfront_api_token) nextDraft.workfront_api_token = trimmed.workfront_api_token;
    } else if (modal.connectorId === 'smartsheet_sync') {
      const trimmed = {
        smartsheet_base_url: String(modal.data.smartsheet_base_url || DEFAULT_SMARTSHEET_BASE_URL).trim(),
        smartsheet_sheet_id: String(modal.data.smartsheet_sheet_id || '').trim(),
        smartsheet_api_token: String(modal.data.smartsheet_api_token || '').trim(),
      };
      const tokenAvailable = Boolean(modal.storedFlags?.smartsheet_api_token) || Boolean(trimmed.smartsheet_api_token);
      if (!trimmed.smartsheet_base_url || !trimmed.smartsheet_sheet_id) {
        setJiraConfigError('Smartsheet URL and sheet id are required.');
        return;
      }
      if (!tokenAvailable) {
        setJiraConfigError('Smartsheet API token is required before enabling Smartsheet sync.');
        return;
      }
      nextDraft.smartsheet_base_url = trimmed.smartsheet_base_url;
      nextDraft.smartsheet_sheet_id = trimmed.smartsheet_sheet_id;
      nextDraft.external_workspace = trimmed.smartsheet_sheet_id;
      if (trimmed.smartsheet_api_token) nextDraft.smartsheet_api_token = trimmed.smartsheet_api_token;
    } else if (modal.connectorId === 'salesforce_insights') {
      const trimmed = {
        salesforce_auth_base_url: String(modal.data.salesforce_auth_base_url || '').trim(),
        salesforce_instance_url: String(modal.data.salesforce_instance_url || '').trim(),
        salesforce_client_id: String(modal.data.salesforce_client_id || '').trim(),
        salesforce_client_secret: String(modal.data.salesforce_client_secret || '').trim(),
        salesforce_refresh_token: String(modal.data.salesforce_refresh_token || '').trim(),
      };
      const hasSecret = Boolean(modal.storedFlags?.salesforce_client_secret) || Boolean(trimmed.salesforce_client_secret);
      const hasRefresh = Boolean(modal.storedFlags?.salesforce_refresh_token) || Boolean(trimmed.salesforce_refresh_token);
      if (!trimmed.salesforce_auth_base_url || !trimmed.salesforce_instance_url || !trimmed.salesforce_client_id) {
        setJiraConfigError('Salesforce auth base URL, instance URL, and client id are required.');
        return;
      }
      if (!hasSecret || !hasRefresh) {
        setJiraConfigError('Salesforce client secret and refresh token are required before enabling.');
        return;
      }
      nextDraft.salesforce_auth_base_url = trimmed.salesforce_auth_base_url;
      nextDraft.salesforce_instance_url = trimmed.salesforce_instance_url;
      nextDraft.salesforce_client_id = trimmed.salesforce_client_id;
      if (trimmed.salesforce_client_secret) nextDraft.salesforce_client_secret = trimmed.salesforce_client_secret;
      if (trimmed.salesforce_refresh_token) nextDraft.salesforce_refresh_token = trimmed.salesforce_refresh_token;
      nextDraft.external_workspace = trimmed.salesforce_instance_url;
    } else if (modal.connectorId === 'snowflake_insights') {
      const trimmed = {
        snowflake_account: String(modal.data.snowflake_account || '').trim(),
        snowflake_warehouse: String(modal.data.snowflake_warehouse || '').trim(),
        snowflake_database: String(modal.data.snowflake_database || '').trim(),
        snowflake_schema: String(modal.data.snowflake_schema || '').trim(),
        snowflake_role: String(modal.data.snowflake_role || '').trim(),
        snowflake_user: String(modal.data.snowflake_user || '').trim(),
        snowflake_password: String(modal.data.snowflake_password || '').trim(),
        snowflake_private_key: String(modal.data.snowflake_private_key || '').trim(),
        snowflake_table_allowlist: String(modal.data.snowflake_table_allowlist || '').trim(),
      };
      const hasPassword = Boolean(modal.storedFlags?.snowflake_password) || Boolean(trimmed.snowflake_password);
      const hasPrivateKey = Boolean(modal.storedFlags?.snowflake_private_key) || Boolean(trimmed.snowflake_private_key);
      if (!trimmed.snowflake_account || !trimmed.snowflake_warehouse || !trimmed.snowflake_database || !trimmed.snowflake_schema || !trimmed.snowflake_user) {
        setJiraConfigError('Snowflake account, warehouse, database, schema, and user are required.');
        return;
      }
      if (!hasPassword && !hasPrivateKey) {
        setJiraConfigError('Snowflake password or private key is required before enabling.');
        return;
      }
      nextDraft.snowflake_account = trimmed.snowflake_account;
      nextDraft.snowflake_warehouse = trimmed.snowflake_warehouse;
      nextDraft.snowflake_database = trimmed.snowflake_database;
      nextDraft.snowflake_schema = trimmed.snowflake_schema;
      nextDraft.snowflake_role = trimmed.snowflake_role;
      nextDraft.snowflake_user = trimmed.snowflake_user;
      nextDraft.snowflake_table_allowlist = trimmed.snowflake_table_allowlist;
      if (trimmed.snowflake_password) nextDraft.snowflake_password = trimmed.snowflake_password;
      if (trimmed.snowflake_private_key) nextDraft.snowflake_private_key = trimmed.snowflake_private_key;
      nextDraft.external_workspace = trimmed.snowflake_database;
    } else if (modal.connectorId === 'oracle_fusion_insights') {
      const trimmed = {
        oracle_fusion_base_url: String(modal.data.oracle_fusion_base_url || '').trim(),
        oracle_fusion_username: String(modal.data.oracle_fusion_username || '').trim(),
        oracle_fusion_password: String(modal.data.oracle_fusion_password || '').trim(),
        oracle_fusion_business_unit: String(modal.data.oracle_fusion_business_unit || '').trim(),
      };
      const hasPassword = Boolean(modal.storedFlags?.oracle_fusion_password) || Boolean(trimmed.oracle_fusion_password);
      if (!trimmed.oracle_fusion_base_url || !trimmed.oracle_fusion_username) {
        setJiraConfigError('Oracle Fusion URL and username are required.');
        return;
      }
      if (!hasPassword) {
        setJiraConfigError('Oracle Fusion password is required before enabling.');
        return;
      }
      nextDraft.oracle_fusion_base_url = trimmed.oracle_fusion_base_url;
      nextDraft.oracle_fusion_username = trimmed.oracle_fusion_username;
      nextDraft.oracle_fusion_business_unit = trimmed.oracle_fusion_business_unit;
      if (trimmed.oracle_fusion_password) nextDraft.oracle_fusion_password = trimmed.oracle_fusion_password;
      nextDraft.external_workspace = trimmed.oracle_fusion_business_unit || trimmed.oracle_fusion_base_url;
    } else if (modal.connectorId === 'servicenow_insights') {
      const trimmed = {
        servicenow_instance_url: String(modal.data.servicenow_instance_url || '').trim(),
        servicenow_username: String(modal.data.servicenow_username || '').trim(),
        servicenow_password: String(modal.data.servicenow_password || '').trim(),
        servicenow_table_allowlist: String(modal.data.servicenow_table_allowlist || '').trim(),
      };
      const hasPassword = Boolean(modal.storedFlags?.servicenow_password) || Boolean(trimmed.servicenow_password);
      if (!trimmed.servicenow_instance_url || !trimmed.servicenow_username) {
        setJiraConfigError('ServiceNow instance URL and username are required.');
        return;
      }
      if (!hasPassword) {
        setJiraConfigError('ServiceNow password is required before enabling.');
        return;
      }
      nextDraft.servicenow_instance_url = trimmed.servicenow_instance_url;
      nextDraft.servicenow_username = trimmed.servicenow_username;
      nextDraft.servicenow_table_allowlist = trimmed.servicenow_table_allowlist;
      if (trimmed.servicenow_password) nextDraft.servicenow_password = trimmed.servicenow_password;
      nextDraft.external_workspace = trimmed.servicenow_instance_url;
    } else if (modal.connectorId === 'netsuite_insights') {
      const trimmed = {
        netsuite_account_id: String(modal.data.netsuite_account_id || '').trim(),
        netsuite_consumer_key: String(modal.data.netsuite_consumer_key || '').trim(),
        netsuite_consumer_secret: String(modal.data.netsuite_consumer_secret || '').trim(),
        netsuite_token_id: String(modal.data.netsuite_token_id || '').trim(),
        netsuite_token_secret: String(modal.data.netsuite_token_secret || '').trim(),
        netsuite_rest_base_url: String(modal.data.netsuite_rest_base_url || '').trim(),
      };
      const hasConsumerSecret = Boolean(modal.storedFlags?.netsuite_consumer_secret) || Boolean(trimmed.netsuite_consumer_secret);
      const hasTokenSecret = Boolean(modal.storedFlags?.netsuite_token_secret) || Boolean(trimmed.netsuite_token_secret);
      if (!trimmed.netsuite_account_id || !trimmed.netsuite_consumer_key || !trimmed.netsuite_token_id) {
        setJiraConfigError('NetSuite account id, consumer key, and token id are required.');
        return;
      }
      if (!hasConsumerSecret || !hasTokenSecret) {
        setJiraConfigError('NetSuite consumer secret and token secret are required before enabling.');
        return;
      }
      nextDraft.netsuite_account_id = trimmed.netsuite_account_id;
      nextDraft.netsuite_consumer_key = trimmed.netsuite_consumer_key;
      nextDraft.netsuite_token_id = trimmed.netsuite_token_id;
      nextDraft.netsuite_rest_base_url = trimmed.netsuite_rest_base_url || DEFAULT_NETSUITE_REST_BASE_URL;
      if (trimmed.netsuite_consumer_secret) nextDraft.netsuite_consumer_secret = trimmed.netsuite_consumer_secret;
      if (trimmed.netsuite_token_secret) nextDraft.netsuite_token_secret = trimmed.netsuite_token_secret;
      nextDraft.external_workspace = trimmed.netsuite_account_id;
    } else {
      setJiraConfigError('Unsupported connector for modal settings.');
      return;
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
  const modalConnectorLabel = connectorApiLabel(jiraConfigModal.connectorId);
  const isJiraModal = jiraConfigModal.connectorId === 'jira_sync';
  const isWorkfrontModal = jiraConfigModal.connectorId === 'workfront_sync';
  const isSmartsheetModal = jiraConfigModal.connectorId === 'smartsheet_sync';
  const isSalesforceModal = jiraConfigModal.connectorId === 'salesforce_insights';
  const isSnowflakeModal = jiraConfigModal.connectorId === 'snowflake_insights';
  const isOracleFusionModal = jiraConfigModal.connectorId === 'oracle_fusion_insights';
  const isServiceNowModal = jiraConfigModal.connectorId === 'servicenow_insights';
  const isNetSuiteModal = jiraConfigModal.connectorId === 'netsuite_insights';
  const modalSaveLabel = jiraConfigModal.intentEnable
    ? `Save & enable ${modalConnectorLabel}`
    : `Save ${modalConnectorLabel} settings`;

  return (
    <div className="account-page">
      <div className="account-panel">
        <div className={`account-content-layout ${sidebarCollapsed ? 'is-sidebar-collapsed' : ''}`}>
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
                <FontAwesomeIcon icon={sidebarCollapsed ? faBars : faTimes} />
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
            {!sidebarCollapsed && (
              <div className="account-sidebar-footer">
                <section className="account-sidebar-footer-group">
                  <p className="account-sidebar-footer-label">Account usage (this month)</p>
                  <p className="account-sidebar-footer-value">
                    {status?.monthly_credit_limit == null
                      ? 'Contracted pooled credits'
                      : `${Number(status.monthly_credit_limit || 0).toLocaleString()} credit limit`}
                  </p>
                </section>
                <section className="account-sidebar-footer-group">
                  <p className="account-sidebar-footer-label">Current thread usage</p>
                  <p className="account-sidebar-footer-value">Open a thread to see usage details.</p>
                </section>
              </div>
            )}
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
          <h2 className="account-tab-title">Connectors</h2>
          <p className="account-connectors-subtext">
            Connector setup, sync mode, conflict policy, field mapping, health, and audit history have moved to the dedicated management page.
          </p>
          <div className="account-connectors-actions">
            <a className="account-primary-btn" href="/connectors-manage">
              Manage Connectors →
            </a>
            <button
              type="button"
              className="account-secondary-btn account-connectors-knowledge-link"
              onClick={() => window.open('/knowledge', '_blank', 'noopener,noreferrer')}
            >
              Open Knowledge
            </button>
          </div>
        </section>
        )}

        {jiraConfigModal.open && (
          <div className="account-jira-modal-backdrop" role="presentation" onClick={() => closeJiraConfigModal(true)}>
            <div
              className="account-jira-modal"
              role="dialog"
              aria-modal="true"
              aria-label={`${modalConnectorLabel} API settings`}
              onClick={(e) => e.stopPropagation()}
            >
              <div className="account-jira-modal-header">
                <h3>{modalConnectorLabel} API settings</h3>
                <button type="button" className="account-jira-modal-close" onClick={() => closeJiraConfigModal(true)} aria-label="Close">
                  ×
                </button>
              </div>
              <p className="account-jira-modal-subtext">
                {isJiraModal && 'Enter Jira credentials and mapping details, then save. Required: URL, project key, Jira email, API token.'}
                {isWorkfrontModal && 'Enter Workfront credentials and mapping details, then save. Required: URL, project id, API token.'}
                {isSmartsheetModal && 'Enter Smartsheet credentials and mapping details, then save. Required: URL, sheet id, API token.'}
                {isSalesforceModal && 'Enter Salesforce OAuth credentials and mapping details, then save. Required: auth base URL, instance URL, client id, client secret, refresh token.'}
                {isSnowflakeModal && 'Enter Snowflake account configuration, then save. Required: account, warehouse, database, schema, user, and password or private key.'}
                {isOracleFusionModal && 'Enter Oracle Fusion credentials and mapping details, then save. Required: base URL, username, password.'}
                {isServiceNowModal && 'Enter ServiceNow credentials and mapping details, then save. Required: instance URL, username, password.'}
                {isNetSuiteModal && 'Enter NetSuite token-based integration details, then save. Required: account id, consumer key/secret, token id/secret.'}
              </p>
              <div className="account-jira-modal-grid">
                {isJiraModal && (
                  <>
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
                        placeholder={jiraConfigModal.storedFlags?.jira_api_token ? 'Token exists. Enter to rotate token.' : 'Enter Jira API token'}
                        onChange={(e) => setJiraConfigModal((prev) => ({
                          ...prev,
                          data: { ...prev.data, jira_api_token: e.target.value },
                        }))}
                        disabled={jiraConfigSaving}
                      />
                    </label>
                  </>
                )}
                {isWorkfrontModal && (
                  <>
                    <label>
                      Workfront URL
                      <input
                        type="text"
                        value={jiraConfigModal.data.workfront_base_url}
                        placeholder={DEFAULT_WORKFRONT_BASE_URL}
                        onChange={(e) => setJiraConfigModal((prev) => ({
                          ...prev,
                          data: { ...prev.data, workfront_base_url: e.target.value },
                        }))}
                        disabled={jiraConfigSaving}
                      />
                    </label>
                    <label>
                      Project ID
                      <input
                        type="text"
                        value={jiraConfigModal.data.workfront_project_id}
                        placeholder="Project or portfolio id"
                        onChange={(e) => setJiraConfigModal((prev) => ({
                          ...prev,
                          data: { ...prev.data, workfront_project_id: e.target.value },
                        }))}
                        disabled={jiraConfigSaving}
                      />
                    </label>
                    <label className="account-jira-modal-token-field">
                      Workfront API token
                      <input
                        type="password"
                        value={jiraConfigModal.data.workfront_api_token}
                        placeholder={jiraConfigModal.storedFlags?.workfront_api_token ? 'Token exists. Enter to rotate token.' : 'Enter Workfront API token'}
                        onChange={(e) => setJiraConfigModal((prev) => ({
                          ...prev,
                          data: { ...prev.data, workfront_api_token: e.target.value },
                        }))}
                        disabled={jiraConfigSaving}
                      />
                    </label>
                  </>
                )}
                {isSmartsheetModal && (
                  <>
                    <label>
                      Smartsheet URL
                      <input
                        type="text"
                        value={jiraConfigModal.data.smartsheet_base_url}
                        placeholder={DEFAULT_SMARTSHEET_BASE_URL}
                        onChange={(e) => setJiraConfigModal((prev) => ({
                          ...prev,
                          data: { ...prev.data, smartsheet_base_url: e.target.value },
                        }))}
                        disabled={jiraConfigSaving}
                      />
                    </label>
                    <label>
                      Sheet ID
                      <input
                        type="text"
                        value={jiraConfigModal.data.smartsheet_sheet_id}
                        placeholder="Sheet id"
                        onChange={(e) => setJiraConfigModal((prev) => ({
                          ...prev,
                          data: { ...prev.data, smartsheet_sheet_id: e.target.value },
                        }))}
                        disabled={jiraConfigSaving}
                      />
                    </label>
                    <label className="account-jira-modal-token-field">
                      Smartsheet API token
                      <input
                        type="password"
                        value={jiraConfigModal.data.smartsheet_api_token}
                        placeholder={jiraConfigModal.storedFlags?.smartsheet_api_token ? 'Token exists. Enter to rotate token.' : 'Enter Smartsheet API token'}
                        onChange={(e) => setJiraConfigModal((prev) => ({
                          ...prev,
                          data: { ...prev.data, smartsheet_api_token: e.target.value },
                        }))}
                        disabled={jiraConfigSaving}
                      />
                    </label>
                  </>
                )}
                {isSalesforceModal && (
                  <>
                    <label>
                      Auth Base URL
                      <input
                        type="text"
                        value={jiraConfigModal.data.salesforce_auth_base_url}
                        placeholder="https://login.salesforce.com"
                        onChange={(e) => setJiraConfigModal((prev) => ({
                          ...prev,
                          data: { ...prev.data, salesforce_auth_base_url: e.target.value },
                        }))}
                        disabled={jiraConfigSaving}
                      />
                    </label>
                    <label>
                      Instance URL
                      <input
                        type="text"
                        value={jiraConfigModal.data.salesforce_instance_url}
                        placeholder="https://your-instance.salesforce.com"
                        onChange={(e) => setJiraConfigModal((prev) => ({
                          ...prev,
                          data: { ...prev.data, salesforce_instance_url: e.target.value },
                        }))}
                        disabled={jiraConfigSaving}
                      />
                    </label>
                    <label>
                      Client ID
                      <input
                        type="text"
                        value={jiraConfigModal.data.salesforce_client_id}
                        placeholder="Connected app client id"
                        onChange={(e) => setJiraConfigModal((prev) => ({
                          ...prev,
                          data: { ...prev.data, salesforce_client_id: e.target.value },
                        }))}
                        disabled={jiraConfigSaving}
                      />
                    </label>
                    <label className="account-jira-modal-token-field">
                      Client secret
                      <input
                        type="password"
                        value={jiraConfigModal.data.salesforce_client_secret}
                        placeholder={jiraConfigModal.storedFlags?.salesforce_client_secret ? 'Secret exists. Enter to rotate.' : 'Enter client secret'}
                        onChange={(e) => setJiraConfigModal((prev) => ({
                          ...prev,
                          data: { ...prev.data, salesforce_client_secret: e.target.value },
                        }))}
                        disabled={jiraConfigSaving}
                      />
                    </label>
                    <label className="account-jira-modal-token-field">
                      Refresh token
                      <input
                        type="password"
                        value={jiraConfigModal.data.salesforce_refresh_token}
                        placeholder={jiraConfigModal.storedFlags?.salesforce_refresh_token ? 'Token exists. Enter to rotate.' : 'Enter refresh token'}
                        onChange={(e) => setJiraConfigModal((prev) => ({
                          ...prev,
                          data: { ...prev.data, salesforce_refresh_token: e.target.value },
                        }))}
                        disabled={jiraConfigSaving}
                      />
                    </label>
                  </>
                )}
                {isSnowflakeModal && (
                  <>
                    <label>
                      Account
                      <input
                        type="text"
                        value={jiraConfigModal.data.snowflake_account}
                        placeholder="org-account.region.cloud"
                        onChange={(e) => setJiraConfigModal((prev) => ({
                          ...prev,
                          data: { ...prev.data, snowflake_account: e.target.value },
                        }))}
                        disabled={jiraConfigSaving}
                      />
                    </label>
                    <label>
                      Warehouse
                      <input
                        type="text"
                        value={jiraConfigModal.data.snowflake_warehouse}
                        placeholder="ANALYTICS_WH"
                        onChange={(e) => setJiraConfigModal((prev) => ({
                          ...prev,
                          data: { ...prev.data, snowflake_warehouse: e.target.value },
                        }))}
                        disabled={jiraConfigSaving}
                      />
                    </label>
                    <label>
                      Database
                      <input
                        type="text"
                        value={jiraConfigModal.data.snowflake_database}
                        placeholder="ANALYTICS"
                        onChange={(e) => setJiraConfigModal((prev) => ({
                          ...prev,
                          data: { ...prev.data, snowflake_database: e.target.value },
                        }))}
                        disabled={jiraConfigSaving}
                      />
                    </label>
                    <label>
                      Schema
                      <input
                        type="text"
                        value={jiraConfigModal.data.snowflake_schema}
                        placeholder="PUBLIC"
                        onChange={(e) => setJiraConfigModal((prev) => ({
                          ...prev,
                          data: { ...prev.data, snowflake_schema: e.target.value },
                        }))}
                        disabled={jiraConfigSaving}
                      />
                    </label>
                    <label>
                      Role
                      <input
                        type="text"
                        value={jiraConfigModal.data.snowflake_role}
                        placeholder="ANALYST_ROLE"
                        onChange={(e) => setJiraConfigModal((prev) => ({
                          ...prev,
                          data: { ...prev.data, snowflake_role: e.target.value },
                        }))}
                        disabled={jiraConfigSaving}
                      />
                    </label>
                    <label>
                      User
                      <input
                        type="text"
                        value={jiraConfigModal.data.snowflake_user}
                        placeholder="service_user"
                        onChange={(e) => setJiraConfigModal((prev) => ({
                          ...prev,
                          data: { ...prev.data, snowflake_user: e.target.value },
                        }))}
                        disabled={jiraConfigSaving}
                      />
                    </label>
                    <label className="account-jira-modal-token-field">
                      Password
                      <input
                        type="password"
                        value={jiraConfigModal.data.snowflake_password}
                        placeholder={jiraConfigModal.storedFlags?.snowflake_password ? 'Password exists. Enter to rotate.' : 'Optional if key is provided'}
                        onChange={(e) => setJiraConfigModal((prev) => ({
                          ...prev,
                          data: { ...prev.data, snowflake_password: e.target.value },
                        }))}
                        disabled={jiraConfigSaving}
                      />
                    </label>
                    <label className="account-jira-modal-token-field">
                      Private key
                      <input
                        type="password"
                        value={jiraConfigModal.data.snowflake_private_key}
                        placeholder={jiraConfigModal.storedFlags?.snowflake_private_key ? 'Key exists. Enter to rotate.' : 'Optional if password is provided'}
                        onChange={(e) => setJiraConfigModal((prev) => ({
                          ...prev,
                          data: { ...prev.data, snowflake_private_key: e.target.value },
                        }))}
                        disabled={jiraConfigSaving}
                      />
                    </label>
                    <label className="account-jira-modal-token-field">
                      Table allowlist
                      <input
                        type="text"
                        value={jiraConfigModal.data.snowflake_table_allowlist}
                        placeholder="schema.table_a, schema.table_b"
                        onChange={(e) => setJiraConfigModal((prev) => ({
                          ...prev,
                          data: { ...prev.data, snowflake_table_allowlist: e.target.value },
                        }))}
                        disabled={jiraConfigSaving}
                      />
                    </label>
                  </>
                )}
                {isOracleFusionModal && (
                  <>
                    <label>
                      Base URL
                      <input
                        type="text"
                        value={jiraConfigModal.data.oracle_fusion_base_url}
                        placeholder={DEFAULT_ORACLE_FUSION_BASE_URL}
                        onChange={(e) => setJiraConfigModal((prev) => ({
                          ...prev,
                          data: { ...prev.data, oracle_fusion_base_url: e.target.value },
                        }))}
                        disabled={jiraConfigSaving}
                      />
                    </label>
                    <label>
                      Username
                      <input
                        type="text"
                        value={jiraConfigModal.data.oracle_fusion_username}
                        placeholder="integration.user@company.com"
                        onChange={(e) => setJiraConfigModal((prev) => ({
                          ...prev,
                          data: { ...prev.data, oracle_fusion_username: e.target.value },
                        }))}
                        disabled={jiraConfigSaving}
                      />
                    </label>
                    <label className="account-jira-modal-token-field">
                      Password
                      <input
                        type="password"
                        value={jiraConfigModal.data.oracle_fusion_password}
                        placeholder={jiraConfigModal.storedFlags?.oracle_fusion_password ? 'Password exists. Enter to rotate.' : 'Enter password'}
                        onChange={(e) => setJiraConfigModal((prev) => ({
                          ...prev,
                          data: { ...prev.data, oracle_fusion_password: e.target.value },
                        }))}
                        disabled={jiraConfigSaving}
                      />
                    </label>
                    <label>
                      Business unit
                      <input
                        type="text"
                        value={jiraConfigModal.data.oracle_fusion_business_unit}
                        placeholder="US Operations"
                        onChange={(e) => setJiraConfigModal((prev) => ({
                          ...prev,
                          data: { ...prev.data, oracle_fusion_business_unit: e.target.value },
                        }))}
                        disabled={jiraConfigSaving}
                      />
                    </label>
                  </>
                )}
                {isServiceNowModal && (
                  <>
                    <label>
                      Instance URL
                      <input
                        type="text"
                        value={jiraConfigModal.data.servicenow_instance_url}
                        placeholder={DEFAULT_SERVICENOW_INSTANCE_URL}
                        onChange={(e) => setJiraConfigModal((prev) => ({
                          ...prev,
                          data: { ...prev.data, servicenow_instance_url: e.target.value },
                        }))}
                        disabled={jiraConfigSaving}
                      />
                    </label>
                    <label>
                      Username
                      <input
                        type="text"
                        value={jiraConfigModal.data.servicenow_username}
                        placeholder="integration.user"
                        onChange={(e) => setJiraConfigModal((prev) => ({
                          ...prev,
                          data: { ...prev.data, servicenow_username: e.target.value },
                        }))}
                        disabled={jiraConfigSaving}
                      />
                    </label>
                    <label className="account-jira-modal-token-field">
                      Password
                      <input
                        type="password"
                        value={jiraConfigModal.data.servicenow_password}
                        placeholder={jiraConfigModal.storedFlags?.servicenow_password ? 'Password exists. Enter to rotate.' : 'Enter password'}
                        onChange={(e) => setJiraConfigModal((prev) => ({
                          ...prev,
                          data: { ...prev.data, servicenow_password: e.target.value },
                        }))}
                        disabled={jiraConfigSaving}
                      />
                    </label>
                    <label className="account-jira-modal-token-field">
                      Table allowlist
                      <input
                        type="text"
                        value={jiraConfigModal.data.servicenow_table_allowlist}
                        placeholder="incident,change_request"
                        onChange={(e) => setJiraConfigModal((prev) => ({
                          ...prev,
                          data: { ...prev.data, servicenow_table_allowlist: e.target.value },
                        }))}
                        disabled={jiraConfigSaving}
                      />
                    </label>
                  </>
                )}
                {isNetSuiteModal && (
                  <>
                    <label>
                      Account ID
                      <input
                        type="text"
                        value={jiraConfigModal.data.netsuite_account_id}
                        placeholder="123456_SB1"
                        onChange={(e) => setJiraConfigModal((prev) => ({
                          ...prev,
                          data: { ...prev.data, netsuite_account_id: e.target.value },
                        }))}
                        disabled={jiraConfigSaving}
                      />
                    </label>
                    <label>
                      Consumer key
                      <input
                        type="text"
                        value={jiraConfigModal.data.netsuite_consumer_key}
                        placeholder="Integration consumer key"
                        onChange={(e) => setJiraConfigModal((prev) => ({
                          ...prev,
                          data: { ...prev.data, netsuite_consumer_key: e.target.value },
                        }))}
                        disabled={jiraConfigSaving}
                      />
                    </label>
                    <label className="account-jira-modal-token-field">
                      Consumer secret
                      <input
                        type="password"
                        value={jiraConfigModal.data.netsuite_consumer_secret}
                        placeholder={jiraConfigModal.storedFlags?.netsuite_consumer_secret ? 'Secret exists. Enter to rotate.' : 'Enter consumer secret'}
                        onChange={(e) => setJiraConfigModal((prev) => ({
                          ...prev,
                          data: { ...prev.data, netsuite_consumer_secret: e.target.value },
                        }))}
                        disabled={jiraConfigSaving}
                      />
                    </label>
                    <label>
                      Token ID
                      <input
                        type="text"
                        value={jiraConfigModal.data.netsuite_token_id}
                        placeholder="Token id"
                        onChange={(e) => setJiraConfigModal((prev) => ({
                          ...prev,
                          data: { ...prev.data, netsuite_token_id: e.target.value },
                        }))}
                        disabled={jiraConfigSaving}
                      />
                    </label>
                    <label className="account-jira-modal-token-field">
                      Token secret
                      <input
                        type="password"
                        value={jiraConfigModal.data.netsuite_token_secret}
                        placeholder={jiraConfigModal.storedFlags?.netsuite_token_secret ? 'Secret exists. Enter to rotate.' : 'Enter token secret'}
                        onChange={(e) => setJiraConfigModal((prev) => ({
                          ...prev,
                          data: { ...prev.data, netsuite_token_secret: e.target.value },
                        }))}
                        disabled={jiraConfigSaving}
                      />
                    </label>
                    <label>
                      REST base URL
                      <input
                        type="text"
                        value={jiraConfigModal.data.netsuite_rest_base_url}
                        placeholder={DEFAULT_NETSUITE_REST_BASE_URL}
                        onChange={(e) => setJiraConfigModal((prev) => ({
                          ...prev,
                          data: { ...prev.data, netsuite_rest_base_url: e.target.value },
                        }))}
                        disabled={jiraConfigSaving}
                      />
                    </label>
                  </>
                )}
              </div>
              {jiraConfigError && <p className="account-jira-modal-error">{jiraConfigError}</p>}
              <div className="account-jira-modal-actions">
                <button type="button" className="account-secondary-btn" onClick={() => closeJiraConfigModal(true)} disabled={jiraConfigSaving}>
                  Cancel
                </button>
                <button type="button" className="account-primary-btn" onClick={saveJiraConfigAndEnable} disabled={jiraConfigSaving}>
                  {jiraConfigSaving ? 'Saving...' : modalSaveLabel}
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
              <button
                type="button"
                className="account-primary-btn"
                onClick={() => window.open('/knowledge', '_blank', 'noopener,noreferrer')}
              >
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
