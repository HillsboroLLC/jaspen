import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faAddressBook, faCheck, faEnvelope, faFilter, faMinus, faRotateRight } from '@fortawesome/free-solid-svg-icons';
import { API_BASE } from '../../config/apiBase';
import { authFetch, buildAuthHeaders } from '../../shared/auth/http';
import AppMenu from '../shared/AppMenu';
import MasterAdminGuard from './MasterAdminGuard';
import './MasterObservability.css';

const PAGE_SIZE = 25;

function authHeaders(method = 'GET') {
  return buildAuthHeaders({ 'Content-Type': 'application/json' }, method);
}

function formatDate(value) {
  if (!value) return 'Unknown';
  try {
    return new Date(value).toLocaleString();
  } catch {
    return 'Unknown';
  }
}

function compactSource(lead) {
  return lead?.utm_source || lead?.source || 'unknown';
}

function LeadToolCell({ tool }) {
  const used = Boolean(tool?.used);
  return (
    <span className={`master-tool-check${used ? ' is-used' : ''}`} title={used ? `${tool.count || 1} capture${Number(tool.count || 1) === 1 ? '' : 's'}` : 'No capture yet'}>
      <FontAwesomeIcon icon={used ? faCheck : faMinus} />
      {used && tool?.latest_at && <span>{formatDate(tool.latest_at)}</span>}
    </span>
  );
}

export default function MasterLeads() {
  const [data, setData] = useState(null);
  const [query, setQuery] = useState('');
  const [source, setSource] = useState('');
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const loadLeads = useCallback(async () => {
    setLoading(true);
    setError('');
    const params = new URLSearchParams({
      page: String(page),
      per_page: String(PAGE_SIZE),
    });
    if (query.trim()) params.set('q', query.trim());
    if (source.trim()) params.set('source', source.trim());

    try {
      const res = await authFetch(`${API_BASE}/api/v1/admin/master/leads?${params.toString()}`, {
        credentials: 'include',
        headers: authHeaders('GET'),
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(payload?.error || `Unable to load leads (${res.status})`);
      setData(payload || {});
    } catch (err) {
      setError(err?.message || 'Unable to load leads.');
    } finally {
      setLoading(false);
    }
  }, [page, query, source]);

  useEffect(() => {
    loadLeads();
  }, [loadLeads]);

  const leads = useMemo(() => Array.isArray(data?.leads) ? data.leads : [], [data]);
  const sources = useMemo(() => Array.isArray(data?.sources) ? data.sources : [], [data]);
  const pagination = data?.pagination || {};

  const applyFilters = (event) => {
    event.preventDefault();
    setPage(1);
    loadLeads();
  };

  return (
    <MasterAdminGuard>
      <div className="master-admin-page int-page">
        <AppMenu />
        <main className="master-admin-inner int-page-inner">
          <header className="master-admin-head int-page-head">
            <div>
              <p className="int-eyebrow">Master Admin</p>
              <h1>Leads</h1>
              <p>Read-only lead capture list with tool usage, attribution, email status, Decision Profile style, and unsubscribe state.</p>
            </div>
            <button type="button" className="master-admin-refresh" onClick={loadLeads} disabled={loading}>
              <FontAwesomeIcon icon={faRotateRight} />
              {loading ? 'Refreshing' : 'Refresh'}
            </button>
          </header>

          <section className="master-admin-panel">
            <form className="master-filter-bar" onSubmit={applyFilters}>
              <label>
                <span>Search</span>
                <input
                  type="search"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Email, company, source"
                />
              </label>
              <label>
                <span>Source</span>
                <select value={source} onChange={(event) => { setSource(event.target.value); setPage(1); }}>
                  <option value="">All sources</option>
                  {sources.map((item) => (
                    <option key={item.source} value={item.source}>
                      {item.source} ({Number(item.count || 0).toLocaleString()})
                    </option>
                  ))}
                </select>
              </label>
              <button type="submit" className="master-admin-refresh">
                <FontAwesomeIcon icon={faFilter} />
                Apply
              </button>
            </form>
          </section>

          {error && <div className="master-admin-state is-error">{error}</div>}
          {loading && !data && <div className="master-admin-state">Loading leads...</div>}

          {!loading && !error && (
            <section className="master-admin-panel">
              <div className="master-panel-title">
                <FontAwesomeIcon icon={faAddressBook} />
                <h2>{Number(pagination.total || 0).toLocaleString()} captured leads</h2>
              </div>
              {leads.length === 0 ? (
                <p className="master-empty">No leads match this view.</p>
              ) : (
                <div className="master-table-wrap">
                  <table className="master-table master-leads-table">
                    <thead>
                      <tr>
                        <th>Email</th>
                        <th>Source</th>
                        <th>Toolkit</th>
                        <th>Decision Profile</th>
                        <th>Profile</th>
                        <th>Email</th>
                        <th>Unsubscribed</th>
                        <th>Captured</th>
                      </tr>
                    </thead>
                    <tbody>
                      {leads.map((lead) => (
                        <tr key={lead.id}>
                          <td>
                            <strong>{lead.email}</strong>
                            {(lead.name || lead.company) && (
                              <span>{[lead.name, lead.company].filter(Boolean).join(' / ')}</span>
                            )}
                          </td>
                          <td>
                            {compactSource(lead)}
                            {lead.utm_campaign && <span>{lead.utm_campaign}</span>}
                          </td>
                          <td>
                            <LeadToolCell tool={lead.lead_tools?.decision_planning_toolkit} />
                          </td>
                          <td>
                            <LeadToolCell tool={lead.lead_tools?.decision_profile} />
                          </td>
                          <td>
                            {lead.decision_profile?.style_name || 'None yet'}
                            {lead.decision_profile?.created_at && <span>{formatDate(lead.decision_profile.created_at)}</span>}
                          </td>
                          <td>
                            <FontAwesomeIcon icon={faEnvelope} /> {lead.latest_email?.status || 'None'}
                            {lead.latest_email?.type && <span>{lead.latest_email.type}</span>}
                          </td>
                          <td>
                            {lead.suppression ? 'Yes' : 'No'}
                            {lead.suppression?.created_at && <span>{formatDate(lead.suppression.created_at)}</span>}
                          </td>
                          <td>{formatDate(lead.created_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <div className="master-pagination">
                <button type="button" className="master-admin-refresh" disabled={!pagination.has_prev || loading} onClick={() => setPage((value) => Math.max(1, value - 1))}>
                  Previous
                </button>
                <span>Page {pagination.page || page}</span>
                <button type="button" className="master-admin-refresh" disabled={!pagination.has_next || loading} onClick={() => setPage((value) => value + 1)}>
                  Next
                </button>
              </div>
            </section>
          )}
        </main>
      </div>
    </MasterAdminGuard>
  );
}
