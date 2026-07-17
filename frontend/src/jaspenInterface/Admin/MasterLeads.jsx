import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faAddressBook, faBuilding, faCheck, faEnvelope, faFilter, faRotateRight, faTrash, faXmark } from '@fortawesome/free-solid-svg-icons';
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

const PREFERENCE_LABELS = {
  marketing: 'Marketing',
  updates: 'Updates',
  decision_notes: 'Decision Notes',
};

function ContactStatus({ lead }) {
  const preferences = lead?.subscription_preferences || {};
  const status = lead?.contact_status || 'no_opt_out_recorded';
  const label = status === 'do_not_contact'
    ? 'Do not contact'
    : status === 'limited'
    ? 'Limited contact'
    : 'No opt-out recorded';
  return (
    <div className={`master-contact-status is-${status}`}>
      <strong>{label}</strong>
      {Object.entries(PREFERENCE_LABELS).map(([scope, scopeLabel]) => (
        <span key={scope}>
          {scopeLabel}: {preferences?.[scope]?.subscribed === false ? 'Unsubscribed' : 'Subscribed'}
        </span>
      ))}
      {status === 'do_not_contact' && <small>Transactional account, security, and billing email only.</small>}
    </div>
  );
}

export default function MasterLeads() {
  const [data, setData] = useState(null);
  const [query, setQuery] = useState('');
  const [source, setSource] = useState('');
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selectedLead, setSelectedLead] = useState(null);
  const [deletingLead, setDeletingLead] = useState(false);

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

  const deleteSelectedLead = async () => {
    if (!selectedLead || deletingLead) return;
    const label = selectedLead.name ? `${selectedLead.name} (${selectedLead.email})` : selectedLead.email;
    if (!window.confirm(`Delete ${label} and all interactions recorded under this email address? This cannot be undone.`)) return;

    setDeletingLead(true);
    setError('');
    try {
      const res = await authFetch(`${API_BASE}/api/v1/admin/master/leads/${encodeURIComponent(selectedLead.id)}`, {
        method: 'DELETE',
        credentials: 'include',
        headers: authHeaders('DELETE'),
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(payload?.error || `Unable to delete lead (${res.status})`);
      setSelectedLead(null);
      await loadLeads();
    } catch (err) {
      setError(err?.message || 'Unable to delete lead.');
    } finally {
      setDeletingLead(false);
    }
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
              <p>Lead capture contacts with account status, tool usage, attribution, email delivery, and category-level contact preferences.</p>
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
                <div className="master-contact-grid">
                  {leads.map((lead) => {
                    const estimates = lead.interactions?.estimates || [];
                    const emails = lead.interactions?.emails || [];
                    const captures = lead.interactions?.captures || [];
                    return (
                      <button type="button" className="master-contact-card" key={lead.id} onClick={() => setSelectedLead(lead)}>
                        <div className="master-contact-card-head">
                          <div>
                            <strong>{lead.name || lead.email}</strong>
                            {lead.name && <span>{lead.email}</span>}
                          </div>
                          <span className={`master-account-badge${lead.account?.exists ? ' is-account' : ''}`}>
                            {lead.account?.exists ? `${lead.account.plan || 'Free'} account` : 'Lead only'}
                          </span>
                        </div>
                        {lead.company && <p><FontAwesomeIcon icon={faBuilding} /> {lead.company}</p>}
                        <div className="master-contact-card-stats">
                          <span><strong>{captures.length}</strong> interactions</span>
                          <span><strong>{estimates.length}</strong> estimates</span>
                          <span><strong>{emails.filter((item) => item.status === 'sent').length}</strong> emails sent</span>
                        </div>
                        <div className="master-contact-card-foot">
                          <span>{compactSource(lead)}</span>
                          <span><FontAwesomeIcon icon={faEnvelope} /> {lead.latest_email?.status === 'sent' ? `Sent ${formatDate(lead.latest_email.sent_at || lead.latest_email.created_at)}` : lead.latest_email?.status || 'No recorded email'}</span>
                        </div>
                      </button>
                    );
                  })}
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
          {selectedLead && (
            <div className="master-contact-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setSelectedLead(null); }}>
              <section className="master-contact-modal" role="dialog" aria-modal="true" aria-labelledby="master-contact-title">
                <header>
                  <div>
                    <p className="int-eyebrow">Contact record</p>
                    <h2 id="master-contact-title">{selectedLead.name || selectedLead.email}</h2>
                    <a href={`mailto:${selectedLead.email}`}>{selectedLead.email}</a>
                    {selectedLead.company && <span>{selectedLead.company}{selectedLead.title ? ` · ${selectedLead.title}` : ''}</span>}
                  </div>
                  <button type="button" aria-label="Close contact details" onClick={() => setSelectedLead(null)}><FontAwesomeIcon icon={faXmark} /></button>
                </header>

                <div className="master-contact-modal-summary">
                  <div><span>Account</span><strong>{selectedLead.account?.exists ? `${selectedLead.account.plan || 'Free'} plan` : 'Lead only'}</strong></div>
                  <div><span>First captured</span><strong>{formatDate(selectedLead.created_at)}</strong></div>
                  <div><span>Decision profile</span><strong>{selectedLead.decision_profile?.style_name || 'None yet'}</strong></div>
                  <div><span>Primary source</span><strong>{compactSource(selectedLead)}</strong></div>
                </div>

                <div className="master-contact-modal-section">
                  <h3>Contact preferences</h3>
                  <ContactStatus lead={selectedLead} />
                </div>

                <div className="master-contact-modal-section">
                  <h3>Enterprise estimates ({selectedLead.interactions?.estimates?.length || 0})</h3>
                  {(selectedLead.interactions?.estimates || []).length === 0 ? <p className="master-empty">No estimates recorded.</p> : (
                    <div className="master-estimate-list">
                      {selectedLead.interactions.estimates.map((estimate) => (
                        <article key={estimate.id}>
                          <div><strong>{estimate.recommendation}</strong><time>{formatDate(estimate.created_at)}</time></div>
                          <p>{estimate.annual_low ? `${estimate.annual_high ? `$${Number(estimate.annual_low).toLocaleString()}–$${Number(estimate.annual_high).toLocaleString()}` : `Starting at $${Number(estimate.annual_low).toLocaleString()}`} annually` : 'Sales-scoped estimate'}</p>
                          <dl>
                            <div><dt>Participants</dt><dd>{estimate.participants}</dd></div>
                            <div><dt>Teams</dt><dd>{estimate.teams}</dd></div>
                            <div><dt>Usage</dt><dd>{estimate.usage}</dd></div>
                            <div><dt>Leadership cost</dt><dd>{estimate.hourly_cost ? `$${estimate.hourly_cost}/hr` : 'Not provided'}</dd></div>
                          </dl>
                          {estimate.requirements?.length > 0 && <small>Needs: {estimate.requirements.join(', ')}</small>}
                          {estimate.comments && <blockquote>{estimate.comments}</blockquote>}
                        </article>
                      ))}
                    </div>
                  )}
                </div>

                <div className="master-contact-modal-section">
                  <h3>Email history ({selectedLead.interactions?.emails?.length || 0})</h3>
                  {(selectedLead.interactions?.emails || []).length === 0 ? <p className="master-empty">No email delivery was recorded.</p> : (
                    <div className="master-interaction-list">
                      {selectedLead.interactions.emails.map((email) => (
                        <div key={email.id}>
                          <FontAwesomeIcon icon={faEnvelope} />
                          <span><strong>{email.type?.replaceAll('_', ' ')}</strong><small>{email.status} · {formatDate(email.sent_at || email.created_at)}</small></span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                <div className="master-contact-modal-section">
                  <h3>Capture history ({selectedLead.interactions?.captures?.length || 0})</h3>
                  <div className="master-interaction-list">
                    {(selectedLead.interactions?.captures || []).map((capture) => (
                      <div key={capture.id}>
                        <FontAwesomeIcon icon={capture.email_delivery_requested ? faEnvelope : faCheck} />
                        <span><strong>{capture.source}</strong><small>{formatDate(capture.created_at)}{capture.email_delivery_requested ? ' · Email requested' : ''}</small></span>
                      </div>
                    ))}
                  </div>
                </div>

                <footer className="master-contact-modal-actions">
                  <button type="button" className="master-danger-button" onClick={deleteSelectedLead} disabled={deletingLead}>
                    <FontAwesomeIcon icon={faTrash} />
                    {deletingLead ? 'Deleting…' : 'Delete contact record'}
                  </button>
                  <small>Deletes this email address and its recorded lead interactions. Account data is not affected.</small>
                </footer>
              </section>
            </div>
          )}
        </main>
      </div>
    </MasterAdminGuard>
  );
}
