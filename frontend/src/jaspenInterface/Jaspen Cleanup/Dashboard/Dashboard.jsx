import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../../shared/auth/AuthContext';
import { API_BASE } from '../../../config/apiBase';
import {
  ArcElement,
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  Legend,
  LineElement,
  LinearScale,
  PointElement,
  Tooltip,
} from 'chart.js';
import { Bar, Line, Pie } from 'react-chartjs-2';
import './Dashboard.css';

const STATUS_LABELS = {
  completed: 'Completed',
  archived: 'Archived',
  in_progress: 'Active',
  active: 'Active',
};

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  ArcElement,
  Tooltip,
  Legend
);

function getToken() {
  return localStorage.getItem('access_token') || localStorage.getItem('token') || '';
}

function formatRelative(isoValue) {
  if (!isoValue) return 'Unknown';
  const value = new Date(isoValue);
  if (Number.isNaN(value.getTime())) return 'Unknown';
  const diffMs = Date.now() - value.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return 'Just now';
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.floor(diffHr / 24);
  if (diffDay < 30) return `${diffDay}d ago`;
  return value.toLocaleDateString();
}

function formatScore(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return '—';
  return `${Math.round(num)}`;
}

function scoreTone(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return 'muted';
  if (num >= 80) return 'excellent';
  if (num >= 60) return 'good';
  if (num >= 40) return 'fair';
  return 'risk';
}

function safeList(value) {
  return Array.isArray(value) ? value : [];
}

function chartDataFor(chart = {}, idx = 0) {
  const labels = safeList(chart?.data?.labels).map((item) => String(item ?? ''));
  const values = safeList(chart?.data?.values).map((value) => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  });
  const palette = ['#3554b3', '#5b74cb', '#7d95dd', '#9db0ea', '#c2cff5', '#dce6fb'];
  const tone = palette[idx % palette.length];
  return {
    labels,
    datasets: [
      {
        label: chart?.title || 'Series',
        data: values,
        backgroundColor: chart?.type === 'pie' ? labels.map((_, i) => palette[i % palette.length]) : tone,
        borderColor: tone,
        borderWidth: 1.5,
        tension: 0.25,
        fill: false,
      },
    ],
  };
}

const CHART_OPTIONS = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: {
      display: true,
      position: 'bottom',
    },
  },
};

