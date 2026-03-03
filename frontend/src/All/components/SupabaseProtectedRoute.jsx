import React, { useEffect, useState } from 'react';
import { Navigate } from 'react-router-dom';
import Spinner from './Spinner/Spinner';

const API_BASE =
  process.env.REACT_APP_API_BASE ||
  process.env.VITE_API_BASE ||
  'https://api.jaspen.ai';

export default function SupabaseProtectedRoute({ children }) {
  const [ok, setOk] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;

    const check = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/auth/me-cookie`, {
          method: 'GET',
          credentials: 'include', // send the sekki_access cookie
        });

        if (!alive) return;

        if (res.ok) {
          setOk(true);
        } else {
          setOk(false);
        }
      } catch (_e) {
        if (!alive) return;
        setOk(false);
      } finally {
        if (!alive) return;
        setLoading(false);
      }
    };

    check();
    return () => {
      alive = false;
    };
  }, []);

  if (loading) return <Spinner />;

  if (!ok) {
    // This keeps your existing behavior (opens the auth modal on home)
    return <Navigate to="/?auth=1" replace />;
  }

  return children;
}
