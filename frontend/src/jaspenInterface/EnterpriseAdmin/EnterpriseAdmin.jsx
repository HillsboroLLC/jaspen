import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { API_BASE } from '../../config/apiBase';
import { authFetch, buildAuthHeaders } from '../../shared/auth/http';
import Team from '../Team/Team';
import './EnterpriseAdmin.css';
import AppMenu from '../shared/AppMenu';

const TAB_TEAM = 'team';
const TAB_SSO = 'sso';
const TAB_GOVERNANCE = 'governance';
const TAB_AUDIT = 'audit';
const TAB_COMPLIANCE = 'compliance';

const TABS = [
  { id: TAB_TEAM, label: 'Team Management' },
  { id: TAB_SSO, label: 'SSO / SAML' },
  { id: TAB_GOVERNANCE, label: 'Data Governance' },
  { id: TAB_AUDIT, label: 'Audit Log' },
  { id: TAB_COMPLIANCE, label: 'Compliance' },
];

const RETENTION_OPTIONS = [
  { value: '30_days', label: '30 days' },
  { value: '90_days', label: '90 days' },
  { value: '1_year', label: '1 year' },
  { value: 'never', label: 'Never' },
];

const SSO_PROVIDERS = ['Okta', 'Azure AD', 'Google Workspace', 'OneLogin'];

const ACTION_FILTERS = [
  { value: '', label: 'All actions' },
  { value: 'score_completed', label: 'Score completed' },
  { value: 'scenario_created', label: 'Scenario created' },
  { value: 'scenario_adopted', label: 'Scenario adopted' },
  { value: 'wbs_generated', label: 'WBS generated' },
  { value: 'wbs_edited', label: 'WBS edited' },
  { value: 'connector_sync', label: 'Connector sync' },
  { value: 'team_member_joined', label: 'Team member joined' },
  { value: 'data_uploaded', label: 'Data uploaded' },
  { value: 'project_activity', label: 'Project activity' },
];

const COMPLIANCE_ROWS = [
  {
    key: 'soc2',
    label: 'SOC 2',
    status: 'In Progress',
    description: 'Enterprise controls, audit logging, and role-based access are available and expanding.',
    action_items: 'Finalize control evidence automation and third-party attestation process.',
  },
  {
    key: 'gdpr',
    label: 'GDPR',
    status: 'In Progress',
    description: 'Data access controls and retention policy settings support privacy operations.',
    action_items: 'Complete data subject request workflow and documented processor controls.',
  },
  {
    key: 'hipaa',
    label: 'HIPAA',
    status: 'Not Started',
    description: 'Platform architecture supports least-privilege and audit trails for regulated deployments.',
    action_items: 'Establish HIPAA-specific safeguards, BAAs, and compliance controls.',
  },
];

function adminFetch(path, options = {}) {
  const method = String(options.method || 'GET').toUpperCase();
  return authFetch(`${API_BASE}${path}`, {
    credentials: 'include',
    headers: buildAuthHeaders(
      {
        'Content-Type': 'application/json',
        ...(options.headers || {}),
      },
      method,
    ),
    ...options,
  }).then(async (res) => {
    const payload = await res.json().catch(() => ({}));
    if (!res.ok) {
      const message = payload?.error || payload?.message || `${res.status} ${res.statusText}`;
      throw new Error(message);
    }
    return payload;
  });
}

function toDatetime(value) {
  const parsed = new Date(value);
  return Number.isFinite(parsed.getTime()) ? parsed : null;
}

function formatDate(value) {
  const parsed = toDatetime(value);
  return parsed ? parsed.toLocaleString() : '—';
}

function summarizeDetails(details) {
  if (!details || typeof details !== 'object') return '—';
  const keys = Object.keys(details).slice(0, 3);
  if (!keys.length) return '—';
  return keys.map((key) => `${key}: ${String(details[key])}`).join(' · ');
}

