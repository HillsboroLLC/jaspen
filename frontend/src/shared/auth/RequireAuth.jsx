// filepath: src/shared/auth/RequireAuth.jsx
import { useEffect, useState } from "react";
import { useLocation, Navigate } from "react-router-dom";
import { authFetch } from "./http";

const SOFT_GATED_PREFIXES = ["/strategy"]; // render page; block server actions

export default function RequireAuth({ children }) {
  const loc = useLocation();
  const [state, setState] = useState("checking"); // checking | authed | anon
  const softGated = SOFT_GATED_PREFIXES.some(p => loc.pathname.startsWith(p));

  useEffect(() => {
    let alive = true;

    authFetch('/api/v1/auth/me', {
      method: "GET",
    })
      .then(r => (r.ok ? "authed" : "anon"))
      .catch(() => "anon")
      .then(s => {
        if (alive) setState(s);
      });

    return () => {
      alive = false;
    };
  }, [loc.pathname]);

  if (state === "checking") return null;

  if (state === "anon" && softGated) {
    // Page may render; your page should gate actions server-side.
    return children;
  }

  if (state === "anon") {
    return (
      <Navigate
        to={`/?auth=1&next=${encodeURIComponent(loc.pathname + loc.search)}`}
        replace
      />
    );
  }

  return children;
}
