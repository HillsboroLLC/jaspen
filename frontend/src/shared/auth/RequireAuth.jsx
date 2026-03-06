// filepath: src/shared/auth/RequireAuth.jsx
import { useEffect, useState } from "react";
import { useLocation, Navigate } from "react-router-dom";
import { API_BASE } from "../../config/apiBase";

const SOFT_GATED_PREFIXES = ["/market-iq"]; // render page; block server actions

export default function RequireAuth({ children }) {
  const loc = useLocation();
  const [state, setState] = useState("checking"); // checking | authed | anon
  const softGated = SOFT_GATED_PREFIXES.some(p => loc.pathname.startsWith(p));

  useEffect(() => {
    let alive = true;

    // Why: Some calls may require Bearer even with cookies; include if present.
    const accessToken =
      localStorage.getItem("access_token") || localStorage.getItem("token");

    fetch(`${API_BASE}/api/auth/me`, {
      method: "GET",
      credentials: "include",
      headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {}
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