export default function EnterpriseAdmin() {
  const [activeTab, setActiveTab] = useState(TAB_TEAM);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const [org, setOrg] = useState(null);
  const [members, setMembers] = useState([]);
  const [connectors, setConnectors] = useState([]);

  const [ssoForm, setSsoForm] = useState({
    identity_provider_url: '',
    entity_id: '',
    certificate: '',
    require_sso: false,
  });
  const [ssoTestMessage, setSsoTestMessage] = useState('');

  const [governanceForm, setGovernanceForm] = useState({
    retention_policy: '90_days',
    allow_member_exports: true,
    pii_masking: false,
    connector_data_access: {},
  });

  const [auditEvents, setAuditEvents] = useState([]);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditFilterUserId, setAuditFilterUserId] = useState('');
  const [auditFilterType, setAuditFilterType] = useState('');
  const [auditFilterDateStart, setAuditFilterDateStart] = useState('');
  const [auditFilterDateEnd, setAuditFilterDateEnd] = useState('');

  const redirectUri = useMemo(() => {
    if (!org?.id) return '';
    return `${window.location.origin}/auth/sso/callback/${encodeURIComponent(org.id)}`;
  }, [org?.id]);

  const ssoConfigured = useMemo(() => {
    return Boolean(
      String(ssoForm.identity_provider_url || '').trim()
      && String(ssoForm.entity_id || '').trim()
      && String(ssoForm.certificate || '').trim()
    );
  }, [ssoForm]);

  const loadAuditEvents = useCallback(async (orgId, { userId = '', actionType = '' } = {}) => {
    if (!orgId) return;
    setAuditLoading(true);
    try {
      const params = new URLSearchParams({
        scope: 'organization',
        limit: '250',
      });
      if (userId) params.set('user_id', userId);
      if (actionType) params.set('type', actionType);
      const payload = await adminFetch(`/api/v1/activity?${params.toString()}`);
      setAuditEvents(Array.isArray(payload?.events) ? payload.events : []);
    } catch (err) {
      setAuditEvents([]);
      setError(err?.message || 'Failed to load organization activity.');
    } finally {
      setAuditLoading(false);
    }
  }, []);

  const loadEnterpriseAdmin = useCallback(async () => {
    setLoading(true);
    setError('');
    setNotice('');
    try {
      const summaryPayload = await adminFetch('/api/v1/team/summary');
      const activeOrg = summaryPayload?.organization || null;
      if (!activeOrg?.id) {
        throw new Error('No active organization found.');
      }

      const [orgPayload, connectorPayload] = await Promise.all([
        adminFetch(`/api/v1/teams/${encodeURIComponent(activeOrg.id)}`),
        adminFetch('/api/v1/connectors/status').catch(() => ({ connectors: [] })),
      ]);

      const orgFromApi = orgPayload?.organization || activeOrg;
      const orgSettings = orgFromApi?.settings && typeof orgFromApi.settings === 'object'
        ? orgFromApi.settings
        : {};

      setOrg(orgFromApi);
      setMembers(Array.isArray(orgPayload?.members) ? orgPayload.members : []);

      const connectorRows = Array.isArray(connectorPayload?.connectors)
        ? connectorPayload.connectors
        : [];
      setConnectors(connectorRows);

      const ssoSettings = orgSettings?.sso && typeof orgSettings.sso === 'object' ? orgSettings.sso : {};
      setSsoForm({
        identity_provider_url: String(ssoSettings.identity_provider_url || ''),
        entity_id: String(ssoSettings.entity_id || ''),
        certificate: String(ssoSettings.certificate || ''),
        require_sso: Boolean(ssoSettings.require_sso),
      });

      const governanceSettings =
        orgSettings?.governance && typeof orgSettings.governance === 'object'
          ? orgSettings.governance
          : {};
      const connectorAccessRaw =
        governanceSettings?.connector_data_access && typeof governanceSettings.connector_data_access === 'object'
          ? governanceSettings.connector_data_access
          : {};
      const connectorAccessMerged = {};
      connectorRows.forEach((connector) => {
        const connectorId = String(connector?.id || '').trim();
        if (connectorId) {
          connectorAccessMerged[connectorId] = Object.prototype.hasOwnProperty.call(connectorAccessRaw, connectorId)
            ? Boolean(connectorAccessRaw[connectorId])
            : true;
        }
      });

      setGovernanceForm({
        retention_policy: String(governanceSettings.retention_policy || '90_days'),
        allow_member_exports: Boolean(
          Object.prototype.hasOwnProperty.call(governanceSettings, 'allow_member_exports')
            ? governanceSettings.allow_member_exports
            : true
        ),
        pii_masking: Boolean(governanceSettings.pii_masking),
        connector_data_access: connectorAccessMerged,
      });

      await loadAuditEvents(activeOrg.id, {});
    } catch (err) {
      setError(err?.message || 'Failed to load enterprise admin.');
    } finally {
      setLoading(false);
    }
  }, [loadAuditEvents]);

  useEffect(() => {
    loadEnterpriseAdmin();
  }, [loadEnterpriseAdmin]);

  const filteredAuditEvents = useMemo(() => {
    const start = auditFilterDateStart ? new Date(`${auditFilterDateStart}T00:00:00`) : null;
    const end = auditFilterDateEnd ? new Date(`${auditFilterDateEnd}T23:59:59`) : null;
    return (Array.isArray(auditEvents) ? auditEvents : []).filter((event) => {
      const ts = toDatetime(event?.timestamp);
      if (!ts) return false;
      if (start && ts < start) return false;
      if (end && ts > end) return false;
      return true;
    });
  }, [auditEvents, auditFilterDateStart, auditFilterDateEnd]);

  const saveSsoSettings = useCallback(async () => {
    if (!org?.id) return;
    setBusy(true);
    setError('');
    setNotice('');
    try {
      await adminFetch(`/api/v1/teams/${encodeURIComponent(org.id)}/settings`, {
        method: 'PATCH',
        body: JSON.stringify({
          settings: {
            sso: {
              identity_provider_url: String(ssoForm.identity_provider_url || '').trim(),
              entity_id: String(ssoForm.entity_id || '').trim(),
              certificate: String(ssoForm.certificate || '').trim(),
              redirect_uri: redirectUri,
              require_sso: Boolean(ssoForm.require_sso),
            },
          },
        }),
      });
      setNotice('SSO configuration saved.');
      await loadEnterpriseAdmin();
    } catch (err) {
      setError(err?.message || 'Failed to save SSO configuration.');
    } finally {
      setBusy(false);
    }
  }, [loadEnterpriseAdmin, org?.id, redirectUri, ssoForm]);

  const testSsoConnection = useCallback(() => {
    const requiredReady = Boolean(
      String(ssoForm.identity_provider_url || '').trim()
      && String(ssoForm.entity_id || '').trim()
      && String(ssoForm.certificate || '').trim()
    );
    if (!requiredReady) {
      setSsoTestMessage('Missing required SSO fields. Add IdP URL, Entity ID, and certificate first.');
      return;
    }
    setSsoTestMessage('Connection test queued. Endpoint validation will be enabled in a later phase.');
  }, [ssoForm]);

  const saveGovernanceSettings = useCallback(async () => {
    if (!org?.id) return;
    setBusy(true);
    setError('');
    setNotice('');
    try {
      await adminFetch(`/api/v1/teams/${encodeURIComponent(org.id)}/settings`, {
        method: 'PATCH',
        body: JSON.stringify({
          settings: {
            governance: {
              retention_policy: governanceForm.retention_policy,
              allow_member_exports: Boolean(governanceForm.allow_member_exports),
              pii_masking: Boolean(governanceForm.pii_masking),
              connector_data_access: governanceForm.connector_data_access,
            },
          },
        }),
      });
      setNotice('Data governance settings saved.');
      await loadEnterpriseAdmin();
    } catch (err) {
      setError(err?.message || 'Failed to save governance settings.');
    } finally {
      setBusy(false);
    }
  }, [governanceForm, loadEnterpriseAdmin, org?.id]);

  const onRefreshAudit = useCallback(async () => {
    if (!org?.id) return;
    setError('');
    await loadAuditEvents(org.id, { userId: auditFilterUserId, actionType: auditFilterType });
  }, [auditFilterType, auditFilterUserId, loadAuditEvents, org?.id]);

  if (loading) {
    return (
      <div className="enterprise-admin-page">
        <AppMenu />
        <div className="enterprise-admin-card">Loading enterprise admin...</div>
      </div>
    );
  }

  return (
    <div className="enterprise-admin-page">
      <AppMenu />
      <section className="enterprise-admin-card enterprise-admin-header">
        <div>
          <p className="enterprise-admin-eyebrow">Jaspen Enterprise</p>
          <h1>Enterprise Admin</h1>
          <p>Manage enterprise controls for team operations, security, data governance, and audit readiness.</p>
        </div>
        <div className="enterprise-admin-meta">
          <span>Organization: <strong>{org?.name || '—'}</strong></span>
          <span>Plan: <strong>{String(org?.plan || org?.plan_key || '').toUpperCase() || 'ENTERPRISE'}</strong></span>
        </div>
      </section>

      {!!error && <section className="enterprise-admin-card enterprise-admin-error">{error}</section>}
      {!!notice && <section className="enterprise-admin-card enterprise-admin-notice">{notice}</section>}

      <section className="enterprise-admin-tabs">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={`enterprise-admin-tab ${activeTab === tab.id ? 'active' : ''}`}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </section>

      {activeTab === TAB_TEAM && (
        <section className="enterprise-admin-panel">
          <Team mode="enterprise" />
        </section>
      )}

      {activeTab === TAB_SSO && (
        <section className="enterprise-admin-panel enterprise-admin-card">
          <header className="enterprise-panel-head">
            <h2>SSO / SAML Configuration</h2>
            <span className={`enterprise-status ${ssoConfigured ? 'ok' : 'off'}`}>
              {ssoConfigured ? 'Configured' : 'Not Configured'}
            </span>
          </header>

          <div className="enterprise-grid-two">
            <label>
              Identity Provider URL
              <input
                type="text"
                value={ssoForm.identity_provider_url}
                onChange={(event) => setSsoForm((prev) => ({ ...prev, identity_provider_url: event.target.value }))}
                placeholder="https://idp.example.com/saml"
              />
            </label>
            <label>
              Entity ID
              <input
                type="text"
                value={ssoForm.entity_id}
                onChange={(event) => setSsoForm((prev) => ({ ...prev, entity_id: event.target.value }))}
                placeholder="urn:jaspen:enterprise"
              />
            </label>
          </div>

          <label className="enterprise-full">
            Certificate
            <textarea
              rows={8}
              value={ssoForm.certificate}
              onChange={(event) => setSsoForm((prev) => ({ ...prev, certificate: event.target.value }))}
              placeholder="-----BEGIN CERTIFICATE-----"
            />
          </label>

          <label className="enterprise-full">
            Redirect URI
            <input type="text" value={redirectUri} readOnly />
          </label>

          <label className="enterprise-checkbox">
            <input
              type="checkbox"
              checked={Boolean(ssoForm.require_sso)}
              onChange={(event) => setSsoForm((prev) => ({ ...prev, require_sso: event.target.checked }))}
            />
            Require SSO for all org members
          </label>

          <div className="enterprise-provider-list">
            Supported providers: {SSO_PROVIDERS.join(', ')}
          </div>

          {!!ssoTestMessage && <div className="enterprise-helper">{ssoTestMessage}</div>}

          <div className="enterprise-actions">
            <button type="button" className="secondary" onClick={testSsoConnection} disabled={busy}>
              Test Connection
            </button>
            <button type="button" className="primary" onClick={saveSsoSettings} disabled={busy}>
              Save Configuration
            </button>
          </div>
        </section>
      )}

      {activeTab === TAB_GOVERNANCE && (
        <section className="enterprise-admin-panel enterprise-admin-card">
          <header className="enterprise-panel-head">
            <h2>Data Governance</h2>
          </header>

          <label className="enterprise-full">
            Data retention policy
            <select
              value={governanceForm.retention_policy}
              onChange={(event) => setGovernanceForm((prev) => ({ ...prev, retention_policy: event.target.value }))}
            >
              {RETENTION_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </label>

          <label className="enterprise-checkbox">
            <input
              type="checkbox"
              checked={Boolean(governanceForm.allow_member_exports)}
              onChange={(event) => setGovernanceForm((prev) => ({ ...prev, allow_member_exports: event.target.checked }))}
            />
            Allow members to export data (CSV/PDF reports)
          </label>

          <label className="enterprise-checkbox">
            <input
              type="checkbox"
              checked={Boolean(governanceForm.pii_masking)}
              onChange={(event) => setGovernanceForm((prev) => ({ ...prev, pii_masking: event.target.checked }))}
            />
            Enable PII detection and masking in uploaded datasets
          </label>

          <div className="enterprise-subsection">
            <h3>Connector data access for AI analysis</h3>
            <div className="enterprise-connector-toggles">
              {(Array.isArray(connectors) ? connectors : []).map((connector) => {
                const connectorId = String(connector?.id || '');
                if (!connectorId) return null;
                const checked = Boolean(governanceForm.connector_data_access?.[connectorId]);
                return (
                  <label key={connectorId} className="enterprise-checkbox">
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={(event) => {
                        const nextChecked = event.target.checked;
                        setGovernanceForm((prev) => ({
                          ...prev,
                          connector_data_access: {
                            ...(prev.connector_data_access || {}),
                            [connectorId]: nextChecked,
                          },
                        }));
                      }}
                    />
                    {connector?.label || connectorId}
                  </label>
                );
              })}
            </div>
          </div>

          <div className="enterprise-actions">
            <button type="button" className="primary" onClick={saveGovernanceSettings} disabled={busy}>
              Save Settings
            </button>
          </div>
        </section>
      )}

      {activeTab === TAB_AUDIT && (
        <section className="enterprise-admin-panel enterprise-admin-card">
          <header className="enterprise-panel-head">
            <h2>Audit Log</h2>
            <button type="button" className="secondary" onClick={onRefreshAudit} disabled={auditLoading}>
              {auditLoading ? 'Refreshing…' : 'Refresh'}
            </button>
          </header>

          <div className="enterprise-audit-filters">
            <select value={auditFilterUserId} onChange={(event) => setAuditFilterUserId(event.target.value)}>
              <option value="">All users</option>
              {(Array.isArray(members) ? members : []).map((member) => (
                <option key={member.id} value={member.user_id}>
                  {member.name || member.email || member.user_id}
                </option>
              ))}
            </select>

            <select value={auditFilterType} onChange={(event) => setAuditFilterType(event.target.value)}>
              {ACTION_FILTERS.map((option) => (
                <option key={option.value || 'all'} value={option.value}>{option.label}</option>
              ))}
            </select>

            <input
              type="date"
              value={auditFilterDateStart}
              onChange={(event) => setAuditFilterDateStart(event.target.value)}
              title="Start date"
            />
            <input
              type="date"
              value={auditFilterDateEnd}
              onChange={(event) => setAuditFilterDateEnd(event.target.value)}
              title="End date"
            />
          </div>

          <div className="enterprise-actions">
            <button type="button" className="secondary" onClick={onRefreshAudit} disabled={auditLoading}>
              Apply Filters
            </button>
          </div>

          <div className="enterprise-audit-table-wrap">
            <table className="enterprise-audit-table">
              <thead>
                <tr>
                  <th>Timestamp</th>
                  <th>User</th>
                  <th>Action</th>
                  <th>Project</th>
                  <th>Details</th>
                </tr>
              </thead>
              <tbody>
                {filteredAuditEvents.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="enterprise-empty">No audit events match your filters.</td>
                  </tr>
                ) : filteredAuditEvents.map((event, idx) => (
                  <tr key={`${event?.timestamp || 'row'}-${event?.type || 'event'}-${idx}`}>
                    <td>{formatDate(event?.timestamp)}</td>
                    <td>{event?.user_name || 'Unknown'}</td>
                    <td>{event?.description || event?.type || 'Activity'}</td>
                    <td>{event?.project_name || '—'}</td>
                    <td>{summarizeDetails(event?.metadata?.details || event?.metadata)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {activeTab === TAB_COMPLIANCE && (
        <section className="enterprise-admin-panel enterprise-admin-card">
          <header className="enterprise-panel-head">
            <h2>Compliance</h2>
          </header>

          <div className="enterprise-compliance-grid">
            {COMPLIANCE_ROWS.map((row) => (
              <article key={row.key} className="enterprise-compliance-card">
                <header>
                  <h3>{row.label}</h3>
                  <span className={`enterprise-status ${String(row.status).toLowerCase().replace(/\s+/g, '-')}`}>
                    {row.status}
                  </span>
                </header>
                <p>{row.description}</p>
                <p><strong>Action items:</strong> {row.action_items}</p>
              </article>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
