import React, { useEffect, useState } from 'react';
import { Navigate } from 'react-router-dom';
import { supabase } from '../shared/supabase/supabaseClient';
import Spinner from './Spinner/Spinner';

export default function SupabaseProtectedRoute({ children }) {
  const [session, setSession] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let subscription;

    const init = async () => {
      if (!supabase) {
        setSession(null);
        setLoading(false);
        return;
      }

      const { data } = await supabase.auth.getSession();
      setSession(data?.session ?? null);
      setLoading(false);

      const { data: listener } = supabase.auth.onAuthStateChange((_event, nextSession) => {
        setSession(nextSession);
      });

      subscription = listener?.subscription;
    };

    init();

    return () => {
      subscription?.unsubscribe?.();
    };
  }, []);

  if (loading) {
    return <Spinner />;
  }

  if (!session) {
    return <Navigate to="/?auth=1" replace />;
  }

  return children;
}
