import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { API_BASE } from '../../config/apiBase';
import './JaspenAdmin.css';


const PLAN_OPTIONS = ['free', 'essential', 'team', 'enterprise'];


function getToken() {
  return localStorage.getItem('access_token') || localStorage.getItem('token');
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
    stripe_customer_id: user.stripe_customer_id || '',
    stripe_subscription_id: user.stripe_subscription_id || '',
  };
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
  const [message, setMessage] = useState('');

  const selectedUser = useMemo(
    () => (users || []).find((u) => u.id === selectedId) || null,
    [users, selectedId],
  );

  const loadUsers = async (nextQuery = query) => {
    const token = getToken();
    const response = await fetch(
      `${API_BASE}/api/admin/users?limit=200&q=${encodeURIComponent(nextQuery || '')}`,
      {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
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

  useEffect(() => {
    let mounted = true;
    (async () => {
      const token = getToken();
      try {
        const capRes = await fetch(`${API_BASE}/api/admin/capabilities`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
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
  };

  const handleSave = async () => {
    if (!draft?.id) return;
    const token = getToken();
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
        throw new Error(data?.error || 'Unable to save user changes.');
      }
      const saved = data?.user;
      if (saved?.id) {
        setUsers((prev) => prev.map((u) => (u.id === saved.id ? saved : u)));
        setDraft(toDraft(saved));
        setSelectedId(saved.id);
      }
      setMessage(`Saved ${saved?.email || 'user'}.`);
    } catch (error) {
      setMessage(error.message || 'Unable to save user changes.');
    } finally {
      setPending(false);
    }
  };

  const forcePlan = async (planKey, resetCredits = true) => {
    if (!draft?.id) return;
    const token = getToken();
    setPending(true);
    setMessage('');
    try {
      const response = await fetch(`${API_BASE}/api/admin/users/${encodeURIComponent(draft.id)}/force-plan`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        credentials: 'include',
        body: JSON.stringify({ plan_key: planKey, reset_credits: resetCredits }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data?.error || 'Unable to force plan.');
      }
      const saved = data?.user;
      if (saved?.id) {
        setUsers((prev) => prev.map((u) => (u.id === saved.id ? saved : u)));
        setDraft(toDraft(saved));
        setSelectedId(saved.id);
      }
      setMessage(`Set ${saved?.email || 'user'} to ${planKey}.`);
    } catch (error) {
      setMessage(error.message || 'Unable to force plan.');
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
            <p className="jas-admin-sub">Search users and directly manage tier, credits, seats, and auth-linked billing fields.</p>
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
            {!draft && (
              <p className="jas-admin-empty">Select a user to edit.</p>
            )}
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
                      placeholder="Leave blank for unlimited"
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
                  <label>
                    Stripe customer id
                    <input
                      type="text"
                      value={draft.stripe_customer_id}
                      onChange={(e) => setDraft((prev) => ({ ...prev, stripe_customer_id: e.target.value }))}
                    />
                  </label>
                  <label>
                    Stripe subscription id
                    <input
                      type="text"
                      value={draft.stripe_subscription_id}
                      onChange={(e) => setDraft((prev) => ({ ...prev, stripe_subscription_id: e.target.value }))}
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
                  <button
                    type="button"
                    className="jas-admin-secondary"
                    onClick={() => {
                      setDraft((prev) => ({ ...prev, credits_remaining: '' }));
                      setMessage('Set credits blank, then click Save user for unlimited.');
                    }}
                    disabled={pending}
                  >
                    Set Unlimited Credits
                  </button>
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

