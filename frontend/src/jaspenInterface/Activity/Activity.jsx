import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faClockRotateLeft } from '@fortawesome/free-solid-svg-icons';
import { List } from 'react-window';
import { API_BASE } from '../../config/apiBase';
import { authFetch, buildAuthHeaders } from '../../shared/auth/http';
import SkeletonBlock from '../../shared/components/SkeletonLoader';
import EmptyState from '../../homeSections/homeUi/EmptyState';
import './Activity.css';
import AppMenu from '../shared/AppMenu';
import JaspenAiDrawer from '../Workspace/JaspenAiDrawer';

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

const PAGE_SIZE = 200;
const ACTIVITY_VIRTUALIZE_THRESHOLD = 80;
const ACTIVITY_ROW_HEIGHT = 136;

function toIsoStart(dateInput) {
  const value = String(dateInput || '').trim();
  if (!value) return '';
  const parsed = new Date(`${value}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return '';
  return parsed.toISOString();
}

function toIsoEnd(dateInput) {
  const value = String(dateInput || '').trim();
  if (!value) return '';
  const parsed = new Date(`${value}T23:59:59.999`);
  if (Number.isNaN(parsed.getTime())) return '';
  return parsed.toISOString();
}

function authHeaders(method = 'GET') {
  return buildAuthHeaders({}, method);
}

function ActivityRow({ index, style, events, typeLabelByValue, ariaAttributes }) {
  const event = events[index];
  if (!event) return null;

  return (
    <div style={style} {...ariaAttributes}>
      <article className="activity-item">
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
    </div>
  );
}

export default function Activity() {
  const navigate = useNavigate();
  const [events, setEvents] = useState([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [pageInput, setPageInput] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [fromDate, setFromDate] = useState('');
  const [toDate, setToDate] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [jaspenOpen, setJaspenOpen] = useState(false);
  const [assistantInput, setAssistantInput] = useState('');
  const [assistantMessages, setAssistantMessages] = useState([
    {
      role: 'assistant',
      text: 'I can summarize this activity feed and highlight where execution is drifting.',
    },
  ]);

  const loadActivity = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String(offset),
      });
      if (typeFilter) params.set('type', typeFilter);
      const fromIso = toIsoStart(fromDate);
      const toIso = toIsoEnd(toDate);
      if (fromIso) params.set('from', fromIso);
      if (toIso) params.set('to', toIso);

      const res = await authFetch(`${API_BASE}/api/v1/activity?${params.toString()}`, {
        credentials: 'include',
        headers: authHeaders('GET'),
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
  }, [fromDate, offset, toDate, typeFilter]);

  useEffect(() => {
    loadActivity();
  }, [loadActivity]);

  const start = total === 0 ? 0 : offset + 1;
  const end = total === 0 ? 0 : Math.min(offset + events.length, total);

  const hasPrev = offset > 0;
  const hasNext = offset + events.length < total;
  const totalPages = total > 0 ? Math.ceil(total / PAGE_SIZE) : 0;
  const currentPage = total > 0 ? Math.floor(offset / PAGE_SIZE) + 1 : 0;
  const useVirtualTimeline = events.length > ACTIVITY_VIRTUALIZE_THRESHOLD;
  const virtualListHeight = Math.min(640, Math.max(280, events.length * ACTIVITY_ROW_HEIGHT));

  const typeLabelByValue = useMemo(
    () => TYPE_OPTIONS.reduce((acc, item) => ({ ...acc, [item.value]: item.label }), {}),
    []
  );

  useEffect(() => {
    const observer = new MutationObserver(() => {
      if (document.body.classList.contains('jaspen-sidebar-open')) {
        setJaspenOpen(false);
      }
    });
    observer.observe(document.body, { attributes: true, attributeFilter: ['class'] });
    return () => observer.disconnect();
  }, []);

  const openJaspen = useCallback(() => {
    document.body.classList.remove('jaspen-sidebar-open');
    setJaspenOpen(true);
  }, []);

  const sendAssistant = useCallback(() => {
    const text = String(assistantInput || '').trim();
    if (!text) return;
    setAssistantMessages((prev) => [
      ...prev,
      { role: 'user', text },
      {
        role: 'assistant',
        text: 'I can group events by risk level and tell you which threads need intervention first.',
      },
    ]);
    setAssistantInput('');
  }, [assistantInput]);

  function goToPage(rawValue) {
    if (totalPages <= 0) return;
    const parsed = Number.parseInt(String(rawValue || '').trim(), 10);
    if (!Number.isFinite(parsed)) return;
    const nextPage = Math.min(totalPages, Math.max(1, parsed));
    setOffset((nextPage - 1) * PAGE_SIZE);
    setPageInput(String(nextPage));
  }

  return (
    <div className={`activity-page int-page${jaspenOpen ? ' drawer-open' : ''}`}>
      <AppMenu />
      <div className="activity-inner int-page-inner">
      <header className="activity-header int-page-head">
        <div>
          <p className="int-eyebrow">Activity</p>
          <h1>Activity</h1>
          <p>Unified timeline of scorecards, scenarios, WBS updates, connectors, team, and data events.</p>
        </div>
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
        <input
          type="date"
          value={fromDate}
          onChange={(event) => {
            setFromDate(event.target.value);
            setOffset(0);
          }}
          aria-label="Filter from date"
        />
        <input
          type="date"
          value={toDate}
          onChange={(event) => {
            setToDate(event.target.value);
            setOffset(0);
          }}
          aria-label="Filter to date"
        />
      </section>

      {loading && (
        <section className="activity-skeleton" role="status" aria-live="polite" aria-label="Loading activity">
          <SkeletonBlock width="28%" height={14} />
          <div className="activity-skeleton-list">
            {Array.from({ length: 5 }).map((_, idx) => (
              <div key={`activity-skeleton-${idx}`} className="activity-skeleton-item">
                <SkeletonBlock width="22%" height={12} />
                <SkeletonBlock width="88%" height={16} />
                <SkeletonBlock width="44%" height={12} />
              </div>
            ))}
          </div>
        </section>
      )}
      {!loading && error && (
        <div className="activity-state activity-state-error" role="status" aria-live="polite">
          <p>{error}</p>
          <button type="button" className="int-btn int-btn-ghost activity-retry-btn" onClick={loadActivity}>
            Retry
          </button>
        </div>
      )}
      {!loading && !error && events.length === 0 && (
        <EmptyState
          className="activity-empty-state"
          title="No matching activity events"
          description="Try resetting filters, or create activity from the workspace."
          icon={<FontAwesomeIcon icon={faClockRotateLeft} />}
          action={(
            <div className="activity-empty-actions">
              <button
                type="button"
                className="int-btn int-btn-ghost"
                onClick={() => {
                  setTypeFilter('');
                  setFromDate('');
                  setToDate('');
                  setOffset(0);
                }}
              >
                Reset filters
              </button>
              <button type="button" className="int-btn int-btn-primary" onClick={() => navigate('/new')}>
                Open Jaspen
              </button>
            </div>
          )}
        />
      )}

      {!loading && !error && events.length > 0 && (
        <section className="activity-timeline">
          {useVirtualTimeline ? (
            <List
              className="activity-virtual-list"
              style={{ height: virtualListHeight }}
              rowCount={events.length}
              rowHeight={ACTIVITY_ROW_HEIGHT}
              rowComponent={ActivityRow}
              rowProps={{ events, typeLabelByValue }}
            />
          ) : (
            events.map((event, index) => (
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
            ))
          )}
        </section>
      )}

      {!loading && !error && total > 0 && (
        <footer className="activity-pagination">
          <p>Showing {start}-{end} of {total}</p>
          <div className="activity-pagination-controls">
            <form
              className="activity-pagination-go"
              onSubmit={(event) => {
                event.preventDefault();
                goToPage(pageInput);
              }}
            >
              <label htmlFor="activity-go-to-page">Go to page</label>
              <input
                id="activity-go-to-page"
                type="number"
                min="1"
                max={Math.max(1, totalPages)}
                value={pageInput}
                onChange={(event) => setPageInput(event.target.value)}
                placeholder={currentPage ? String(currentPage) : '1'}
              />
              <button type="submit" disabled={totalPages <= 1} aria-disabled={totalPages <= 1}>Go</button>
            </form>
            <button type="button" onClick={() => setOffset((prev) => Math.max(0, prev - PAGE_SIZE))} disabled={!hasPrev} aria-disabled={!hasPrev}>Previous</button>
            <button type="button" onClick={() => setOffset((prev) => prev + PAGE_SIZE)} disabled={!hasNext} aria-disabled={!hasNext}>Next</button>
          </div>
        </footer>
      )}
      </div>
      <JaspenAiDrawer
        isOpen={jaspenOpen}
        onOpen={openJaspen}
        onClose={() => setJaspenOpen(false)}
        messages={assistantMessages}
        input={assistantInput}
        onInputChange={setAssistantInput}
        onSend={sendAssistant}
        busy={false}
        starterPrompts={[
          'Where is execution getting blocked?',
          'Which thread needs attention first?',
        ]}
        placeholder="Ask Jaspen about activity..."
      />
    </div>
  );
}
