import React from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../../shared/auth/AuthContext';
import { isMasterAdminUser } from '../../shared/auth/masterAdmin';

export default function MasterAdminGuard({ children }) {
  const { user } = useAuth();
  if (!isMasterAdminUser(user)) {
    return <Navigate to="/new" replace />;
  }
  return children;
}
