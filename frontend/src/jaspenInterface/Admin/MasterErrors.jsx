import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faBug, faFlag, faGaugeHigh, faRotateRight, faServer } from '@fortawesome/free-solid-svg-icons';
import { API_BASE } from '../../config/apiBase';
import { authFetch, buildAuthHeaders } from '../../shared/auth/http';
import AppMenu from '../shared/AppMenu';
import MasterAdminGuard from './MasterAdminGuard';
import './MasterObservability.css';

function authHeaders(method = 'GET') {
  return buildAuthHeaders({ 'Content-Type': 'application/json' }, method);
}

function statusLabel(status) {
  if (status === 'online') return 'Online';
  if (status === 'attention') return 'Needs attention';
  if (status === 'not_instrumented') return 'Not instrumented';
  return 'Watching';
}

export default function MasterErrors() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const loadErrors = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await authFetch(`${API_BASE}/api/v1/admin/master/errors`, {
        credentials: 'include',
        headers: authHeaders('GET'),
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(payload?.error || `Unable to load error dashboard (${res.status})`);
      setData(payload || {});
    } catch (err) {
      setError(err?.message || 'Unable to load error dashboard.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadErrors();
  }, [loadErrors]);

  const sections = useMemo(() => Array.isArray(data?.sections) ? data.sections : [], [data]);
  const logs = useMemo(() => Array.isArray(data?.recent_logs) ? data.recent_logs : [], [data]);
  const flags = useMemo(() => Array.isArray(data?.feature_flags) ? data.feature_flags : [], [data]);
  const providerSummary = data?.provider_health?.summary || {};

  return (
    <MasterAdminGuard>
      <div className="master-admin-page int-page">
        <AppMenu />
        <main className="master-admin-inner int-page-inner">
          <header className="master-admin-head int-page-head">
            <div>
              <p className="int-eyebrow">Master Admin</p>
              <h1>Error Dashboard</h1>
              <p>Operational watchboard for admin, analytics, users, subscriptions, flags, health, and logs.</p>
            </div>
            <button type="button" className="master-admin-refresh" onClick={loadErrors} disabled={loading}>
              <FontAwesomeIcon icon={faRotateRight} />
              {loading ? 'Refreshing' : 'Refresh'}
            </button>
          </header>

          {error && <div className="master-admin-state is-error">{error}</div>}
          {loading && !data && <div className="master-admin-state">Loading error dashboard...</div>}

          {!loading && !error && (
            <>
              <section className="master-status-grid" aria-label="Admin dashboard sections">
                {sections.map((section) => (
                  <article key={section.key} className={`master-status-card is-${section.status}`}>
                    <span>{section.label}</span>
                    <strong>{Number(section.count || 0).toLocaleString()}</strong>
                    <p>{statusLabel(section.status)}</p>
                  </article>
                ))}
              </section>

              <section className="master-admin-columns">
                <article className="master-admin-panel">
                  <div className="master-panel-title">
                    <FontAwesomeIcon icon={faGaugeHigh} />
                    <h2>System Health</h2>
                  </div>
                  <div className="master-health-grid">
                    <div><span>Provider events</span><strong>{Number(providerSummary.total_events || 0).toLocaleString()}</strong></div>
                    <div><span>Failovers</span><strong>{Number(providerSummary.failover_events || 0).toLocaleString()}</strong></div>
                    <div><span>Failover rate</span><strong>{Number(providerSummary.failover_rate || 0).toLocaleString()}%</strong></div>
                  </div>
                </article>

                <article className="master-admin-panel">
                  <div className="master-panel-title">
                    <FontAwesomeIcon icon={faFlag} />
                    <h2>Feature Flags</h2>
                  </div>
                  {flags.length === 0 ? (
                    <p className="master-empty">No feature flags reported.</p>
                  ) : flags.map((flag) => (
                    <div key={flag.key} className="master-source-row">
                      <span>{flag.key}</span>
                      <strong>{flag.enabled ? 'Enabled' : 'Disabled'}</strong>
                    </div>
                  ))}
                </article>
              </section>

              <section className="master-admin-panel">
                <div className="master-panel-title">
                  <FontAwesomeIcon icon={faBug} />
                  <h2>Logs</h2>
                </div>
                {logs.length === 0 ? (
                  <p className="master-empty">No admin logs yet.</p>
                ) : (
                  <div className="master-table-wrap">
                    <table className="master-table">
                      <thead>
                        <tr><th>Time</th><th>Action</th><th>Actor</th><th>Target</th></tr>
                      </thead>
                      <tbody>
                        {logs.map((log, index) => (
                          <tr key={`${log.timestamp}-${log.action}-${index}`}>
                            <td>{log.timestamp ? new Date(log.timestamp).toLocaleString() : 'Unknown'}</td>
                            <td>{log.action}</td>
                            <td>{log.actor_email || 'System'}</td>
                            <td>{log.target_email || '-'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>

              <section className="master-admin-panel">
                <div className="master-panel-title">
                  <FontAwesomeIcon icon={faServer} />
                  <h2>Foundation</h2>
                </div>
                <p className="master-empty">
                  Admin, Dashboard, Analytics, Users, Subscriptions, Errors, Decision Records, Feature Flags, Email Queue, System Health, and Logs are represented here so each can become a deeper drill-down later.
                </p>
              </section>
            </>
          )}
        </main>
      </div>
    </MasterAdminGuard>
  );
}
