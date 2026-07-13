// src/components/ProtectedRoute.js
import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../shared/auth/AuthContext';
import Spinner from './Spinner/Spinner';

export default function ProtectedRoute({ children }) {
  const location = useLocation();
  const { user, loading } = useAuth();

  if (loading) {
    return <Spinner />;
  }
  
  if (!user) {
    const params = new URLSearchParams(location.search || '');
    const wantsDecisionProfile = location.pathname === '/decision-profile';
    if (wantsDecisionProfile) {
      const redirectParams = new URLSearchParams({
        auth: 'signup',
        next: '/decision-profile',
      });
      const source = params.get('source');
      if (source) redirectParams.set('source', source);
      return <Navigate to={`/?${redirectParams.toString()}`} replace />;
    }
    return <Navigate to="/?auth=1" replace />;
  }
  
  return children;
}