export default function Dashboard() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');
  const [data, setData] = useState(null);

  const fetchDashboard = useCallback(async ({ silent = false } = {}) => {
    if (silent) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setError('');

    try {
      const token = getToken();
      const headers = token ? { Authorization: `Bearer ${token}` } : {};
      const response = await fetch(`${API_BASE}/api/dashboard`, {
        method: 'GET',
        credentials: 'include',
        headers,
      });
      const payload = await response.json().catch(() => ({}));

      if (response.status === 401) {
        navigate('/login');
        return;
      }

      if (!response.ok) {
        throw new Error(payload?.error || payload?.msg || 'Unable to load dashboard.');
      }

      setData(payload || null);
    } catch (err) {
      setError(err?.message || 'Unable to load dashboard.');
      setData(null);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [navigate]);

  useEffect(() => {
    fetchDashboard();
  }, [fetchDashboard]);

  const organization = data?.organization || {};
  const membership = data?.membership || {};
  const metrics = data?.metrics || {};
  const projects = Array.isArray(data?.projects) ? data.projects : [];
  const activity = Array.isArray(data?.activity) ? data.activity : [];
  const widgetCharts = safeList(data?.insights_widget?.charts);
  const widgetCards = safeList(data?.insights_widget?.cards);

  const scopeLabel = useMemo(() => {
    const scope = String(data?.scope || '').toLowerCase();
    if (scope === 'organization') return 'Organization view';
    if (scope === 'creator') return 'Creator view';
    return 'Dashboard view';
  }, [data?.scope]);

  if (loading) {
    return (
      <div className="dash-page">
        <div className="dash-card dash-loading">Loading dashboard...</div>
      </div>
    );
  }

  return (
    <div className="dash-page">
      <section className="dash-hero dash-card">
        <div>
          <p className="dash-eyebrow">Team Workspace</p>
          <h1>{organization?.name || 'Dashboard'}</h1>
          <p className="dash-subtitle">
            {scopeLabel} for {String(organization?.plan_key || user?.active_organization_plan_key || '').toUpperCase() || 'TEAM'}
            {' · '}
            Role: {String(membership?.role || 'member').replace('_', ' ')}
          </p>
        </div>
        <button
          type="button"
          className="dash-refresh"
          onClick={() => fetchDashboard({ silent: true })}
          disabled={refreshing}
        >
          {refreshing ? 'Refreshing...' : 'Refresh'}
        </button>
      </section>

      {error && (
        <section className="dash-card dash-error">
          <strong>Dashboard unavailable.</strong>
          <span>{error}</span>
          <button type="button" onClick={() => navigate('/new')}>Go to Workspace</button>
        </section>
      )}

      {!error && (
        <>
          <section className="dash-metrics">
            <article className="dash-card">
              <h3>Projects</h3>
              <p>{metrics.projects_total ?? 0}</p>
              <small>{metrics.projects_active ?? 0} active</small>
            </article>
            <article className="dash-card">
              <h3>Completed</h3>
              <p>{metrics.projects_completed ?? 0}</p>
              <small>{metrics.projects_archived ?? 0} archived</small>
            </article>
            <article className="dash-card">
              <h3>Average Score</h3>
              <p>{metrics.avg_score == null ? '—' : `${metrics.avg_score}`}</p>
              <small>{metrics.scored_projects ?? 0} scored projects</small>
            </article>
            <article className="dash-card">
              <h3>Team Members</h3>
              <p>{metrics.team_members ?? 0}</p>
              <small>{metrics.collaborator_viewer_activity ?? 0} collaborator/viewer actions</small>
            </article>
          </section>

          <section className="dash-card dash-insights-widget">
            <div className="dash-section-header">
              <h2>Insights Snapshot</h2>
              <span>{widgetCards.length} recent cards</span>
            </div>
            {widgetCharts.length > 0 ? (
              <div className="dash-insights-chart-grid">
                {widgetCharts.map((chart, idx) => {
                  const chartType = String(chart?.type || '').toLowerCase();
                  const dataPayload = chartDataFor(chart, idx);
                  const valid = safeList(dataPayload.labels).length > 0 && safeList(dataPayload.datasets?.[0]?.data).length > 0;
                  return (
                    <article className="dash-chart-card" key={`dash_chart_${idx}`}>
                      <h3>{chart?.title || `Chart ${idx + 1}`}</h3>
                      {!valid && <p className="dash-empty">No chart data available.</p>}
                      {valid && chartType === 'bar' && <Bar data={dataPayload} options={CHART_OPTIONS} />}
                      {valid && chartType === 'line' && <Line data={dataPayload} options={CHART_OPTIONS} />}
                      {valid && chartType === 'pie' && <Pie data={dataPayload} options={CHART_OPTIONS} />}
                      {valid && !['bar', 'line', 'pie'].includes(chartType) && (
                        <p className="dash-empty">Unsupported chart type: {chartType || 'unknown'}.</p>
                      )}
                    </article>
                  );
                })}
              </div>
            ) : (
              <p className="dash-empty">No chart data yet.</p>
            )}

            <div className="dash-insight-card-grid">
              {widgetCards.length === 0 ? (
                <p className="dash-empty">No insight cards yet. Upload and analyze data in Insights.</p>
              ) : widgetCards.map((card, idx) => (
                <article className="dash-insight-card" key={card.id || `insight_${idx}`}>
                  <div className="dash-insight-meta">
                    <strong>{card.project_name || 'Project Insight'}</strong>
                    <span>{card.owner_name || 'Unknown owner'}</span>
                    <time>{formatRelative(card.timestamp)}</time>
                  </div>
                  <p>{card.summary || 'Insight captured.'}</p>
                  {card.file_name ? <small>Source: {card.file_name}</small> : null}
                  {card.thread_id ? (
                    <button
                      type="button"
                      className="dash-link"
                      onClick={() => navigate(`/new?session_id=${encodeURIComponent(card.thread_id)}`)}
                    >
                      Open project
                    </button>
                  ) : null}
                </article>
              ))}
            </div>
          </section>

          <section className="dash-grid">
            <article className="dash-card dash-table-wrap">
              <div className="dash-section-header">
                <h2>Project Snapshot</h2>
                <span>{projects.length} shown</span>
              </div>
              {projects.length === 0 ? (
                <p className="dash-empty">No projects available yet.</p>
              ) : (
                <div className="dash-table-scroll">
                  <table className="dash-table">
                    <thead>
                      <tr>
                        <th>Project</th>
                        <th>Status</th>
                        <th>Score</th>
                        <th>Owner</th>
                        <th>Updated</th>
                        <th>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {projects.map((project) => {
                        const status = String(project.status || 'in_progress').toLowerCase();
                        const scoreClass = `dash-score dash-score-${scoreTone(project.jaspen_score)}`;
                        return (
                          <tr key={project.thread_id}>
                            <td>{project.project_name || 'Untitled project'}</td>
                            <td>
                              <span className={`dash-pill dash-pill-${status}`}>{STATUS_LABELS[status] || 'Active'}</span>
                            </td>
                            <td>
                              <span className={scoreClass}>{formatScore(project.jaspen_score)}</span>
                            </td>
                            <td>{project.owner_name || 'Unknown'}</td>
                            <td>{formatRelative(project.updated_at)}</td>
                            <td>
                              <button
                                type="button"
                                className="dash-link"
                                onClick={() => navigate(`/new?session_id=${encodeURIComponent(project.thread_id)}`)}
                              >
                                Open
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </article>

            <article className="dash-card dash-activity-wrap">
              <div className="dash-section-header">
                <h2>Recent Activity</h2>
                <span>{activity.length} events</span>
              </div>
              {activity.length === 0 ? (
                <p className="dash-empty">No activity yet.</p>
              ) : (
                <ul className="dash-activity-list">
                  {activity.map((event, index) => (
                    <li key={`${event.project_id || 'project'}-${event.timestamp || index}-${index}`}>
                      <div>
                        <strong>{event.actor_name || 'Someone'}</strong>
                        <span>{event.action || 'updated a project'}</span>
                        {event.project_name ? <em>{event.project_name}</em> : null}
                      </div>
                      <time>{formatRelative(event.timestamp)}</time>
                    </li>
                  ))}
                </ul>
              )}
            </article>
          </section>
        </>
      )}
    </div>
  );
}
