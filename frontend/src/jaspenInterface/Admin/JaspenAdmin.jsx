import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { API_BASE } from '../../config/apiBase';
import { buildAuthHeaders } from '../../shared/auth/http';
import Feedback from './Feedback';
import './JaspenAdmin.css';


const PLAN_OPTIONS = ['free', 'essential', 'team', 'enterprise'];
const CREDIT_MODE_OPTIONS = [
  { value: 'adjust', label: 'Adjust (+/-)' },
  { value: 'set', label: 'Set exact value' },
  { value: 'reset_plan', label: 'Reset to plan default' },
];
const ROLE_EXPERIENCE_OPTIONS = [
  {
    label: 'Individual · Free',
    description: 'Personal workspace, 300 credits, Pluto only. No org features or shared dashboards.',
    path: '/new?admin_preview=workspace&plan_key=free',
  },
  {
    label: 'Individual · Essential',
    description: 'Personal workspace with higher limits and starter data-source access.',
    path: '/new?admin_preview=workspace&plan_key=essential',
  },
  {
    label: 'Team · Viewer',
    description: 'Read-only access to shared projects in the active team. No editing or admin controls.',
    path: '/new?admin_preview=workspace&plan_key=team&role=viewer',
  },
  {
    label: 'Team · Collaborator',
    description: 'Can interact inside shared projects in the active team, but cannot start new ones.',
    path: '/new?admin_preview=workspace&plan_key=team&role=collaborator',
  },
  {
    label: 'Team · Creator',
    description: 'Can create and develop projects in the active team, but cannot manage users or settings.',
    path: '/new?admin_preview=workspace&plan_key=team&role=creator',
  },
  {
    label: 'Team · Admin',
    description: 'Can manage team users and settings in the active org and create projects.',
    path: '/new?admin_preview=workspace&plan_key=team&role=admin',
  },
  {
    label: 'Enterprise · Viewer',
    description: 'Read-only access to shared enterprise projects using the active org data.',
    path: '/new?admin_preview=workspace&plan_key=enterprise&role=viewer',
  },
  {
    label: 'Enterprise · Collaborator',
    description: 'Can work inside shared enterprise projects but cannot start new ones.',
    path: '/new?admin_preview=workspace&plan_key=enterprise&role=collaborator',
  },
  {
    label: 'Enterprise · Creator',
    description: 'Can create and develop projects in the active enterprise org without org admin controls.',
    path: '/new?admin_preview=workspace&plan_key=enterprise&role=creator',
  },
  {
    label: 'Enterprise · Admin',
    description: 'Enterprise governance and admin controls using the active enterprise org.',
    path: '/enterprise-admin?admin_preview=enterprise&role=admin',
  },
];
const ACCESS_CONTROL_FIELDS = [
  {
    key: 'open_signup',
    label: 'Open signup',
    description: 'Anyone can create a Jaspen account unless another gate is turned on.',
  },
  {
    key: 'require_invite_code',
    label: 'Require invite code',
    description: 'New signups need a valid invite or referral code before they can get in.',
  },
  {
    key: 'require_admin_approval',
    label: 'Require admin approval',
    description: 'New signups land on the list first, and you decide when they can enter.',
  },
  {
    key: 'require_email_verification',
    label: 'Require email verification',
    description: 'New signups must verify their inbox before Jaspen treats the account as active.',
  },
];
const USER_STATUS_FILTERS = [
  { value: '', label: 'All users' },
  { value: 'active', label: 'Active' },
  { value: 'pending', label: 'Pending approval' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'deactivated', label: 'Deactivated' },
];


