import React, { useCallback, useEffect, useMemo, useState } from 'react';
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
import './ConnectorsManage.css';

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

function authHeaders(json = false) {
  const token = localStorage.getItem('access_token') || localStorage.getItem('token');
  return {
    ...(json ? { 'Content-Type': 'application/json' } : {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
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

function buildUpdatePayload(connectorId, draft) {
  const payload = {
    connection_status: draft.connection_status,
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

  const loadConnectors = useCallback(async () => {
    const res = await fetch(`${API_BASE}/api/connectors/status`, {
      credentials: 'include',
      headers: authHeaders(),
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

  const loadThreads = useCallback(async () => {
    const res = await fetch(`${API_BASE}/api/ai-agent/threads`, {
      credentials: 'include',
      headers: authHeaders(),
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
    const res = await fetch(`${API_BASE}/api/connectors/${encodeURIComponent(connectorId)}/audit?limit=20`, {
      credentials: 'include',
      headers: authHeaders(),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setAuditRows([]);
      return;
    }
    setAuditRows(Array.isArray(data?.events) ? data.events : []);
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      await Promise.all([loadConnectors(), loadThreads()]);
    } catch (err) {
      setError(err?.message || 'Failed to load connector management data.');
    } finally {
      setLoading(false);
    }
  }, [loadConnectors, loadThreads]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    loadAudit(selectedConnectorId);
  }, [loadAudit, selectedConnectorId]);

  const selectedConnector = useMemo(
    () => connectors.find((item) => item.id === selectedConnectorId) || null,
    [connectors, selectedConnectorId]
  );

  const selectedDraft = selectedConnector ? drafts[selectedConnector.id] || normalizeDraft(selectedConnector) : null;

  function updateDraft(field, value) {
    if (!selectedConnector) return;
    setDrafts((prev) => ({
      ...prev,
      [selectedConnector.id]: {
        ...(prev[selectedConnector.id] || normalizeDraft(selectedConnector)),
        [field]: value,
      },
    }));
  }

  async function saveConnector() {
    if (!selectedConnector || !selectedDraft) return;
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const payload = buildUpdatePayload(selectedConnector.id, selectedDraft);
      const res = await fetch(`${API_BASE}/api/connectors/${encodeURIComponent(selectedConnector.id)}`, {
        method: 'PATCH',
        credentials: 'include',
        headers: authHeaders(true),
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

  async function testConnection() {
    if (!selectedConnector) return;
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const res = await fetch(`${API_BASE}/api/connectors/${encodeURIComponent(selectedConnector.id)}/health`, {
        credentials: 'include',
        headers: authHeaders(),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.error || `Test failed (${res.status})`);
      const liveStatus = data?.live_status?.status || data?.health?.status || 'unknown';
      setMessage(`Health check complete: ${liveStatus}`);
      await loadAudit(selectedConnector.id);
    } catch (err) {
      setError(err?.message || 'Health check failed.');
    } finally {
      setBusy(false);
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
        endpoint = `${API_BASE}/api/connectors/threads/${encodeURIComponent(selectedThreadId)}/jira/sync`;
      } else if (selectedConnector.id === 'workfront_sync') {
        if (!selectedThreadId) throw new Error('Select a thread for Workfront sync.');
        endpoint = `${API_BASE}/api/connectors/threads/${encodeURIComponent(selectedThreadId)}/workfront/sync`;
      } else if (selectedConnector.id === 'smartsheet_sync') {
        if (!selectedThreadId) throw new Error('Select a thread for Smartsheet sync.');
        endpoint = `${API_BASE}/api/connectors/threads/${encodeURIComponent(selectedThreadId)}/smartsheet/sync`;
      } else if (selectedConnector.id === 'salesforce_insights') {
        endpoint = `${API_BASE}/api/connectors/salesforce/pipeline/summary?days=30&limit=200`;
        method = 'GET';
      } else {
        endpoint = `${API_BASE}/api/connectors/${encodeURIComponent(selectedConnector.id)}/health`;
        method = 'GET';
      }

      const res = await fetch(endpoint, {
        method,
        credentials: 'include',
        headers: authHeaders(Boolean(body)),
        body: body ? JSON.stringify(body) : undefined,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.error || `Sync failed (${res.status})`);

      setMessage('Sync completed successfully.');
      await loadConnectors();
      await loadAudit(selectedConnector.id);
    } catch (err) {
      setError(err?.message || 'Sync failed.');
    } finally {
      setBusy(false);
    }
  }

  function renderConnectorSpecificFields(connectorId, draft) {
    if (!draft) return null;

    if (connectorId === 'jira_sync') {
      return (
        <>
          <label>Jira Base URL<input value={draft.jira_base_url} onChange={(event) => updateDraft('jira_base_url', event.target.value)} /></label>
          <label>Project Key<input value={draft.jira_project_key} onChange={(event) => updateDraft('jira_project_key', event.target.value)} /></label>
          <label>Email<input value={draft.jira_email} onChange={(event) => updateDraft('jira_email', event.target.value)} /></label>
          <label>Issue Type<input value={draft.jira_issue_type} onChange={(event) => updateDraft('jira_issue_type', event.target.value)} /></label>
          <label>API Token<input type="password" value={draft.jira_api_token} onChange={(event) => updateDraft('jira_api_token', event.target.value)} placeholder="Enter token to set or rotate" /></label>
          <label>Field Mapping JSON<textarea value={draft.jira_field_mapping} onChange={(event) => updateDraft('jira_field_mapping', event.target.value)} /></label>
        </>
      );
    }

    if (connectorId === 'workfront_sync') {
      return (
        <>
          <label>Workfront URL<input value={draft.workfront_base_url} onChange={(event) => updateDraft('workfront_base_url', event.target.value)} /></label>
          <label>Project ID<input value={draft.workfront_project_id} onChange={(event) => updateDraft('workfront_project_id', event.target.value)} /></label>
          <label>API Token<input type="password" value={draft.workfront_api_token} onChange={(event) => updateDraft('workfront_api_token', event.target.value)} placeholder="Enter token to set or rotate" /></label>
          <label>Field Mapping JSON<textarea value={draft.workfront_field_mapping} onChange={(event) => updateDraft('workfront_field_mapping', event.target.value)} /></label>
        </>
      );
    }

    if (connectorId === 'smartsheet_sync') {
      return (
        <>
          <label>Smartsheet Base URL<input value={draft.smartsheet_base_url} onChange={(event) => updateDraft('smartsheet_base_url', event.target.value)} /></label>
          <label>Sheet ID<input value={draft.smartsheet_sheet_id} onChange={(event) => updateDraft('smartsheet_sheet_id', event.target.value)} /></label>
          <label>API Token<input type="password" value={draft.smartsheet_api_token} onChange={(event) => updateDraft('smartsheet_api_token', event.target.value)} placeholder="Enter token to set or rotate" /></label>
          <label>Field Mapping JSON<textarea value={draft.smartsheet_field_mapping} onChange={(event) => updateDraft('smartsheet_field_mapping', event.target.value)} /></label>
        </>
      );
    }

    if (connectorId === 'salesforce_insights') {
      return (
        <>
          <label>Auth Base URL<input value={draft.salesforce_auth_base_url} onChange={(event) => updateDraft('salesforce_auth_base_url', event.target.value)} /></label>
          <label>Instance URL<input value={draft.salesforce_instance_url} onChange={(event) => updateDraft('salesforce_instance_url', event.target.value)} /></label>
          <label>Client ID<input value={draft.salesforce_client_id} onChange={(event) => updateDraft('salesforce_client_id', event.target.value)} /></label>
          <label>Client Secret<input type="password" value={draft.salesforce_client_secret} onChange={(event) => updateDraft('salesforce_client_secret', event.target.value)} placeholder="Enter secret to set or rotate" /></label>
          <label>Refresh Token<input type="password" value={draft.salesforce_refresh_token} onChange={(event) => updateDraft('salesforce_refresh_token', event.target.value)} placeholder="Enter token to set or rotate" /></label>
        </>
      );
    }

    if (connectorId === 'snowflake_insights') {
      return (
        <>
          <label>Account<input value={draft.snowflake_account} onChange={(event) => updateDraft('snowflake_account', event.target.value)} /></label>
          <label>Warehouse<input value={draft.snowflake_warehouse} onChange={(event) => updateDraft('snowflake_warehouse', event.target.value)} /></label>
          <label>Database<input value={draft.snowflake_database} onChange={(event) => updateDraft('snowflake_database', event.target.value)} /></label>
          <label>Schema<input value={draft.snowflake_schema} onChange={(event) => updateDraft('snowflake_schema', event.target.value)} /></label>
          <label>Role<input value={draft.snowflake_role} onChange={(event) => updateDraft('snowflake_role', event.target.value)} /></label>
          <label>User<input value={draft.snowflake_user} onChange={(event) => updateDraft('snowflake_user', event.target.value)} /></label>
          <label>Password<input type="password" value={draft.snowflake_password} onChange={(event) => updateDraft('snowflake_password', event.target.value)} placeholder="Enter password to set or rotate" /></label>
          <label>Private Key<input type="password" value={draft.snowflake_private_key} onChange={(event) => updateDraft('snowflake_private_key', event.target.value)} placeholder="Enter key to set or rotate" /></label>
          <label>Table Allowlist (comma-separated)<input value={draft.snowflake_table_allowlist} onChange={(event) => updateDraft('snowflake_table_allowlist', event.target.value)} /></label>
        </>
      );
    }

    if (connectorId === 'oracle_fusion_insights') {
      return (
        <>
          <label>Oracle Fusion URL<input value={draft.oracle_fusion_base_url} onChange={(event) => updateDraft('oracle_fusion_base_url', event.target.value)} /></label>
          <label>Username<input value={draft.oracle_fusion_username} onChange={(event) => updateDraft('oracle_fusion_username', event.target.value)} /></label>
          <label>Password<input type="password" value={draft.oracle_fusion_password} onChange={(event) => updateDraft('oracle_fusion_password', event.target.value)} placeholder="Enter password to set or rotate" /></label>
          <label>Business Unit<input value={draft.oracle_fusion_business_unit} onChange={(event) => updateDraft('oracle_fusion_business_unit', event.target.value)} /></label>
        </>
      );
    }

    if (connectorId === 'servicenow_insights') {
      return (
        <>
          <label>Instance URL<input value={draft.servicenow_instance_url} onChange={(event) => updateDraft('servicenow_instance_url', event.target.value)} /></label>
          <label>Username<input value={draft.servicenow_username} onChange={(event) => updateDraft('servicenow_username', event.target.value)} /></label>
          <label>Password<input type="password" value={draft.servicenow_password} onChange={(event) => updateDraft('servicenow_password', event.target.value)} placeholder="Enter password to set or rotate" /></label>
          <label>Table Allowlist (comma-separated)<input value={draft.servicenow_table_allowlist} onChange={(event) => updateDraft('servicenow_table_allowlist', event.target.value)} /></label>
        </>
      );
    }

    if (connectorId === 'netsuite_insights') {
      return (
        <>
          <label>Account ID<input value={draft.netsuite_account_id} onChange={(event) => updateDraft('netsuite_account_id', event.target.value)} /></label>
          <label>Consumer Key<input value={draft.netsuite_consumer_key} onChange={(event) => updateDraft('netsuite_consumer_key', event.target.value)} /></label>
          <label>Consumer Secret<input type="password" value={draft.netsuite_consumer_secret} onChange={(event) => updateDraft('netsuite_consumer_secret', event.target.value)} placeholder="Enter secret to set or rotate" /></label>
          <label>Token ID<input value={draft.netsuite_token_id} onChange={(event) => updateDraft('netsuite_token_id', event.target.value)} /></label>
          <label>Token Secret<input type="password" value={draft.netsuite_token_secret} onChange={(event) => updateDraft('netsuite_token_secret', event.target.value)} placeholder="Enter secret to set or rotate" /></label>
          <label>REST Base URL<input value={draft.netsuite_rest_base_url} onChange={(event) => updateDraft('netsuite_rest_base_url', event.target.value)} /></label>
        </>
      );
    }

    return null;
  }

  return (
    <div className="connectors-manage-page">
      <header className="connectors-manage-header">
        <h1>Connectors</h1>
        <p>Centralized connector management with settings, health checks, and sync history.</p>
      </header>

      {loading && <div className="connectors-manage-state">Loading connectors...</div>}
      {!loading && error && <div className="connectors-manage-state is-error">{error}</div>}
      {!loading && !error && message && <div className="connectors-manage-state is-success">{message}</div>}

      {!loading && !error && (
        <div className="connectors-manage-layout">
          <section className="connectors-card-grid">
            {connectors.map((connector) => (
              <button
                key={connector.id}
                type="button"
                className={`connector-card ${selectedConnectorId === connector.id ? 'is-selected' : ''}`}
                onClick={() => setSelectedConnectorId(connector.id)}
              >
                <div className="connector-card-head">
                  <span className="connector-card-icon"><FontAwesomeIcon icon={connectorIcon(connector.id)} /></span>
                  <span className={`connector-card-status ${connector.connected ? 'is-on' : 'is-off'}`}>
                    {connector.connected ? 'Connected' : 'Disconnected'}
                  </span>
                </div>
                <h3>{connector.label}</h3>
                <p>{connector.description}</p>
                <div className="connector-card-foot">
                  <span>{connector.sync_mode || 'import'}</span>
                  <span>{connector.last_sync_at ? new Date(connector.last_sync_at).toLocaleString() : 'Never synced'}</span>
                </div>
              </button>
            ))}
          </section>

          <section className="connector-detail-panel">
            {!selectedConnector && <div className="connectors-manage-state">Select a connector.</div>}
            {selectedConnector && selectedDraft && (
              <>
                <header className="connector-detail-header">
                  <div>
                    <h2>{selectedConnector.label}</h2>
                    <p>{selectedConnector.description}</p>
                  </div>
                  <div className="connector-detail-actions">
                    <button type="button" onClick={testConnection} disabled={busy}><FontAwesomeIcon icon={faFlask} /> Test Connection</button>
                    <button type="button" onClick={syncNow} disabled={busy}><FontAwesomeIcon icon={faRotate} /> Sync Now</button>
                    <button type="button" onClick={saveConnector} disabled={busy}><FontAwesomeIcon icon={faServer} /> Save Settings</button>
                  </div>
                </header>

                <div className="connector-core-controls">
                  <label>
                    Status
                    <select value={selectedDraft.connection_status} onChange={(event) => updateDraft('connection_status', event.target.value)}>
                      <option value="disconnected">Disconnected</option>
                      <option value="connected">Connected</option>
                    </select>
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
                  <label className="connector-auto-sync">
                    <input type="checkbox" checked={Boolean(selectedDraft.auto_sync)} onChange={(event) => updateDraft('auto_sync', event.target.checked)} />
                    Auto-sync
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

                <div className="connector-field-grid">
                  {renderConnectorSpecificFields(selectedConnector.id, selectedDraft)}
                </div>

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
          </section>
        </div>
      )}
    </div>
  );
}
