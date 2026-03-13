import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { API_BASE } from '../../config/apiBase';
import './Team.css';

const ROLE_OPTIONS = ['owner', 'admin', 'creator', 'collaborator', 'viewer'];
const INVITE_ROLE_OPTIONS = ['admin', 'creator', 'collaborator', 'viewer'];
const VISIBILITY_OPTIONS = ['private', 'team', 'specific'];
const SEAT_EDITABLE_ROLES = ROLE_OPTIONS.filter((role) => role !== 'owner');
const SEAT_MODE_DEFAULT = 'default';
const SEAT_MODE_LIMITED = 'limited';
const SEAT_MODE_UNLIMITED = 'unlimited';
const PREVIEW_ROLE_ACTUAL = '__actual__';
const MANAGE_ROLE_SET = new Set(['owner', 'admin']);
const EDIT_ROLE_SET = new Set(['owner', 'admin', 'creator', 'collaborator']);

async function teamFetch(path, options = {}) {
  const token = localStorage.getItem('access_token') || localStorage.getItem('token');
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
    ...options,
  });

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = payload?.error || payload?.message || `${response.status} ${response.statusText}`;
    throw new Error(message);
  }
  return payload;
}

function limitLabel(limit, isUnlimited) {
  if (isUnlimited || limit == null) return 'Unlimited';
  return String(limit);
}

