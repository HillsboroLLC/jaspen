import React, { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { supabase } from '../shared/supabase/supabaseClient';
import './AuthCallback.css';

const FALLBACK_TIMEOUT_MS = 3500;

export default function AuthCallback() {
  const navigate = useNavigate();

  useEffect(() => {
    let timeoutId;
    let subscription;
    const params = new URLSearchParams(window.location.search);
    const next = params.get('next') || '/market-iq';

    const redirectHome = () => {
      navigate('/?auth=1', { replace: true });
    };

    const redirectMarket = () => {
      navigate(next, { replace: true });
    };

    const init = async () => {
      if (!supabase) {
        redirectHome();
        return;
      }

      const { data } = await supabase.auth.getSession();
      if (data?.session) {
        redirectMarket();
        return;
      }

      const { data: listener } = supabase.auth.onAuthStateChange((_event, session) => {
        if (session) {
          redirectMarket();
        }
      });

      subscription = listener?.subscription;
      timeoutId = setTimeout(redirectHome, FALLBACK_TIMEOUT_MS);
    };

    init();

    return () => {
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
      subscription?.unsubscribe?.();
    };
  }, [navigate]);

  return (
    <div className="auth-callback">
      <div className="auth-callback-card">
        <div className="auth-callback-spinner" />
        <h1>Signing you in…</h1>
        <p>Hang tight while we secure your session.</p>
      </div>
    </div>
  );
}
