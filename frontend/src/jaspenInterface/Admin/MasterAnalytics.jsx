import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faArrowTrendUp, faChartLine, faEnvelope, faRotateRight } from '@fortawesome/free-solid-svg-icons';
import { API_BASE } from '../../config/apiBase';
import { authFetch, buildAuthHeaders } from '../../shared/auth/http';
import AppMenu from '../shared/AppMenu';
import MasterAdminGuard from './MasterAdminGuard';
import './MasterObservability.css';

const METRIC_LABELS = [
  ['todays_visitors', "Today's Visitors"],
  ['linkedin_visitors', 'LinkedIn Visitors'],
  ['youtube_visitors', 'YouTube Visitors'],
  ['conversions', 'Conversions'],
  ['emails_captured', 'Emails Captured'],
  ['scorecards_generated', 'Scorecards Generated'],
  ['upgrades_started', 'Upgrades Started'],
  ['completed_purchases', 'Completed Purchases'],
  ['failed_payments', 'Failed Payments'],
  ['errors', 'Errors'],
  ['average_time_to_first_scorecard', 'Average Time to First Scorecard'],
  ['activation_percent', 'Activation %'],
  ['conversion_percent', 'Conversion %'],
  ['mrr', 'MRR'],
];

function authHeaders(method = 'GET') {
  return buildAuthHeaders({ 'Content-Type': 'application/json' }, method);
}

function formatMetric(key, value) {
  if (value == null || value === '') return 'Pending';
  if (key === 'mrr') return `$${Number(value || 0).toLocaleString()}`;
  if (key.endsWith('_percent')) return `${Number(value || 0).toLocaleString()}%`;
  if (key === 'average_time_to_first_scorecard') return `${Number(value || 0).toLocaleString()} min`;
  return Number.isFinite(Number(value)) ? Number(value).toLocaleString() : String(value);
}

export default function MasterAnalytics() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const loadAnalytics = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await authFetch(`${API_BASE}/api/v1/admin/master/analytics`, {
        credentials: 'include',
        headers: authHeaders('GET'),
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(payload?.error || `Unable to load analytics (${res.status})`);
      setData(payload || {});
    } catch (err) {
      setError(err?.message || 'Unable to load analytics.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAnalytics();
  }, [loadAnalytics]);

  const metrics = data?.metrics || {};
  const recentSignups = useMemo(() => Array.isArray(data?.recent_signups) ? data.recent_signups : [], [data]);
  const trafficSources = useMemo(() => Array.isArray(data?.traffic_sources) ? data.traffic_sources : [], [data]);

  return (
    <MasterAdminGuard>
      <div className="master-admin-page int-page">
        <AppMenu />
        <main className="master-admin-inner int-page-inner">
          <header className="master-admin-head int-page-head">
            <div>
              <p className="int-eyebrow">Master Admin</p>
              <h1>Analytics</h1>
              <p>Lead capture, activation, and revenue signals for Jaspen growth monitoring.</p>
            </div>
            <button type="button" className="master-admin-refresh" onClick={loadAnalytics} disabled={loading}>
              <FontAwesomeIcon icon={faRotateRight} />
              {loading ? 'Refreshing' : 'Refresh'}
            </button>
          </header>

          {error && <div className="master-admin-state is-error">{error}</div>}
          {loading && !data && <div className="master-admin-state">Loading analytics...</div>}

          {!loading && !error && (
            <>
              <section className="master-metric-grid" aria-label="Analytics metrics">
                {METRIC_LABELS.map(([key, label]) => (
                  <article key={key} className={`master-metric-card${key === 'errors' || key === 'failed_payments' ? ' is-alert' : ''}`}>
                    <span>{label}</span>
                    <strong>{formatMetric(key, metrics[key])}</strong>
                    {data?.notes?.[key] && <p>{data.notes[key]}</p>}
                  </article>
                ))}
              </section>

              <section className="master-admin-columns">
                <article className="master-admin-panel">
                  <div className="master-panel-title">
                    <FontAwesomeIcon icon={faChartLine} />
                    <h2>Traffic Sources</h2>
                  </div>
                  {trafficSources.length === 0 ? (
                    <p className="master-empty">No captured source data yet.</p>
                  ) : (
                    <div className="master-source-list">
                      {trafficSources.map((item) => (
                        <div key={item.source} className="master-source-row">
                          <span>{item.source}</span>
                          <strong>{Number(item.count || 0).toLocaleString()}</strong>
                        </div>
                      ))}
                    </div>
                  )}
                </article>

                <article className="master-admin-panel">
                  <div className="master-panel-title">
                    <FontAwesomeIcon icon={faEnvelope} />
                    <h2>Recent Signups</h2>
                  </div>
                  {recentSignups.length === 0 ? (
                    <p className="master-empty">No recent signups yet.</p>
                  ) : (
                    <div className="master-table-wrap">
                      <table className="master-table">
                        <thead>
                          <tr><th>Email</th><th>Plan</th><th>Created</th></tr>
                        </thead>
                        <tbody>
                          {recentSignups.map((user) => (
                            <tr key={user.id}>
                              <td>{user.email}</td>
                              <td>{user.plan}</td>
                              <td>{user.created_at ? new Date(user.created_at).toLocaleDateString() : 'Unknown'}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </article>
              </section>

              <section className="master-admin-panel">
                <div className="master-panel-title">
                  <FontAwesomeIcon icon={faArrowTrendUp} />
                  <h2>Instrumentation Notes</h2>
                </div>
                <p className="master-empty">
                  Checkout starts, email queue depth, and anonymous visitor analytics are reserved in the schema but need event collection before they can become live metrics.
                </p>
              </section>
            </>
          )}
        </main>
      </div>
    </MasterAdminGuard>
  );
}