function formatDate(value) {
  if (!value) return '—';
  const parsed = new Date(value);
  if (!Number.isFinite(parsed.getTime())) return '—';
  return parsed.toLocaleString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

function normalizeCsvIds(value) {
  const values = String(value || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
  return [...new Set(values)];
}

function buildSeatDraft(organization) {
  const policy = organization?.seat_policy || {};
  const defaults = organization?.seat_policy_defaults || {};
  const next = {};
  SEAT_EDITABLE_ROLES.forEach((role) => {
    const row = policy?.[role] || {};
    const baseline = defaults?.[role] || {};
    const unlimited = Boolean(row?.is_unlimited || row?.limit == null);
    const baselineUnlimited = Boolean(baseline?.is_unlimited || baseline?.limit == null);
    const baselineLimit = baselineUnlimited ? null : Number(baseline?.limit);
    const rowLimit = unlimited ? null : Number(row?.limit);
    const sameAsDefault =
      (baselineUnlimited && unlimited) ||
      (!baselineUnlimited && !unlimited && Number.isFinite(baselineLimit) && Number.isFinite(rowLimit) && baselineLimit === rowLimit);

    const mode = sameAsDefault
      ? (baselineUnlimited ? SEAT_MODE_UNLIMITED : SEAT_MODE_DEFAULT)
      : (unlimited ? SEAT_MODE_UNLIMITED : SEAT_MODE_LIMITED);
    next[role] = {
      mode,
      limit: unlimited ? '' : String(row?.limit ?? ''),
    };
  });
  return next;
}

export default function Team({ mode = 'team' }) {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const [summary, setSummary] = useState(null);
  const [members, setMembers] = useState([]);
  const [invitations, setInvitations] = useState([]);
  const [organizations, setOrganizations] = useState([]);
  const [projects, setProjects] = useState([]);

  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteRole, setInviteRole] = useState('collaborator');
  const [sharingDrafts, setSharingDrafts] = useState({});
  const [isGlobalAdmin, setIsGlobalAdmin] = useState(false);
  const [previewRole, setPreviewRole] = useState(PREVIEW_ROLE_ACTUAL);
  const [seatDraft, setSeatDraft] = useState({});
  const [savedSeatDraft, setSavedSeatDraft] = useState({});

  const actualRole = String(summary?.membership?.role || 'viewer');
  const previewModeActive = Boolean(isGlobalAdmin && previewRole !== PREVIEW_ROLE_ACTUAL);
  const effectiveRole = previewModeActive ? previewRole : actualRole;
  const canManageMembers = MANAGE_ROLE_SET.has(effectiveRole);
  const canEditProjects = EDIT_ROLE_SET.has(effectiveRole);
  const isEnterpriseMode = String(mode || '').toLowerCase() === 'enterprise';
  const activeOrg = summary?.organization || null;
  const activeOrgPlanKey = String(activeOrg?.plan_key || '').toLowerCase();
  const canAccessEnterpriseView = isGlobalAdmin || activeOrgPlanKey === 'enterprise';
  const seatPolicyDefaults = activeOrg?.seat_policy_defaults || {};
  const seatUsage = summary?.seat_usage || {};
  const seatDraftDirty = useMemo(
    () => JSON.stringify(seatDraft || {}) !== JSON.stringify(savedSeatDraft || {}),
    [seatDraft, savedSeatDraft]
  );
  const canEditSeatPolicy = canManageMembers && !previewModeActive && (!isEnterpriseMode || canAccessEnterpriseView);
  const pendingInvitations = useMemo(
    () => (invitations || []).filter((row) => row?.status === 'pending'),
    [invitations]
  );

  const memberIdSet = useMemo(
    () => new Set((members || []).map((member) => String(member?.user_id || ''))),
    [members]
  );

  const loadAll = async () => {
    setLoading(true);
    setError('');
    try {
      const [summaryData, membersData, invitationsData, organizationsData, projectsData] = await Promise.all([
        teamFetch('/api/team/summary'),
        teamFetch('/api/team/members'),
        teamFetch('/api/team/invitations'),
        teamFetch('/api/team/organizations'),
        teamFetch('/api/team/projects'),
      ]);
      const adminCapsData = await teamFetch('/api/admin/capabilities').catch(() => ({}));

      setSummary(summaryData || null);
      const nextSeatDraft = buildSeatDraft(summaryData?.organization || null);
      setSeatDraft(nextSeatDraft);
      setSavedSeatDraft(nextSeatDraft);
      setMembers(Array.isArray(membersData?.members) ? membersData.members : []);
      setInvitations(Array.isArray(invitationsData?.invitations) ? invitationsData.invitations : []);
      setOrganizations(Array.isArray(organizationsData?.organizations) ? organizationsData.organizations : []);
      const nextIsGlobalAdmin = Boolean(adminCapsData?.is_admin);
      setIsGlobalAdmin(nextIsGlobalAdmin);
      if (!nextIsGlobalAdmin) setPreviewRole(PREVIEW_ROLE_ACTUAL);
      const loadedProjects = Array.isArray(projectsData?.projects) ? projectsData.projects : [];
      setProjects(loadedProjects);

      const nextDrafts = {};
      loadedProjects.forEach((project) => {
        const shared = Array.isArray(project?.shared_with_user_ids) ? project.shared_with_user_ids : [];
        nextDrafts[project.session_id] = {
          visibility: String(project?.visibility || 'private'),
          sharedWithCsv: shared.join(', '),
        };
      });
      setSharingDrafts(nextDrafts);
    } catch (err) {
      setError(err?.message || 'Failed to load team data');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAll();
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const inviteToken = String(params.get('invite') || '').trim();
    if (!inviteToken) return;

    let cancelled = false;
    (async () => {
      setBusy(true);
      setNotice('');
      setError('');
      try {
        await teamFetch('/api/team/invitations/accept', {
          method: 'POST',
          body: JSON.stringify({ token: inviteToken }),
        });
        if (cancelled) return;
        setNotice('Invitation accepted. You are now part of this organization.');
        await loadAll();
      } catch (err) {
        if (!cancelled) setError(err?.message || 'Could not accept invitation');
      } finally {
        if (!cancelled) setBusy(false);
        const next = `${window.location.pathname}`;
        window.history.replaceState({}, '', next);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const onSwitchOrganization = async (orgId) => {
    if (!orgId) return;
    setBusy(true);
    setNotice('');
    setError('');
    try {
      await teamFetch('/api/team/organizations/active', {
        method: 'POST',
        body: JSON.stringify({ organization_id: orgId }),
      });
      await loadAll();
      setNotice('Switched active organization.');
    } catch (err) {
      setError(err?.message || 'Could not switch organization');
    } finally {
      setBusy(false);
    }
  };

  const onInvite = async (event) => {
    event.preventDefault();
    if (!canManageMembers || previewModeActive) return;
    setBusy(true);
    setNotice('');
    setError('');
    try {
      const result = await teamFetch('/api/team/invitations', {
        method: 'POST',
        body: JSON.stringify({ email: inviteEmail, role: inviteRole }),
      });
      setInviteEmail('');
      setInviteRole('collaborator');
      await loadAll();
      const token = result?.invitation?.token;
      setNotice(token ? `Invite sent. Token: ${token}` : 'Invite sent.');
    } catch (err) {
      setError(err?.message || 'Failed to send invite');
    } finally {
      setBusy(false);
    }
  };

  const onRoleChange = async (memberId, role) => {
    if (!canManageMembers || previewModeActive) return;
    setBusy(true);
    setNotice('');
    setError('');
    try {
      await teamFetch(`/api/team/members/${memberId}`, {
        method: 'PATCH',
        body: JSON.stringify({ role }),
      });
      await loadAll();
      setNotice('Member role updated.');
    } catch (err) {
      setError(err?.message || 'Failed to update role');
    } finally {
      setBusy(false);
    }
  };

  const onRemoveMember = async (member) => {
    if (!canManageMembers || previewModeActive) return;
    const label = member?.user?.name || member?.user?.email || member?.user_id;
    if (!window.confirm(`Remove ${label} from this team?`)) return;
    setBusy(true);
    setNotice('');
    setError('');
    try {
      await teamFetch(`/api/team/members/${member.id}`, { method: 'DELETE' });
      await loadAll();
      setNotice('Member removed.');
    } catch (err) {
      setError(err?.message || 'Failed to remove member');
    } finally {
      setBusy(false);
    }
  };

  const onRevokeInvitation = async (invitationId) => {
    if (!canManageMembers || previewModeActive) return;
    if (!window.confirm('Revoke this invitation?')) return;
    setBusy(true);
    setNotice('');
    setError('');
    try {
      await teamFetch(`/api/team/invitations/${invitationId}/revoke`, { method: 'POST' });
      await loadAll();
      setNotice('Invitation revoked.');
    } catch (err) {
      setError(err?.message || 'Failed to revoke invitation');
    } finally {
      setBusy(false);
    }
  };

  const onSharingDraftChange = (sessionId, patch) => {
    setSharingDrafts((prev) => ({
      ...prev,
      [sessionId]: {
        visibility: prev?.[sessionId]?.visibility || 'private',
        sharedWithCsv: prev?.[sessionId]?.sharedWithCsv || '',
        ...patch,
      },
    }));
  };

  const onSeatModeChange = (role, nextMode) => {
    if (!SEAT_EDITABLE_ROLES.includes(role)) return;
    const baseline = seatPolicyDefaults?.[role] || {};
    const baselineUnlimited = Boolean(baseline?.is_unlimited || baseline?.limit == null);
    const baselineLimit = baselineUnlimited ? '' : String(baseline?.limit ?? '');
    setSeatDraft((prev) => ({
      ...prev,
      [role]: {
        mode: nextMode,
        limit: nextMode === SEAT_MODE_LIMITED
          ? (prev?.[role]?.limit || String((seatUsage?.[role]?.used ?? 1)))
          : (nextMode === SEAT_MODE_DEFAULT ? baselineLimit : ''),
      },
    }));
  };

  const onSeatLimitChange = (role, nextLimit) => {
    if (!SEAT_EDITABLE_ROLES.includes(role)) return;
    setSeatDraft((prev) => ({
      ...prev,
      [role]: {
        mode: SEAT_MODE_LIMITED,
        limit: nextLimit,
      },
    }));
  };

  const onDiscardSeatPolicy = () => {
    setSeatDraft(savedSeatDraft || {});
    setError('');
    setNotice('Seat policy edits discarded.');
  };

  const onResetSeatPolicy = async () => {
    if (!canManageMembers || previewModeActive) return;
    setBusy(true);
    setNotice('');
    setError('');
    try {
      await teamFetch('/api/team/seat-policy', {
        method: 'PATCH',
        body: JSON.stringify({ seat_policy_overrides: {} }),
      });
      await loadAll();
      setNotice('Seat policy reset to plan defaults.');
    } catch (err) {
      setError(err?.message || 'Failed to reset seat policy');
    } finally {
      setBusy(false);
    }
  };

  const onSaveSeatPolicy = async () => {
    if (!canEditSeatPolicy) return;

    const payload = {};
    for (const role of SEAT_EDITABLE_ROLES) {
      const draft = seatDraft?.[role] || {};
      const baseline = seatPolicyDefaults?.[role] || {};
      const baselineUnlimited = Boolean(baseline?.is_unlimited || baseline?.limit == null);
      const baselineLimit = baselineUnlimited ? null : Number(baseline?.limit);

      if (draft.mode === SEAT_MODE_DEFAULT) {
        payload[role] = null;
        continue;
      }
      if (draft.mode === SEAT_MODE_UNLIMITED) {
        if (!baselineUnlimited) {
          setError(`Unlimited is not available for ${role} on the ${activeOrgPlanKey || 'current'} plan.`);
          return;
        }
        payload[role] = null;
        continue;
      }
      const next = Number.parseInt(String(draft.limit || '').trim(), 10);
      if (!Number.isFinite(next) || next < 0) {
        setError(`Seat limit for ${role} must be a non-negative integer.`);
        return;
      }
      if (!baselineUnlimited && Number.isFinite(baselineLimit) && next > baselineLimit) {
        setError(`Seat limit for ${role} cannot exceed plan cap (${baselineLimit}).`);
        return;
      }
      if (!baselineUnlimited && Number.isFinite(baselineLimit) && next === baselineLimit) {
        payload[role] = null;
        continue;
      }
      payload[role] = next;
    }

    setBusy(true);
    setNotice('');
    setError('');
    try {
      await teamFetch('/api/team/seat-policy', {
        method: 'PATCH',
        body: JSON.stringify({ seat_policy_overrides: payload }),
      });
      await loadAll();
      setNotice('Seat policy updated.');
    } catch (err) {
      setError(err?.message || 'Failed to update seat policy');
    } finally {
      setBusy(false);
    }
  };

  const onSaveSharing = async (sessionId) => {
    if (!canEditProjects || previewModeActive) return;
    const draft = sharingDrafts?.[sessionId] || {};
    const visibility = String(draft.visibility || 'private');
    const sharedIds = normalizeCsvIds(draft.sharedWithCsv || '').filter((id) => memberIdSet.has(id));

    setBusy(true);
    setNotice('');
    setError('');
    try {
      await teamFetch(`/api/team/projects/${encodeURIComponent(sessionId)}/sharing`, {
        method: 'PATCH',
        body: JSON.stringify({
          visibility,
          shared_with_user_ids: sharedIds,
        }),
      });
      await loadAll();
      setNotice('Project visibility updated.');
    } catch (err) {
      setError(err?.message || 'Failed to update project visibility');
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <div className="team-page">
        <div className="team-panel">
          <div className="team-state">Loading team data…</div>
        </div>
      </div>
    );
  }

  const activePlanLabel = activeOrgPlanKey
    ? `${activeOrgPlanKey.charAt(0).toUpperCase()}${activeOrgPlanKey.slice(1)}`
    : 'Current';

  return (
    <div className="team-page">
      <div className="team-panel">
      <header className="team-head">
        <div>
          <p className="team-eyebrow">{isEnterpriseMode ? 'Jaspen Enterprise' : 'Jaspen Team'}</p>
          <h1>{isEnterpriseMode ? 'Enterprise Admin' : 'Team'}</h1>
          <p className="team-sub">
            {isEnterpriseMode
              ? 'Manage enterprise role capacity, members, invitations, and shared project visibility.'
              : 'Manage members, invitations, role capacity, and shared project visibility.'}
          </p>
        </div>
        <button type="button" className="team-btn ghost team-back-btn" onClick={() => navigate('/new')}>
          Back to Jaspen
        </button>
      </header>

      <section className="team-toolbar">
        <div className="team-toolbar-fields">
          <label className="team-inline-field">
            <span>Organization</span>
            <select
              value={activeOrg?.id || ''}
              onChange={(event) => onSwitchOrganization(event.target.value)}
              disabled={busy}
            >
              {(organizations || []).map((entry) => (
                <option key={entry?.organization?.id} value={entry?.organization?.id}>
                  {entry?.organization?.name || 'Organization'}
                </option>
              ))}
            </select>
          </label>
          {isGlobalAdmin && (
            <label className="team-inline-field">
              <span>Role Preview</span>
              <select
                value={previewRole}
                onChange={(event) => setPreviewRole(event.target.value)}
                disabled={busy}
              >
                <option value={PREVIEW_ROLE_ACTUAL}>Actual ({actualRole})</option>
                {ROLE_OPTIONS.map((role) => (
                  <option key={role} value={role}>{role}</option>
                ))}
              </select>
            </label>
          )}
        </div>
      </section>

      {(error || notice) && (
        <div className={`team-state ${error ? 'error' : 'success'}`}>
          {error || notice}
        </div>
      )}

      {previewModeActive && (
        <div className="team-state team-state-preview">
          Preview mode active: viewing Team as <strong>{effectiveRole}</strong>. Mutating actions are disabled in preview mode.
        </div>
      )}

      {isEnterpriseMode && !canAccessEnterpriseView && (
        <div className="team-state error">
          Enterprise Admin requires an Enterprise organization. Switch to an Enterprise org or upgrade in Billing.
        </div>
      )}

      {canManageMembers && (
        <section className={`team-seat-policy-bar ${seatDraftDirty ? 'is-dirty' : ''}`}>
          <div className="team-seat-policy-copy">
            <strong>{seatDraftDirty ? 'Unsaved seat policy changes' : 'Seat policy saved'}</strong>
            <span>Plan defaults ({activePlanLabel}) are enforced: Team (2/5/10/Unlimited), Enterprise (5/25/Unlimited/Unlimited).</span>
          </div>
          <div className="team-seat-policy-actions">
            <button
              type="button"
              className="team-btn ghost"
              onClick={onDiscardSeatPolicy}
              disabled={busy || !seatDraftDirty || !canEditSeatPolicy}
            >
              Discard changes
            </button>
            <button
              type="button"
              className="team-btn"
              onClick={onSaveSeatPolicy}
              disabled={busy || !seatDraftDirty || !canEditSeatPolicy}
            >
              {busy ? 'Saving…' : 'Save seat policy'}
            </button>
            <button
              type="button"
              className="team-btn ghost"
              onClick={onResetSeatPolicy}
              disabled={busy || !canEditSeatPolicy}
            >
              Reset to plan defaults
            </button>
          </div>
        </section>
      )}

      <section className="team-seat-grid">
        {ROLE_OPTIONS.map((role) => {
          const row = seatUsage?.[role] || {};
          const draft = seatDraft?.[role] || {};
          const saved = savedSeatDraft?.[role] || {};
          const defaultRow = seatPolicyDefaults?.[role] || {};
          const defaultLabel = limitLabel(defaultRow?.limit, defaultRow?.is_unlimited);
          const baselineUnlimited = Boolean(defaultRow?.is_unlimited || defaultRow?.limit == null);
          const maxCap = baselineUnlimited ? null : Number(defaultRow?.limit);
          const canEditSeatRole = canEditSeatPolicy && role !== 'owner';
          const roleIsDirty = role !== 'owner' && JSON.stringify(draft || {}) !== JSON.stringify(saved || {});
          const pendingLabel = draft?.mode === SEAT_MODE_LIMITED
            ? (String(draft?.limit || '').trim() || '—')
            : (draft?.mode === SEAT_MODE_DEFAULT ? defaultLabel : 'Unlimited');
          const roleMode = draft?.mode || (baselineUnlimited ? SEAT_MODE_UNLIMITED : SEAT_MODE_DEFAULT);
          return (
            <article key={role} className="team-seat-card">
              <h3>{row?.label || role}</h3>
              <p className="team-seat-main">
                {row?.used ?? 0} / {limitLabel(row?.limit, row?.is_unlimited)}
              </p>
              <p className="team-seat-sub">
                {row?.is_unlimited ? 'No cap for this role' : `${row?.available ?? 0} seats remaining`}
              </p>
              <p className="team-seat-meta">Plan default: {defaultLabel}</p>
              {role !== 'owner' && (
                <p className={`team-seat-meta ${roleIsDirty ? 'is-pending' : ''}`}>
                  {roleIsDirty ? `Pending: ${pendingLabel}` : `Current policy: ${limitLabel(row?.limit, row?.is_unlimited)}`}
                </p>
              )}
              {canEditSeatRole && (
                <div className="team-seat-editor">
                  <select
                    value={roleMode}
                    onChange={(event) => onSeatModeChange(role, event.target.value)}
                    disabled={busy}
                  >
                    {baselineUnlimited ? (
                      <option value={SEAT_MODE_UNLIMITED}>Unlimited (plan default)</option>
                    ) : (
                      <option value={SEAT_MODE_DEFAULT}>Plan default ({defaultLabel})</option>
                    )}
                    <option value={SEAT_MODE_LIMITED}>Custom cap</option>
                  </select>
                  {roleMode === SEAT_MODE_LIMITED && (
                    <input
                      type="number"
                      min={Math.max(0, Number(row?.used || 0))}
                      value={draft?.limit || ''}
                      onChange={(event) => onSeatLimitChange(role, event.target.value)}
                      disabled={busy}
                      max={maxCap == null ? undefined : String(maxCap)}
                      placeholder={`Min ${Math.max(0, Number(row?.used || 0))}`}
                    />
                  )}
                  {maxCap != null && roleMode === SEAT_MODE_LIMITED && (
                    <p className="team-seat-cap-note">Max for {activePlanLabel}: {maxCap}</p>
                  )}
                </div>
              )}
            </article>
          );
        })}
      </section>

      <section className="team-layout">
        <div className="team-card">
          <h2>Members</h2>
          <div className="team-table-wrap">
            <table className="team-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Email</th>
                  <th>Role</th>
                  <th>Status</th>
                  <th>Last active</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {(members || []).map((member) => {
                  const role = String(member?.role || 'viewer');
                  const isOwner = role === 'owner';
                  return (
                    <tr key={member.id}>
                      <td>{member?.user?.name || 'Unknown'}</td>
                      <td>{member?.user?.email || '—'}</td>
                      <td>
                        {canManageMembers && !isOwner ? (
                          <select
                            value={role}
                            disabled={busy || previewModeActive}
                            onChange={(event) => onRoleChange(member.id, event.target.value)}
                          >
                            {INVITE_ROLE_OPTIONS.map((option) => (
                              <option key={option} value={option}>{option}</option>
                            ))}
                          </select>
                        ) : (
                          <span className="team-pill">{role}</span>
                        )}
                      </td>
                      <td>{member?.status || 'active'}</td>
                      <td>{formatDate(member?.last_active_at || member?.updated_at)}</td>
                      <td>
                        {canManageMembers && !isOwner ? (
                          <button
                            type="button"
                            className="team-btn tiny danger"
                            onClick={() => onRemoveMember(member)}
                            disabled={busy || previewModeActive}
                          >
                            Remove
                          </button>
                        ) : (
                          '—'
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        <div className="team-card">
          <h2>Invite Members</h2>
          <form className="team-invite-form" onSubmit={onInvite}>
            <input
              type="email"
              placeholder="name@company.com"
              value={inviteEmail}
              onChange={(event) => setInviteEmail(event.target.value)}
              disabled={!canManageMembers || busy || previewModeActive}
              required
            />
            <select
              value={inviteRole}
              onChange={(event) => setInviteRole(event.target.value)}
              disabled={!canManageMembers || busy || previewModeActive}
            >
              {INVITE_ROLE_OPTIONS.map((role) => (
                <option key={role} value={role}>{role}</option>
              ))}
            </select>
            <button type="submit" className="team-btn" disabled={!canManageMembers || busy || previewModeActive}>
              Send invite
            </button>
          </form>

          <h3 className="team-subhead">Pending Invitations</h3>
          <div className="team-list">
            {pendingInvitations.map((row) => (
              <article key={row.id} className="team-list-item">
                <div>
                  <strong>{row.email}</strong>
                  <p>{row.role} • expires {formatDate(row.expires_at)}</p>
                </div>
                <div className="team-inline-actions">
                  {canManageMembers && (
                    <button
                      type="button"
                      className="team-btn tiny ghost"
                      onClick={() => navigator.clipboard?.writeText?.(`${window.location.origin}/team?invite=${row.token}`)}
                    >
                      Copy link
                    </button>
                  )}
                  {canManageMembers && (
                    <button
                      type="button"
                      className="team-btn tiny danger"
                      onClick={() => onRevokeInvitation(row.id)}
                      disabled={busy || previewModeActive}
                    >
                      Revoke
                    </button>
                  )}
                </div>
              </article>
            ))}
            {pendingInvitations.length === 0 && (
              <p className="team-empty">No pending invites.</p>
            )}
          </div>
        </div>
      </section>

      <section className="team-card">
        <h2>Shared Projects</h2>
        <p className="team-subcopy">Projects belong to the active organization. Set visibility for private, team-wide, or specific members.</p>
        <div className="team-table-wrap">
          <table className="team-table">
            <thead>
              <tr>
                <th>Project</th>
                <th>Owner</th>
                <th>Status</th>
                <th>Visibility</th>
                <th>Specific members (comma-separated user IDs)</th>
                <th>Comments</th>
                <th>Updated</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {(projects || []).map((project) => {
                const projectOwnerId = String(project?.created_by_user_id || '');
                const currentUserId = String(summary?.membership?.user_id || '');
                const isOwnerProject = Boolean(projectOwnerId && currentUserId && projectOwnerId === currentUserId);
                const canSaveSharing = canManageMembers || (canEditProjects && isOwnerProject);
                const draft = sharingDrafts?.[project.session_id] || {
                  visibility: project.visibility || 'private',
                  sharedWithCsv: (project.shared_with_user_ids || []).join(', '),
                };
                return (
                  <tr key={project.session_id}>
                    <td>{project.name || project.session_id}</td>
                    <td>{project.owner_name || '—'}</td>
                    <td>{project.status || '—'}</td>
                    <td>
                      <select
                        value={draft.visibility}
                        disabled={busy || previewModeActive || !canSaveSharing}
                        onChange={(event) => onSharingDraftChange(project.session_id, { visibility: event.target.value })}
                      >
                        {VISIBILITY_OPTIONS.map((option) => (
                          <option key={option} value={option}>{option}</option>
                        ))}
                      </select>
                    </td>
                    <td>
                      <input
                        type="text"
                        value={draft.sharedWithCsv}
                        disabled={busy || previewModeActive || !canSaveSharing}
                        onChange={(event) => onSharingDraftChange(project.session_id, { sharedWithCsv: event.target.value })}
                        placeholder="user_id_1, user_id_2"
                      />
                    </td>
                    <td>{project.comment_count ?? 0}</td>
                    <td>{formatDate(project.updated_at)}</td>
                    <td>
                      <button
                        type="button"
                        className="team-btn tiny"
                        onClick={() => onSaveSharing(project.session_id)}
                        disabled={busy || previewModeActive || !canSaveSharing}
                      >
                        Save
                      </button>
                    </td>
                  </tr>
                );
              })}
              {(projects || []).length === 0 && (
                <tr>
                  <td colSpan={8}>
                    <p className="team-empty">No organization projects yet.</p>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
      </div>
    </div>
  );
}
