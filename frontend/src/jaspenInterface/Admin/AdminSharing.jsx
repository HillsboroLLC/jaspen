import React, { useCallback, useEffect, useState } from 'react';

import { API_BASE } from '../../config/apiBase';
import { buildAuthHeaders } from '../../shared/auth/http';

const SHARES_API = `${API_BASE}/api/v1/shares/admin`;

async function adminRequest(url, { method = 'GET', body } = {}) {
  const response = await fetch(url, {
    method,
    credentials: 'include',
    headers: buildAuthHeaders({ 'Content-Type': 'application/json' }, method),
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data?.error || `Request failed (${response.status})`);
  return data;
}

const formatDate = (iso) => (iso ? new Date(iso).toLocaleString() : '—');

function LinksTable({ links, onRevoke, busyId }) {
  if (!links.length) return <p className="jas-admin-empty">No share links.</p>;
  return (
    <div className="jas-admin-table-wrap">
      <table className="jas-admin-table">
        <thead>
          <tr>
            <th>Title</th><th>Type</th><th>Status</th><th>Views</th><th>Reports</th><th>Created</th><th>Expires</th><th />
          </tr>
        </thead>
        <tbody>
          {links.map((link) => (
            <tr key={link.id}>
              <td>
                <a href={link.url} target="_blank" rel="noopener noreferrer">{link.title || 'Untitled'}</a>
                {link.include_evidence ? ' · evidence' : ''}
              </td>
              <td>{link.artifact_type}</td>
              <td>{link.status}{link.revoked_by ? ` (${link.revoked_by})` : ''}</td>
              <td>{link.view_count}</td>
              <td>{link.report_count || 0}</td>
              <td>{formatDate(link.created_at)}</td>
              <td>{link.expires_at ? formatDate(link.expires_at) : 'Never'}</td>
              <td>
                {link.status === 'active' && (
                  <button
                    type="button"
                    className="jas-admin-secondary jas-admin-danger int-btn int-btn-ghost int-btn-danger"
                    disabled={busyId === link.id}
                    onClick={() => onRevoke(link)}
                  >
                    Revoke
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Without `userId`: find a link by URL and review reported links.
// With `userId`: that account's links and its sharing on/off switch.
export default function AdminSharing({ userId = null }) {
  const [links, setLinks] = useState([]);
  const [lookup, setLookup] = useState('');
  const [sharingDisabled, setSharingDisabled] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [error, setError] = useState('');

  const load = useCallback(async (params) => {
    setError('');
    try {
      const query = new URLSearchParams(params).toString();
      const data = await adminRequest(`${SHARES_API}/links?${query}`);
      setLinks(data?.links || []);
    } catch (loadError) {
      setError(loadError.message);
    }
  }, []);

  useEffect(() => {
    if (userId) {
      void load({ user_id: userId });
      adminRequest(`${SHARES_API}/users/${encodeURIComponent(userId)}`)
        .then((data) => setSharingDisabled(Boolean(data?.sharing_disabled)))
        .catch((loadError) => setError(loadError.message));
    } else {
      void load({ reported: '1' });
    }
  }, [userId, load]);

  const onRevoke = async (link) => {
    // eslint-disable-next-line no-alert
    const reason = window.prompt(`Revoke "${link.title}"? Add a reason for the audit log:`, 'Policy violation');
    if (reason === null) return;
    setBusyId(link.id);
    try {
      const data = await adminRequest(`${SHARES_API}/links/${encodeURIComponent(link.id)}/revoke`, {
        method: 'POST',
        body: { reason },
      });
      setLinks((current) => current.map((item) => (item.id === link.id ? { ...item, ...data.link } : item)));
    } catch (revokeError) {
      setError(revokeError.message);
    } finally {
      setBusyId(null);
    }
  };

  const onToggleSharing = async () => {
    const next = !sharingDisabled;
    try {
      const data = await adminRequest(`${SHARES_API}/users/${encodeURIComponent(userId)}`, {
        method: 'PATCH',
        body: { sharing_disabled: next },
      });
      setSharingDisabled(Boolean(data?.sharing_disabled));
    } catch (toggleError) {
      setError(toggleError.message);
    }
  };

  return (
    <section className="jas-admin-subsection">
      <h3>{userId ? 'Share Links' : 'Share Links (Reported)'}</h3>
      {userId ? (
        <div className="jas-admin-actions">
          <span>
            Sharing is <strong>{sharingDisabled === null ? '…' : sharingDisabled ? 'disabled' : 'enabled'}</strong> for this account.
            {sharingDisabled ? ' Their links are not being served.' : ''}
          </span>
          {sharingDisabled !== null && (
            <button
              type="button"
              className={`jas-admin-secondary int-btn int-btn-ghost ${sharingDisabled ? '' : 'jas-admin-danger int-btn-danger'}`}
              onClick={onToggleSharing}
            >
              {sharingDisabled ? 'Enable sharing' : 'Disable sharing'}
            </button>
          )}
        </div>
      ) : (
        <form
          className="jas-admin-actions"
          onSubmit={(event) => {
            event.preventDefault();
            void load(lookup.trim() ? { token: lookup.trim() } : { reported: '1' });
          }}
        >
          <input
            type="text"
            placeholder="Paste a share link to look it up"
            value={lookup}
            onChange={(event) => setLookup(event.target.value)}
            aria-label="Share link"
          />
          <button type="submit" className="jas-admin-secondary int-btn int-btn-ghost">Find</button>
        </form>
      )}
      {error && <p className="jas-admin-empty" role="alert">{error}</p>}
      <LinksTable links={links} onRevoke={onRevoke} busyId={busyId} />
    </section>
  );
}
