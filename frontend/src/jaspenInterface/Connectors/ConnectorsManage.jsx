import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faArrowRightArrowLeft,
  faFlask,
  faPlugCircleCheck,
  faRotate,
  faServer,
  faSitemap,
} from '@fortawesome/free-solid-svg-icons';
import { API_BASE } from '../../config/apiBase';
import { useAuth } from '../../shared/auth/AuthContext';
import { authFetch, buildAuthHeaders } from '../../shared/auth/http';
import ConfirmDialog from '../../shared/components/ConfirmDialog';
import FieldError from '../../shared/components/FieldError';
import SkeletonBlock from '../../shared/components/SkeletonLoader';
import { getPlanConnectors } from '../../shared/billing/planConnectors';
import { PLAN_ORDER, PLAN_RANK } from '../../shared/constants/appConstants';
import ConnectorMonitor from '../Monitoring/ConnectorMonitor';
import './ConnectorsManage.css';
import AppMenu from '../shared/AppMenu';

const CONNECTOR_ORDER = [
  'jira_sync',
  'workfront_sync',
  'smartsheet_sync',
  'salesforce_insights',
  'snowflake_insights',
  'oracle_fusion_insights',
  'servicenow_insights',
  'netsuite_insights',
];

const PLAN_CONNECTOR_IDS = {
  free: [],
  essential: ['salesforce_insights', 'snowflake_insights'],
  team: ['salesforce_insights', 'snowflake_insights', 'jira_sync', 'workfront_sync', 'smartsheet_sync'],
  enterprise: CONNECTOR_ORDER,
};
const EXECUTION_SYNC_CONNECTOR_IDS = ['jira_sync', 'workfront_sync', 'smartsheet_sync'];
const REQUIRED_FIELDS_BY_CONNECTOR = {
  jira_sync: ['jira_base_url', 'jira_project_key', 'jira_email', 'jira_api_token'],
  workfront_sync: ['workfront_base_url', 'workfront_project_id', 'workfront_api_token'],
  smartsheet_sync: ['smartsheet_base_url', 'smartsheet_sheet_id', 'smartsheet_api_token'],
  salesforce_insights: [
    'salesforce_auth_base_url',
    'salesforce_instance_url',
    'salesforce_client_id',
    'salesforce_client_secret',
  ],
  snowflake_insights: [
    'snowflake_account',
    'snowflake_warehouse',
    'snowflake_database',
    'snowflake_schema',
    'snowflake_role',
    'snowflake_user',
    // password or private_key — handled by special case in validateRequiredFields
  ],
  oracle_fusion_insights: ['oracle_fusion_base_url', 'oracle_fusion_username', 'oracle_fusion_password'],
  servicenow_insights: ['servicenow_instance_url', 'servicenow_username', 'servicenow_password'],
  netsuite_insights: [
    'netsuite_account_id',
    'netsuite_consumer_key',
    'netsuite_consumer_secret',
    'netsuite_token_id',
    'netsuite_token_secret',
  ],
};

function authHeaders(json = false, method = 'GET') {
  return buildAuthHeaders(json ? { 'Content-Type': 'application/json' } : {}, method);
}

function normalizePlanKey(planKey) {
  return String(planKey || '').trim().toLowerCase();
}

function highestPlanKey(...plans) {
  return plans
    .map((plan) => normalizePlanKey(plan))
    .filter((plan) => Object.prototype.hasOwnProperty.call(PLAN_RANK, plan))
    .sort((a, b) => PLAN_RANK[b] - PLAN_RANK[a])[0] || 'free';
}

function connectorIcon(connectorId) {
  if (connectorId === 'jira_sync' || connectorId === 'workfront_sync' || connectorId === 'smartsheet_sync') return faSitemap;
  if (connectorId === 'snowflake_insights') return faServer;
  if (connectorId === 'salesforce_insights') return faArrowRightArrowLeft;
  return faPlugCircleCheck;
}

function mapConnectors(items) {
  const map = new Map();
  (Array.isArray(items) ? items : []).forEach((item) => {
    map.set(item.id, item);
  });
  return CONNECTOR_ORDER.map((id) => map.get(id)).filter(Boolean);
}

function connectorIsImplemented(connector) {
  return String(connector?.implementation_status || 'implemented').trim().toLowerCase() === 'implemented';
}

function normalizeDraft(connector) {
  return {
    connection_status: connector?.connected ? 'connected' : 'disconnected',
    sync_mode: connector?.sync_mode || 'import',
    conflict_policy: connector?.conflict_policy || 'prefer_external',
    auto_sync: Boolean(connector?.auto_sync),
    external_workspace: String(connector?.external_workspace || ''),
    jira_base_url: String(connector?.jira?.base_url || ''),
    jira_project_key: String(connector?.jira?.project_key || ''),
    jira_email: String(connector?.jira?.email || ''),
    jira_issue_type: String(connector?.jira?.issue_type || 'Task'),
    jira_api_token: '',
    jira_field_mapping: JSON.stringify(connector?.jira?.field_mapping || {}, null, 2),
    workfront_base_url: String(connector?.workfront?.base_url || ''),
    workfront_project_id: String(connector?.workfront?.project_id || ''),
    workfront_api_token: '',
    workfront_field_mapping: JSON.stringify(connector?.workfront?.field_mapping || {}, null, 2),
    smartsheet_base_url: String(connector?.smartsheet?.base_url || 'https://api.smartsheet.com'),
    smartsheet_sheet_id: String(connector?.smartsheet?.sheet_id || ''),
    smartsheet_api_token: '',
    smartsheet_field_mapping: JSON.stringify(connector?.smartsheet?.field_mapping || {}, null, 2),
    salesforce_auth_base_url: String(connector?.salesforce?.auth_base_url || ''),
    salesforce_instance_url: String(connector?.salesforce?.instance_url || ''),
    salesforce_client_id: String(connector?.salesforce?.client_id || ''),
    salesforce_client_secret: '',
    salesforce_refresh_token: '',
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
    oracle_fusion_base_url: String(connector?.oracle_fusion?.base_url || ''),
    oracle_fusion_username: String(connector?.oracle_fusion?.username || ''),
    oracle_fusion_password: '',
    oracle_fusion_business_unit: String(connector?.oracle_fusion?.business_unit || ''),
    servicenow_instance_url: String(connector?.servicenow?.instance_url || ''),
    servicenow_username: String(connector?.servicenow?.username || ''),
    servicenow_password: '',
    servicenow_table_allowlist: Array.isArray(connector?.servicenow?.table_allowlist)
      ? connector.servicenow.table_allowlist.join(', ')
      : '',
    netsuite_account_id: String(connector?.netsuite?.account_id || ''),
    netsuite_consumer_key: String(connector?.netsuite?.consumer_key || ''),
    netsuite_consumer_secret: '',
    netsuite_token_id: String(connector?.netsuite?.token_id || ''),
    netsuite_token_secret: '',
    netsuite_rest_base_url: String(connector?.netsuite?.rest_base_url || ''),
  };
}

