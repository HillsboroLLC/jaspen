import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { API_BASE } from '../../config/apiBase';
import './Activity.css';

const TYPE_OPTIONS = [
  { value: '', label: 'All activity' },
  { value: 'score_completed', label: 'Score completions' },
  { value: 'scenario_created', label: 'Scenario created' },
  { value: 'scenario_adopted', label: 'Scenario adopted' },
  { value: 'wbs_generated', label: 'WBS generated' },
  { value: 'wbs_edited', label: 'WBS edited' },
  { value: 'connector_sync', label: 'Connector syncs' },
  { value: 'team_member_joined', label: 'Team joins' },
  { value: 'data_uploaded', label: 'Data uploads' },
  { value: 'project_activity', label: 'Project activity' },
];

const PAGE_SIZE = 50;

function authHeaders() {
  const token = localStorage.getItem('access_token') || localStorage.getItem('token');
  return {
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

export default function Activity() {
  const [events, setEvents] = useState([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [typeFilter, setTypeFilter] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const loadActivity = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String(offset),
      });
      if (typeFilter) params.set('type', typeFilter);

      const res = await fetch(`${API_BASE}/api/activity?${params.toString()}`, {
        credentials: 'include',
        headers: authHeaders(),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data?.error || `Failed to load activity (${res.status})`);
      }

      setEvents(Array.isArray(data?.events) ? data.events : []);
      setTotal(Number(data?.total) || 0);
    } catch (err) {
      setError(err?.message || 'Failed to load activity feed.');
      setEvents([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [offset, typeFilter]);

  useEffect(() => {
    loadActivity();
  }, [loadActivity]);

  const start = total === 0 ? 0 : offset + 1;
  const end = total === 0 ? 0 : Math.min(offset + events.length, total);

  const hasPrev = offset > 0;
  const hasNext = offset + events.length < total;

  const typeLabelByValue = useMemo(
    () => TYPE_OPTIONS.reduce((acc, item) => ({ ...acc, [item.value]: item.label }), {}),
    []
  );

  return (
    <div className="activity-page">
      <header className="activity-header">
        <h1>Activity</h1>
        <p>Unified timeline of scorecards, scenarios, WBS updates, connectors, team, and data events.</p>
      </header>

      <section className="activity-controls">
        <select
          value={typeFilter}
          onChange={(event) => {
            setTypeFilter(event.target.value);
            setOffset(0);
          }}
        >
          {TYPE_OPTIONS.map((option) => (
            <option key={option.value || 'all'} value={option.value}>{option.label}</option>
          ))}
        </select>
      </section>

      {loading && <div className="activity-state">Loading activity...</div>}
      {!loading && error && <div className="activity-state activity-state-error">{error}</div>}
      {!loading && !error && events.length === 0 && (
        <div className="activity-state">No matching activity events yet.</div>
      )}

      {!loading && !error && events.length > 0 && (
        <section className="activity-timeline">
          {events.map((event, index) => (
            <article className="activity-item" key={`${event.timestamp}-${index}-${event.type}`}>
              <div className="activity-dot" aria-hidden="true" />
              <div className="activity-content">
                <header>
                  <span className="activity-type">{typeLabelByValue[event.type] || event.type}</span>
                  <time title={event.timestamp}>{event.timestamp ? new Date(event.timestamp).toLocaleString() : 'Unknown time'}</time>
                </header>
                <p>{event.description || 'Activity event'}</p>
                <div className="activity-meta">
                  {event.project_name && <span>Project: {event.project_name}</span>}
                  {event.user_name && <span>User: {event.user_name}</span>}
                </div>
              </div>
            </article>
          ))}
        </section>
      )}

      {!loading && !error && total > 0 && (
        <footer className="activity-pagination">
          <p>Showing {start}-{end} of {total}</p>
          <div>
            <button type="button" onClick={() => setOffset((prev) => Math.max(0, prev - PAGE_SIZE))} disabled={!hasPrev}>Previous</button>
            <button type="button" onClick={() => setOffset((prev) => prev + PAGE_SIZE)} disabled={!hasNext}>Next</button>
          </div>
        </footer>
      )}
    </div>
  );
}
