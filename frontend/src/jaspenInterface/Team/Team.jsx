import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import BackToJaspen from '../../shared/components/BackToJaspen';
import { API_BASE } from '../../config/apiBase';
import { useAuth } from '../../shared/auth/AuthContext';
import { authFetch, buildAuthHeaders } from '../../shared/auth/http';
import ConfirmDialog from '../../shared/components/ConfirmDialog';
import FieldError from '../../shared/components/FieldError';
import { ROLE_OPTIONS, INVITE_ROLE_OPTIONS } from '../../shared/constants/appConstants';
import './Team.css';
import AppMenu from '../shared/AppMenu';
import JaspenAiDrawer from '../Workspace/JaspenAiDrawer';
import { Jaspen } from '../Workspace/JaspenClient';

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
    admin: 3,
    creator: null,
    collaborator: null,
    viewer: null,
  },
  enterprise: {
    admin: 10,
    creator: null,
    collaborator: null,
    viewer: null,
  },
};

async function teamFetch(path, options = {}) {
  const method = String(options.method || 'GET').toUpperCase();
  const response = await authFetch(`${API_BASE}${path}`, {
    credentials: 'include',
    headers: buildAuthHeaders(
      {
        'Content-Type': 'application/json',
        ...(options.headers || {}),
      },
      method,
    ),
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
  if (planKey === 'team' || planKey === 'enterprise') {
    return `Admin ${map.admin} • Paid seats pooled across admin, creator, and collaborator • Viewer Unlimited`;
  }
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
  const [inviteFieldErrors, setInviteFieldErrors] = useState({});
  const [orgNameFieldError, setOrgNameFieldError] = useState('');
  const [sharingDrafts, setSharingDrafts] = useState({});
  const [isGlobalAdmin, setIsGlobalAdmin] = useState(false);
  const [previewRole, setPreviewRole] = useState(PREVIEW_ROLE_ACTUAL);
  const [seatDraft, setSeatDraft] = useState({});
  const [savedSeatDraft, setSavedSeatDraft] = useState({});
  const [confirmDialog, setConfirmDialog] = useState(null);
  const [jaspenOpen, setJaspenOpen] = useState(false);
  const [assistantInput, setAssistantInput] = useState('');
  const [assistantMessages, setAssistantMessages] = useState([
    {
      role: 'assistant',
      text: 'I can help with seat policy, role assignments, and project-sharing decisions on this page.',
    },
  ]);
  const [assistantBusy, setAssistantBusy] = useState(false);
  const [assistantSessionId, setAssistantSessionId] = useState(null);
  const assistantAbortRef = useRef(null);

  const isEnterpriseMode = String(mode || '').toLowerCase() === 'enterprise';
  const routePlanForCopy = isEnterpriseMode ? 'enterprise' : 'team';
  const teamLabel = isEnterpriseMode ? 'Enterprise' : 'Team';
  const teamLabelLower = teamLabel.toLowerCase();
  const teamNameLabel = isEnterpriseMode ? 'Enterprise name' : 'Team name';
  const routePreviewRole = useMemo(() => {
    if (!Boolean(user?.is_admin)) return null;
    const params = new URLSearchParams(location.search);
    const previewType = String(params.get('admin_preview') || '').trim().toLowerCase();
    const expectedType = isEnterpriseMode ? 'enterprise' : 'team';
    if (previewType !== expectedType) return null;
    const role = String(params.get('role') || '').trim().toLowerCase();
    return ROLE_OPTIONS.includes(role) ? role : null;
  }, [isEnterpriseMode, location.search, user?.is_admin]);
  const actualRole = String(summary?.membership?.role || 'viewer');
  const previewModeActive = Boolean(routePreviewRole) || Boolean(isGlobalAdmin && previewRole !== PREVIEW_ROLE_ACTUAL);
  const effectiveRole = routePreviewRole || (previewModeActive ? previewRole : actualRole);
  const isOwnerRole = actualRole === 'owner';
  const canManageMembers = MANAGE_ROLE_SET.has(effectiveRole);
  const canEditProjects = EDIT_ROLE_SET.has(effectiveRole);
  const activeOrg = summary?.organization || null;
  const activeOrgId = String(activeOrg?.id || '');
  const activeOrgPlanKey = String(activeOrg?.plan_key || '').toLowerCase();
  const canAccessEnterpriseView = isGlobalAdmin || activeOrgPlanKey === 'enterprise';
  const seatPolicyDefaults = activeOrg?.seat_policy_defaults || {};
  const seatUsage = summary?.seat_usage || {};
  const assistantAdminSeatsUsed = Number(seatUsage?.admin?.used ?? 0);
  const assistantPaidSeatsUsed = Number(seatUsage?.total_paid_used ?? 0);
  const assistantPaidSeatsLimit = seatUsage?.total_paid_limit ?? 'unlimited';
  const assistantViewerSeatsUsed = Number(seatUsage?.viewer?.used ?? 0);
  const seatDraftDirty = useMemo(
    () => JSON.stringify(seatDraft || {}) !== JSON.stringify(savedSeatDraft || {}),
    [seatDraft, savedSeatDraft]
  );
  const canEditSeatPolicy = canManageMembers && !previewModeActive && (!isEnterpriseMode || canAccessEnterpriseView);
  const pendingInvitations = useMemo(
    () => (invitations || []).filter((row) => row?.status === 'pending'),
    [invitations]
  );
  const showSeatPolicy = canManageMembers;
  const showInviteForm = canManageMembers;
  const showOrgNameSave = canManageMembers && !previewModeActive;
  const showOwnershipCard = !previewModeActive && MANAGE_ROLE_SET.has(actualRole);
  const visibleProjects = useMemo(() => {
    if (canManageMembers) return projects || [];
    const currentUserId = String(summary?.membership?.user_id || '');
    return (projects || []).filter((project) => {
      const ownerId = String(project?.created_by_user_id || '');
      if (ownerId && currentUserId && ownerId === currentUserId) return true;
      if (String(project?.visibility || '').toLowerCase() === 'team') return true;
      if (String(project?.visibility || '').toLowerCase() === 'specific') {
        return Array.isArray(project?.shared_with_user_ids) && project.shared_with_user_ids.map((id) => String(id)).includes(currentUserId);
      }
      return false;
    });
  }, [canManageMembers, projects, summary?.membership?.user_id]);

  const memberIdSet = useMemo(
    () => new Set((members || []).map((member) => String(member?.user_id || ''))),
    [members]
  );

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [summaryData, membersData, invitationsData, organizationsData, projectsData] = await Promise.all([
        teamFetch('/api/v1/team/summary'),
        teamFetch('/api/v1/team/members'),
        teamFetch('/api/v1/team/invitations'),
        teamFetch('/api/v1/team/organizations'),
        teamFetch('/api/v1/team/projects'),
      ]);
      const adminCapsData = await teamFetch('/api/v1/admin/capabilities').catch(() => ({}));

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
  }, [routePlanForCopy]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

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
        await teamFetch(`/api/v1/teams/invitations/${encodeURIComponent(inviteToken)}/accept`, {
          method: 'POST',
        });
        if (cancelled) return;
        setNotice(`Invitation accepted. You are now part of this ${teamLabelLower}.`);
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
  }, [loadAll, teamLabelLower]);

  useEffect(() => {
    const observer = new MutationObserver(() => {
      if (document.body.classList.contains('jaspen-sidebar-open')) {
        setJaspenOpen(false);
      }
    });
    observer.observe(document.body, { attributes: true, attributeFilter: ['class'] });
    return () => observer.disconnect();
  }, []);

  const openJaspen = useCallback(() => {
    document.body.classList.remove('jaspen-sidebar-open');
    setJaspenOpen(true);
  }, []);

  const sendAssistant = useCallback(async () => {
    const text = String(assistantInput || '').trim();
    if (!text || assistantBusy) return;
    const assistantIndex = assistantMessages.length + 1;
    setAssistantMessages((prev) => ([
      ...prev,
      { role: 'user', text },
      { role: 'assistant', text: '', streaming: true },
    ]));
    setAssistantInput('');
    setAssistantBusy(true);
    const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
    assistantAbortRef.current = controller;
    let replyText = '';
    const view_context = {
      current_view: 'team',
      page_facts: [
        `Page mode: ${teamLabel}.`,
        `Members visible: ${members.length}.`,
        `Projects visible: ${projects.length}.`,
        `Admin seats used: ${assistantAdminSeatsUsed}.`,
        `Paid seats used: ${assistantPaidSeatsUsed} of ${assistantPaidSeatsLimit}.`,
        `Viewer seats used: ${assistantViewerSeatsUsed}.`,
        seatDraftDirty ? 'There are unsaved seat policy changes.' : 'Seat policy is saved.',
      ].filter(Boolean).join(' '),
    };

    try {
      const streamArgs = {
        view_context,
        abortSignal: controller?.signal,
        onDelta: (delta) => {
          replyText += delta || '';
          setAssistantMessages((prev) => prev.map((msg, idx) => (
            idx === assistantIndex ? { ...msg, text: replyText, streaming: true } : msg
          )));
        },
        onDone: (payload) => {
          const finalText = payload?.reply || payload?.message || replyText;
          setAssistantMessages((prev) => prev.map((msg, idx) => (
            idx === assistantIndex ? { ...msg, text: finalText, streaming: false } : msg
          )));
        },
      };
      if (assistantSessionId) {
        await Jaspen.streamConversation({ ...streamArgs, session_id: assistantSessionId, user_message: text });
      } else {
        let nextSessionId = null;
        await Jaspen.streamConversationStart({
          ...streamArgs,
          description: text,
          onDone: (payload) => {
            nextSessionId = payload?.thread_id || payload?.session_id || null;
            streamArgs.onDone(payload);
          },
        });
        if (nextSessionId) setAssistantSessionId(nextSessionId);
      }
    } catch (error) {
      if (error?.name === 'AbortError' || controller?.signal?.aborted) {
        setAssistantMessages((prev) => prev.map((msg, idx) => (
          idx === assistantIndex ? { ...msg, text: 'Stopped.', streaming: false } : msg
        )));
        return;
      }
      setAssistantMessages((prev) => prev.map((msg, idx) => (
        idx === assistantIndex
          ? { ...msg, text: error?.message || 'Something went wrong. Please try again.', streaming: false, error: true }
          : msg
      )));
    } finally {
      if (assistantAbortRef.current === controller) {
        assistantAbortRef.current = null;
      }
      setAssistantBusy(false);
    }
  }, [assistantAdminSeatsUsed, assistantBusy, assistantInput, assistantMessages.length, assistantPaidSeatsLimit, assistantPaidSeatsUsed, assistantSessionId, assistantViewerSeatsUsed, members.length, projects.length, seatDraftDirty, teamLabel]);

  const stopAssistant = useCallback(() => {
    try {
      assistantAbortRef.current?.abort();
    } catch (_) { /* no-op */ }
    assistantAbortRef.current = null;
    setAssistantBusy(false);
    setAssistantMessages((prev) => {
      if (!Array.isArray(prev) || prev.length === 0) return prev;
      const next = prev.slice();
      const last = next[next.length - 1];
      if (last?.streaming) {
        next[next.length - 1] = { ...last, text: String(last.text || '').trim() || 'Stopped.', streaming: false };
      }
      return next;
    });
  }, []);

  const onSwitchOrganization = async (orgId) => {
    if (!orgId) return;
    setBusy(true);
    setNotice('');
    setError('');
    try {
      await teamFetch('/api/v1/team/organizations/active', {
        method: 'POST',
        body: JSON.stringify({ organization_id: orgId }),
      });
      await loadAll();
      setNotice(`Switched active ${teamLabelLower}.`);
    } catch (err) {
      setError(err?.message || `Could not switch ${teamLabelLower}`);
    } finally {
      setBusy(false);
    }
  };

  const onSaveOrganizationName = async () => {
    if (!canManageMembers || previewModeActive || !activeOrgId) return;
    const nextName = String(orgNameDraft || '').trim();
    if (!nextName) {
      setOrgNameFieldError(`${teamNameLabel} is required.`);
      setError(`${teamNameLabel} is required.`);
      return;
    }
    setOrgNameFieldError('');
    if (nextName === String(activeOrg?.name || '').trim()) return;
    setBusy(true);
    setNotice('');
    setError('');
    try {
      await teamFetch(`/api/v1/teams/${encodeURIComponent(activeOrgId)}`, {
        method: 'PATCH',
        body: JSON.stringify({ name: nextName }),
      });
      await loadAll();
      setNotice(`${teamLabel} name updated.`);
    } catch (err) {
      setError(err?.message || `Failed to update ${teamLabelLower} name`);
    } finally {
      setBusy(false);
    }
  };

  const onInvite = async (event) => {
    event.preventDefault();
    if (!canManageMembers || previewModeActive || !activeOrgId) return;
    const normalizedEmail = String(inviteEmail || '').trim().toLowerCase();
    const nextFieldErrors = {};
    if (!normalizedEmail) {
      nextFieldErrors.inviteEmail = 'Invite email is required.';
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(normalizedEmail)) {
      nextFieldErrors.inviteEmail = 'Enter a valid email address.';
    }
    if (!String(inviteRole || '').trim()) {
      nextFieldErrors.inviteRole = 'Role is required.';
    }
    if (Object.keys(nextFieldErrors).length > 0) {
      setInviteFieldErrors(nextFieldErrors);
      setError('Please fix the highlighted invite fields.');
      return;
    }

    setBusy(true);
    setNotice('');
    setError('');
    try {
      const result = await teamFetch(`/api/v1/teams/${encodeURIComponent(activeOrgId)}/invite`, {
        method: 'POST',
        body: JSON.stringify({ email: normalizedEmail, role: inviteRole }),
      });
      setInviteEmail('');
      setInviteRole('collaborator');
      setInviteFieldErrors({});
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
      await teamFetch(`/api/v1/teams/${encodeURIComponent(activeOrgId)}/members/${encodeURIComponent(memberId)}`, {
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
    setConfirmDialog({
      title: 'Remove team member',
      message: `Remove ${label} from this team?`,
      confirmLabel: 'Remove member',
      confirmVariant: 'danger',
      onConfirm: async () => {
        setConfirmDialog(null);
        setBusy(true);
        setNotice('');
        setError('');
        try {
          await teamFetch(`/api/v1/teams/${encodeURIComponent(activeOrgId)}/members/${encodeURIComponent(member.id)}`, { method: 'DELETE' });
          await loadAll();
          setNotice('Member removed.');
        } catch (err) {
          setError(err?.message || 'Failed to remove member');
        } finally {
          setBusy(false);
        }
      },
    });
  };

  const onResendInvitation = async (invitationId) => {
    if (!canManageMembers || previewModeActive || !activeOrgId) return;
    setBusy(true);
    setNotice('');
    setError('');
    try {
      const result = await teamFetch(
        `/api/v1/teams/${encodeURIComponent(activeOrgId)}/invitations/${encodeURIComponent(invitationId)}/resend`,
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
    setConfirmDialog({
      title: 'Cancel invitation',
      message: 'Cancel this invitation?',
      confirmLabel: 'Cancel invitation',
      confirmVariant: 'danger',
      onConfirm: async () => {
        setConfirmDialog(null);
        setBusy(true);
        setNotice('');
        setError('');
        try {
          await teamFetch(
            `/api/v1/teams/${encodeURIComponent(activeOrgId)}/invitations/${encodeURIComponent(invitationId)}`,
            { method: 'DELETE' }
          );
          await loadAll();
          setNotice('Invitation cancelled.');
        } catch (err) {
          setError(err?.message || 'Failed to cancel invitation');
        } finally {
          setBusy(false);
        }
      },
    });
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
      await teamFetch('/api/v1/team/seat-policy', {
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
      await teamFetch('/api/v1/team/seat-policy', {
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
      await teamFetch(`/api/v1/team/projects/${encodeURIComponent(sessionId)}/sharing`, {
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
      <div className={`team-page jas-internal-page jas-internal-page-shell int-page${jaspenOpen ? ' drawer-open' : ''}`}>
        <AppMenu />
        <div className="team-inner int-page-inner">
          <div className="team-state">Loading team data…</div>
        </div>
        <JaspenAiDrawer
          isOpen={jaspenOpen}
          onOpen={openJaspen}
          onClose={() => setJaspenOpen(false)}
          messages={assistantMessages}
          input={assistantInput}
          onInputChange={setAssistantInput}
          onSend={sendAssistant}
          onStop={stopAssistant}
          busy={assistantBusy}
          starterPrompts={[
            'Who should have admin access?',
            'How should I set seat limits?',
          ]}
          placeholder="Ask Jaspen about team management..."
          contextLabel="Team"
          contextTitle="Team Management"
          contextDescription="Ask Jaspen about roles, seats, invitations, or project access."
        />
      </div>
    );
  }

  const activePlanLabel = activeOrgPlanKey
    ? `${activeOrgPlanKey.charAt(0).toUpperCase()}${activeOrgPlanKey.slice(1)}`
    : 'Current';
  const seatSummaryLabel = (routePlanForCopy === 'team' || routePlanForCopy === 'enterprise')
    ? `Admin: ${Number(seatUsage?.admin?.used ?? 0)}/${seatLimitForPlanRole(routePlanForCopy, 'admin') ?? '∞'} · Paid seats: ${Number(seatUsage?.total_paid_used ?? 0)}/${seatUsage?.total_paid_limit ?? '∞'} · Viewers: ${Number(seatUsage?.viewer?.used ?? 0)}`
    : ['admin', 'creator', 'collaborator', 'viewer']
        .map((role) => {
          const used = Number(seatUsage?.[role]?.used ?? 0);
          const roleDefaultLimit = seatLimitForPlanRole(routePlanForCopy, role);
          const cap = roleDefaultLimit == null ? '∞' : String(roleDefaultLimit);
          return `${roleLabel(role)}: ${used}/${cap}`;
        })
        .join(' · ');
  const activePolicyPlanKey = PLAN_SEAT_MATRIX?.[activeOrgPlanKey] ? activeOrgPlanKey : null;
  const showingPlanMismatch = Boolean(activePolicyPlanKey && activePolicyPlanKey !== routePlanForCopy);
  const totalPaidUsed = Number(seatUsage?.total_paid_used || 0);
  const totalPaidLimit = seatUsage?.total_paid_limit;
  const totalPaidAvailable = totalPaidLimit == null ? null : Math.max(Number(totalPaidLimit) - totalPaidUsed, 0);
  const viewerUsed = Number(seatUsage?.viewer?.used || 0);
  const seatPolicyHelperCopy = (routePlanForCopy === 'team' || routePlanForCopy === 'enterprise')
    ? `Admin cap can be managed here. Paid seats are pooled across admin, creator, and collaborator and are managed ${routePlanForCopy === 'team' ? 'in Billing' : 'by contract'}. Viewers remain unlimited.`
    : `${routePlanForCopy.charAt(0).toUpperCase() + routePlanForCopy.slice(1)} defaults: ${planSeatSummary(routePlanForCopy)}.`;

  return (
    <div className={`team-page jas-internal-page jas-internal-page-shell int-page${jaspenOpen ? ' drawer-open' : ''}`}>
      <AppMenu />
      <div className="team-inner int-page-inner">
      <header className="team-head int-page-head">
        <div>
          <p className="team-eyebrow int-eyebrow">{isEnterpriseMode ? 'Jaspen Enterprise' : 'Jaspen Team'}</p>
          <h1>{isEnterpriseMode ? 'Enterprise Admin' : 'Team'}</h1>
          <p className="team-sub">
            {isEnterpriseMode
              ? 'Manage enterprise role capacity, members, invitations, and shared project visibility.'
              : 'Manage members, invitations, role capacity, and shared project visibility.'}
          </p>
        </div>
        <BackToJaspen
          to={routePreviewRole ? '/jaspen-admin' : '/new'}
          label={routePreviewRole ? 'Back to Jaspen Admin' : 'Back to Jaspen'}
        />
      </header>

      <section className="team-toolbar">
        <div className="team-toolbar-fields">
          <label className="team-inline-field">
            <span>{teamNameLabel}</span>
            <div style={{ display: 'inline-flex', gap: 8 }}>
              <input
                type="text"
                value={orgNameDraft}
                onChange={(event) => {
                  setOrgNameDraft(event.target.value);
                  setOrgNameFieldError('');
                }}
                onBlur={() => {
                  const nextName = String(orgNameDraft || '').trim();
                  setOrgNameFieldError(nextName ? '' : `${teamNameLabel} is required.`);
                }}
                disabled={busy || !canManageMembers || previewModeActive}
                style={{ minWidth: 240 }}
                className={orgNameFieldError ? 'is-invalid' : ''}
                aria-invalid={Boolean(orgNameFieldError)}
                aria-describedby={orgNameFieldError ? 'team-org-name-error' : undefined}
              />
              <FieldError id="team-org-name-error" message={orgNameFieldError} />
              <button
                type="button"
                className="team-btn ghost int-btn int-btn-ghost"
                onClick={onSaveOrganizationName}
                disabled={busy || !showOrgNameSave || !activeOrgId} aria-disabled={busy || !showOrgNameSave || !activeOrgId}
              >
                Save
              </button>
            </div>
          </label>
          <label className="team-inline-field">
            <span>{teamLabel}</span>
            <select
              value={activeOrg?.id || ''}
              onChange={(event) => onSwitchOrganization(event.target.value)}
              disabled={busy}
            >
              {(organizations || []).map((entry) => (
                <option key={entry?.organization?.id} value={entry?.organization?.id}>
                  {entry?.organization?.name || teamLabel}
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
        <div className={`team-state ${error ? 'error with-action' : 'success'}`} role="status" aria-live="polite">
          <span>{error || notice}</span>
          {error && (
            <button
              type="button"
              className="int-btn int-btn-ghost team-state-retry-btn"
              onClick={loadAll}
              disabled={loading || busy}
              aria-disabled={loading || busy}
            >
              Retry
            </button>
          )}
        </div>
      )}

      {routePreviewRole && (
        <div className="team-state team-state-preview">
          Jaspen Admin preview: viewing the <strong>{activePlanLabel}</strong> {teamLabel} interface as <strong>{effectiveRole}</strong> using your active {teamLabelLower} data. Mutating actions remain disabled while previewing.
        </div>
      )}

      {!routePreviewRole && previewModeActive && (
        <div className="team-state team-state-preview">
          Preview mode active: viewing Team as <strong>{effectiveRole}</strong>. Mutating actions are disabled in preview mode.
        </div>
      )}

      {isEnterpriseMode && !canAccessEnterpriseView && (
        <div className="team-state error">
          Enterprise Admin requires a Business plan. Switch to a Business workspace or upgrade in Billing.
        </div>
      )}

      {showingPlanMismatch && (
        <div className="team-state team-state-preview">
          Active {teamLabelLower} plan is <strong>{activePlanLabel}</strong>, but this page is using <strong>{routePlanForCopy}</strong> seat policy for preview and editing.
        </div>
      )}

      {showSeatPolicy && (
        <section className={`team-seat-policy-bar ${seatDraftDirty ? 'is-dirty' : ''}`}>
          <div className="team-seat-policy-copy">
            <strong>{seatDraftDirty ? 'Unsaved seat policy changes' : 'Seat policy saved'}</strong>
            <span>{seatPolicyHelperCopy}</span>
          </div>
          <div className="team-seat-policy-actions">
            <button
              type="button"
              className="team-btn ghost int-btn int-btn-ghost"
              onClick={onDiscardSeatPolicy}
              disabled={busy || !seatDraftDirty || !canEditSeatPolicy} aria-disabled={busy || !seatDraftDirty || !canEditSeatPolicy}
            >
              Discard changes
            </button>
            <button
              type="button"
              className="team-btn"
              onClick={onSaveSeatPolicy}
              disabled={busy || !seatDraftDirty || !canEditSeatPolicy} aria-disabled={busy || !seatDraftDirty || !canEditSeatPolicy}
            >
              {busy ? 'Saving…' : 'Save seat policy'}
            </button>
            <button
              type="button"
              className="team-btn ghost int-btn int-btn-ghost"
              onClick={onResetSeatPolicy}
              disabled={busy || !canEditSeatPolicy} aria-disabled={busy || !canEditSeatPolicy}
            >
              Reset to plan defaults
            </button>
          </div>
        </section>
      )}

      <section className="team-seat-grid">
        {ROLE_OPTIONS.filter((role) => {
          if (role === 'owner') return false;
          if (routePlanForCopy === 'team' || routePlanForCopy === 'enterprise') {
            return role === 'admin';
          }
          return true;
        }).map((role) => {
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
        {(routePlanForCopy === 'team' || routePlanForCopy === 'enterprise') && (
          <article className="team-seat-card">
            <h3>Total Paid Seats</h3>
            <p className="team-seat-main">
              {totalPaidUsed} / {totalPaidLimit == null ? '∞' : totalPaidLimit}
            </p>
            <p className="team-seat-sub">Admin + Creator + Collaborator seats</p>
            <p className="team-seat-meta">
              {totalPaidAvailable == null ? 'Managed by contract or billing.' : `${totalPaidAvailable} paid seats remaining.`}
            </p>
            <p className="team-seat-meta">
              {routePlanForCopy === 'team'
                ? 'Adjust this in Billing when you need to add paid seats.'
                : 'Adjust this through your enterprise contract or billing admin.'}
            </p>
          </article>
        )}
        {(routePlanForCopy === 'team' || routePlanForCopy === 'enterprise') && (
          <article className="team-seat-card">
            <h3>Viewer Seats</h3>
            <p className="team-seat-main">
              {viewerUsed} / Unlimited
            </p>
            <p className="team-seat-sub">Read-only members stay outside the paid seat pool.</p>
            <p className="team-seat-meta">Viewer access is intended for invited read-only participants.</p>
          </article>
        )}
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
                            disabled={busy || previewModeActive} aria-disabled={busy || previewModeActive}
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

        <div className="team-side-column">
          {showInviteForm && (
            <div className="team-card">
              <h2>Invite Members</h2>
              <form className="team-invite-form" onSubmit={onInvite}>
                <p className="team-required-legend">
                  <span className="team-required-mark" aria-hidden="true">*</span> Required fields
                </p>
                <div className="team-invite-field">
                  <label htmlFor="team-invite-email" className="team-field-label">
                    Invite email <span className="team-required-mark" aria-hidden="true">*</span>
                  </label>
                  <input
                    id="team-invite-email"
                    type="email"
                    placeholder="name@company.com"
                    value={inviteEmail}
                    onChange={(event) => {
                      setInviteEmail(event.target.value);
                      setInviteFieldErrors((prev) => ({ ...prev, inviteEmail: '' }));
                    }}
                    onBlur={() => {
                      const normalizedEmail = String(inviteEmail || '').trim().toLowerCase();
                      if (!normalizedEmail) {
                        setInviteFieldErrors((prev) => ({ ...prev, inviteEmail: 'Invite email is required.' }));
                      } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(normalizedEmail)) {
                        setInviteFieldErrors((prev) => ({ ...prev, inviteEmail: 'Enter a valid email address.' }));
                      }
                    }}
                    disabled={!canManageMembers || busy || previewModeActive}
                    required
                    aria-required="true"
                    className={inviteFieldErrors.inviteEmail ? 'is-invalid' : ''}
                    aria-invalid={Boolean(inviteFieldErrors.inviteEmail)}
                    aria-describedby={inviteFieldErrors.inviteEmail ? 'team-invite-email-error' : undefined}
                  />
                  <FieldError id="team-invite-email-error" message={inviteFieldErrors.inviteEmail} />
                </div>
                <div className="team-invite-field">
                  <label htmlFor="team-invite-role" className="team-field-label">
                    Role <span className="team-required-mark" aria-hidden="true">*</span>
                  </label>
                  <select
                    id="team-invite-role"
                    value={inviteRole}
                    onChange={(event) => {
                      setInviteRole(event.target.value);
                      setInviteFieldErrors((prev) => ({ ...prev, inviteRole: '' }));
                    }}
                    disabled={!canManageMembers || busy || previewModeActive}
                    aria-required="true"
                    className={inviteFieldErrors.inviteRole ? 'is-invalid' : ''}
                    aria-invalid={Boolean(inviteFieldErrors.inviteRole)}
                    aria-describedby={inviteFieldErrors.inviteRole ? 'team-invite-role-error' : undefined}
                  >
                    {INVITE_ROLE_OPTIONS.map((role) => (
                      <option key={role} value={role}>{role}</option>
                    ))}
                  </select>
                  <FieldError id="team-invite-role-error" message={inviteFieldErrors.inviteRole} />
                </div>
                <button type="submit" className="team-btn" disabled={!canManageMembers || busy || previewModeActive} aria-disabled={!canManageMembers || busy || previewModeActive}>
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
                              disabled={!canManageMembers || busy || previewModeActive} aria-disabled={!canManageMembers || busy || previewModeActive}
                            >
                              Resend
                            </button>
                            <button
                              type="button"
                              className="team-btn tiny danger"
                              onClick={() => onCancelInvitation(row.id)}
                              disabled={!canManageMembers || busy || previewModeActive} aria-disabled={!canManageMembers || busy || previewModeActive}
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
          )}

          {showOwnershipCard && (
            <div className="team-card">
              <h2>Ownership & Billing</h2>
              {isOwnerRole ? (
                <>
                  <p className="team-subcopy">
                    Owners manage billing for this {teamLabelLower}. Member access, seat policy, and project controls remain shared with admins.
                  </p>
                  <div className="team-inline-actions">
                    <button
                      type="button"
                      className="team-btn"
                      onClick={() => navigate('/account')}
                    >
                      Open Billing
                    </button>
                  </div>
                  <p className="team-meta-note">
                    Ownership transfer and {teamLabelLower} deletion remain owner-only operations, but they are not exposed in self-serve UI yet.
                  </p>
                </>
              ) : (
                <>
                  <p className="team-subcopy">
                    Admins can manage members, seats, and shared projects, but billing and ownership actions stay with the owner.
                  </p>
                  <p className="team-meta-note">
                    Ask the owner to manage billing, ownership transfer, or account-level changes.
                  </p>
                </>
              )}
            </div>
          )}
        </div>
      </section>

      <section className="team-card">
        <h2>Shared Projects</h2>
        <p className="team-subcopy">Projects belong to the active {teamLabelLower}. Set visibility for private, team-wide, or specific members.</p>
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
              {visibleProjects.map((project) => {
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
                        disabled={busy || previewModeActive || !canSaveSharing} aria-disabled={busy || previewModeActive || !canSaveSharing}
                      >
                        Save
                      </button>
                    </td>
                  </tr>
                );
              })}
              {visibleProjects.length === 0 && (
                <tr>
                  <td colSpan={8}>
                    <p className="team-empty">No shared projects are visible for this role yet.</p>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
      <ConfirmDialog
        isOpen={Boolean(confirmDialog)}
        title={confirmDialog?.title}
        message={confirmDialog?.message}
        confirmLabel={confirmDialog?.confirmLabel}
        confirmVariant={confirmDialog?.confirmVariant}
        pending={busy}
        onCancel={() => setConfirmDialog(null)}
        onConfirm={() => confirmDialog?.onConfirm?.()}
      />
      </div>
      <JaspenAiDrawer
        isOpen={jaspenOpen}
        onOpen={openJaspen}
        onClose={() => setJaspenOpen(false)}
        messages={assistantMessages}
        input={assistantInput}
        onInputChange={setAssistantInput}
        onSend={sendAssistant}
        onStop={stopAssistant}
        busy={assistantBusy}
        starterPrompts={[
          'Who should have admin access?',
          'How should I set seat limits?',
        ]}
        placeholder="Ask Jaspen about team management..."
        contextLabel="Team"
        contextTitle="Team Management"
        contextDescription="Ask Jaspen about roles, seats, invitations, or project access."
      />
    </div>
  );
}
