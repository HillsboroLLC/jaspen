import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { API_BASE } from '../../config/apiBase';
import './Team.css';

const ROLE_OPTIONS = ['owner', 'admin', 'creator', 'collaborator', 'viewer'];
const INVITE_ROLE_OPTIONS = ['admin', 'creator', 'collaborator', 'viewer'];
const VISIBILITY_OPTIONS = ['private', 'team', 'specific'];

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

export default function Team() {
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

  const canManageMembers = Boolean(summary?.permissions?.can_manage_members);
  const activeOrg = summary?.organization || null;
  const seatUsage = summary?.seat_usage || {};

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

      setSummary(summaryData || null);
      setMembers(Array.isArray(membersData?.members) ? membersData.members : []);
      setInvitations(Array.isArray(invitationsData?.invitations) ? invitationsData.invitations : []);
      setOrganizations(Array.isArray(organizationsData?.organizations) ? organizationsData.organizations : []);
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

  const onSaveSharing = async (sessionId) => {
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
    return <div className="team-page"><div className="team-state">Loading team data…</div></div>;
  }

  return (
    <div className="team-page">
      <div className="team-topbar">
        <button type="button" className="team-btn ghost" onClick={() => navigate('/new')}>
          Back to Jaspen
        </button>
      </div>

      <header className="team-header">
        <div>
          <h1>Team</h1>
          <p>Manage members, invitations, role capacity, and shared project visibility.</p>
        </div>
        <div className="team-header-actions">
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
        </div>
      </header>

      {(error || notice) && (
        <div className={`team-state ${error ? 'error' : 'success'}`}>
          {error || notice}
        </div>
      )}

      <section className="team-seat-grid">
        {ROLE_OPTIONS.map((role) => {
          const row = seatUsage?.[role] || {};
          return (
            <article key={role} className="team-seat-card">
              <h3>{row?.label || role}</h3>
              <p className="team-seat-main">
                {row?.used ?? 0} / {limitLabel(row?.limit, row?.is_unlimited)}
              </p>
              <p className="team-seat-sub">
                {row?.is_unlimited ? 'No cap for this role' : `${row?.available ?? 0} seats remaining`}
              </p>
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
                            disabled={busy}
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
                          <button type="button" className="team-btn tiny danger" onClick={() => onRemoveMember(member)} disabled={busy}>
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
              disabled={!canManageMembers || busy}
              required
            />
            <select
              value={inviteRole}
              onChange={(event) => setInviteRole(event.target.value)}
              disabled={!canManageMembers || busy}
            >
              {INVITE_ROLE_OPTIONS.map((role) => (
                <option key={role} value={role}>{role}</option>
              ))}
            </select>
            <button type="submit" className="team-btn" disabled={!canManageMembers || busy}>
              Send invite
            </button>
          </form>

          <h3 className="team-subhead">Pending Invitations</h3>
          <div className="team-list">
            {(invitations || []).filter((row) => row?.status === 'pending').map((row) => (
              <article key={row.id} className="team-list-item">
                <div>
                  <strong>{row.email}</strong>
                  <p>{row.role} • expires {formatDate(row.expires_at)}</p>
                </div>
                <div className="team-inline-actions">
                  <button
                    type="button"
                    className="team-btn tiny ghost"
                    onClick={() => navigator.clipboard?.writeText?.(`${window.location.origin}/team?invite=${row.token}`)}
                  >
                    Copy link
                  </button>
                  {canManageMembers && (
                    <button
                      type="button"
                      className="team-btn tiny danger"
                      onClick={() => onRevokeInvitation(row.id)}
                      disabled={busy}
                    >
                      Revoke
                    </button>
                  )}
                </div>
              </article>
            ))}
            {(invitations || []).filter((row) => row?.status === 'pending').length === 0 && (
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
                        disabled={busy}
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
                        disabled={busy}
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
                        disabled={busy}
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
  );
}
