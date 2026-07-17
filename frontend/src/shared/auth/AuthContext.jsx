// Enhanced AuthContext with cookie-friendly auth + server logout
import React, { createContext, useContext, useState, useEffect, useRef } from 'react';
import { API_BASE } from '../../config/apiBase';
import { AUTH_EVENTS, authFetch as cookieAuthFetch } from './http';

// Auto sign-out after this much continuous inactivity. The session normally
// renews itself in the background, so without this an open tab stays logged in
// indefinitely. We persist the last-activity timestamp so the timeout is also
// enforced across a hard refresh (e.g. coming back the next day).
const IDLE_LOGOUT_MS = 8 * 60 * 60 * 1000; // 8 hours
const LAST_ACTIVITY_STORAGE_KEY = 'jas_last_activity';

function readLastActivity() {
  try {
    const raw = window.localStorage.getItem(LAST_ACTIVITY_STORAGE_KEY);
    const ts = raw ? parseInt(raw, 10) : NaN;
    return Number.isFinite(ts) ? ts : null;
  } catch {
    return null;
  }
}

function writeLastActivity(ts) {
  try {
    window.localStorage.setItem(LAST_ACTIVITY_STORAGE_KEY, String(ts));
  } catch {
    // ignore storage failures (private mode, quota)
  }
}

export function isDecisionProfileEmailEntry() {
  if (typeof window === 'undefined') return false;
  try {
    const params = new URLSearchParams(window.location.search || '');
    return (
      String(params.get('auth') || '').trim().toLowerCase() === 'signup'
      && String(params.get('source') || '').trim().toLowerCase() === 'decision-profile-email'
    );
  } catch {
    return false;
  }
}

// User roles for LSS system
export const USER_ROLES = {
  ADMIN: 'admin',
  PROJECT_LEAD: 'project_lead',
  TEAM_MEMBER: 'team_member'
};

// Permissions for LSS system
export const PERMISSIONS = {
  // Admin permissions
  MANAGE_USERS: 'manage_users',
  CONFIGURE_SYSTEM: 'configure_system',
  VIEW_ALL_PROJECTS: 'view_all_projects',
  MANAGE_TOLLGATES: 'manage_tollgates',

  // Project Lead permissions
  CREATE_PROJECTS: 'create_projects',
  MANAGE_OWN_PROJECTS: 'manage_own_projects',
  ACCESS_KANBAN: 'access_kanban',
  ASSIGN_TEAM_MEMBERS: 'assign_team_members',

  // Team Member permissions
  VIEW_ASSIGNED_PROJECTS: 'view_assigned_projects',
  EDIT_ARTIFACTS: 'edit_artifacts',
  SUBMIT_WORK: 'submit_work'
};

// Role permissions mapping
const ROLE_PERMISSIONS = {
  [USER_ROLES.ADMIN]: [
    PERMISSIONS.MANAGE_USERS,
    PERMISSIONS.CONFIGURE_SYSTEM,
    PERMISSIONS.VIEW_ALL_PROJECTS,
    PERMISSIONS.MANAGE_TOLLGATES,
    PERMISSIONS.CREATE_PROJECTS,
    PERMISSIONS.MANAGE_OWN_PROJECTS,
    PERMISSIONS.ASSIGN_TEAM_MEMBERS,
    PERMISSIONS.VIEW_ASSIGNED_PROJECTS,
    PERMISSIONS.EDIT_ARTIFACTS,
    PERMISSIONS.SUBMIT_WORK
  ],
  [USER_ROLES.PROJECT_LEAD]: [
    PERMISSIONS.CREATE_PROJECTS,
    PERMISSIONS.MANAGE_OWN_PROJECTS,
    PERMISSIONS.ACCESS_KANBAN,
    PERMISSIONS.ASSIGN_TEAM_MEMBERS,
    PERMISSIONS.VIEW_ASSIGNED_PROJECTS,
    PERMISSIONS.EDIT_ARTIFACTS,
    PERMISSIONS.SUBMIT_WORK
  ],
  [USER_ROLES.TEAM_MEMBER]: [
    PERMISSIONS.VIEW_ASSIGNED_PROJECTS,
    PERMISSIONS.EDIT_ARTIFACTS,
    PERMISSIONS.SUBMIT_WORK
  ]
};

const AuthContext = createContext();

