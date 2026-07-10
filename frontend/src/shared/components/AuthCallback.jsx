import React, { useEffect } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { authFetch } from "../auth/http";
import {
  readPendingIntakeContext,
  clearPendingIntakeContext,
  getOrCreatePendingThreadId,
  clearPendingIntakeThreadId,
  runExclusiveHandoff,
} from "../auth/pendingIntakeContext";
import "./AuthCallback.css";

export default function AuthCallback() {
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    let cancelled = false;

    const go = (path) => {
      if (!cancelled) navigate(path, { replace: true });
    };

    const init = async () => {
      try {
        const params = new URLSearchParams(location.search);
        const next = params.get("next") || "/new";

        // If the visitor analyzed context on the homepage before Google sign-in,
        // continue that same conversation instead of losing it. Backend auth has
        // already set the session cookie during its callback, so this is a
        // normal credentialed request — no token to pass. Shares the same
        // in-flight guard + reused thread_id as the email signup/login path
        // (pendingIntakeContext.js) so a race between the two never creates
        // duplicate threads.
        const context = readPendingIntakeContext();
        if (context) {
          const handedOff = await runExclusiveHandoff(async () => {
            const threadId = getOrCreatePendingThreadId();
            try {
              const res = await authFetch('/api/v1/ai-agent/conversation/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                // strategy_objective is sent explicitly — and must stay
                // 'balanced' — because the homepage computed its readiness
                // promise under 'balanced' (public_intake.py). Omitting it
                // lets conversation/start re-INFER an objective from the
                // text (e.g. cost-heavy briefs flip to Cost Optimization),
                // so the workspace would open under a different profile
                // than the one the visitor was just shown. Same contract as
                // the workspace composer, which always sends its pill value.
                body: JSON.stringify({ message: context, thread_id: threadId, strategy_objective: 'balanced' }),
              });
              const data = await res.json().catch(() => ({}));
              const sid = data?.thread_id || data?.session_id;
              if (!cancelled && res.ok && sid) {
                // Clear only on confirmed success; on failure both keys stay
                // and /new recovers the context as a composer prefill.
                clearPendingIntakeContext();
                clearPendingIntakeThreadId();
                window.location.href = `/new?sid=${encodeURIComponent(sid)}`;
                return true;
              }
            } catch { /* fall through to normal redirect; pending keys intentionally kept */ }
            return false;
          });
          if (handedOff) return;
        }

        // No Supabase. Backend auth should set cookie/JWT during its callback.
        // We simply forward the user to the intended page.
        return go(next);
      } catch (e) {
        console.error("AuthCallback init error:", e);
        go("/?auth=1");
      }
    };

    init();
    return () => {
      cancelled = true;
    };
  }, [navigate, location.search]);

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