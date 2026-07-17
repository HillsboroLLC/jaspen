import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from './AuthContext';

export default function RequireTeamAccess({ children }) {
  const location = useLocation();
  const { user } = useAuth();

  const params = new URLSearchParams(location.search);
  const hasInviteToken = Boolean(String(params.get('invite') || '').trim());
  const canAccessTeam = Boolean(user?.can_access_team);
  const isGlobalAdmin = Boolean(user?.is_admin);
  const isAdminPreview = Boolean(
    isGlobalAdmin && ['team', 'business'].includes(String(params.get('admin_preview') || '').trim().toLowerCase())
  );

  if (canAccessTeam || hasInviteToken || isGlobalAdmin || isAdminPreview) {
    return children;
  }

  return <Navigate to="/new" replace />;
}