function parseObject(text) {
  try {
    const parsed = JSON.parse(String(text || '{}'));
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function parseList(text) {
  return String(text || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

function connectorDraftChanged(connector, draft) {
  if (!connector || !draft) return false;
  const base = normalizeDraft(connector);
  const fields = [
    'connection_status',
    'sync_mode',
    'conflict_policy',
    'auto_sync',
    'external_workspace',
    'jira_base_url',
    'jira_project_key',
    'jira_email',
    'jira_issue_type',
    'jira_field_mapping',
    'workfront_base_url',
    'workfront_project_id',
    'workfront_field_mapping',
    'smartsheet_base_url',
    'smartsheet_sheet_id',
    'smartsheet_field_mapping',
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
  const differs = fields.some((field) => String(base[field] ?? '') !== String(draft[field] ?? ''));
  const hasSecretUpdates = [
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
  ].some((field) => String(draft[field] || '').trim().length > 0);
  return differs || hasSecretUpdates;
}

function fieldLabel(text, required = false) {
  return (
    <>
      {text}
      {required && <span className="connector-required-marker" aria-hidden="true"> *</span>}
    </>
  );
}

function validateRequiredFields(connectorId, draft) {
  const requiredFields = REQUIRED_FIELDS_BY_CONNECTOR[connectorId] || [];
  const errors = {};
  requiredFields.forEach((field) => {
    if (!String(draft?.[field] || '').trim()) {
      errors[field] = 'Required field';
    }
  });
  if (connectorId === 'snowflake_insights') {
    const hasPassword = String(draft?.snowflake_password || '').trim();
    const hasPrivateKey = String(draft?.snowflake_private_key || '').trim();
    if (!hasPassword && !hasPrivateKey) {
      errors.snowflake_password = 'Password or private key is required';
      errors.snowflake_private_key = 'Password or private key is required';
    }
  }
  return errors;
}

function isMissingThreadSyncContextError(message) {
  const text = String(message || '').trim().toLowerCase();
  return text.includes('thread not found') || text.includes('no wbs found for thread');
}

function buildUpdatePayload(connectorId, draft) {
  const payload = {
    sync_mode: draft.sync_mode,
    conflict_policy: draft.conflict_policy,
    auto_sync: Boolean(draft.auto_sync),
    external_workspace: draft.external_workspace,
  };

  if (connectorId === 'jira_sync') {
    payload.jira_base_url = draft.jira_base_url;
    payload.jira_project_key = draft.jira_project_key;
    payload.jira_email = draft.jira_email;
    payload.jira_issue_type = draft.jira_issue_type;
    payload.jira_field_mapping = parseObject(draft.jira_field_mapping);
    if (String(draft.jira_api_token || '').trim()) payload.jira_api_token = draft.jira_api_token.trim();
  } else if (connectorId === 'workfront_sync') {
    payload.workfront_base_url = draft.workfront_base_url;
    payload.workfront_project_id = draft.workfront_project_id;
    payload.workfront_field_mapping = parseObject(draft.workfront_field_mapping);
    if (String(draft.workfront_api_token || '').trim()) payload.workfront_api_token = draft.workfront_api_token.trim();
  } else if (connectorId === 'smartsheet_sync') {
    payload.smartsheet_base_url = draft.smartsheet_base_url;
    payload.smartsheet_sheet_id = draft.smartsheet_sheet_id;
    payload.smartsheet_field_mapping = parseObject(draft.smartsheet_field_mapping);
    if (String(draft.smartsheet_api_token || '').trim()) payload.smartsheet_api_token = draft.smartsheet_api_token.trim();
  } else if (connectorId === 'salesforce_insights') {
    payload.salesforce_auth_base_url = draft.salesforce_auth_base_url;
    payload.salesforce_instance_url = draft.salesforce_instance_url;
    payload.salesforce_client_id = draft.salesforce_client_id;
    if (String(draft.salesforce_client_secret || '').trim()) payload.salesforce_client_secret = draft.salesforce_client_secret.trim();
    if (String(draft.salesforce_refresh_token || '').trim()) payload.salesforce_refresh_token = draft.salesforce_refresh_token.trim();
  } else if (connectorId === 'snowflake_insights') {
    payload.snowflake_account = draft.snowflake_account;
    payload.snowflake_warehouse = draft.snowflake_warehouse;
    payload.snowflake_database = draft.snowflake_database;
    payload.snowflake_schema = draft.snowflake_schema;
    payload.snowflake_role = draft.snowflake_role;
    payload.snowflake_user = draft.snowflake_user;
    payload.snowflake_table_allowlist = parseList(draft.snowflake_table_allowlist);
    if (String(draft.snowflake_password || '').trim()) payload.snowflake_password = draft.snowflake_password.trim();
    if (String(draft.snowflake_private_key || '').trim()) payload.snowflake_private_key = draft.snowflake_private_key.trim();
  } else if (connectorId === 'oracle_fusion_insights') {
    payload.oracle_fusion_base_url = draft.oracle_fusion_base_url;
    payload.oracle_fusion_username = draft.oracle_fusion_username;
    payload.oracle_fusion_business_unit = draft.oracle_fusion_business_unit;
    if (String(draft.oracle_fusion_password || '').trim()) payload.oracle_fusion_password = draft.oracle_fusion_password.trim();
  } else if (connectorId === 'servicenow_insights') {
    payload.servicenow_instance_url = draft.servicenow_instance_url;
    payload.servicenow_username = draft.servicenow_username;
    payload.servicenow_table_allowlist = parseList(draft.servicenow_table_allowlist);
    if (String(draft.servicenow_password || '').trim()) payload.servicenow_password = draft.servicenow_password.trim();
  } else if (connectorId === 'netsuite_insights') {
    payload.netsuite_account_id = draft.netsuite_account_id;
    payload.netsuite_consumer_key = draft.netsuite_consumer_key;
    payload.netsuite_token_id = draft.netsuite_token_id;
    payload.netsuite_rest_base_url = draft.netsuite_rest_base_url;
    if (String(draft.netsuite_consumer_secret || '').trim()) payload.netsuite_consumer_secret = draft.netsuite_consumer_secret.trim();
    if (String(draft.netsuite_token_secret || '').trim()) payload.netsuite_token_secret = draft.netsuite_token_secret.trim();
  }

  return payload;
}

export default function ConnectorsManage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { user } = useAuth();
  const [connectors, setConnectors] = useState([]);
  const [drafts, setDrafts] = useState({});
  const [selectedConnectorId, setSelectedConnectorId] = useState('');
  const [auditRows, setAuditRows] = useState([]);
  const [threads, setThreads] = useState([]);
  const [selectedThreadId, setSelectedThreadId] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [draftErrors, setDraftErrors] = useState({});
  const [discardDialog, setDiscardDialog] = useState(null);
  const [snowflakeProbeBusy, setSnowflakeProbeBusy] = useState(false);
  const [snowflakeProbeResult, setSnowflakeProbeResult] = useState(null);
  const [setupModeByConnector, setSetupModeByConnector] = useState({});

  const adminPreviewPlan = useMemo(() => {
    if (!Boolean(user?.is_admin)) return '';
    const params = new URLSearchParams(location.search);
    if (String(params.get('admin_preview') || '').trim().toLowerCase() !== 'workspace') return '';
    const planKey = normalizePlanKey(params.get('plan_key'));
    return PLAN_ORDER.includes(planKey) ? planKey : '';
  }, [location.search, user?.is_admin]);

  // Handle Salesforce OAuth callback result — backend redirects back here with ?sf_oauth=success|error
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const sfOauth = String(params.get('sf_oauth') || '').trim().toLowerCase();
    const reason = String(params.get('reason') || '').trim();
    if (!sfOauth) return;

    if (sfOauth === 'success') {
      setMessage('Salesforce connected successfully.');
      // Refresh connector list (with short retries) so badge flips reliably.
      waitForSalesforceConnected();
      // Auto-select Salesforce in the sidebar so user sees the updated status
      setSelectedConnectorId('salesforce_insights');
    } else {
      setError(`Salesforce connection failed${reason ? `: ${reason.replace(/_/g, ' ')}` : ''}. Check your credentials and try again.`);
    }

    // Clean the URL so refreshing doesn't re-trigger
    params.delete('sf_oauth');
    params.delete('reason');
    const cleanSearch = params.toString();
    navigate(
      `${location.pathname}${cleanSearch ? `?${cleanSearch}` : ''}`,
      { replace: true }
    );
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const effectivePlanKey = useMemo(() => (
    adminPreviewPlan || highestPlanKey(user?.active_organization_plan_key, user?.subscription_plan)
  ), [adminPreviewPlan, user?.active_organization_plan_key, user?.subscription_plan]);

  const allowedConnectorIds = useMemo(() => (
    PLAN_CONNECTOR_IDS[effectivePlanKey] || []
  ), [effectivePlanKey]);

  const planConnectorNames = useMemo(() => getPlanConnectors(effectivePlanKey), [effectivePlanKey]);
  const isFreePlan = effectivePlanKey === 'free';

  const loadConnectors = useCallback(async () => {
    const res = await authFetch(`${API_BASE}/api/v1/connectors/status`, {
      credentials: 'include',
      headers: authHeaders(false, 'GET'),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data?.error || `Failed to load connectors (${res.status})`);

    const ordered = mapConnectors(data?.connectors || []);
    setConnectors(ordered);
    setDrafts((prev) => {
      const next = { ...prev };
      ordered.forEach((item) => {
        next[item.id] = normalizeDraft(item);
      });
      return next;
    });
    if (!selectedConnectorId && ordered.length) {
      setSelectedConnectorId(ordered[0].id);
    }
  }, [selectedConnectorId]);

  const waitForSalesforceConnected = useCallback(async () => {
    const maxAttempts = 8;
    for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
      let connected = false;
      try {
        const res = await authFetch(`${API_BASE}/api/v1/connectors/status`, {
          credentials: 'include',
          headers: authHeaders(false, 'GET'),
        });
        const data = await res.json().catch(() => ({}));
        if (res.ok) {
          const ordered = mapConnectors(data?.connectors || []);
          setConnectors(ordered);
          setDrafts((prev) => {
            const next = { ...prev };
            ordered.forEach((item) => {
              next[item.id] = normalizeDraft(item);
            });
            return next;
          });
          connected = Boolean(ordered.find((item) => item.id === 'salesforce_insights')?.connected);
        }
      } catch {
        // best effort retries
      }
      if (connected) return true;
      // eslint-disable-next-line no-await-in-loop
      await new Promise((resolve) => setTimeout(resolve, 600));
    }
    return false;
  }, []);

  const loadThreads = useCallback(async () => {
    const res = await authFetch(`${API_BASE}/api/v1/ai-agent/threads`, {
      credentials: 'include',
      headers: authHeaders(false, 'GET'),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data?.success) {
      setThreads([]);
      return;
    }
    const rows = (Array.isArray(data.sessions) ? data.sessions : [])
      .map((item) => ({
        threadId: String(item?.session_id || '').trim(),
        name: String(item?.name || item?.result?.project_name || '').trim(),
      }))
      .filter((item) => item.threadId);
    setThreads(rows);
    if (!selectedThreadId && rows.length) {
      setSelectedThreadId(rows[0].threadId);
    }
  }, [selectedThreadId]);

  const loadAudit = useCallback(async (connectorId) => {
    if (!connectorId) {
      setAuditRows([]);
      return;
    }
    const res = await authFetch(`${API_BASE}/api/v1/connectors/${encodeURIComponent(connectorId)}/audit?limit=20`, {
      credentials: 'include',
      headers: authHeaders(false, 'GET'),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setAuditRows([]);
      return;
    }
    setAuditRows(Array.isArray(data?.events) ? data.events : []);
  }, []);

  const refresh = useCallback(async () => {
    if (isFreePlan) {
      setConnectors([]);
      setDrafts({});
      setAuditRows([]);
      setThreads([]);
      setSelectedConnectorId('');
      setLoading(false);
      setError('');
      return;
    }
    setLoading(true);
    setError('');
    try {
      await Promise.all([loadConnectors(), loadThreads()]);
    } catch (err) {
      setError(err?.message || 'Failed to load connector management data.');
    } finally {
      setLoading(false);
    }
  }, [isFreePlan, loadConnectors, loadThreads]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    loadAudit(selectedConnectorId);
  }, [loadAudit, selectedConnectorId]);

  const selectedConnector = useMemo(
    () => connectors.find((item) => item.id === selectedConnectorId && allowedConnectorIds.includes(item.id)) || null,
    [allowedConnectorIds, connectors, selectedConnectorId]
  );

  const visibleConnectors = useMemo(
    () => connectors.filter((item) => allowedConnectorIds.includes(item.id)),
    [allowedConnectorIds, connectors]
  );

  const selectedDraft = selectedConnector ? drafts[selectedConnector.id] || normalizeDraft(selectedConnector) : null;
  const selectedDraftErrors = selectedConnector ? draftErrors[selectedConnector.id] || {} : {};
  const selectedSetupMode = selectedConnector
    ? (setupModeByConnector[selectedConnector.id] || 'automatic')
    : 'automatic';
  const selectedConnectorImplemented = connectorIsImplemented(selectedConnector);
  const selectedConnectorDirty = useMemo(
    () => connectorDraftChanged(selectedConnector, selectedDraft),
    [selectedConnector, selectedDraft]
  );
  const hasUnsavedChanges = useMemo(
    () => connectors.some((connector) => connectorDraftChanged(connector, drafts[connector.id] || normalizeDraft(connector))),
    [connectors, drafts]
  );

  const guardUnsavedChanges = useCallback((onProceed, prompt = 'You have unsaved changes. Leave this page and discard them?') => {
    if (!hasUnsavedChanges) {
      onProceed?.();
      return;
    }
    setDiscardDialog({
      title: 'Discard unsaved changes?',
      message: prompt,
      confirmLabel: 'Discard changes',
      confirmVariant: 'danger',
      onConfirm: () => {
        setDiscardDialog(null);
        onProceed?.();
      },
    });
  }, [hasUnsavedChanges]);

  useEffect(() => {
    if (!visibleConnectors.length) {
      setSelectedConnectorId('');
      return;
    }
    if (!visibleConnectors.some((item) => item.id === selectedConnectorId)) {
      setSelectedConnectorId(visibleConnectors[0].id);
    }
  }, [selectedConnectorId, visibleConnectors]);

  useEffect(() => {
    const onBeforeUnload = (event) => {
      if (!hasUnsavedChanges) return;
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => window.removeEventListener('beforeunload', onBeforeUnload);
  }, [hasUnsavedChanges]);

  function updateDraft(field, value) {
    if (!selectedConnector) return;
    setDrafts((prev) => ({
      ...prev,
      [selectedConnector.id]: {
        ...(prev[selectedConnector.id] || normalizeDraft(selectedConnector)),
        [field]: value,
      },
    }));
    setDraftErrors((prev) => ({
      ...prev,
      [selectedConnector.id]: {
        ...(prev[selectedConnector.id] || {}),
        [field]: '',
      },
    }));
  }

  async function saveConnector() {
    if (!selectedConnector || !selectedDraft) return;
    const validationErrors = validateRequiredFields(selectedConnector.id, selectedDraft);
    if (Object.keys(validationErrors).length > 0) {
      setDraftErrors((prev) => ({
        ...prev,
        [selectedConnector.id]: validationErrors,
      }));
      setError('Please fix the highlighted required fields.');
      setMessage('');
      return;
    }
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const payload = {
        ...buildUpdatePayload(selectedConnector.id, selectedDraft),
        connection_status: 'connected',
      };
      const res = await authFetch(`${API_BASE}/api/v1/connectors/${encodeURIComponent(selectedConnector.id)}`, {
        method: 'PATCH',
        credentials: 'include',
        headers: authHeaders(true, 'PATCH'),
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.error || `Save failed (${res.status})`);

      setMessage(`${selectedConnector.label} saved.`);
      await loadConnectors();
      await loadAudit(selectedConnector.id);
    } catch (err) {
      setError(err?.message || 'Failed to save connector.');
    } finally {
      setBusy(false);
    }
  }

  function revertSelectedDraft() {
    if (!selectedConnector) return;
    setDrafts((prev) => ({
      ...prev,
      [selectedConnector.id]: normalizeDraft(selectedConnector),
    }));
    setMessage(`Reverted unsaved changes for ${selectedConnector.label}.`);
    setError('');
  }

  async function testConnection() {
    if (!selectedConnector) return;
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const res = await authFetch(`${API_BASE}/api/v1/connectors/${encodeURIComponent(selectedConnector.id)}/health`, {
        credentials: 'include',
        headers: authHeaders(false, 'GET'),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.error || `Test failed (${res.status})`);
      const live = data?.live_status;
      if (live) {
        if (live.status === 'error') {
          setError(`Connection failed: ${live.message || 'Unknown error'}`);
        } else {
          if (selectedConnector.id === 'snowflake_insights') {
            setMessage(`Connectivity test passed: ${live.message || live.status}. Next, run "Validate Data Access" to confirm table permissions.`);
          } else {
            setMessage(`Connection test passed: ${live.message || live.status}`);
          }
        }
      } else {
        const storedStatus = data?.health?.status || 'unknown';
        setMessage(`Health check complete: ${storedStatus}`);
      }
      await loadAudit(selectedConnector.id);
    } catch (err) {
      setError(err?.message || 'Health check failed.');
    } finally {
      setBusy(false);
    }
  }

  async function runSetupCheck() {
    if (!selectedConnector || !selectedDraft) return;
    const validationErrors = validateRequiredFields(selectedConnector.id, selectedDraft);
    if (Object.keys(validationErrors).length > 0) {
      setDraftErrors((prev) => ({
        ...prev,
        [selectedConnector.id]: validationErrors,
      }));
      setError('Please fix the highlighted required fields.');
      setMessage('');
      return;
    }

    setBusy(true);
    setSnowflakeProbeResult(null);
    setError('');
    setMessage('');

    try {
      const payload = {
        ...buildUpdatePayload(selectedConnector.id, selectedDraft),
        connection_status: 'connected',
      };
      const saveRes = await authFetch(`${API_BASE}/api/v1/connectors/${encodeURIComponent(selectedConnector.id)}`, {
        method: 'PATCH',
        credentials: 'include',
        headers: authHeaders(true, 'PATCH'),
        body: JSON.stringify(payload),
      });
      const saveData = await saveRes.json().catch(() => ({}));
      if (!saveRes.ok) throw new Error(saveData?.error || `Save failed (${saveRes.status})`);

      const healthRes = await authFetch(`${API_BASE}/api/v1/connectors/${encodeURIComponent(selectedConnector.id)}/health`, {
        credentials: 'include',
        headers: authHeaders(false, 'GET'),
      });
      const healthData = await healthRes.json().catch(() => ({}));
      if (!healthRes.ok) throw new Error(healthData?.error || `Connection test failed (${healthRes.status})`);

      if (selectedConnector.id === 'snowflake_insights') {
        const tables = parseList(selectedDraft.snowflake_table_allowlist).slice(0, 10);
        const results = [];
        for (const table of tables) {
          const response = await authFetch(`${API_BASE}/api/v1/connectors/snowflake/query`, {
            method: 'POST',
            credentials: 'include',
            headers: authHeaders(true, 'POST'),
            body: JSON.stringify({ table, limit: 1 }),
          });
          const data = await response.json().catch(() => ({}));
          if (!response.ok) {
            results.push({ table, ok: false, message: data?.error || `HTTP ${response.status}` });
          } else {
            results.push({
              table,
              ok: true,
              message: `Readable (${Array.isArray(data?.rows) ? data.rows.length : 0} row sampled)`,
            });
          }
        }
        const okCount = results.filter((row) => row.ok).length;
        const failCount = results.length - okCount;
        setSnowflakeProbeResult({
          checkedAt: Date.now(),
          rows: results,
          okCount,
          failCount,
        });
        if (failCount > 0) {
          throw new Error(`Snowflake validation failed for ${failCount}/${results.length} table(s).`);
        }
      }

      if (EXECUTION_SYNC_CONNECTOR_IDS.includes(selectedConnector.id)) {
        if (!selectedThreadId) {
          setMessage('Setup check passed for connector credentials. Select a sync thread with an execution plan (WBS) to validate push sync.');
          await loadConnectors();
          await loadAudit(selectedConnector.id);
          return;
        }

        let syncEndpoint = '';
        if (selectedConnector.id === 'jira_sync') {
          syncEndpoint = `${API_BASE}/api/v1/connectors/threads/${encodeURIComponent(selectedThreadId)}/jira/sync`;
        } else if (selectedConnector.id === 'workfront_sync') {
          syncEndpoint = `${API_BASE}/api/v1/connectors/threads/${encodeURIComponent(selectedThreadId)}/workfront/sync`;
        } else if (selectedConnector.id === 'smartsheet_sync') {
          syncEndpoint = `${API_BASE}/api/v1/connectors/threads/${encodeURIComponent(selectedThreadId)}/smartsheet/sync`;
        }

        const syncRes = await authFetch(syncEndpoint, {
          method: 'POST',
          credentials: 'include',
          headers: authHeaders(false, 'POST'),
        });
        const syncData = await syncRes.json().catch(() => ({}));
        if (!syncRes.ok) {
          const syncError = syncData?.error || `Sync failed (${syncRes.status})`;
          if (isMissingThreadSyncContextError(syncError)) {
            setMessage('Setup check passed for connector credentials. The selected sync thread is not available for WBS sync yet; select another thread or generate an execution plan first.');
            await loadConnectors();
            await loadAudit(selectedConnector.id);
            return;
          }
          throw new Error(syncError);
        }
      }

      await loadConnectors();
      await loadAudit(selectedConnector.id);
      setMessage('Setup check passed. Connector is ready to use.');
    } catch (err) {
      setError(err?.message || 'Setup check failed.');
    } finally {
      setBusy(false);
    }
  }

  async function validateSnowflakeDataAccess() {
    if (!selectedConnector || selectedConnector.id !== 'snowflake_insights' || !selectedDraft) return;
    const tables = parseList(selectedDraft.snowflake_table_allowlist).slice(0, 10);
    if (!tables.length) {
      setError('Add at least one table in Table Allowlist before running data validation.');
      return;
    }

    setSnowflakeProbeBusy(true);
    setError('');
    setMessage('');
    setSnowflakeProbeResult(null);
    try {
      const results = [];
      for (const table of tables) {
        const response = await authFetch(`${API_BASE}/api/v1/connectors/snowflake/query`, {
          method: 'POST',
          credentials: 'include',
          headers: authHeaders(true, 'POST'),
          body: JSON.stringify({ table, limit: 1 }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          results.push({
            table,
            ok: false,
            message: data?.error || `HTTP ${response.status}`,
          });
          continue;
        }
        results.push({
          table,
          ok: true,
          message: `Readable (${Array.isArray(data?.rows) ? data.rows.length : 0} row sampled)`,
        });
      }

      const okCount = results.filter((row) => row.ok).length;
      const failCount = results.length - okCount;
      setSnowflakeProbeResult({
        checkedAt: Date.now(),
        rows: results,
        okCount,
        failCount,
      });
      if (failCount === 0) {
        setMessage(`Snowflake data validation passed for ${okCount}/${results.length} allowlisted table(s).`);
      } else {
        setError(`Snowflake data validation failed for ${failCount}/${results.length} table(s). Review diagnostics below.`);
      }
    } catch (err) {
      setError(err?.message || 'Snowflake data validation failed.');
    } finally {
      setSnowflakeProbeBusy(false);
    }
  }

  async function syncNow() {
    if (!selectedConnector) return;
    setBusy(true);
    setError('');
    setMessage('');
    try {
      let endpoint = '';
      let method = 'POST';
      let body = null;

      if (selectedConnector.id === 'jira_sync') {
        if (!selectedThreadId) throw new Error('Select a thread for Jira sync.');
        endpoint = `${API_BASE}/api/v1/connectors/threads/${encodeURIComponent(selectedThreadId)}/jira/sync`;
      } else if (selectedConnector.id === 'workfront_sync') {
        if (!selectedThreadId) throw new Error('Select a thread for Workfront sync.');
        endpoint = `${API_BASE}/api/v1/connectors/threads/${encodeURIComponent(selectedThreadId)}/workfront/sync`;
      } else if (selectedConnector.id === 'smartsheet_sync') {
        if (!selectedThreadId) throw new Error('Select a thread for Smartsheet sync.');
        endpoint = `${API_BASE}/api/v1/connectors/threads/${encodeURIComponent(selectedThreadId)}/smartsheet/sync`;
      } else if (selectedConnector.id === 'salesforce_insights') {
        endpoint = `${API_BASE}/api/v1/connectors/salesforce/pipeline/summary?days=30&limit=200`;
        method = 'GET';
      } else if (selectedConnector.id === 'snowflake_insights') {
        const tables = parseList(selectedDraft?.snowflake_table_allowlist || '');
        if (!tables.length) {
          throw new Error('Add at least one table in Table Allowlist to run Snowflake sync.');
        }
        endpoint = `${API_BASE}/api/v1/connectors/snowflake/query`;
        method = 'POST';
        body = {
          table: tables[0],
          limit: 200,
        };
      } else {
        endpoint = `${API_BASE}/api/v1/connectors/${encodeURIComponent(selectedConnector.id)}/health`;
        method = 'GET';
      }

      const res = await authFetch(endpoint, {
        method,
        credentials: 'include',
        headers: authHeaders(Boolean(body), method),
        body: body ? JSON.stringify(body) : undefined,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.error || `Sync failed (${res.status})`);

      if (selectedConnector.id === 'snowflake_insights') {
        const rowCount = Array.isArray(data?.rows) ? data.rows.length : 0;
        const tableName = String(data?.summary?.table || body?.table || '').trim();
        setMessage(`Snowflake sync completed: read ${rowCount} row(s) from ${tableName || 'allowlisted table'}.`);
      } else if (selectedConnector.id === 'salesforce_insights') {
        const oppCount = Number(data?.summary?.opportunity_count || 0);
        setMessage(`Salesforce sync completed: ${oppCount} opportunities summarized.`);
      } else {
        setMessage('Sync completed successfully.');
      }
      await loadConnectors();
      await loadAudit(selectedConnector.id);
    } catch (err) {
      const syncError = err?.message || 'Sync failed.';
      if (EXECUTION_SYNC_CONNECTOR_IDS.includes(selectedConnector?.id) && isMissingThreadSyncContextError(syncError)) {
        setError('Connector is connected, but the selected sync thread is not available for WBS sync yet. Select another thread or generate an execution plan first.');
      } else {
        setError(syncError);
      }
    } finally {
      setBusy(false);
    }
  }

  async function connectWithSalesforce() {
    try {
      // Save credentials first so the backend has them before starting OAuth
      if (selectedConnector?.id === 'salesforce_insights' && selectedDraft) {
        const validationErrors = validateRequiredFields('salesforce_insights', selectedDraft);
        if (Object.keys(validationErrors).length > 0) {
          setDraftErrors((prev) => ({ ...prev, salesforce_insights: validationErrors }));
          setError('Please fill in all required Salesforce fields before connecting.');
          return;
        }
        setBusy(true);
        setError('');
        setMessage('');
        const savePayload = buildUpdatePayload('salesforce_insights', selectedDraft);
        const saveRes = await authFetch(`${API_BASE}/api/v1/connectors/salesforce_insights`, {
          method: 'PATCH',
          credentials: 'include',
          headers: authHeaders(true, 'PATCH'),
          body: JSON.stringify(savePayload),
        });
        const saveData = await saveRes.json().catch(() => ({}));
        if (!saveRes.ok) throw new Error(saveData?.error || 'Failed to save Salesforce credentials.');
        await loadConnectors();
        setBusy(false);
      }

      const nextPath = window.location.pathname + window.location.search;
      const response = await fetch(
        `${API_BASE}/api/v1/connectors/salesforce/oauth/start?next=${encodeURIComponent(nextPath)}`,
        {
          method: 'GET',
          headers: authHeaders(false, 'GET'),
          credentials: 'include',
        }
      );
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data?.auth_url) {
        throw new Error(data?.error || 'Could not start Salesforce OAuth. Check your Client ID and Secret.');
      }
      window.location.href = data.auth_url;
    } catch (err) {
      setBusy(false);
      setError(err?.message || 'Failed to connect to Salesforce. Try again.');
    }
  }

  function renderConnectorSpecificFields(connectorId, draft) {
    if (!draft) return null;
    const fieldError = (field) => selectedDraftErrors?.[field] || '';
    const describedBy = (field) => (fieldError(field) ? `connector-field-error-${connectorId}-${field}` : undefined);
    const inputClassName = (field) => (fieldError(field) ? 'connector-input-invalid' : '');
    const renderRequiredField = (field, label, options = {}) => {
      const type = options.type || 'text';
      return (
        <label>
          {fieldLabel(label, true)}
          <input
            type={type}
            value={draft[field]}
            onChange={(event) => updateDraft(field, event.target.value)}
            placeholder={options.placeholder}
            className={inputClassName(field)}
            aria-invalid={Boolean(fieldError(field))}
            aria-describedby={describedBy(field)}
          />
          <FieldError id={`connector-field-error-${connectorId}-${field}`} message={fieldError(field)} />
        </label>
      );
    };

    if (connectorId === 'jira_sync') {
      return (
        <>
          {renderRequiredField('jira_base_url', 'Jira Base URL')}
          {renderRequiredField('jira_project_key', 'Project Key')}
          {renderRequiredField('jira_email', 'Email')}
          <label>Issue Type<input value={draft.jira_issue_type} onChange={(event) => updateDraft('jira_issue_type', event.target.value)} /></label>
          {renderRequiredField('jira_api_token', 'API Token', { type: 'password', placeholder: 'Enter token to set or rotate' })}
          <label>Field Mapping JSON<textarea value={draft.jira_field_mapping} onChange={(event) => updateDraft('jira_field_mapping', event.target.value)} /></label>
        </>
      );
    }

    if (connectorId === 'workfront_sync') {
      return (
        <>
          {renderRequiredField('workfront_base_url', 'Workfront URL')}
          {renderRequiredField('workfront_project_id', 'Project ID')}
          {renderRequiredField('workfront_api_token', 'API Token', { type: 'password', placeholder: 'Enter token to set or rotate' })}
          <label>Field Mapping JSON<textarea value={draft.workfront_field_mapping} onChange={(event) => updateDraft('workfront_field_mapping', event.target.value)} /></label>
        </>
      );
    }

    if (connectorId === 'smartsheet_sync') {
      return (
        <>
          {renderRequiredField('smartsheet_base_url', 'Smartsheet Base URL')}
          {renderRequiredField('smartsheet_sheet_id', 'Sheet ID')}
          {renderRequiredField('smartsheet_api_token', 'API Token', { type: 'password', placeholder: 'Enter token to set or rotate' })}
          <label>Field Mapping JSON<textarea value={draft.smartsheet_field_mapping} onChange={(event) => updateDraft('smartsheet_field_mapping', event.target.value)} /></label>
        </>
      );
    }

    if (connectorId === 'salesforce_insights') {
      return (
        <>
          {renderRequiredField('salesforce_auth_base_url', 'Auth Base URL')}
          {renderRequiredField('salesforce_instance_url', 'Instance URL')}
          {renderRequiredField('salesforce_client_id', 'Client ID')}
          {renderRequiredField('salesforce_client_secret', 'Client Secret', { type: 'password', placeholder: 'Enter secret to set or rotate' })}
          <label>
            Refresh Token <span className="connector-field-optional">(auto-populated after OAuth)</span>
            <input
              type="password"
              value={draft.salesforce_refresh_token}
              onChange={(event) => updateDraft('salesforce_refresh_token', event.target.value)}
              placeholder="Auto-populated after connecting via OAuth"
            />
          </label>
          <div className="connector-oauth-row">
            <button
              type="button"
              className="connector-oauth-btn"
              onClick={connectWithSalesforce}
              title="Authorize Jaspen to access your Salesforce data via OAuth"
            >
              <img
                src="https://c1.sfdcstatic.com/content/dam/sfdc-docs/www/logos/logo-salesforce.svg"
                alt=""
                className="connector-oauth-logo"
                onError={(event) => { event.currentTarget.style.display = 'none'; }}
              />
              Connect with Salesforce
            </button>
            <p className="connector-oauth-hint">
              Enter your Client ID and Secret above, save credentials, then click Connect to authorize via OAuth.
              You will not need to enter a refresh token manually after authorization.
            </p>
          </div>
        </>
      );
    }

    if (connectorId === 'snowflake_insights') {
      // Snowflake renders its own grid — caller must NOT wrap in connector-field-grid
      return (
        <div className="connector-sf-grid">
          {/* Setup guide */}
          <p className="connector-sf-guide">
            <strong>Account:</strong> Snowsight → Admin → Accounts. Format: <code>abc12345.us-east-1</code> — no <em>.snowflakecomputing.com</em>.{' '}
            <strong>Role:</strong> Must have SELECT on your tables; <code>SYSADMIN</code> works for testing.{' '}
            <strong>Table Allowlist:</strong> Required — Jaspen only queries tables you explicitly list here.
          </p>

          {/* Row 1: Account + Warehouse */}
          {renderRequiredField('snowflake_account', 'Account Identifier', { placeholder: 'e.g. qzc42998.us-east-1' })}
          {renderRequiredField('snowflake_warehouse', 'Warehouse', { placeholder: 'e.g. COMPUTE_WH' })}

          {/* Row 2: Database + Schema */}
          {renderRequiredField('snowflake_database', 'Database', { placeholder: 'e.g. SNOWFLAKE_SAMPLE_DATA' })}
          {renderRequiredField('snowflake_schema', 'Schema', { placeholder: 'e.g. TPCH_SF1' })}

          {/* Row 3: Role + Username */}
          {renderRequiredField('snowflake_role', 'Role', { placeholder: 'e.g. SYSADMIN' })}
          {renderRequiredField('snowflake_user', 'Username', { placeholder: 'Your Snowflake username' })}

          {/* Credentials section */}
          <p className="connector-sf-section">Credentials — password or private key required</p>
          {renderRequiredField('snowflake_password', 'Password', { type: 'password', placeholder: 'Enter to set or rotate' })}
          <label>
            Private Key (alternative)
            <input
              type="password"
              value={draft.snowflake_private_key}
              onChange={(event) => updateDraft('snowflake_private_key', event.target.value)}
              placeholder="Paste PEM key to set or rotate"
              className={inputClassName('snowflake_private_key')}
              aria-invalid={Boolean(fieldError('snowflake_private_key'))}
              aria-describedby={describedBy('snowflake_private_key')}
            />
            <FieldError id={`connector-field-error-${connectorId}-snowflake_private_key`} message={fieldError('snowflake_private_key')} />
          </label>
          {fieldError('snowflake_password') && fieldError('snowflake_password') === fieldError('snowflake_private_key') && (
            <p className="connector-sf-error-text">{fieldError('snowflake_password')}</p>
          )}

          {/* Data access */}
          <p className="connector-sf-section">Data Access</p>
          <label className="connector-sf-full">
            Table Allowlist <span className="connector-required-marker" aria-hidden="true"> *</span>
            <input
              value={draft.snowflake_table_allowlist}
              onChange={(event) => updateDraft('snowflake_table_allowlist', event.target.value)}
              placeholder="e.g. tpch_sf1.lineitem, tpch_sf1.orders, tpch_sf1.customer"
            />
          </label>
        </div>
      );
    }

    if (connectorId === 'oracle_fusion_insights') {
      return (
        <>
          {renderRequiredField('oracle_fusion_base_url', 'Oracle Fusion URL')}
          {renderRequiredField('oracle_fusion_username', 'Username')}
          {renderRequiredField('oracle_fusion_password', 'Password', { type: 'password', placeholder: 'Enter password to set or rotate' })}
          <label>Business Unit<input value={draft.oracle_fusion_business_unit} onChange={(event) => updateDraft('oracle_fusion_business_unit', event.target.value)} /></label>
        </>
      );
    }

    if (connectorId === 'servicenow_insights') {
      return (
        <>
          {renderRequiredField('servicenow_instance_url', 'Instance URL')}
          {renderRequiredField('servicenow_username', 'Username')}
          {renderRequiredField('servicenow_password', 'Password', { type: 'password', placeholder: 'Enter password to set or rotate' })}
          <label>Table Allowlist (comma-separated)<input value={draft.servicenow_table_allowlist} onChange={(event) => updateDraft('servicenow_table_allowlist', event.target.value)} /></label>
        </>
      );
    }

    if (connectorId === 'netsuite_insights') {
      return (
        <>
          {renderRequiredField('netsuite_account_id', 'Account ID')}
          {renderRequiredField('netsuite_consumer_key', 'Consumer Key')}
          {renderRequiredField('netsuite_consumer_secret', 'Consumer Secret', { type: 'password', placeholder: 'Enter secret to set or rotate' })}
          {renderRequiredField('netsuite_token_id', 'Token ID')}
          {renderRequiredField('netsuite_token_secret', 'Token Secret', { type: 'password', placeholder: 'Enter secret to set or rotate' })}
          <label>REST Base URL<input value={draft.netsuite_rest_base_url} onChange={(event) => updateDraft('netsuite_rest_base_url', event.target.value)} /></label>
        </>
      );
    }

    return null;
  }

  return (
    <div className="connectors-manage-page int-page">
      <AppMenu />
      <div className="connectors-manage-inner int-page-inner">
      <header className="connectors-manage-header int-page-head">
        <div>
          <p className="int-eyebrow">Data Sources</p>
          <h1>Connectors</h1>
          <p>Centralized connector management with monitoring, health checks, and sync history.</p>
        </div>
      </header>

      {loading && (
        <section className="connectors-skeleton" role="status" aria-live="polite" aria-label="Loading connectors">
          <SkeletonBlock width="26%" height={14} />
          <SkeletonBlock width="68%" height={52} />
          <div className="connectors-skeleton-layout">
            <div className="connectors-skeleton-list">
              {Array.from({ length: 6 }).map((_, idx) => (
                <div key={`connectors-skeleton-list-${idx}`} className="connectors-skeleton-card">
                  <div className="connectors-skeleton-card-top">
                    <SkeletonBlock width={34} height={34} />
                    <SkeletonBlock width={92} height={20} />
                  </div>
                  <SkeletonBlock width="58%" height={20} />
                  <SkeletonBlock width="88%" height={12} />
                  <SkeletonBlock width="44%" height={12} />
                </div>
              ))}
            </div>
            <div className="connectors-skeleton-detail">
              <div className="connectors-skeleton-detail-head">
                <SkeletonBlock width="34%" height={30} />
                <div className="connectors-skeleton-detail-actions">
                  <SkeletonBlock width={118} height={36} />
                  <SkeletonBlock width={108} height={36} />
                  <SkeletonBlock width={122} height={36} />
                </div>
              </div>
              <div className="connectors-skeleton-form">
                {Array.from({ length: 8 }).map((__, formIdx) => (
                  <SkeletonBlock key={`connectors-skeleton-field-${formIdx}`} width="100%" height={40} />
                ))}
              </div>
            </div>
          </div>
        </section>
      )}
      {!loading && error && (
        <div className="connectors-manage-state is-error" role="status" aria-live="polite">
          <p>{error}</p>
          <button type="button" className="int-btn int-btn-ghost connectors-retry-btn" onClick={refresh}>
            Retry
          </button>
        </div>
      )}
      {!loading && !error && message && <div className="connectors-manage-state is-success" role="status" aria-live="polite">{message}</div>}

      {!loading && !error && (
        <>
          {isFreePlan ? (
            <section className="connectors-plan-gate">
              <p className="connectors-plan-gate-kicker">Free plan</p>
              <h2>Upgrade to Essential to unlock data sources</h2>
              <p>
                Free accounts can preview the category, but setup, monitoring, and sync controls start on paid plans.
                Essential unlocks starter integrations, Team expands execution sync, and Enterprise unlocks business-system sources.
              </p>
              <div className="connectors-plan-gate-grid">
                <article>
                  <strong>Essential</strong>
                  <span>{getPlanConnectors('essential').join(', ') || 'Starter connectors'}</span>
                </article>
                <article>
                  <strong>Team</strong>
                  <span>{getPlanConnectors('team').join(', ')}</span>
                </article>
                <article>
                  <strong>Enterprise</strong>
                  <span>{getPlanConnectors('enterprise').join(', ')}</span>
                </article>
              </div>
              <button
                type="button"
                className="connectors-plan-gate-btn"
                onClick={() => guardUnsavedChanges(() => navigate('/account'))}
              >
                Upgrade in Account
              </button>
            </section>
          ) : (
            <>
              <div className="connectors-plan-note">
                <strong>{adminPreviewPlan ? 'Preview mode' : 'Current access'}</strong>
                <span>
                  {adminPreviewPlan
                    ? `Viewing Data Sources as ${effectivePlanKey}.`
                    : `Your ${effectivePlanKey} plan includes: ${planConnectorNames.join(', ')}.`}
                </span>
              </div>
              <ConnectorMonitor
                selectedThreadId={selectedThreadId}
                onResynced={refresh}
                allowedConnectorIds={allowedConnectorIds}
              />
            </>
          )}
          {!isFreePlan && (
          <div className="connectors-manage-layout">
            <section className="connectors-card-grid">
              {visibleConnectors.map((connector) => {
                const implemented = connectorIsImplemented(connector);
                return (
                  <button
                    key={connector.id}
                    type="button"
                    className={`connector-card ${selectedConnectorId === connector.id ? 'is-selected' : ''}`}
                    onClick={() => setSelectedConnectorId(connector.id)}
                  >
                    <div className="connector-card-head">
                      <span className="connector-card-icon"><FontAwesomeIcon icon={connectorIcon(connector.id)} /></span>
                      <span className={`connector-card-status int-badge ${implemented ? (connector.connected ? 'is-on int-badge-success' : 'is-off int-badge-danger') : ''}`}>
                        {implemented ? (connector.connected ? 'Connected' : 'Disconnected') : 'Coming soon'}
                      </span>
                    </div>
                    <h3>{connector.label}</h3>
                    <p>{connector.description}</p>
                    <div className="connector-card-foot">
                      <span>{implemented ? (connector.sync_mode || 'import') : 'Not yet available'}</span>
                      <span>{implemented ? (connector.last_sync_at ? new Date(connector.last_sync_at).toLocaleString() : 'Never synced') : 'Coming soon'}</span>
                    </div>
                  </button>
                );
              })}
            </section>

            <section className="connector-detail-panel">
              {!selectedConnector && <div className="connectors-manage-state">Select a connector.</div>}
              {selectedConnector && selectedDraft && (
                <>
                  <header className="connector-detail-header">
                    <div>
                      <h2>{selectedConnector.label}</h2>
                      <p>{selectedConnector.description}</p>
                      {selectedConnectorImplemented && selectedConnectorDirty && (
                        <p className="connector-unsaved-note" role="status" aria-live="polite">
                          You have unsaved changes for this connector.
                        </p>
                      )}
                    </div>
                    <div className="connector-detail-actions">
                      {selectedConnectorImplemented ? (
                        <>
                          <div className="connector-setup-mode">
                            <button
                              type="button"
                              className={selectedSetupMode === 'automatic' ? 'is-active' : ''}
                              onClick={() => setSetupModeByConnector((prev) => ({ ...prev, [selectedConnector.id]: 'automatic' }))}
                            >
                              Automatic
                            </button>
                            <button
                              type="button"
                              className={selectedSetupMode === 'manual' ? 'is-active' : ''}
                              onClick={() => setSetupModeByConnector((prev) => ({ ...prev, [selectedConnector.id]: 'manual' }))}
                            >
                              Manual
                            </button>
                          </div>
                          {selectedSetupMode === 'automatic' ? (
                            <button type="button" onClick={runSetupCheck} disabled={busy} aria-disabled={busy}>
                              <FontAwesomeIcon icon={faPlugCircleCheck} /> Run Setup Check
                            </button>
                          ) : (
                            <>
                              <button type="button" onClick={testConnection} disabled={busy} aria-disabled={busy}><FontAwesomeIcon icon={faFlask} /> Test Connection</button>
                              {selectedConnector.id === 'snowflake_insights' && (
                                <button
                                  type="button"
                                  onClick={validateSnowflakeDataAccess}
                                  disabled={busy || snowflakeProbeBusy}
                                  aria-disabled={busy || snowflakeProbeBusy}
                                >
                                  <FontAwesomeIcon icon={faPlugCircleCheck} />
                                  {snowflakeProbeBusy ? 'Validating data…' : 'Validate Data Access'}
                                </button>
                              )}
                              <button type="button" onClick={syncNow} disabled={busy} aria-disabled={busy}><FontAwesomeIcon icon={faRotate} /> Sync Now</button>
                              <button type="button" onClick={saveConnector} disabled={busy} aria-disabled={busy}><FontAwesomeIcon icon={faServer} /> Save Settings</button>
                            </>
                          )}
                          <button
                            type="button"
                            onClick={revertSelectedDraft}
                            disabled={busy || !selectedConnectorDirty}
                            aria-disabled={busy || !selectedConnectorDirty}
                          >
                            Revert Draft
                          </button>
                        </>
                      ) : (
                        <span className="int-badge">Coming soon</span>
                      )}
                    </div>
                  </header>
                  {!selectedConnectorImplemented ? (
                    <div className="connectors-manage-state">
                      This connector is marked as coming soon and is currently read-only.
                    </div>
                  ) : (
                    <>
                  <p className="connector-required-legend"><span aria-hidden="true">*</span> Required</p>

                  <div className="connector-core-controls">
                    <label>
                      Connection Status
                      <div className="connector-status-readonly">
                        <span className={`int-badge ${selectedConnector.connected ? 'int-badge-success' : 'int-badge-danger'}`}>
                          {selectedConnector.connected ? 'Connected' : 'Disconnected'}
                        </span>
                      </div>
                    </label>
                    <label>
                      Sync Mode
                      <select value={selectedDraft.sync_mode} onChange={(event) => updateDraft('sync_mode', event.target.value)}>
                        {(selectedConnector.available_sync_modes || ['import']).map((mode) => (
                          <option key={mode} value={mode}>{mode}</option>
                        ))}
                      </select>
                    </label>
                    <label>
                      Conflict Policy
                      <select value={selectedDraft.conflict_policy} onChange={(event) => updateDraft('conflict_policy', event.target.value)}>
                        {(selectedConnector.available_conflict_policies || ['prefer_external']).map((policy) => (
                          <option key={policy} value={policy}>{policy}</option>
                        ))}
                      </select>
                    </label>
                    <label>
                      External Workspace
                      <input value={selectedDraft.external_workspace} onChange={(event) => updateDraft('external_workspace', event.target.value)} />
                    </label>
                    {(selectedConnector.id === 'jira_sync' || selectedConnector.id === 'workfront_sync' || selectedConnector.id === 'smartsheet_sync') && (
                      <label>
                        Sync Thread
                        <select value={selectedThreadId} onChange={(event) => setSelectedThreadId(event.target.value)}>
                          <option value="">Select thread...</option>
                          {threads.map((thread) => (
                            <option key={thread.threadId} value={thread.threadId}>{thread.name || thread.threadId}</option>
                          ))}
                        </select>
                      </label>
                    )}
                  </div>
                  <div className="connector-auto-sync-row">
                    <label className="connector-auto-sync">
                      <input
                        type="checkbox"
                        checked={Boolean(selectedDraft.auto_sync)}
                        onChange={(event) => updateDraft('auto_sync', event.target.checked)}
                      />
                      <span>Auto-sync</span>
                    </label>
                    <p className="connector-auto-sync-help">
                      Auto-sync runs scheduled refreshes for this connector when supported.
                    </p>
                  </div>

                  {/* Snowflake renders its own grid to avoid auto-fit column breaks */}
                  {selectedConnector.id === 'snowflake_insights'
                    ? renderConnectorSpecificFields(selectedConnector.id, selectedDraft)
                    : (
                      <div className="connector-field-grid">
                        {renderConnectorSpecificFields(selectedConnector.id, selectedDraft)}
                      </div>
                    )
                  }
                  {selectedConnector.id === 'snowflake_insights' && snowflakeProbeResult && (
                    <section className="connector-diagnostics">
                      <h3>Snowflake Diagnostics</h3>
                      <p className="connector-diagnostics-summary">
                        Checked {snowflakeProbeResult.rows.length} table(s): {snowflakeProbeResult.okCount} passed, {snowflakeProbeResult.failCount} failed.
                      </p>
                      <div className="connector-audit-table-wrap">
                        <table>
                          <thead>
                            <tr>
                              <th>Table</th>
                              <th>Status</th>
                              <th>Details</th>
                            </tr>
                          </thead>
                          <tbody>
                            {snowflakeProbeResult.rows.map((row) => (
                              <tr key={`sf-probe-${row.table}`}>
                                <td>{row.table}</td>
                                <td>{row.ok ? 'pass' : 'fail'}</td>
                                <td>{row.message}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </section>
                  )}

                  <section className="connector-audit-history">
                    <h3>Sync History</h3>
                    {auditRows.length === 0 ? (
                      <p>No sync events yet.</p>
                    ) : (
                      <div className="connector-audit-table-wrap">
                        <table>
                          <thead>
                            <tr>
                              <th>Timestamp</th>
                              <th>Action</th>
                              <th>Status</th>
                              <th>Thread</th>
                              <th>Message</th>
                            </tr>
                          </thead>
                          <tbody>
                            {auditRows.map((row) => (
                              <tr key={row.id || `${row.timestamp}-${row.action}`}>
                                <td>{row.timestamp ? new Date(row.timestamp).toLocaleString() : 'N/A'}</td>
                                <td>{row.action || 'sync'}</td>
                                <td>{row.status || 'unknown'}</td>
                                <td>{row.thread_id || '—'}</td>
                                <td>{row.message || '—'}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </section>
                    </>
                  )}
                </>
              )}
            </section>
          </div>
          )}
        </>
      )}
      <ConfirmDialog
        isOpen={Boolean(discardDialog)}
        title={discardDialog?.title || 'Discard unsaved changes?'}
        message={discardDialog?.message || 'You have unsaved changes. Leave this page and discard them?'}
        confirmLabel={discardDialog?.confirmLabel || 'Discard changes'}
        confirmVariant={discardDialog?.confirmVariant || 'danger'}
        onConfirm={discardDialog?.onConfirm}
        onCancel={() => setDiscardDialog(null)}
      />
      </div>
    </div>
  );
}
