// Enhanced AuthContext with cookie-friendly auth + server logout
import React, { createContext, useContext, useState, useEffect } from 'react';
import { API_BASE } from '../../config/apiBase';

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
const isSelfServePlan = (plan) => ['free', 'essential'].includes(normalizePlanKey(plan));
const resolvePlanCategory = (user) => {
  const rankedPlans = [
    normalizePlanKey(user?.active_organization_plan_key),
    normalizePlanKey(user?.subscription_plan),
  ];
  if (rankedPlans.includes('enterprise')) return 'enterprise';
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

// Small helper to always send cookies + attach Bearer token if present
async function authFetch(path, options = {}) {
  const url = path.startsWith('http') ? path : `${API_BASE_URL}${path}`;

  // Merge headers safely
  const headers = { ...(options.headers || {}) };
  const method = String(options.method || 'GET').toUpperCase();

  // When JWT cookie CSRF protection is enabled server-side, mutating requests
  // must include the double-submit token from cookie in X-CSRF-TOKEN.
  if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method) && !headers['X-CSRF-TOKEN']) {
    const cookieParts = String(document.cookie || '')
      .split(';')
      .map((part) => part.trim())
      .filter(Boolean);
    const cookieMap = {};
    cookieParts.forEach((part) => {
      const eq = part.indexOf('=');
      if (eq > 0) {
        const key = part.slice(0, eq);
        const value = part.slice(eq + 1);
        cookieMap[key] = value;
      }
    });

    const csrfToken =
      cookieMap.csrf_access_token ||
      cookieMap.csrf_token ||
      cookieMap['XSRF-TOKEN'] ||
      null;

    if (csrfToken) {
      headers['X-CSRF-TOKEN'] = decodeURIComponent(csrfToken);
    }
  }

  return fetch(url, {
    ...options,
    credentials: 'include',
    headers
  });
}

export function AuthProvider({ children }) {
  // Original state
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  // Enhanced LSS state
  const [lssUsers, setLssUsers] = useState([]);
  const [currentUserRole, setCurrentUserRole] = useState(null);
  const [permissions, setPermissions] = useState([]);
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

  // Re-check auth quietly so UI does not remain in a stale "looks logged in" state.
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === 'visible') {
        checkAuthStatus({ silent: true });
      }
    };
    document.addEventListener('visibilitychange', onVisible);

    const intervalId = window.setInterval(() => {
      checkAuthStatus({ silent: true });
    }, 5 * 60 * 1000);

    return () => {
      document.removeEventListener('visibilitychange', onVisible);
      window.clearInterval(intervalId);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
        // Cookie auth is canonical; remove any stale legacy bearer tokens.
        localStorage.removeItem('access_token');
        localStorage.removeItem('token');
        localStorage.removeItem('refresh_token');
        syncSelfServeStorageOwnership(normalized);
        setUser(normalized);
        return { authenticated: true, user: normalized };
      } else {
        // Clear any stale token if server says no
        clearAuthTokens();
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

  const login = async (email, password) => {
    try {
      setLoading(true);
      const res = await authFetch('/api/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password })
      });

      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        // Cookie is the source of truth; do not persist auth tokens in localStorage.
        localStorage.removeItem('access_token');
        localStorage.removeItem('token');
        localStorage.removeItem('refresh_token');
        const normalized = normalizeUser(data?.user || { email });
        syncSelfServeStorageOwnership(normalized);
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

    setUser(null);
    setCurrentUserRole(null);
    setPermissions([]);
    setLssUsers([]);

    // Redirect
    window.location.href = '/?auth=1';
  };

  const signup = async (email, password, name) => {
    try {
      setLoading(true);
      const res = await authFetch('/api/v1/auth/signup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password, name })
      });

      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        // Cookie is the source of truth; do not persist auth tokens in localStorage.
        localStorage.removeItem('access_token');
        localStorage.removeItem('token');
        localStorage.removeItem('refresh_token');
        const normalized = normalizeUser(data?.user || { email, name });
        syncSelfServeStorageOwnership(normalized);
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
    : (String(user?.active_organization_name || '').trim() || 'Organization');
  const isPlatformAdmin = Boolean(user?.is_admin);
  const isEnterpriseAdmin = Boolean(user?.can_access_enterprise_admin || isPlatformAdmin);
  const canAccessOrgSettings = Boolean(user?.can_access_team || user?.can_access_enterprise_admin || isPlatformAdmin);

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
    isAuthenticated,
    planCategory,
    orgDisplayName,
    isPlatformAdmin,
    isEnterpriseAdmin,
    canAccessOrgSettings,

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