function authHeaders(extra = {}, method = 'GET') {
  return buildAuthHeaders(extra, method);
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
    deactivated_at: user.deactivated_at || null,
    recovery_expires_at: user.recovery_expires_at || null,
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
  const [userStatusFilter, setUserStatusFilter] = useState('');
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
  const [feedbackItems, setFeedbackItems] = useState([]);
  const [feedbackSummary, setFeedbackSummary] = useState(null);
  const [feedbackLoading, setFeedbackLoading] = useState(false);
  const [feedbackQuery, setFeedbackQuery] = useState('');
  const [feedbackValueFilter, setFeedbackValueFilter] = useState('');
  const [accessControls, setAccessControls] = useState(null);
  const [accessReview, setAccessReview] = useState(null);
  const [accessLoading, setAccessLoading] = useState(false);
  const [accessPending, setAccessPending] = useState(false);

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

  const pendingAccessCount = Number(accessReview?.pending_count || 0);
  const rejectedAccessCount = Number(accessReview?.rejected_count || 0);

  const applySavedUser = (saved) => {
    if (!saved?.id) return;
    setUsers((prev) => prev.map((u) => (u.id === saved.id ? saved : u)));
    setDraft(toDraft(saved));
    setSelectedId(saved.id);
  };

  const loadUsers = async (nextQuery = query, nextStatus = userStatusFilter) => {
    const response = await fetch(
      `${API_BASE}/api/v1/admin/users?limit=200&q=${encodeURIComponent(nextQuery || '')}&status=${encodeURIComponent(nextStatus || '')}`,
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
        fetch(`${API_BASE}/api/v1/admin/users/${encodeURIComponent(userId)}/connectors`, {
          headers: authHeaders(),
          credentials: 'include',
        }),
        fetch(`${API_BASE}/api/v1/admin/users/${encodeURIComponent(userId)}/sessions?limit=20`, {
          headers: authHeaders(),
          credentials: 'include',
        }),
        fetch(`${API_BASE}/api/v1/admin/audit?user_id=${encodeURIComponent(userId)}&limit=25`, {
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

  const loadFeedback = async ({ userId = selectedId, q = feedbackQuery, value = feedbackValueFilter } = {}) => {
    setFeedbackLoading(true);
    try {
      const params = new URLSearchParams();
      params.set('limit', '100');
      if (userId) params.set('user_id', userId);
      if (q) params.set('q', q);
      if (value) params.set('value', value);
      const response = await fetch(`${API_BASE}/api/v1/admin/message-feedback?${params.toString()}`, {
        headers: authHeaders(),
        credentials: 'include',
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data?.error || 'Unable to load feedback.');
      setFeedbackItems(Array.isArray(data?.items) ? data.items : []);
      setFeedbackSummary(data?.summary || null);
    } catch (error) {
      setMessage(error.message || 'Unable to load feedback.');
    } finally {
      setFeedbackLoading(false);
    }
  };

  const loadAccessControls = async () => {
    setAccessLoading(true);
    try {
      const response = await fetch(`${API_BASE}/api/v1/admin/access-controls`, {
        headers: authHeaders(),
        credentials: 'include',
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data?.error || 'Unable to load Access Controls.');
      setAccessControls(data?.controls || null);
      setAccessReview(data?.review || null);
    } catch (error) {
      setMessage(error.message || 'Unable to load Access Controls.');
    } finally {
      setAccessLoading(false);
    }
  };

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const capRes = await fetch(`${API_BASE}/api/v1/admin/capabilities`, {
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
          await loadFeedback({ userId: '', q: '', value: '' });
          await loadAccessControls();
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

  useEffect(() => {
    const handle = window.setTimeout(() => {
      loadFeedback();
    }, 250);
    return () => window.clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [feedbackQuery, feedbackValueFilter, selectedId]);

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

      const response = await fetch(`${API_BASE}/api/v1/admin/users/${encodeURIComponent(draft.id)}`, {
        method: 'PATCH',
        headers: authHeaders({ 'Content-Type': 'application/json' }, 'PATCH'),
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
      const response = await fetch(`${API_BASE}/api/v1/admin/users/${encodeURIComponent(draft.id)}/force-plan`, {
        method: 'POST',
        headers: authHeaders({ 'Content-Type': 'application/json' }, 'POST'),
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
      const response = await fetch(`${API_BASE}/api/v1/admin/users/${encodeURIComponent(draft.id)}/credits`, {
        method: 'POST',
        headers: authHeaders({ 'Content-Type': 'application/json' }, 'POST'),
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
        `${API_BASE}/api/v1/admin/users/${encodeURIComponent(draft.id)}/connectors/${encodeURIComponent(connectorId)}`,
        {
          method: 'PATCH',
          headers: authHeaders({ 'Content-Type': 'application/json' }, 'PATCH'),
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
      const response = await fetch(`${API_BASE}/api/v1/admin/users/${encodeURIComponent(draft.id)}/recovery`, {
        method: 'POST',
        headers: authHeaders({ 'Content-Type': 'application/json' }, 'POST'),
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

  const deactivateUser = async () => {
    if (!draft?.id) return;
    const reason = String(recoveryReason || '').trim();
    if (!reason) {
      setMessage('A reason is required before deactivating a user.');
      return;
    }
    if (!window.confirm(`Deactivate ${draft.email}? Their sessions will be invalidated, but their data will stay recoverable for 30 days.`)) {
      return;
    }

    setPending(true);
    setMessage('');
    try {
      const response = await fetch(`${API_BASE}/api/v1/admin/users/${encodeURIComponent(draft.id)}/deactivate`, {
        method: 'POST',
        headers: authHeaders({ 'Content-Type': 'application/json' }, 'POST'),
        credentials: 'include',
        body: JSON.stringify({ reason, recovery_days: 30 }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data?.error || 'Unable to deactivate user.');
      applySavedUser(data?.user);
      await loadUsers(query);
      setMessage(`Deactivated ${data?.user?.email || 'user'}.`);
    } catch (error) {
      setMessage(error.message || 'Unable to deactivate user.');
    } finally {
      setPending(false);
    }
  };

  const restoreUser = async () => {
    if (!draft?.id) return;
    if (!window.confirm(`Restore ${draft.email}? This will reopen account access.`)) {
      return;
    }

    setPending(true);
    setMessage('');
    try {
      const response = await fetch(`${API_BASE}/api/v1/admin/users/${encodeURIComponent(draft.id)}/restore`, {
        method: 'POST',
        headers: authHeaders({ 'Content-Type': 'application/json' }, 'POST'),
        credentials: 'include',
        body: JSON.stringify({ reason: String(recoveryReason || '').trim() || undefined }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data?.error || 'Unable to restore user.');
      applySavedUser(data?.user);
      await loadUsers(query);
      setMessage(`Restored ${data?.user?.email || 'user'}.`);
    } catch (error) {
      setMessage(error.message || 'Unable to restore user.');
    } finally {
      setPending(false);
    }
  };

  const saveAccessControls = async () => {
    if (!accessControls) return;
    setAccessPending(true);
    setMessage('');
    try {
      const response = await fetch(`${API_BASE}/api/v1/admin/access-controls`, {
        method: 'PATCH',
        headers: authHeaders({ 'Content-Type': 'application/json' }, 'PATCH'),
        credentials: 'include',
        body: JSON.stringify(accessControls),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data?.error || 'Unable to save Access Controls.');
      setAccessControls(data?.controls || accessControls);
      setAccessReview(data?.review || accessReview);
      setMessage('Saved Access Controls.');
    } catch (error) {
      setMessage(error.message || 'Unable to save Access Controls.');
    } finally {
      setAccessPending(false);
    }
  };

  const reviewUserAccess = async (userId, status) => {
    if (!userId || !status) return;
    setAccessPending(true);
    setMessage('');
    try {
      const response = await fetch(`${API_BASE}/api/v1/admin/users/${encodeURIComponent(userId)}`, {
        method: 'PATCH',
        headers: authHeaders({ 'Content-Type': 'application/json' }, 'PATCH'),
        credentials: 'include',
        body: JSON.stringify({ access_approval_status: status }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data?.error || 'Unable to update access review status.');
      applySavedUser(data?.user);
      await loadUsers(query);
      await loadAccessControls();
      setMessage(`Updated access review for ${data?.user?.email || 'user'}.`);
    } catch (error) {
      setMessage(error.message || 'Unable to update access review status.');
    } finally {
      setAccessPending(false);
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
          <select
            value={userStatusFilter}
            onChange={(e) => setUserStatusFilter(e.target.value)}
            aria-label="Filter users by status"
          >
            {USER_STATUS_FILTERS.map((option) => (
              <option key={option.value || 'all'} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <button type="button" className="jas-admin-secondary" onClick={() => loadUsers(query, userStatusFilter)} disabled={pending}>
            Search
          </button>
        </div>

        {message && <p className="jas-admin-message">{message}</p>}

        <section className="jas-admin-subsection">
          <div className="jas-admin-section-head">
            <div>
              <h3>Access Controls</h3>
              <p className="jas-admin-empty">
                Shift between open, invite-led, and reviewed access without redeploying Jaspen.
              </p>
            </div>
            <div className="jas-admin-actions">
              <button type="button" className="jas-admin-secondary" onClick={loadAccessControls} disabled={accessLoading || accessPending}>
                {accessLoading ? 'Refreshing...' : 'Refresh'}
              </button>
              <button type="button" className="jas-admin-primary" onClick={saveAccessControls} disabled={accessLoading || accessPending || !accessControls}>
                {accessPending ? 'Saving...' : 'Save Access Controls'}
              </button>
            </div>
          </div>

          <div className="jas-admin-access-grid">
            {ACCESS_CONTROL_FIELDS.map((field) => (
              <label key={field.key} className="jas-admin-access-card">
                <div className="jas-admin-access-copy">
                  <strong>{field.label}</strong>
                  <span>{field.description}</span>
                </div>
                <input
                  type="checkbox"
                  checked={Boolean(accessControls?.[field.key])}
                  onChange={(e) => setAccessControls((prev) => ({ ...(prev || {}), [field.key]: e.target.checked }))}
                  disabled={!accessControls || accessLoading || accessPending}
                />
              </label>
            ))}
          </div>

          <div className="jas-admin-review-grid">
            <div className="jas-admin-review-summary">
              <strong>{pendingAccessCount}</strong>
              <span>Waiting for review</span>
            </div>
            <div className="jas-admin-review-summary">
              <strong>{rejectedAccessCount}</strong>
              <span>Not confirmed</span>
            </div>
          </div>

          <div className="jas-admin-access-review">
            {(accessReview?.items || []).length === 0 && (
              <p className="jas-admin-empty">No access requests need attention right now.</p>
            )}
            {(accessReview?.items || []).map((item) => (
              <div key={item.id} className="jas-admin-review-row">
                <button
                  type="button"
                  className="jas-admin-review-meta"
                  onClick={() => handleSelectUser(item)}
                >
                  <strong>{item.email}</strong>
                  <span>{item.name || 'No name yet'}</span>
                  <span>
                    {item.signup_referral_code_used ? `Referred via ${item.signup_referral_code_used}` : 'No invite code used'}
                  </span>
                </button>
                <span className={`jas-admin-status-badge is-${item.access_approval_status || 'pending'}`}>
                  {item.access_approval_status || 'pending'}
                </span>
                <div className="jas-admin-actions">
                  {item.access_approval_status !== 'approved' && (
                    <button
                      type="button"
                      className="jas-admin-primary"
                      onClick={() => reviewUserAccess(item.id, 'approved')}
                      disabled={accessPending}
                    >
                      Approve
                    </button>
                  )}
                  {item.access_approval_status !== 'pending' && (
                    <button
                      type="button"
                      className="jas-admin-secondary"
                      onClick={() => reviewUserAccess(item.id, 'pending')}
                      disabled={accessPending}
                    >
                      Move to list
                    </button>
                  )}
                  {item.access_approval_status !== 'rejected' && (
                    <button
                      type="button"
                      className="jas-admin-secondary"
                      onClick={() => reviewUserAccess(item.id, 'rejected')}
                      disabled={accessPending}
                    >
                      Reject
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="jas-admin-subsection">
          <h3>Role Experience Preview</h3>
          <p className="jas-admin-empty">
            Preview the customer-facing interface using your active organization data and the selected role restrictions.
          </p>
          <div className="jas-admin-role-grid">
            {ROLE_EXPERIENCE_OPTIONS.map((option) => (
              <div key={option.label} className="jas-admin-role-card">
                <strong>{option.label}</strong>
                <p>{option.description}</p>
                <button
                  type="button"
                  className="jas-admin-secondary"
                  onClick={() => openPreview(option.path)}
                >
                  Preview
                </button>
              </div>
            ))}
          </div>
        </section>

        <Feedback
          items={feedbackItems}
          summary={feedbackSummary}
          isLoading={feedbackLoading}
          query={feedbackQuery}
          onQueryChange={setFeedbackQuery}
          onRefresh={() => loadFeedback()}
          valueFilter={feedbackValueFilter}
          onValueFilterChange={setFeedbackValueFilter}
          scopedUserLabel={selectedUser?.email || ''}
        />

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
                  <span>{user.deactivated_at ? 'deactivated' : (user.access_approval_status || 'approved')}</span>
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
                            <div className="jas-admin-connector-actions">
                              <label className="jas-admin-check-inline">
                                <input
                                  type="checkbox"
                                  checked={Boolean(cd.auto_sync)}
                                  onChange={(e) => handleConnectorDraftChange(connectorId, 'auto_sync', e.target.checked)}
                                />
                                <span>Auto sync</span>
                              </label>
                              <button
                                type="button"
                                className="jas-admin-connector-save"
                                disabled={connectorPendingId === connectorId}
                                onClick={() => saveConnector(connectorId)}
                              >
                                {connectorPendingId === connectorId ? 'Saving…' : 'Save'}
                              </button>
                            </div>
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
                  {draft.deactivated_at && (
                    <p className="jas-admin-empty">
                      Deactivated until recovery window closes: {draft.recovery_expires_at ? new Date(draft.recovery_expires_at).toLocaleString() : 'n/a'}
                    </p>
                  )}
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
                    {!draft.deactivated_at && (
                      <button type="button" className="jas-admin-secondary jas-admin-danger" disabled={pending} onClick={deactivateUser}>
                        Deactivate User
                      </button>
                    )}
                    {draft.deactivated_at && (
                      <button type="button" className="jas-admin-primary" disabled={pending} onClick={restoreUser}>
                        Restore User
                      </button>
                    )}
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