// Backend URL configuration
const API_BASE_URL = API_BASE;

// Normalize user shape across email + Google sign-in payloads.
const normalizeUser = (raw) => {
  if (!raw) return null;
  const email =
    raw.email ||
    raw.user_metadata?.email ||
    raw.profile?.email ||
    raw.identity?.email ||
    null;

  let name =
    raw.name ||
    raw.full_name ||
    raw.user_metadata?.full_name ||
    raw.user_metadata?.name ||
    raw.profile?.name ||
    null;

  if (!name) {
    const first =
      raw.given_name ||
      raw.first_name ||
      raw.user_metadata?.given_name ||
      raw.user_metadata?.first_name ||
      raw.profile?.given_name ||
      raw.profile?.first_name ||
      null;
    const last =
      raw.family_name ||
      raw.last_name ||
      raw.user_metadata?.family_name ||
      raw.user_metadata?.last_name ||
      raw.profile?.family_name ||
      raw.profile?.last_name ||
      null;
    name = [first, last].filter(Boolean).join(' ').trim() || null;
  }

  if (!name && email) {
    name = email.split('@')[0] || null;
  }

  return {
    ...raw,
    email: email || raw.email || null,
    name: name || raw.name || null
  };
};

const normalizePlanKey = (plan) => String(plan || '').trim().toLowerCase();
const isSelfServePlan = (plan) => ['free', 'starter', 'essential'].includes(normalizePlanKey(plan));
const resolvePlanCategory = (user) => {
  const rankedPlans = [
    normalizePlanKey(user?.active_organization_plan_key),
    normalizePlanKey(user?.subscription_plan),
  ];
  if (rankedPlans.includes('enterprise_custom')) return 'enterprise';
  if (rankedPlans.includes('business')) return 'business';
  if (rankedPlans.includes('team')) return 'team';
  return 'individual';
};
const AUTH_STORAGE_OWNER_KEY = 'jas_storage_owner_id';

const clearLegacySessionCaches = () => {
  const fixedKeys = [
    'jas_history',
    'jas_projects',
    'jas_last_session_id',
    'jas_sid',
    'jaspen_last_email',
    'jaspen_history',
    'jaspen_projects',
    'jaspen_last_session_id',
    'jaspen_sid',
  ];
  fixedKeys.forEach((key) => localStorage.removeItem(key));

  for (let i = localStorage.length - 1; i >= 0; i -= 1) {
    const key = localStorage.key(i);
    if (key && key.startsWith('session_')) {
      localStorage.removeItem(key);
    }
  }
};

const getSignupReferralCode = () => {
  if (typeof window === 'undefined') return null;
  try {
    const params = new URLSearchParams(window.location.search || '');
    return (
      params.get('referral_code')
      || params.get('invite_code')
      || params.get('ref')
      || params.get('invite')
      || null
    );
  } catch (error) {
    console.debug('Failed reading referral code from URL:', error);
    return null;
  }
};

const hasLegacySessionKeys = () => {
  for (let i = 0; i < localStorage.length; i += 1) {
    const key = localStorage.key(i);
    if (key && key.startsWith('session_')) {
      return true;
    }
  }
  return false;
};

const syncSelfServeStorageOwnership = (user) => {
  if (!isSelfServePlan(user?.subscription_plan)) {
    return;
  }

  // Always remove obsolete legacy keys for self-serve sessions.
  ['jaspen_last_session_id', 'jaspen_sid', 'jaspen_history', 'jaspen_projects'].forEach((key) => localStorage.removeItem(key));

  const ownerId = String(user?.id || user?.email || '').trim();
  if (!ownerId) {
    return;
  }

  const currentOwner = String(localStorage.getItem(AUTH_STORAGE_OWNER_KEY) || '').trim();
  if (!currentOwner || currentOwner !== ownerId) {
    if (currentOwner || hasLegacySessionKeys()) {
      clearLegacySessionCaches();
    }
    localStorage.setItem(AUTH_STORAGE_OWNER_KEY, ownerId);
  }
};

// Small helper to always send cookies and the CSRF header when needed.
async function authFetch(path, options = {}) {
  const url = path.startsWith('http') ? path : `${API_BASE_URL}${path}`;
  return cookieAuthFetch(url, options);
}

