import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { API_BASE } from '../../config/apiBase';
import './JaspenAdmin.css';


const PLAN_OPTIONS = ['free', 'essential', 'team', 'enterprise'];
const CREDIT_MODE_OPTIONS = [
  { value: 'adjust', label: 'Adjust (+/-)' },
  { value: 'set', label: 'Set exact value' },
  { value: 'reset_plan', label: 'Reset to plan default' },
];
const WORKSPACE_PREVIEW_OPTIONS = [
  { label: 'Free', planKey: 'free' },
  { label: 'Essential', planKey: 'essential' },
  { label: 'Team', planKey: 'team' },
  { label: 'Enterprise', planKey: 'enterprise' },
];
const TEAM_ROLE_PREVIEW_OPTIONS = [
  { label: 'Owner', role: 'owner' },
  { label: 'Admin', role: 'admin' },
  { label: 'Creator', role: 'creator' },
  { label: 'Collaborator', role: 'collaborator' },
  { label: 'Viewer', role: 'viewer' },
];


function getToken() {
  return localStorage.getItem('access_token') || localStorage.getItem('token');
}


function authHeaders(extra = {}) {
  const token = getToken();
  return {
    ...extra,
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}


function toDraft(user) {
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
  };
}


function toConnectorDrafts(connectorList) {
  const next = {};
  (Array.isArray(connectorList) ? connectorList : []).forEach((connector) => {
    const id = String(connector?.id || '').trim();
    if (!id) return;
    next[id] = {
      connection_status: String(connector?.connection_status || 'disconnected'),
      auto_sync: Boolean(connector?.auto_sync),
    };
  });
  return next;
}


