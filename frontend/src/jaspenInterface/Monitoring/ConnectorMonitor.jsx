import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { API_BASE } from '../../config/apiBase';
import './ConnectorMonitor.css';

const PM_SYNC_ENDPOINTS = {
  jira_sync: 'jira/sync',
  workfront_sync: 'workfront/sync',
  smartsheet_sync: 'smartsheet/sync',
};

function authHeaders(json = false) {
  const token = localStorage.getItem('access_token') || localStorage.getItem('token');
  return {
    ...(json ? { 'Content-Type': 'application/json' } : {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

function hoursAgoLabel(value) {
  if (!value) return 'Never synced';
  const stamp = new Date(value);
  if (Number.isNaN(stamp.getTime())) return 'Unknown';
  const diffMs = Date.now() - stamp.getTime();
  const hours = Math.max(0, Math.floor(diffMs / (1000 * 60 * 60)));
  if (hours < 1) return 'Less than 1 hour ago';
  if (hours === 1) return '1 hour ago';
  return `${hours} hours ago`;
}

function severityClass(severity) {
  if (severity === 'critical') return 'is-critical';
  if (severity === 'warning') return 'is-warning';
  return 'is-info';
}

function trendGlyph(direction) {
  if (direction === 'up') return '↑';
  if (direction === 'down') return '↓';
  return '→';
}

export default function ConnectorMonitor({ selectedThreadId = '', onResynced = null, allowedConnectorIds = null }) {
  const [report, setReport] = useState({ connectors: [], alerts: [], checked_at: null });
  const [expandedId, setExpandedId] = useState('');
  const [insightsByConnector, setInsightsByConnector] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busyConnectorId, setBusyConnectorId] = useState('');

  const loadHealth = useCallback(async () => {
    const response = await fetch(`${API_BASE}/api/v1/monitoring/health`, {
      credentials: 'include',
      headers: authHeaders(),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload?.error || `Failed to load monitoring health (${response.status})`);
    }
    setReport({
      connectors: Array.isArray(payload?.connectors) ? payload.connectors : [],
      alerts: Array.isArray(payload?.alerts) ? payload.alerts : [],
      checked_at: payload?.checked_at || null,
    });
  }, []);

  const refreshHealth = useCallback(async () => {
    try {
      setError('');
      await loadHealth();
    } catch (err) {
      setError(err?.message || 'Unable to load connector monitoring.');
    }
  }, [loadHealth]);

  useEffect(() => {
    let cancelled = false;

    const run = async () => {
      try {
        await refreshHealth();
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    run();
    const timer = window.setInterval(run, 60000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [refreshHealth]);

  const loadInsights = useCallback(async (connectorId) => {
    const params = new URLSearchParams();
    if (selectedThreadId) {
      params.set('thread_id', selectedThreadId);
    }
    const suffix = params.toString() ? `?${params.toString()}` : '';
    const response = await fetch(`${API_BASE}/api/v1/monitoring/insights/${encodeURIComponent(connectorId)}${suffix}`, {
      credentials: 'include',
      headers: authHeaders(),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload?.error || `Failed to load insights (${response.status})`);
    }
    setInsightsByConnector((prev) => ({ ...prev, [connectorId]: payload }));
  }, [selectedThreadId]);

  const toggleExpanded = useCallback(async (connectorId) => {
    setExpandedId((current) => (current === connectorId ? '' : connectorId));
    if (!insightsByConnector[connectorId]) {
      try {
        await loadInsights(connectorId);
      } catch (err) {
        setInsightsByConnector((prev) => ({
          ...prev,
          [connectorId]: { insights: [], error: err?.message || 'Unable to load insights.' },
        }));
      }
    }
  }, [insightsByConnector, loadInsights]);

  const triggerResync = useCallback(async (connector) => {
    const suffix = PM_SYNC_ENDPOINTS[connector?.id];
    if (!suffix || !selectedThreadId) {
      return;
    }
    setBusyConnectorId(connector.id);
    try {
      const response = await fetch(
        `${API_BASE}/api/v1/connectors/threads/${encodeURIComponent(selectedThreadId)}/${suffix}`,
        {
          method: 'POST',
          credentials: 'include',
          headers: authHeaders(true),
        }
      );
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload?.error || `Sync failed (${response.status})`);
      }
      await loadHealth();
      if (typeof onResynced === 'function') {
        await onResynced();
      }
    } catch (err) {
      setError(err?.message || 'Unable to trigger connector sync.');
    } finally {
      setBusyConnectorId('');
    }
  }, [loadHealth, onResynced, selectedThreadId]);

  const alertGroups = useMemo(() => {
    const grouped = {};
    for (const alert of Array.isArray(report.alerts) ? report.alerts : []) {
      const key = String(alert?.connector_id || '').trim();
      if (!key) continue;
      if (!grouped[key]) grouped[key] = [];
      grouped[key].push(alert);
    }
    return grouped;
  }, [report.alerts]);

  const allowedSet = useMemo(() => {
    if (!Array.isArray(allowedConnectorIds) || allowedConnectorIds.length === 0) return null;
    return new Set(allowedConnectorIds);
  }, [allowedConnectorIds]);

  const visibleConnectors = useMemo(() => (
    allowedSet
      ? (report.connectors || []).filter((connector) => allowedSet.has(connector.id))
      : (report.connectors || [])
  ), [allowedSet, report.connectors]);

  const visibleAlerts = useMemo(() => (
    allowedSet
      ? (report.alerts || []).filter((alert) => allowedSet.has(String(alert?.connector_id || '').trim()))
      : (report.alerts || [])
  ), [allowedSet, report.alerts]);

  return (
    <section className="connector-monitor-panel">
      <header className="connector-monitor-header">
        <div>
          <p className="connector-monitor-kicker">Data Sources</p>
          <h2>Connector monitoring</h2>
          <p>Live health, freshness, and sync-drift signals for connected systems.</p>
        </div>
        <div className="connector-monitor-meta">
          <span>{report.checked_at ? `Checked ${new Date(report.checked_at).toLocaleTimeString()}` : 'Waiting for first check'}</span>
          <button type="button" onClick={refreshHealth}>Refresh</button>
        </div>
      </header>

      {loading && <div className="connector-monitor-state">Loading data source health...</div>}
      {!loading && error && <div className="connector-monitor-state is-error">{error}</div>}

      {!loading && !error && (
        <>
          <div className="connector-alert-grid">
            {visibleAlerts.length === 0 ? (
              <article className="connector-alert-card is-healthy">
                <strong>No active connector alerts.</strong>
                <span>Connected systems look healthy right now.</span>
              </article>
            ) : (
              visibleAlerts.map((alert, index) => (
                <article key={`${alert.connector_id}-${alert.type}-${index}`} className={`connector-alert-card ${severityClass(alert.severity)}`}>
                  <strong>{alert.connector_id}</strong>
                  <p>{alert.message}</p>
                  <span>{alert.action}</span>
                </article>
              ))
            )}
          </div>

          <div className="connector-monitor-grid">
            {visibleConnectors.map((connector) => {
              const expanded = expandedId === connector.id;
              const insightsPayload = insightsByConnector[connector.id] || {};
              const insights = Array.isArray(insightsPayload?.insights) ? insightsPayload.insights : [];
              const canResync = Boolean(PM_SYNC_ENDPOINTS[connector.id] && selectedThreadId);
              const connectorAlerts = alertGroups[connector.id] || [];

              return (
                <article key={connector.id} className={`connector-monitor-card ${expanded ? 'is-expanded' : ''}`}>
                  <button type="button" className="connector-monitor-card-head" onClick={() => toggleExpanded(connector.id)}>
                    <div>
                      <h3>{connector.label}</h3>
                      <p>{connector.group === 'execution' ? 'Execution sync' : 'Data insight source'}</p>
                    </div>
                    <div className={`connector-monitor-badge ${connector.status_badge || 'red'}`}>
                      {connector.connection_status}
                    </div>
                  </button>

                  <div className="connector-monitor-stats">
                    <span>Health: <strong>{connector.health_status}</strong></span>
                    <span>Last sync: <strong>{hoursAgoLabel(connector.last_sync_at)}</strong></span>
                    <span>Failures: <strong>{connector.consecutive_failures || 0}</strong></span>
                  </div>

                  <div className="connector-monitor-actions">
                    <button
                      type="button"
                      disabled={!canResync || busyConnectorId === connector.id}
                      onClick={() => triggerResync(connector)}
                    >
                      {busyConnectorId === connector.id ? 'Re-syncing...' : 'Re-sync Now'}
                    </button>
                    {!selectedThreadId && connector.supports_pm_sync && (
                      <span className="connector-monitor-hint">Select a thread below to enable manual re-sync.</span>
                    )}
                  </div>

                  {connectorAlerts.length > 0 && (
                    <ul className="connector-monitor-inline-alerts">
                      {connectorAlerts.map((alert, index) => (
                        <li key={`${alert.type}-${index}`} className={severityClass(alert.severity)}>
                          <strong>{alert.severity}</strong> {alert.message}
                        </li>
                      ))}
                    </ul>
                  )}

                  {expanded && (
                    <div className="connector-monitor-insights">
                      {insightsPayload?.error && <p className="connector-monitor-insight-error">{insightsPayload.error}</p>}
                      {!insightsPayload?.error && insights.length === 0 && (
                        <p className="connector-monitor-empty">No proactive insights yet for this connector.</p>
                      )}
                      {insights.map((insight, index) => (
                        <article key={`${connector.id}-insight-${index}`} className="connector-monitor-insight-card">
                          <div className="connector-monitor-insight-row">
                            <strong>{insight.message}</strong>
                            <span className={`connector-monitor-trend ${insight.trend_direction || insightsPayload.trend_direction || 'flat'}`}>
                              {trendGlyph(insight.trend_direction || insightsPayload.trend_direction || 'flat')}
                            </span>
                          </div>
                          {insight.detail && <p>{insight.detail}</p>}
                        </article>
                      ))}
                    </div>
                  )}
                </article>
              );
            })}
          </div>
        </>
      )}
    </section>
  );
}