export function AuthProvider({ children }) {
  // Original state
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  // MFA enforcement state — set when /me returns 403 with mfa_required
  const [mfaEnforcement, setMfaEnforcement] = useState(null);

  // Enhanced LSS state
  const [lssUsers, setLssUsers] = useState([]);
  const [currentUserRole, setCurrentUserRole] = useState(null);
  const [permissions, setPermissions] = useState([]);
  const authRedirectInFlightRef = useRef(false);
  // Tracks whether this browser session ever had an authenticated user. Used to
  // distinguish "session expired" (was logged in, now 401) from "never logged in"
  // (anonymous visitor whose background request returned 401).
  const hadUserRef = useRef(false);
  // Timestamp (ms) of the user's last interaction, used for idle auto sign-out.
  const lastActivityRef = useRef(readLastActivity() || Date.now());
  // The persisted activity timestamp captured at app boot, before any new
  // activity overwrites it — used for the one-time load-time idle check so a
  // hard refresh after a long idle period signs the user out.
  const bootLastActivityRef = useRef(readLastActivity());
  const didInitialIdleCheckRef = useRef(false);
  const idleLogoutInFlightRef = useRef(false);
  const clearAuthTokens = () => {
    localStorage.removeItem('access_token');
    localStorage.removeItem('token');
    localStorage.removeItem('refresh_token');
    document.cookie = 'jaspen_sid=; Max-Age=0; Path=/; Secure; SameSite=None';
  };

  // Check if user is authenticated on app load (cookie OR token)
  useEffect(() => {
    checkAuthStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Auto-detect and persist the user's browser timezone so the backend
  // can use it for emails, notifications, and scheduled reports.
  useEffect(() => {
    if (!user) return;
    try {
      const detectedTz = Intl.DateTimeFormat().resolvedOptions().timeZone;
      if (!detectedTz) return;
      const storedTz = user?.ui_preferences?.timezone;
      if (storedTz === detectedTz) return;
      authFetch('/api/v1/auth/me', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ui_preferences: { timezone: detectedTz } }),
      }).then((res) => {
        if (res.ok) res.json().then((data) => setUser(normalizeUser(data))).catch(() => {});
      }).catch(() => {});
    } catch {}
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id]);

  // Sign the user out after a long stretch of inactivity. Clears auth state and
  // sends them to the login screen with an explanatory flag.
  const performIdleLogout = () => {
    if (idleLogoutInFlightRef.current) return;
    if (isDecisionProfileEmailEntry()) {
      try {
        clearAuthTokens();
        localStorage.removeItem('lss_user_roles');
        localStorage.removeItem(LAST_ACTIVITY_STORAGE_KEY);
      } catch {}
      setUser(null);
      setCurrentUserRole(null);
      setPermissions([]);
      setLssUsers([]);
      return;
    }
    idleLogoutInFlightRef.current = true;
    try {
      // Best-effort server logout; don't block the redirect on it.
      authFetch('/api/v1/auth/logout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      }).catch(() => {});
    } catch {}
    try {
      clearAuthTokens();
      localStorage.removeItem('lss_user_roles');
      localStorage.removeItem(LAST_ACTIVITY_STORAGE_KEY);
    } catch {}
    window.location.href = '/?auth=1&signed_out=1&reason=idle';
  };

  // Track user activity so we can enforce an idle timeout. The timestamp is
  // persisted to localStorage so the timeout survives a hard refresh.
  useEffect(() => {
    const markActive = () => {
      const now = Date.now();
      lastActivityRef.current = now;
      writeLastActivity(now);
    };
    // Seed once on mount so a fresh login starts the clock.
    markActive();
    const events = ['mousedown', 'keydown', 'scroll', 'touchstart', 'click'];
    const opts = { passive: true };
    events.forEach((evt) => window.addEventListener(evt, markActive, opts));
    return () => {
      events.forEach((evt) => window.removeEventListener(evt, markActive, opts));
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Re-check auth quietly so UI does not remain in a stale "looks logged in" state.
  // Also silently renews the access token cookie on each tick so the session stays
  // alive throughout the work session without mid-session logouts — unless the
  // user has been idle past the idle-logout threshold, in which case we sign out.
  useEffect(() => {
    const isIdleExpired = () => {
      const last = lastActivityRef.current || readLastActivity();
      if (!last) return false;
      return Date.now() - last > IDLE_LOGOUT_MS;
    };

    const silentRefresh = async () => {
      // Never renew a session the user has effectively abandoned.
      if (isIdleExpired()) {
        performIdleLogout();
        return;
      }
      try {
        await authFetch('/api/v1/auth/refresh', { method: 'POST' });
      } catch {
        // Refresh failures are silent — the next checkAuthStatus will handle expiry.
      }
    };

    const onVisible = () => {
      if (document.visibilityState === 'visible') {
        if (isIdleExpired()) {
          performIdleLogout();
          return;
        }
        silentRefresh().then(() => checkAuthStatus({ silent: true })).catch(() => {});
      }
    };
    document.addEventListener('visibilitychange', onVisible);

    const intervalId = window.setInterval(async () => {
      if (isIdleExpired()) {
        performIdleLogout();
        return;
      }
      await silentRefresh();
      checkAuthStatus({ silent: true });
    }, 5 * 60 * 1000);

    return () => {
      document.removeEventListener('visibilitychange', onVisible);
      window.clearInterval(intervalId);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const handleSessionExpired = () => {
      // If the user was never authenticated in this session, a 401 is expected
      // (anonymous visitor) — don't redirect to the session-expired error page.
      if (!hadUserRef.current) return;
      if (authRedirectInFlightRef.current) return;
      authRedirectInFlightRef.current = true;

      clearAuthTokens();
      setMfaEnforcement(null);
      setUser(null);
      setCurrentUserRole(null);
      setPermissions([]);
      setLssUsers([]);

      const target = '/?auth=1&error=session_expired';
      const current = `${window.location.pathname}${window.location.search}`;
      if (current !== target) {
        window.location.assign(target);
        return;
      }

      authRedirectInFlightRef.current = false;
    };

    const handleServerError = () => {
      const protectedPrefixes = [
        '/new',
        '/dashboard',
        '/projects',
        '/scores',
        '/insights',
        '/reports',
        '/activity',
        '/connectors-manage',
        '/account',
        '/team',
        '/enterprise-admin',
        '/knowledge',
        '/jaspen-admin',
      ];
      const isProtectedPath = protectedPrefixes.some((prefix) => window.location.pathname.startsWith(prefix));
      if (isProtectedPath) {
        window.location.assign('/server-error');
      }
    };

    window.addEventListener(AUTH_EVENTS.SESSION_EXPIRED_EVENT, handleSessionExpired);
    window.addEventListener(AUTH_EVENTS.SERVER_ERROR_EVENT, handleServerError);
    return () => {
      window.removeEventListener(AUTH_EVENTS.SESSION_EXPIRED_EVENT, handleSessionExpired);
      window.removeEventListener(AUTH_EVENTS.SERVER_ERROR_EVENT, handleServerError);
    };
  }, []);

  // Track that this session had a real user — prevents spurious session-expired redirects
  // for anonymous visitors whose background requests return 401.
  useEffect(() => {
    if (user) hadUserRef.current = true;
  }, [user]);

  // Load LSS users and set role when user changes
  useEffect(() => {
    if (user) {
      loadLSSUsers();
      setUserLSSRole();
    } else {
      setCurrentUserRole(null);
      setPermissions([]);
    }
  }, [user]);

  // Update permissions when role changes
  useEffect(() => {
    if (currentUserRole) {
      const rolePermissions = ROLE_PERMISSIONS[currentUserRole] || [];
      setPermissions(rolePermissions);
      console.log('Role changed to:', currentUserRole, 'Permissions:', rolePermissions);
    }
  }, [currentUserRole]);

  // ===== Auth functions =====

  // IMPORTANT: do NOT require localStorage token just to check session.
  // If the cookie is present, /api/v1/auth/me will return 200 and user info.
  const checkAuthStatus = async ({ silent = false } = {}) => {
    if (!silent) setLoading(true);
    try {
      const res = await authFetch('/api/v1/auth/me', { method: 'GET' });

      if (res.ok) {
        const userData = await res.json();
        const normalized = normalizeUser(userData);
        // Enforce the idle timeout across hard refreshes: if the cookie is still
        // valid but the user was inactive past the threshold at app boot (e.g.
        // returning the next day), sign them out instead of restoring the
        // session. Only runs once, on the first auth check, using the boot-time
        // timestamp so later background checks don't see overwritten activity.
        if (!didInitialIdleCheckRef.current) {
          didInitialIdleCheckRef.current = true;
          const boot = bootLastActivityRef.current;
          if (boot && Date.now() - boot > IDLE_LOGOUT_MS) {
            performIdleLogout();
            return { authenticated: false, user: null };
          }
        }
        // Cookie auth is canonical; remove any stale legacy bearer tokens.
        localStorage.removeItem('access_token');
        localStorage.removeItem('token');
        localStorage.removeItem('refresh_token');
        syncSelfServeStorageOwnership(normalized);
        setMfaEnforcement(null);
        setUser(normalized);
        return { authenticated: true, user: normalized };
      } else {
        // Check if the session is valid but MFA is required
        const data = await res.json().catch(() => ({}));
        if (res.status === 403 && data?.mfa_required) {
          // Session exists but org requires MFA — force MFA setup/challenge
          clearAuthTokens();
          setUser(null);
          const enforcement = {
            mfaRequired: true,
            mfaSetupRequired: Boolean(data?.mfa_setup_required),
            pendingToken: data?.pending_token || '',
            organizationId: data?.organization_id || '',
            organizationName: data?.organization_name || '',
          };
          setMfaEnforcement(enforcement);
          return { authenticated: false, user: null, ...enforcement };
        }
        // Clear any stale token if server says no
        clearAuthTokens();
        setMfaEnforcement(null);
        setUser(null);
        return { authenticated: false, user: null };
      }
    } catch (error) {
      console.error('Auth check failed:', error);
      clearAuthTokens();
      setUser(null);
      return { authenticated: false, user: null };
    } finally {
      if (!silent) setLoading(false);
    }
  };

  const updateDisplayName = async (name) => {
    const trimmed = String(name || '').trim();
    if (!trimmed) {
      return { success: false, error: 'Name is required.' };
    }

    try {
      const res = await authFetch('/api/v1/auth/me', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: trimmed })
      });

      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        return { success: false, error: data?.error || data?.msg || data?.message || 'Unable to update display name.' };
      }

      const normalized = normalizeUser(data);
      setUser(normalized);
      return { success: true, user: normalized };
    } catch (error) {
      console.error('Update display name error:', error);
      return { success: false, error: 'Network error. Please try again.' };
    }
  };

  const updateUiPreferences = async (uiPreferences = {}) => {
    if (!uiPreferences || typeof uiPreferences !== 'object' || Array.isArray(uiPreferences)) {
      return { success: false, error: 'Invalid preferences payload.' };
    }

    try {
      const res = await authFetch('/api/v1/auth/me', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ui_preferences: uiPreferences })
      });

      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        return { success: false, error: data?.error || data?.msg || data?.message || 'Unable to update preferences.' };
      }

      const normalized = normalizeUser(data);
      setUser(normalized);
      return { success: true, user: normalized };
    } catch (error) {
      console.error('Update UI preferences error:', error);
      return { success: false, error: 'Network error. Please try again.' };
    }
  };

  const login = async (email, password) => {
    try {
      setLoading(true);
      const res = await authFetch('/api/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password })
      });

      const data = await res.json().catch(() => ({}));

      // MFA required — return special result so the UI can show the challenge/setup form
      if (data?.mfa_required) {
        return {
          success: false,
          mfaRequired: true,
          mfaSetupRequired: Boolean(data?.mfa_setup_required),
          pendingToken: data?.pending_token || '',
          organizationId: data?.organization_id || '',
          organizationName: data?.organization_name || '',
          error: data?.message || '',
        };
      }

      if (res.ok) {
        if (data?.approval_required || data?.verification_required) {
          return {
            success: false,
            pending: Boolean(data?.approval_required),
            verificationRequired: Boolean(data?.verification_required),
            error: data?.message || 'Sign-in is not available yet.',
            detail: data?.detail || '',
          };
        }
        // Cookie is the source of truth; do not persist auth tokens in localStorage.
        localStorage.removeItem('access_token');
        localStorage.removeItem('token');
        localStorage.removeItem('refresh_token');
        const normalized = normalizeUser(data?.user || { email });
        syncSelfServeStorageOwnership(normalized);
        // Fresh login starts the idle clock and clears any stale boot value so a
        // leftover timestamp can't immediately sign the new session out.
        const now = Date.now();
        lastActivityRef.current = now;
        bootLastActivityRef.current = now;
        didInitialIdleCheckRef.current = true;
        writeLastActivity(now);
        setUser(normalized);
        return { success: true };
      } else {
        return { success: false, error: data?.message || 'Sign-in failed' };
      }
    } catch (error) {
      console.error('Sign-in error:', error);
      return { success: false, error: 'Network error. Please try again.' };
    } finally {
      setLoading(false);
    }
  };

  // Call server to clear the cookie; then clear local state.
  const logout = async () => {
    try {
      await authFetch('/api/v1/auth/logout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      });
    } catch (e) {
      // non-blocking
      console.debug('Logout request failed silently:', e);
    }

    // Clear client state regardless
    if (isSelfServePlan(user?.subscription_plan)) {
      clearLegacySessionCaches();
      localStorage.removeItem(AUTH_STORAGE_OWNER_KEY);
    }
    clearAuthTokens();
    localStorage.removeItem('lss_user_roles');
    localStorage.removeItem(LAST_ACTIVITY_STORAGE_KEY);

    setUser(null);
    setCurrentUserRole(null);
    setPermissions([]);
    setLssUsers([]);

    // Redirect to login with a visible signed-out confirmation.
    window.location.href = '/?auth=1&signed_out=1';
  };

  const signup = async (email, password, name, options = {}) => {
    try {
      setLoading(true);
      const referralCode = String(
        options?.referralCode
        || options?.inviteCode
        || getSignupReferralCode()
        || ''
      ).trim();
      const res = await authFetch('/api/v1/auth/signup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email,
          password,
          name,
          ...(options?.planKey || options?.plan ? {
            plan_key: options?.planKey || options?.plan,
          } : {}),
          ...(referralCode ? { referral_code: referralCode } : {}),
        })
      });

      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        if (res.status === 202 || data?.approval_required || data?.verification_required) {
          return {
            success: false,
            pending: Boolean(data?.approval_required),
            verificationRequired: Boolean(data?.verification_required),
            paymentPending: Boolean(data?.payment_pending),
            planKey: data?.plan_key || '',
            error: data?.message || 'Your signup is in progress.',
            detail: data?.detail || '',
          };
        }
        // Cookie is the source of truth; do not persist auth tokens in localStorage.
        localStorage.removeItem('access_token');
        localStorage.removeItem('token');
        localStorage.removeItem('refresh_token');
        const normalized = normalizeUser(data?.user || { email, name });
        syncSelfServeStorageOwnership(normalized);
        const now = Date.now();
        lastActivityRef.current = now;
        bootLastActivityRef.current = now;
        didInitialIdleCheckRef.current = true;
        writeLastActivity(now);
        setUser(normalized);
        return { success: true };
      } else {
        return { success: false, error: data?.message || 'Signup failed' };
      }
    } catch (error) {
      console.error('Signup error:', error);
      return { success: false, error: 'Network error. Please try again.' };
    } finally {
      setLoading(false);
    }
  };

  // ===== LSS helpers =====

  const loadLSSUsers = () => {
    try {
      const savedUsers = localStorage.getItem('lss_users');
      const users = savedUsers ? JSON.parse(savedUsers) : [];
      setLssUsers(users);
    } catch (error) {
      console.error('Failed to load LSS users:', error);
    }
  };

  const setUserLSSRole = () => {
    if (!user) return;

    const lssUserData = localStorage.getItem('lss_user_roles');
    if (lssUserData) {
      try {
        const roles = JSON.parse(lssUserData);
        const userRole = roles[user.id] || roles[user.email];
        if (userRole && Object.values(USER_ROLES).includes(userRole)) {
          console.log('Loading saved role:', userRole, 'for user:', user.id || user.email);
          setCurrentUserRole(userRole);
          return;
        }
      } catch (error) {
        console.error('Failed to parse LSS roles:', error);
      }
    }

    // Default role assignment logic
    console.log('Setting default role for user:', user.email);
    if (user.email && user.email.toLowerCase().includes('admin')) {
      setCurrentUserRole(USER_ROLES.ADMIN);
    } else {
      setCurrentUserRole(USER_ROLES.PROJECT_LEAD);
    }
  };

  const setUserRole = (userId, role) => {
    try {
      console.log('Setting role:', role, 'for user:', userId);

      if (!Object.values(USER_ROLES).includes(role)) {
        console.error('Invalid role:', role);
        return false;
      }

      const lssUserData = localStorage.getItem('lss_user_roles');
      const roles = lssUserData ? JSON.parse(lssUserData) : {};

      roles[userId] = role;
      if (user && user.email) {
        roles[user.email] = role;
      }

      localStorage.setItem('lss_user_roles', JSON.stringify(roles));
      console.log('Saved roles to localStorage:', roles);

      if (userId === user?.id || userId === user?.email) {
        console.log('Updating current user role to:', role);
        setCurrentUserRole(role);
      }

      return true;
    } catch (error) {
      console.error('Failed to set user role:', error);
      return false;
    }
  };

  // Permission checking functions
  const hasPermission = (permission) => {
    const hasIt = permissions.includes(permission);
    console.log('Checking permission:', permission, 'Result:', hasIt, 'Current permissions:', permissions);
    return hasIt;
  };

  const hasRole = (role) => {
    const hasIt = currentUserRole === role;
    console.log('Checking role:', role, 'Current role:', currentUserRole, 'Result:', hasIt);
    return hasIt;
  };

  const isAdmin = () => hasRole(USER_ROLES.ADMIN);
  const isProjectLead = () => hasRole(USER_ROLES.PROJECT_LEAD);
  const isTeamMember = () => hasRole(USER_ROLES.TEAM_MEMBER);

  // Project access checking
  const canAccessProject = (project) => {
    if (isAdmin()) return true;
    if (isProjectLead() && project.leadId === user?.id) return true;
    if (project.teamMembers && project.teamMembers.includes(user?.id)) return true;
    return false;
  };

  const canEditProject = (project) => {
    if (isAdmin()) return true;
    if (isProjectLead() && project.leadId === user?.id) return true;
    return false;
  };

  const canAccessKanban = (project) => isProjectLead() && project && project.leadId === user?.id;
  const canAccessKanbanGeneral = () => isProjectLead();

  // Helper function to check if user is authenticated
  const isAuthenticated = () => !!user; // cookie session populates user

  const planCategory = resolvePlanCategory(user);
  const orgDisplayName = planCategory === 'individual'
    ? 'Personal Workspace'
    : (
        String(user?.active_organization_name || '').trim()
        || (planCategory === 'business' ? 'Business Workspace' : 'Team Workspace')
      );
  const orgRole = String(user?.active_organization_role || '').toLowerCase() || null;
  const isPlatformAdmin = Boolean(user?.is_admin);
  const isEnterpriseAdmin = Boolean(user?.can_access_enterprise_admin || isPlatformAdmin);
  const canAccessOrgSettings = Boolean(user?.can_access_team || user?.can_access_enterprise_admin || isPlatformAdmin);
  const canManageOrg = orgRole === 'owner' || orgRole === 'admin' || isPlatformAdmin;
  const canEditProjects = ['owner', 'admin', 'creator', 'collaborator'].includes(orgRole) || isPlatformAdmin;
  const isOrgViewer = orgRole === 'viewer';
  const isOrgCollaborator = orgRole === 'collaborator';
  const isOrgCreator = ['owner', 'admin', 'creator'].includes(orgRole) || isPlatformAdmin;

  const value = {
    // Original functionality (preserved)
    user,
    loading,
    login,
    logout,
    signup,
    setUser,
    checkAuthStatus,
    updateDisplayName,
    updateUiPreferences,
    isAuthenticated,
    planCategory,
    orgDisplayName,
    isPlatformAdmin,
    isEnterpriseAdmin,
    canAccessOrgSettings,
    orgRole,
    canManageOrg,
    canEditProjects,
    isOrgViewer,
    isOrgCollaborator,
    isOrgCreator,

    // LSS functionality
    lssUsers,
    currentUserRole,
    permissions,
    setUserRole,

    // Permission checking
    hasPermission,
    hasRole,
    isAdmin,
    isProjectLead,
    isTeamMember,

    // Project access
    canAccessProject,
    canEditProject,
    canAccessKanban,
    canAccessKanbanGeneral,

    // Constants
    USER_ROLES,
    PERMISSIONS,

    // MFA enforcement (set when /me returns mfa_required for existing session)
    mfaEnforcement,
    setMfaEnforcement,

    // helper for API calls elsewhere
    authFetch
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// Preserve original useAuth hook
export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
