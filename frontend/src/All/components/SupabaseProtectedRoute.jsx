import React from 'react';
import { Navigate } from 'react-router-dom';
import { useSupabaseAuth } from '../shared/supabase/SupabaseAuthContext';
import Spinner from './Spinner/Spinner';

export default function SupabaseProtectedRoute({ children }) {
  const { user, loading } = useSupabaseAuth();

  if (loading) {
    return <Spinner />;
  }

  if (!user) {
    return <Navigate to="/?auth=1" replace />;
  }

  return children;
}
