import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { API_BASE } from '../../config/apiBase';
import { useAuth } from '../../shared/auth/AuthContext';
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
const PLAN_SEAT_MATRIX = {
  team: {
    admin: 2,
    creator: 5,
    collaborator: 10,
    viewer: null,
  },
  enterprise: {
    admin: 5,
    creator: 25,
    collaborator: null,
    viewer: null,
  },
};

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

function planSeatSummary(planKey) {
  const map = PLAN_SEAT_MATRIX?.[planKey] || PLAN_SEAT_MATRIX.team;
  const fmt = (value) => (value == null ? 'Unlimited' : String(value));
  return `Admin ${fmt(map.admin)} • Creator ${fmt(map.creator)} • Collaborator ${fmt(map.collaborator)} • Viewer ${fmt(map.viewer)}`;
}

function seatLimitForPlanRole(planKey, role) {
  if (role === 'owner') return 1;
  const matrix = PLAN_SEAT_MATRIX?.[planKey] || PLAN_SEAT_MATRIX.team;
  return Object.prototype.hasOwnProperty.call(matrix, role) ? matrix[role] : null;
}

function limitsEqual(a, b) {
  const aUnlimited = a == null;
  const bUnlimited = b == null;
  if (aUnlimited || bUnlimited) return aUnlimited === bUnlimited;
  return Number(a) === Number(b);
}