export default function JaspenAdmin() {
  const navigate = useNavigate();
  const [isLoading, setIsLoading] = useState(true);
  const [isAdmin, setIsAdmin] = useState(false);
  const [query, setQuery] = useState('');
  const [users, setUsers] = useState([]);
  const [selectedId, setSelectedId] = useState('');
  const [draft, setDraft] = useState(null);
  const [pending, setPending] = useState(false);
  const [connectorPendingId, setConnectorPendingId] = useState('');
  const [opsLoading, setOpsLoading] = useState(false);
  const [message, setMessage] = useState('');

  const [connectors, setConnectors] = useState([]);
  const [connectorDrafts, setConnectorDrafts] = useState({});
  const [sessions, setSessions] = useState([]);
  const [auditEvents, setAuditEvents] = useState([]);

  const [creditOp, setCreditOp] = useState({
    mode: 'adjust',
    delta: '',
    value: '',
    reason: '',
  });
  const [recoveryReason, setRecoveryReason] = useState('');

  const openPreview = (path) => {
    navigate(path);
  };

  const selectedUser = useMemo(
    () => (users || []).find((u) => u.id === selectedId) || null,
    [users, selectedId],
  );

  const applySavedUser = (saved) => {
    if (!saved?.id) return;
    setUsers((prev) => prev.map((u) => (u.id === saved.id ? saved : u)));
    setDraft(toDraft(saved));
    setSelectedId(saved.id);
  };

  const loadUsers = async (nextQuery = query) => {
    const response = await fetch(
      `${API_BASE}/api/admin/users?limit=200&q=${encodeURIComponent(nextQuery || '')}`,
      {
        headers: authHeaders(),
        credentials: 'include',
      },
    );
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      if (response.status === 401) {
        navigate('/?auth=1', { replace: true });
        return;
      }
      if (response.status === 403) {
        setIsAdmin(false);
        return;
      }
      throw new Error(data?.error || 'Unable to load users.');
    }

    const list = Array.isArray(data?.users) ? data.users : [];
    setUsers(list);
    if (selectedId) {
      const refreshed = list.find((u) => u.id === selectedId);
      if (refreshed) {
        setDraft(toDraft(refreshed));
      } else {
        setSelectedId('');
        setDraft(null);
      }
    }
  };

  const loadUserOps = async (userId) => {
    if (!userId) return;
    setOpsLoading(true);
    try {
      const [connectorsRes, sessionsRes, auditRes] = await Promise.all([
        fetch(`${API_BASE}/api/admin/users/${encodeURIComponent(userId)}/connectors`, {
          headers: authHeaders(),
          credentials: 'include',
        }),
        fetch(`${API_BASE}/api/admin/users/${encodeURIComponent(userId)}/sessions?limit=20`, {
          headers: authHeaders(),
          credentials: 'include',
        }),
        fetch(`${API_BASE}/api/admin/audit?user_id=${encodeURIComponent(userId)}&limit=25`, {
          headers: authHeaders(),
          credentials: 'include',
        }),
      ]);

      const connectorsData = await connectorsRes.json().catch(() => ({}));
      const sessionsData = await sessionsRes.json().catch(() => ({}));
      const auditData = await auditRes.json().catch(() => ({}));

      if (!connectorsRes.ok) throw new Error(connectorsData?.error || 'Unable to load connectors.');
      if (!sessionsRes.ok) throw new Error(sessionsData?.error || 'Unable to load sessions.');
      if (!auditRes.ok) throw new Error(auditData?.error || 'Unable to load audit events.');

      const connectorList = Array.isArray(connectorsData?.connectors) ? connectorsData.connectors : [];
      setConnectors(connectorList);
      setConnectorDrafts(toConnectorDrafts(connectorList));
      setSessions(Array.isArray(sessionsData?.sessions) ? sessionsData.sessions : []);
      setAuditEvents(Array.isArray(auditData?.events) ? auditData.events : []);
    } catch (error) {
      setMessage(error.message || 'Unable to load user operations.');
    } finally {
      setOpsLoading(false);
    }
  };

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const capRes = await fetch(`${API_BASE}/api/admin/capabilities`, {
          headers: authHeaders(),
          credentials: 'include',
        });
        const capData = await capRes.json().catch(() => ({}));
        if (!capRes.ok) {
          if (capRes.status === 401) {
            navigate('/?auth=1', { replace: true });
            return;
          }
          throw new Error(capData?.error || 'Unable to verify admin access.');
        }

        const canAdmin = Boolean(capData?.is_admin);
        if (!mounted) return;
        setIsAdmin(canAdmin);
        if (canAdmin) {
          await loadUsers('');
        }
      } catch (error) {
        if (mounted) setMessage(error.message || 'Unable to load admin console.');
      } finally {
        if (mounted) setIsLoading(false);
      }
    })();
    return () => {
      mounted = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [navigate]);

  const handleSelectUser = (user) => {
    if (!user?.id) return;
    setSelectedId(user.id);
    setDraft(toDraft(user));
    setMessage('');
    setCreditOp((prev) => ({ ...prev, delta: '', value: '', reason: '' }));
    setRecoveryReason('');
    loadUserOps(user.id);
  };

  const handleSave = async () => {
    if (!draft?.id) return;
    setPending(true);
    setMessage('');
    try {
      const payload = {
        name: String(draft.name || '').trim(),
        subscription_plan: String(draft.subscription_plan || '').trim().toLowerCase(),
        credits_remaining: draft.credits_remaining === '' ? null : Number(draft.credits_remaining),
        seat_limit: draft.seat_limit === '' ? 0 : Number(draft.seat_limit),
        max_seats: draft.max_seats === '' ? 0 : Number(draft.max_seats),
        unlimited_analysis: Boolean(draft.unlimited_analysis),
        max_concurrent_sessions: draft.max_concurrent_sessions === '' ? null : Number(draft.max_concurrent_sessions),
      };

      const response = await fetch(`${API_BASE}/api/admin/users/${encodeURIComponent(draft.id)}`, {
        method: 'PATCH',
        headers: authHeaders({ 'Content-Type': 'application/json' }),
        credentials: 'include',
        body: JSON.stringify(payload),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data?.error || 'Unable to save user changes.');
      }
      applySavedUser(data?.user);
      setMessage(`Saved ${data?.user?.email || 'user'}.`);
      await loadUserOps(draft.id);
    } catch (error) {
      setMessage(error.message || 'Unable to save user changes.');
    } finally {
      setPending(false);
    }
  };

  const forcePlan = async (planKey, resetCredits = true) => {
    if (!draft?.id) return;
    setPending(true);
    setMessage('');
    try {
      const response = await fetch(`${API_BASE}/api/admin/users/${encodeURIComponent(draft.id)}/force-plan`, {
        method: 'POST',
        headers: authHeaders({ 'Content-Type': 'application/json' }),
        credentials: 'include',
        body: JSON.stringify({ plan_key: planKey, reset_credits: resetCredits }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data?.error || 'Unable to force plan.');
      }
      applySavedUser(data?.user);
      setMessage(`Set ${data?.user?.email || 'user'} to ${planKey}.`);
      await loadUserOps(draft.id);
    } catch (error) {
      setMessage(error.message || 'Unable to force plan.');
    } finally {
      setPending(false);
    }
  };

  const runCreditAction = async () => {
    if (!draft?.id) return;
    const reason = String(creditOp.reason || '').trim();
    if (!reason) {
      setMessage('Credit reason is required.');
      return;
    }

    const payload = { mode: creditOp.mode, reason };
    if (creditOp.mode === 'adjust') {
      const delta = Number(creditOp.delta);
      if (!Number.isInteger(delta) || delta === 0) {
        setMessage('Adjust mode requires a non-zero integer delta.');
        return;
      }
      payload.delta = delta;
    } else if (creditOp.mode === 'set') {
      const raw = String(creditOp.value || '').trim();
      payload.value = raw === '' ? null : Number(raw);
      if (raw !== '' && (!Number.isFinite(payload.value) || payload.value < 0)) {
        setMessage('Set mode requires a non-negative number or blank for unlimited.');
        return;
      }
    }

    setPending(true);
    setMessage('');
    try {
      const response = await fetch(`${API_BASE}/api/admin/users/${encodeURIComponent(draft.id)}/credits`, {
        method: 'POST',
        headers: authHeaders({ 'Content-Type': 'application/json' }),
        credentials: 'include',
        body: JSON.stringify(payload),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data?.error || 'Unable to update credits.');
      applySavedUser(data?.user);
      setMessage('Credit action applied.');
      setCreditOp((prev) => ({ ...prev, delta: '', value: '', reason: '' }));
      await loadUserOps(draft.id);
    } catch (error) {
      setMessage(error.message || 'Unable to update credits.');
    } finally {
      setPending(false);
    }
  };

  const handleConnectorDraftChange = (connectorId, field, value) => {
    setConnectorDrafts((prev) => ({
      ...prev,
      [connectorId]: {
        ...(prev[connectorId] || {}),
        [field]: value,
      },
    }));
  };

  const saveConnector = async (connectorId) => {
    if (!draft?.id || !connectorId) return;
    const connectorPayload = {
      auto_sync: Boolean(connectorDrafts[connectorId]?.auto_sync),
    };
    setConnectorPendingId(connectorId);
    setMessage('');
    try {
      const response = await fetch(
        `${API_BASE}/api/admin/users/${encodeURIComponent(draft.id)}/connectors/${encodeURIComponent(connectorId)}`,
        {
          method: 'PATCH',
          headers: authHeaders({ 'Content-Type': 'application/json' }),
          credentials: 'include',
          body: JSON.stringify(connectorPayload),
        },
      );
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data?.error || `Unable to save connector ${connectorId}.`);
      setMessage(`Saved connector ${connectorId}.`);
      await loadUserOps(draft.id);
    } catch (error) {
      setMessage(error.message || `Unable to save connector ${connectorId}.`);
    } finally {
      setConnectorPendingId('');
    }
  };

  const runRecoveryAction = async (action, label) => {
    if (!draft?.id) return;
    const reason = String(recoveryReason || '').trim();
    if (!reason) {
      setMessage('Recovery reason is required.');
      return;
    }
    if (!window.confirm(`Run "${label}" for ${draft.email}?`)) return;

    setPending(true);
    setMessage('');
    try {
      const response = await fetch(`${API_BASE}/api/admin/users/${encodeURIComponent(draft.id)}/recovery`, {
        method: 'POST',
        headers: authHeaders({ 'Content-Type': 'application/json' }),
        credentials: 'include',
        body: JSON.stringify({ action, reason }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data?.error || `Unable to run ${label}.`);
      applySavedUser(data?.user);
      setMessage(`Recovery action completed: ${label}.`);
      await loadUserOps(draft.id);
    } catch (error) {
      setMessage(error.message || `Unable to run ${label}.`);
    } finally {
      setPending(false);
    }
  };

  if (isLoading) {
    return (
      <div className="jas-admin-page">
        <div className="jas-admin-panel">Loading Jaspen Admin...</div>
      </div>
    );
  }

  if (!isAdmin) {
    return (
      <div className="jas-admin-page">
        <div className="jas-admin-panel">
          <h1>Jaspen Admin</h1>
          <p>You do not have global admin access on this environment.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="jas-admin-page">
      <div className="jas-admin-panel">
        <div className="jas-admin-head">
          <div>
            <p className="jas-admin-eyebrow">Jaspen Internal</p>
            <h1>Jaspen Admin</h1>
            <p className="jas-admin-sub">
              Search users and manage tier, credits, connectors, and recovery actions from one control plane.
            </p>
          </div>
          <button type="button" className="jas-admin-secondary" onClick={() => navigate('/new')}>
            Back to Jaspen
          </button>
        </div>

        <div className="jas-admin-search">
          <input
            type="text"
            placeholder="Search by email or name"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button type="button" className="jas-admin-secondary" onClick={() => loadUsers(query)} disabled={pending}>
            Search
          </button>
        </div>

        {message && <p className="jas-admin-message">{message}</p>}

        <section className="jas-admin-subsection">
          <h3>Experience Preview</h3>
          <p className="jas-admin-empty">
            Launch support previews for customer-facing interfaces without loading real organization data.
          </p>
          <div className="jas-admin-preview-groups">
            <div className="jas-admin-preview-group">
              <strong>Workspace</strong>
              <div className="jas-admin-preview-actions">
                {WORKSPACE_PREVIEW_OPTIONS.map((option) => (
                  <button
                    key={option.planKey}
                    type="button"
                    className="jas-admin-secondary"
                    onClick={() => openPreview(`/new?admin_preview=workspace&plan_key=${encodeURIComponent(option.planKey)}`)}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="jas-admin-preview-group">
              <strong>Team</strong>
              <div className="jas-admin-preview-actions">
                {TEAM_ROLE_PREVIEW_OPTIONS.map((option) => (
                  <button
                    key={`team-${option.role}`}
                    type="button"
                    className="jas-admin-secondary"
                    onClick={() => openPreview(`/team?admin_preview=team&role=${encodeURIComponent(option.role)}`)}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="jas-admin-preview-group">
              <strong>Enterprise</strong>
              <div className="jas-admin-preview-actions">
                {TEAM_ROLE_PREVIEW_OPTIONS.map((option) => (
                  <button
                    key={`enterprise-${option.role}`}
                    type="button"
                    className="jas-admin-secondary"
                    onClick={() => openPreview(`/enterprise-admin?admin_preview=enterprise&role=${encodeURIComponent(option.role)}`)}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </section>

        <div className="jas-admin-layout">
          <div className="jas-admin-users">
            {(users || []).map((user) => {
              const selected = user.id === selectedId;
              return (
                <button
                  type="button"
                  key={user.id}
                  className={`jas-admin-user ${selected ? 'is-selected' : ''}`}
                  onClick={() => handleSelectUser(user)}
                >
                  <strong>{user.email}</strong>
                  <span>{user.name}</span>
                  <span>{user.subscription_plan}</span>
                </button>
              );
            })}
            {(users || []).length === 0 && (
              <p className="jas-admin-empty">No users found.</p>
            )}
          </div>

          <div className="jas-admin-editor">
            {!draft && <p className="jas-admin-empty">Select a user to edit.</p>}
            {draft && (
              <>
                <div className="jas-admin-grid">
                  <label>
                    Email
                    <input type="text" value={draft.email} disabled />
                  </label>
                  <label>
                    Name
                    <input
                      type="text"
                      value={draft.name}
                      onChange={(e) => setDraft((prev) => ({ ...prev, name: e.target.value }))}
                    />
                  </label>
                  <label>
                    Tier
                    <select
                      value={draft.subscription_plan}
                      onChange={(e) => setDraft((prev) => ({ ...prev, subscription_plan: e.target.value }))}
                    >
                      {PLAN_OPTIONS.map((plan) => (
                        <option key={plan} value={plan}>{plan}</option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Credits remaining
                    <input
                      type="number"
                      placeholder="Blank = unlimited"
                      value={draft.credits_remaining}
                      onChange={(e) => setDraft((prev) => ({ ...prev, credits_remaining: e.target.value }))}
                    />
                  </label>
                  <label>
                    Seat limit
                    <input
                      type="number"
                      value={draft.seat_limit}
                      onChange={(e) => setDraft((prev) => ({ ...prev, seat_limit: e.target.value }))}
                    />
                  </label>
                  <label>
                    Max seats
                    <input
                      type="number"
                      value={draft.max_seats}
                      onChange={(e) => setDraft((prev) => ({ ...prev, max_seats: e.target.value }))}
                    />
                  </label>
                  <label>
                    Max concurrent sessions
                    <input
                      type="number"
                      placeholder="Blank = no cap"
                      value={draft.max_concurrent_sessions}
                      onChange={(e) => setDraft((prev) => ({ ...prev, max_concurrent_sessions: e.target.value }))}
                    />
                  </label>
                  <label className="jas-admin-check">
                    <input
                      type="checkbox"
                      checked={Boolean(draft.unlimited_analysis)}
                      onChange={(e) => setDraft((prev) => ({ ...prev, unlimited_analysis: e.target.checked }))}
                    />
                    Unlimited analysis
                  </label>
                </div>

                <div className="jas-admin-actions">
                  <button type="button" className="jas-admin-primary" onClick={handleSave} disabled={pending}>
                    {pending ? 'Saving...' : 'Save user'}
                  </button>
                  <button type="button" className="jas-admin-secondary" onClick={() => forcePlan('essential', true)} disabled={pending}>
                    Force Essential
                  </button>
                  <button type="button" className="jas-admin-secondary" onClick={() => forcePlan('enterprise', true)} disabled={pending}>
                    Force Enterprise
                  </button>
                </div>

                <section className="jas-admin-subsection">
                  <h3>Credit Operations</h3>
                  <div className="jas-admin-inline-grid">
                    <label>
                      Mode
                      <select
                        value={creditOp.mode}
                        onChange={(e) => setCreditOp((prev) => ({ ...prev, mode: e.target.value }))}
                      >
                        {CREDIT_MODE_OPTIONS.map((option) => (
                          <option key={option.value} value={option.value}>{option.label}</option>
                        ))}
                      </select>
                    </label>
                    {creditOp.mode === 'adjust' && (
                      <label>
                        Delta
                        <input
                          type="number"
                          placeholder="e.g. 500 or -100"
                          value={creditOp.delta}
                          onChange={(e) => setCreditOp((prev) => ({ ...prev, delta: e.target.value }))}
                        />
                      </label>
                    )}
                    {creditOp.mode === 'set' && (
                      <label>
                        Set value
                        <input
                          type="number"
                          placeholder="Blank = unlimited"
                          value={creditOp.value}
                          onChange={(e) => setCreditOp((prev) => ({ ...prev, value: e.target.value }))}
                        />
                      </label>
                    )}
                    <label className="jas-admin-wide">
                      Reason
                      <input
                        type="text"
                        placeholder="Required for audit trail"
                        value={creditOp.reason}
                        onChange={(e) => setCreditOp((prev) => ({ ...prev, reason: e.target.value }))}
                      />
                    </label>
                  </div>
                  <div className="jas-admin-actions">
                    <button type="button" className="jas-admin-primary" onClick={runCreditAction} disabled={pending}>
                      Apply Credit Action
                    </button>
                  </div>
                </section>

                <section className="jas-admin-subsection">
                  <h3>Connector Status</h3>
                  {opsLoading && <p className="jas-admin-empty">Loading connector state...</p>}
                  {!opsLoading && connectors.length === 0 && <p className="jas-admin-empty">No connectors available.</p>}
                  {!opsLoading && connectors.length > 0 && (
                    <div className="jas-admin-connectors">
                      {connectors.map((connector) => {
                        const connectorId = String(connector.id || '');
                        const cd = connectorDrafts[connectorId] || {};
                        const connectionStatus = String(connector.connection_status || 'disconnected');
                        const healthStatus = String(connector.health_status || 'unknown');
                        const lastSyncAt = connector.last_sync_at
                          ? new Date(connector.last_sync_at).toLocaleString()
                          : 'Never';
                        return (
                          <div key={connectorId} className="jas-admin-connector-row">
                            <div className="jas-admin-connector-meta">
                              <strong>{connector.label || connectorId}</strong>
                              <span>{connector.group || 'connector'}</span>
                            </div>
                            <div className="jas-admin-connector-stat">
                              <span className="jas-admin-connector-label">Connection</span>
                              <span className={`jas-admin-status-badge is-${connectionStatus}`}>
                                {connectionStatus}
                              </span>
                            </div>
                            <div className="jas-admin-connector-stat">
                              <span className="jas-admin-connector-label">Health</span>
                              <strong>{healthStatus}</strong>
                            </div>
                            <div className="jas-admin-connector-stat">
                              <span className="jas-admin-connector-label">Last sync</span>
                              <strong>{lastSyncAt}</strong>
                            </div>
                            <div className="jas-admin-connector-stat">
                              <span className="jas-admin-connector-label">Failures</span>
                              <strong>{Number(connector.consecutive_failures || 0)}</strong>
                            </div>
                            <label className="jas-admin-check-inline">
                              <input
                                type="checkbox"
                                checked={Boolean(cd.auto_sync)}
                                onChange={(e) => handleConnectorDraftChange(connectorId, 'auto_sync', e.target.checked)}
                              />
                              Auto sync
                            </label>
                            <button
                              type="button"
                              className="jas-admin-secondary"
                              disabled={connectorPendingId === connectorId}
                              onClick={() => saveConnector(connectorId)}
                            >
                              {connectorPendingId === connectorId ? 'Saving...' : 'Save Auto Sync'}
                            </button>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </section>

                <section className="jas-admin-subsection">
                  <h3>Recovery Tools</h3>
                  <div className="jas-admin-inline-grid">
                    <label className="jas-admin-wide">
                      Reason
                      <input
                        type="text"
                        placeholder="Required for recovery actions"
                        value={recoveryReason}
                        onChange={(e) => setRecoveryReason(e.target.value)}
                      />
                    </label>
                  </div>
                  <div className="jas-admin-actions">
                    <button type="button" className="jas-admin-secondary" disabled={pending} onClick={() => runRecoveryAction('clear_sessions', 'Clear sessions')}>
                      Clear Sessions
                    </button>
                    <button type="button" className="jas-admin-secondary" disabled={pending} onClick={() => runRecoveryAction('clear_connectors', 'Clear connectors')}>
                      Clear Connectors
                    </button>
                    <button type="button" className="jas-admin-secondary" disabled={pending} onClick={() => runRecoveryAction('reset_plan_defaults', 'Reset plan defaults')}>
                      Reset Plan Defaults
                    </button>
                    <button type="button" className="jas-admin-secondary" disabled={pending} onClick={() => runRecoveryAction('clear_billing_links', 'Clear billing links')}>
                      Clear Billing Links
                    </button>
                  </div>
                </section>

                <div className="jas-admin-info-grid">
                  <section className="jas-admin-subsection">
                    <h3>Recent Sessions</h3>
                    {opsLoading && <p className="jas-admin-empty">Loading sessions...</p>}
                    {!opsLoading && sessions.length === 0 && <p className="jas-admin-empty">No sessions found.</p>}
                    {!opsLoading && sessions.length > 0 && (
                      <div className="jas-admin-list">
                        {sessions.map((session) => (
                          <div key={session.id || session.session_id} className="jas-admin-list-row">
                            <strong>{session.name || session.session_id}</strong>
                            <span>{session.status} • {session.document_type}</span>
                            <span>{session.updated_at ? new Date(session.updated_at).toLocaleString() : 'n/a'}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </section>

                  <section className="jas-admin-subsection">
                    <h3>Audit Trail</h3>
                    {opsLoading && <p className="jas-admin-empty">Loading audit...</p>}
                    {!opsLoading && auditEvents.length === 0 && <p className="jas-admin-empty">No audit events yet.</p>}
                    {!opsLoading && auditEvents.length > 0 && (
                      <div className="jas-admin-list">
                        {auditEvents.map((event, idx) => (
                          <div key={`${event.timestamp || 'event'}-${idx}`} className="jas-admin-list-row">
                            <strong>{event.action || 'event'}</strong>
                            <span>{event.actor_email || 'unknown actor'}</span>
                            <span>{event.timestamp ? new Date(event.timestamp).toLocaleString() : 'n/a'}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </section>
                </div>
              </>
            )}
          </div>
        </div>

        {selectedUser && (
          <p className="jas-admin-selected">
            Editing: <strong>{selectedUser.email}</strong> ({selectedUser.subscription_plan})
          </p>
        )}
      </div>
    </div>
  );
}
