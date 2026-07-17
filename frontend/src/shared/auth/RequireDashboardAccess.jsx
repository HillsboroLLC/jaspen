import React from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from './AuthContext';

const DASHBOARD_PLAN_KEYS = new Set(['team', 'business', 'enterprise_custom']);

function normalizePlan(value) {
  return String(value || '').trim().toLowerCase();
}

export default function RequireDashboardAccess({ children }) {
  const { user } = useAuth();

  const userPlan = normalizePlan(user?.active_organization_plan_key || user?.subscription_plan);
  const isGlobalAdmin = Boolean(user?.is_admin);
  const hasTeamAccess = Boolean(user?.can_access_team || user?.can_access_enterprise_admin);
  const planAllowsDashboard = DASHBOARD_PLAN_KEYS.has(userPlan);

  if (isGlobalAdmin || hasTeamAccess || planAllowsDashboard) {
    return children;
  }

  return <Navigate to="/new" replace />;
}