function buildSeatDraft(organization, profilePlanKey) {
  const policy = organization?.seat_policy || {};
  const next = {};
  SEAT_EDITABLE_ROLES.forEach((role) => {
    const row = policy?.[role] || {};
    const routeLimit = seatLimitForPlanRole(profilePlanKey, role);
    const baseline = {
      is_unlimited: routeLimit == null,
      limit: routeLimit,
    };
    const unlimited = Boolean(row?.is_unlimited || row?.limit == null);
    const baselineUnlimited = Boolean(baseline?.is_unlimited || baseline?.limit == null);
    const baselineLimit = baselineUnlimited ? null : baseline?.limit;
    const rowLimit = unlimited ? null : row?.limit;
    const sameAsDefault = limitsEqual(baselineLimit, rowLimit);

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

function roleLabel(role) {
  const token = String(role || '').trim();
  return token ? token.charAt(0).toUpperCase() + token.slice(1) : 'Viewer';
}

function buildSerializedSeatPolicy(planKey) {
  const next = {};
  ROLE_OPTIONS.forEach((role) => {
    const limit = seatLimitForPlanRole(planKey, role);
    next[role] = {
      label: roleLabel(role),
      limit,
      is_unlimited: limit == null,
    };
  });
  return next;
}

function buildSupportSeatUsage(planKey, previewRole) {
  const counts = {
    owner: 1,
    admin: previewRole === 'admin' ? 2 : 1,
    creator: previewRole === 'creator' ? 1 : 2,
    collaborator: previewRole === 'collaborator' ? 3 : 4,
    viewer: previewRole === 'viewer' ? 2 : 1,
  };

  return ROLE_OPTIONS.reduce((acc, role) => {
    const limit = seatLimitForPlanRole(planKey, role);
    const used = role === 'admin' ? counts.admin + counts.owner : counts[role];
    acc[role] = {
      label: roleLabel(role),
      used,
      limit,
      available: limit == null ? null : Math.max(Number(limit) - used, 0),
      is_unlimited: limit == null,
    };
    return acc;
  }, {});
}

function buildSupportPreviewState(planKey, previewRole) {
  const previewOrgId = `support-preview-${planKey}`;
  const previewUserId = `support-preview-${previewRole}`;
  const seatPolicy = buildSerializedSeatPolicy(planKey);
  const organization = {
    id: previewOrgId,
    name: planKey === 'enterprise' ? 'Enterprise Support Preview' : 'Team Support Preview',
    plan_key: planKey,
    seat_policy_defaults: seatPolicy,
    seat_policy: seatPolicy,
    seat_policy_overrides: {},
  };
  const members = [
    {
      id: `${previewOrgId}-owner`,
      user_id: 'org-owner',
      name: 'Olivia Owner',
      email: 'owner@example.com',
      role: 'owner',
      status: 'active',
      joined_at: '2026-02-01T13:00:00Z',
      last_active_at: '2026-03-13T12:00:00Z',
    },
    {
      id: `${previewOrgId}-admin`,
      user_id: 'org-admin',
      name: 'Avery Admin',
      email: 'admin@example.com',
      role: 'admin',
      status: 'active',
      joined_at: '2026-02-11T13:00:00Z',
      last_active_at: '2026-03-13T10:45:00Z',
    },
    {
      id: `${previewOrgId}-current`,
      user_id: previewUserId,
      name: `Preview ${roleLabel(previewRole)}`,
      email: `${previewRole}@preview.jaspen.ai`,
      role: previewRole,
      status: 'active',
      joined_at: '2026-02-20T13:00:00Z',
      last_active_at: '2026-03-13T09:15:00Z',
    },
    {
      id: `${previewOrgId}-viewer`,
      user_id: 'org-viewer',
      name: 'Vera Viewer',
      email: 'viewer@example.com',
      role: 'viewer',
      status: 'active',
      joined_at: '2026-02-23T13:00:00Z',
      last_active_at: '2026-03-12T18:30:00Z',
    },
  ];
  const invitations = [
    {
      id: `${previewOrgId}-invite-1`,
      email: 'collab@company.com',
      role: 'collaborator',
      invited_by_name: 'Olivia Owner',
      created_at: '2026-03-12T14:10:00Z',
      status: 'pending',
    },
  ];
  const projects = [
    {
      session_id: `${previewOrgId}-project-1`,
      name: 'Support Preview Rollout',
      owner_name: 'Olivia Owner',
      created_by_user_id: 'org-owner',
      status: 'active',
      visibility: 'team',
      shared_with_user_ids: [previewUserId],
      comment_count: 4,
      updated_at: '2026-03-13T11:40:00Z',
    },
    {
      session_id: `${previewOrgId}-project-2`,
      name: 'Executive Scorecard Refresh',
      owner_name: `Preview ${roleLabel(previewRole)}`,
      created_by_user_id: previewUserId,
      status: 'in_review',
      visibility: previewRole === 'viewer' ? 'private' : 'specific',
      shared_with_user_ids: ['org-admin', 'org-viewer'],
      comment_count: 2,
      updated_at: '2026-03-13T08:55:00Z',
    },
  ];
  const sharingDrafts = projects.reduce((acc, project) => {
    acc[project.session_id] = {
      visibility: project.visibility || 'private',
      sharedWithCsv: (project.shared_with_user_ids || []).join(', '),
    };
    return acc;
  }, {});

  return {
    summary: {
      organization,
      membership: {
        id: `${previewOrgId}-membership`,
        organization_id: previewOrgId,
        user_id: previewUserId,
        role: previewRole,
        role_label: roleLabel(previewRole),
        status: 'active',
      },
      seat_usage: buildSupportSeatUsage(planKey, previewRole),
    },
    members,
    invitations,
    organizations: [
      {
        organization,
        membership: {
          organization_id: previewOrgId,
          user_id: previewUserId,
          role: previewRole,
          status: 'active',
        },
        is_active: true,
      },
    ],
    projects,
    orgNameDraft: organization.name,
    sharingDrafts,
  };
}

export default function Team({ mode = 'team' }) {
  const navigate = useNavigate();
  const location = useLocation();
  const { user } = useAuth();
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const [summary, setSummary] = useState(null);
  const [members, setMembers] = useState([]);
  const [invitations, setInvitations] = useState([]);
  const [organizations, setOrganizations] = useState([]);
  const [projects, setProjects] = useState([]);
  const [orgNameDraft, setOrgNameDraft] = useState('');

  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteRole, setInviteRole] = useState('collaborator');
  const [sharingDrafts, setSharingDrafts] = useState({});
  const [isGlobalAdmin, setIsGlobalAdmin] = useState(false);
  const [previewRole, setPreviewRole] = useState(PREVIEW_ROLE_ACTUAL);
  const [seatDraft, setSeatDraft] = useState({});
  const [savedSeatDraft, setSavedSeatDraft] = useState({});

  const isEnterpriseMode = String(mode || '').toLowerCase() === 'enterprise';
  const routePlanForCopy = isEnterpriseMode ? 'enterprise' : 'team';
  const supportPreviewConfig = useMemo(() => {
    if (!Boolean(user?.is_admin)) return null;
    const params = new URLSearchParams(location.search);
    const previewType = String(params.get('admin_preview') || '').trim().toLowerCase();
    const expectedType = isEnterpriseMode ? 'enterprise' : 'team';
    if (previewType !== expectedType) return null;
    const role = ROLE_OPTIONS.includes(String(params.get('role') || '').trim().toLowerCase())
      ? String(params.get('role') || '').trim().toLowerCase()
      : 'viewer';
    return {
      type: previewType,
      role,
      planKey: routePlanForCopy,
    };
  }, [isEnterpriseMode, location.search, routePlanForCopy, user?.is_admin]);
  const supportPreviewActive = Boolean(supportPreviewConfig);
  const actualRole = supportPreviewActive
    ? String(supportPreviewConfig?.role || 'viewer')
    : String(summary?.membership?.role || 'viewer');
  const previewModeActive = supportPreviewActive || Boolean(isGlobalAdmin && previewRole !== PREVIEW_ROLE_ACTUAL);
  const effectiveRole = supportPreviewActive
    ? actualRole
    : (previewModeActive ? previewRole : actualRole);
  const canManageMembers = MANAGE_ROLE_SET.has(effectiveRole);
  const canEditProjects = EDIT_ROLE_SET.has(effectiveRole);
  const activeOrg = summary?.organization || null;
  const activeOrgId = String(activeOrg?.id || '');
  const activeOrgPlanKey = String(activeOrg?.plan_key || '').toLowerCase();
  const canAccessEnterpriseView = supportPreviewActive || isGlobalAdmin || activeOrgPlanKey === 'enterprise';
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

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      if (supportPreviewActive) {
        const previewData = buildSupportPreviewState(routePlanForCopy, supportPreviewConfig?.role || 'viewer');
        setSummary(previewData.summary || null);
        setOrgNameDraft(String(previewData.orgNameDraft || ''));
        const nextSeatDraft = buildSeatDraft(previewData.summary?.organization || null, routePlanForCopy);
        setSeatDraft(nextSeatDraft);
        setSavedSeatDraft(nextSeatDraft);
        setMembers(Array.isArray(previewData.members) ? previewData.members : []);
        setInvitations(Array.isArray(previewData.invitations) ? previewData.invitations : []);
        setOrganizations(Array.isArray(previewData.organizations) ? previewData.organizations : []);
        setProjects(Array.isArray(previewData.projects) ? previewData.projects : []);
        setSharingDrafts(previewData.sharingDrafts || {});
        setIsGlobalAdmin(false);
        setPreviewRole(PREVIEW_ROLE_ACTUAL);
        setNotice('');
        return;
      }

      const [summaryData, membersData, invitationsData, organizationsData, projectsData] = await Promise.all([
        teamFetch('/api/team/summary'),
        teamFetch('/api/team/members'),
        teamFetch('/api/team/invitations'),
        teamFetch('/api/team/organizations'),
        teamFetch('/api/team/projects'),
      ]);
      const adminCapsData = await teamFetch('/api/admin/capabilities').catch(() => ({}));

      setSummary(summaryData || null);
      setOrgNameDraft(String(summaryData?.organization?.name || ''));
      const nextSeatDraft = buildSeatDraft(summaryData?.organization || null, routePlanForCopy);
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
  }, [routePlanForCopy, supportPreviewActive, supportPreviewConfig?.role]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  useEffect(() => {
    if (supportPreviewActive) return;
    const params = new URLSearchParams(window.location.search);
    const inviteToken = String(params.get('invite') || '').trim();
    if (!inviteToken) return;

    let cancelled = false;
    (async () => {
      setBusy(true);
      setNotice('');
      setError('');
      try {
        await teamFetch(`/api/teams/invitations/${encodeURIComponent(inviteToken)}/accept`, {
          method: 'POST',
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
  }, [loadAll, supportPreviewActive]);

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

  const onSaveOrganizationName = async () => {
    if (!canManageMembers || previewModeActive || !activeOrgId) return;
    const nextName = String(orgNameDraft || '').trim();
    if (!nextName) {
      setError('Organization name is required.');
      return;
    }
    if (nextName === String(activeOrg?.name || '').trim()) return;
    setBusy(true);
    setNotice('');
    setError('');
    try {
      await teamFetch(`/api/teams/${encodeURIComponent(activeOrgId)}`, {
        method: 'PATCH',
        body: JSON.stringify({ name: nextName }),
      });
      await loadAll();
      setNotice('Organization name updated.');
    } catch (err) {
      setError(err?.message || 'Failed to update organization name');
    } finally {
      setBusy(false);
    }
  };

  const onInvite = async (event) => {
    event.preventDefault();
    if (!canManageMembers || previewModeActive || !activeOrgId) return;
    setBusy(true);
    setNotice('');
    setError('');
    try {
      const result = await teamFetch(`/api/teams/${encodeURIComponent(activeOrgId)}/invite`, {
        method: 'POST',
        body: JSON.stringify({ email: inviteEmail, role: inviteRole }),
      });
      setInviteEmail('');
      setInviteRole('collaborator');
      await loadAll();
      setNotice(result?.email_error ? `Invite saved, but email failed: ${result.email_error}` : 'Invite sent.');
    } catch (err) {
      setError(err?.message || 'Failed to send invite');
    } finally {
      setBusy(false);
    }
  };

  const onRoleChange = async (memberId, role) => {
    if (!canManageMembers || previewModeActive || !activeOrgId) return;
    setBusy(true);
    setNotice('');
    setError('');
    try {
      await teamFetch(`/api/teams/${encodeURIComponent(activeOrgId)}/members/${encodeURIComponent(memberId)}`, {
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
    if (!canManageMembers || previewModeActive || !activeOrgId) return;
    const label = member?.user?.name || member?.user?.email || member?.user_id;
    if (!window.confirm(`Remove ${label} from this team?`)) return;
    setBusy(true);
    setNotice('');
    setError('');
    try {
      await teamFetch(`/api/teams/${encodeURIComponent(activeOrgId)}/members/${encodeURIComponent(member.id)}`, { method: 'DELETE' });
      await loadAll();
      setNotice('Member removed.');
    } catch (err) {
      setError(err?.message || 'Failed to remove member');
    } finally {
      setBusy(false);
    }
  };

  const onResendInvitation = async (invitationId) => {
    if (!canManageMembers || previewModeActive || !activeOrgId) return;
    setBusy(true);
    setNotice('');
    setError('');
    try {
      const result = await teamFetch(
        `/api/teams/${encodeURIComponent(activeOrgId)}/invitations/${encodeURIComponent(invitationId)}/resend`,
        { method: 'POST' }
      );
      await loadAll();
      setNotice(result?.email_error ? `Invite resent, but email failed: ${result.email_error}` : 'Invitation resent.');
    } catch (err) {
      setError(err?.message || 'Failed to resend invitation');
    } finally {
      setBusy(false);
    }
  };

  const onCancelInvitation = async (invitationId) => {
    if (!canManageMembers || previewModeActive || !activeOrgId) return;
    if (!window.confirm('Cancel this invitation?')) return;
    setBusy(true);
    setNotice('');
    setError('');
    try {
      await teamFetch(
        `/api/teams/${encodeURIComponent(activeOrgId)}/invitations/${encodeURIComponent(invitationId)}`,
        { method: 'DELETE' }
      );
      await loadAll();
      setNotice('Invitation cancelled.');
    } catch (err) {
      setError(err?.message || 'Failed to cancel invitation');
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
    const routeDefaultLimit = seatLimitForPlanRole(routePlanForCopy, role);
    const baselineUnlimited = routeDefaultLimit == null;
    const baselineLimit = baselineUnlimited ? '' : String(routeDefaultLimit);
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
    if (!canEditSeatPolicy) return;
    const payload = {};
    for (const role of SEAT_EDITABLE_ROLES) {
      const routeDefaultLimit = seatLimitForPlanRole(routePlanForCopy, role);
      const activeBaseline = seatPolicyDefaults?.[role] || {};
      const activeBaselineUnlimited = Boolean(activeBaseline?.is_unlimited || activeBaseline?.limit == null);
      const activeBaselineLimit = activeBaselineUnlimited ? null : Number(activeBaseline?.limit);
      const shouldUseNull = limitsEqual(activeBaselineLimit, routeDefaultLimit);
      payload[role] = shouldUseNull ? null : routeDefaultLimit;
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
      setNotice(`Seat policy reset to ${routePlanForCopy} defaults.`);
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
      const activeBaseline = seatPolicyDefaults?.[role] || {};
      const activeBaselineUnlimited = Boolean(activeBaseline?.is_unlimited || activeBaseline?.limit == null);
      const activeBaselineLimit = activeBaselineUnlimited ? null : Number(activeBaseline?.limit);
      const routeDefaultLimit = seatLimitForPlanRole(routePlanForCopy, role);
      const routeDefaultUnlimited = routeDefaultLimit == null;
      const routeDefaultNumber = routeDefaultUnlimited ? null : Number(routeDefaultLimit);

      if (draft.mode === SEAT_MODE_DEFAULT) {
        payload[role] = limitsEqual(activeBaselineLimit, routeDefaultLimit) ? null : routeDefaultLimit;
        continue;
      }
      if (draft.mode === SEAT_MODE_UNLIMITED) {
        if (!routeDefaultUnlimited) {
          setError(`Unlimited is not available for ${role} in ${routePlanForCopy} policy.`);
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
      if (!routeDefaultUnlimited && Number.isFinite(routeDefaultNumber) && next > routeDefaultNumber) {
        setError(`Seat limit for ${role} cannot exceed ${routePlanForCopy} cap (${routeDefaultNumber}).`);
        return;
      }
      if (limitsEqual(next, routeDefaultLimit)) {
        payload[role] = limitsEqual(activeBaselineLimit, routeDefaultLimit) ? null : routeDefaultLimit;
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
  const seatSummaryLabel = ['admin', 'creator', 'collaborator', 'viewer']
    .map((role) => {
      const used = Number(seatUsage?.[role]?.used ?? 0);
      const roleDefaultLimit = seatLimitForPlanRole(routePlanForCopy, role);
      const cap = roleDefaultLimit == null ? '∞' : String(roleDefaultLimit);
      return `${roleLabel(role)}: ${used}/${cap}`;
    })
    .join(' · ');
  const activePolicyPlanKey = PLAN_SEAT_MATRIX?.[activeOrgPlanKey] ? activeOrgPlanKey : null;
  const showingPlanMismatch = Boolean(activePolicyPlanKey && activePolicyPlanKey !== routePlanForCopy);

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
        <button
          type="button"
          className="team-btn ghost team-back-btn"
          onClick={() => navigate(supportPreviewActive ? '/jaspen-admin' : '/new')}
        >
          {supportPreviewActive ? 'Back to Jaspen Admin' : 'Back to Jaspen'}
        </button>
      </header>

      <section className="team-toolbar">
        <div className="team-toolbar-fields">
          <label className="team-inline-field">
            <span>Organization name</span>
            <div style={{ display: 'inline-flex', gap: 8 }}>
              <input
                type="text"
                value={orgNameDraft}
                onChange={(event) => setOrgNameDraft(event.target.value)}
                disabled={busy || !canManageMembers || previewModeActive}
                style={{ minWidth: 240 }}
              />
              <button
                type="button"
                className="team-btn ghost"
                onClick={onSaveOrganizationName}
                disabled={busy || !canManageMembers || previewModeActive || !activeOrgId}
              >
                Save
              </button>
            </div>
          </label>
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
          <label className="team-inline-field">
            <span>Plan</span>
            <input type="text" value={activePlanLabel} disabled style={{ minWidth: 120 }} />
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

      <section className="team-state">
        <strong>Seat usage:</strong> {seatSummaryLabel}
      </section>

      {(error || notice) && (
        <div className={`team-state ${error ? 'error' : 'success'}`}>
          {error || notice}
        </div>
      )}

      {supportPreviewActive && (
        <div className="team-state team-state-preview">
          Jaspen Admin preview: viewing the <strong>{activePlanLabel}</strong> {isEnterpriseMode ? 'Enterprise' : 'Team'} interface as <strong>{effectiveRole}</strong>. All data on this page is synthetic and read-only.
        </div>
      )}

      {!supportPreviewActive && previewModeActive && (
        <div className="team-state team-state-preview">
          Preview mode active: viewing Team as <strong>{effectiveRole}</strong>. Mutating actions are disabled in preview mode.
        </div>
      )}

      {isEnterpriseMode && !canAccessEnterpriseView && (
        <div className="team-state error">
          Enterprise Admin requires an Enterprise organization. Switch to an Enterprise org or upgrade in Billing.
        </div>
      )}

      {showingPlanMismatch && (
        <div className="team-state team-state-preview">
          Active organization is <strong>{activePlanLabel}</strong>, but this page is using <strong>{routePlanForCopy}</strong> seat policy for preview and editing.
        </div>
      )}

      {canManageMembers && (
        <section className={`team-seat-policy-bar ${seatDraftDirty ? 'is-dirty' : ''}`}>
          <div className="team-seat-policy-copy">
            <strong>{seatDraftDirty ? 'Unsaved seat policy changes' : 'Seat policy saved'}</strong>
            <span>{routePlanForCopy.charAt(0).toUpperCase() + routePlanForCopy.slice(1)} defaults: {planSeatSummary(routePlanForCopy)}.</span>
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
          const routeDefaultLimit = seatLimitForPlanRole(routePlanForCopy, role);
          const baselineUnlimited = routeDefaultLimit == null;
          const defaultLabel = limitLabel(routeDefaultLimit, baselineUnlimited);
          const maxCap = baselineUnlimited ? null : Number(routeDefaultLimit);
          const used = Number(row?.used || 0);
          const displayedAvailable = baselineUnlimited ? null : Math.max(maxCap - used, 0);
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
                {used} / {defaultLabel}
              </p>
              <p className="team-seat-sub">
                {baselineUnlimited ? 'No cap for this role' : `${displayedAvailable} seats remaining`}
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
                      min={Math.max(0, used)}
                      value={draft?.limit || ''}
                      onChange={(event) => onSeatLimitChange(role, event.target.value)}
                      disabled={busy}
                      max={maxCap == null ? undefined : String(maxCap)}
                      placeholder={`Min ${Math.max(0, used)}`}
                    />
                  )}
                  {maxCap != null && roleMode === SEAT_MODE_LIMITED && (
                    <p className="team-seat-cap-note">Max for {routePlanForCopy}: {maxCap}</p>
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
                  <th>Joined</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {(members || []).map((member) => {
                  const role = String(member?.role || 'viewer');
                  const isOwner = role === 'owner';
                  return (
                    <tr key={member.id}>
                      <td>{member?.name || member?.user?.name || 'Unknown'}</td>
                      <td>{member?.email || member?.user?.email || '—'}</td>
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
                      <td>{formatDate(member?.last_active || member?.last_active_at || member?.updated_at)}</td>
                      <td>{formatDate(member?.joined_at || member?.created_at)}</td>
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
          <div className="team-table-wrap">
            <table className="team-table">
              <thead>
                <tr>
                  <th>Email</th>
                  <th>Role</th>
                  <th>Invited by</th>
                  <th>Sent</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {pendingInvitations.length === 0 && (
                  <tr>
                    <td colSpan={6} className="team-empty">No pending invites.</td>
                  </tr>
                )}
                {pendingInvitations.map((row) => (
                  <tr key={row.id}>
                    <td>{row.email}</td>
                    <td>{row.role}</td>
                    <td>{row.invited_by_name || row.invited_by || '—'}</td>
                    <td>{formatDate(row.created_at)}</td>
                    <td>{row.status}</td>
                    <td>
                      <div className="team-inline-actions">
                        <button
                          type="button"
                          className="team-btn tiny ghost"
                          onClick={() => onResendInvitation(row.id)}
                          disabled={!canManageMembers || busy || previewModeActive}
                        >
                          Resend
                        </button>
                        <button
                          type="button"
                          className="team-btn tiny danger"
                          onClick={() => onCancelInvitation(row.id)}
                          disabled={!canManageMembers || busy || previewModeActive}
                        >
                          Cancel
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
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
