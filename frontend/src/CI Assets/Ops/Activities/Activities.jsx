// filepath: src/Ops/Activities/Activities.jsx
import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../All/shared/auth/AuthContext';
import './Activities.css';
import ThreadEditModal from '../../Market/components/ThreadEditModal';

export default function Activities() {
  const navigate = useNavigate();
  const { authFetch } = useAuth();

  const [queueItems, setQueueItems] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [refreshing, setRefreshing] = React.useState(false);
  const [error, setError] = React.useState(null);
  const [query, setQuery] = React.useState('');
  const [openingId, setOpeningId] = React.useState(null);
  
  // New state for filters and sorting
  const [sortBy, setSortBy] = React.useState('date_newest');
  const [statusFilter, setStatusFilter] = React.useState('all');
  const [viewMode, setViewMode] = React.useState('my'); // 'my' or 'enterprise'

  const loadQueue = React.useCallback(
    async ({ silent = false } = {}) => {
      let alive = true;

      try {
        if (!silent) setLoading(true);
        setRefreshing(silent);
        setError(null);

        const res = await authFetch('/api/ai-agent/threads', {
          method: 'GET',
          headers: { Accept: 'application/json' },
        });

        const data = await res.json().catch(() => ({}));

        if (!res.ok) {
          throw new Error(data?.error || data?.msg || `HTTP ${res.status}`);
        }

        if (alive) {
          setQueueItems(Array.isArray(data?.items) ? data.items : []);
        }
      } catch (e) {
        if (alive) setError(e?.message || 'Failed to load queue');
      } finally {
        if (alive) {
          setLoading(false);
          setRefreshing(false);
        }
      }

      return () => {
        alive = false;
      };
    },
    [authFetch]
  );

  React.useEffect(() => {
    loadQueue();
  }, [loadQueue]);

  // Filter and sort logic
  const filtered = React.useMemo(() => {
    let result = [...queueItems];

    // Search filter
    const q = query.trim().toLowerCase();
    if (q) {
      result = result.filter((it) => {
        const name = (it?.name || '').toLowerCase();
        const sid = (it?.session_id || '').toLowerCase();
        const preview = (it?.last_message_preview || '').toLowerCase();
        return name.includes(q) || sid.includes(q) || preview.includes(q);
      });
    }

    // Status filter
    if (statusFilter !== 'all') {
      result = result.filter((it) => (it?.status || '').toLowerCase() === statusFilter);
    }

    // Sorting
    result.sort((a, b) => {
      switch (sortBy) {
        case 'score_high':
          return (b?.market_iq_score || 0) - (a?.market_iq_score || 0);
        case 'score_low':
          return (a?.market_iq_score || 0) - (b?.market_iq_score || 0);
        case 'npv_high':
          return (b?.npv || 0) - (a?.npv || 0);
        case 'irr_high':
          return (b?.irr || 0) - (a?.irr || 0);
        case 'date_newest':
          return new Date(b?.timestamp || b?.created_at || 0) - new Date(a?.timestamp || a?.created_at || 0);
        case 'date_oldest':
          return new Date(a?.timestamp || a?.created_at || 0) - new Date(b?.timestamp || b?.created_at || 0);
        case 'name_az':
          return (a?.name || '').localeCompare(b?.name || '');
        default:
          return 0;
      }
    });

    return result;
  }, [queueItems, query, statusFilter, sortBy]);

  const fmtTime = (iso) => {
    if (!iso) return '';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  };

  const fmtRelativeTime = (iso) => {
    if (!iso) return '';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '';
    const now = new Date();
    const diff = now - d;
    const days = Math.floor(diff / (1000 * 60 * 60 * 24));
    if (days === 0) return 'Today';
    if (days === 1) return '1 day ago';
    return `${days} days ago`;
  };

  const formatCurrency = (v) => {
    if (v === null || v === undefined || v === '') return 'N/A';
    const n = Number(String(v).replace(/[^\d.-]/g, ''));
    if (isNaN(n)) return 'N/A';
    if (Math.abs(n) >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
    if (Math.abs(n) >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
    if (Math.abs(n) >= 1e3) return `$${(n / 1e3).toFixed(1)}K`;
    return `$${n.toLocaleString()}`;
  };

  const formatPercent = (v) => {
    if (v === null || v === undefined || v === '') return 'N/A';
    const n = Number(String(v).replace(/[^\d.-]/g, ''));
    if (isNaN(n)) return 'N/A';
    return `${n.toFixed(1)}%`;
  };

  const getScoreLabel = (score) => {
    if (!score || score === '--') return 'Pending';
    if (score >= 80) return 'Excellent';
    if (score >= 60) return 'Good';
    if (score >= 40) return 'Fair';
    return 'At Risk';
  };

  const handleOpen = async (sessionId) => {
    if (!sessionId) return;
    setOpeningId(sessionId);

    try {
      await authFetch(`/api/ai-agent/threads/${encodeURIComponent(sessionId)}`, {
        method: 'GET',
        headers: { Accept: 'application/json' },
      }).catch(() => null);

      navigate(`/market-iq?analysis=${encodeURIComponent(sessionId)}`);
    } finally {
      setOpeningId(null);
    }
  };

  return (
    <div className="analyses-page">
      {/* Header */}
      <div className="analyses-header">
        <div>
          <h1>Market IQ Analyses</h1>
          <p>Track and compare all your strategic assessments</p>
        </div>
        <div className="analyses-actions">
          <div className="view-toggle">
            <button 
              className={`view-toggle-btn ${viewMode === 'my' ? 'active' : ''}`}
              onClick={() => setViewMode('my')}
            >
              My Analyses
            </button>
            <button 
              className={`view-toggle-btn ${viewMode === 'enterprise' ? 'active' : ''}`}
              onClick={() => setViewMode('enterprise')}
            >
              Enterprise
            </button>
          </div>
          <button className="btn primary" onClick={() => navigate('/market-iq')}>
            + New Analysis
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="analyses-filters">
        <input
          type="text"
          className="search-input"
          placeholder="Search by project name or description..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />

        <div className="filter-group">
          <span className="filter-label">Sort by:</span>
          <select 
            className="filter-select" 
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value)}
          >
            <option value="score_high">Score (Highest First)</option>
            <option value="score_low">Score (Lowest First)</option>
            <option value="npv_high">NPV (Highest First)</option>
            <option value="irr_high">IRR (Highest First)</option>
            <option value="date_newest">Date Created (Newest)</option>
            <option value="date_oldest">Date Created (Oldest)</option>
            <option value="name_az">Project Name (A-Z)</option>
          </select>
        </div>

        <div className="filter-group">
          <span className="filter-label">Status:</span>
          <select 
            className="filter-select"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            <option value="all">All Statuses</option>
            <option value="completed">Completed</option>
            <option value="in_progress">In Progress</option>
            <option value="draft">Draft</option>
          </select>
        </div>

        <button
          className="btn"
          onClick={() => loadQueue({ silent: true })}
          disabled={refreshing}
        >
          {refreshing ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>

      {/* Error State */}
      {error && (
        <div className="analyses-error">
          <div>Couldn't load analyses: {error}</div>
          <button className="btn" onClick={() => loadQueue()}>
            Try again
          </button>
        </div>
      )}

      {/* Loading State */}
      {loading ? (
        <div className="analyses-loading">Loading analyses...</div>
      ) : (
        /* Table */
        <div className="analyses-card">
          {filtered.length === 0 ? (
            <div className="empty-state">
              <div className="empty-state-icon">📊</div>
              <div>
                <strong>No analyses found</strong>
                <p>Start a new Market IQ analysis to see it here</p>
              </div>
            </div>
          ) : (
            <table className="analyses-table">
              <thead>
                <tr>
                  <th onClick={() => setSortBy('name_az')}>
                    Project <span className="sort-icon">▼</span>
                  </th>
                  <th onClick={() => setSortBy('score_high')}>
                    Score <span className="sort-icon">▼</span>
                  </th>
                  <th onClick={() => setSortBy('npv_high')}>
                    NPV <span className="sort-icon">▼</span>
                  </th>
                  <th onClick={() => setSortBy('irr_high')}>
                    IRR <span className="sort-icon">▼</span>
                  </th>
                  <th>Payback</th>
                  <th>Status</th>
                  <th onClick={() => setSortBy('date_newest')}>
                    Created <span className="sort-icon">▼</span>
                  </th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((it) => {
                  const sid = it?.session_id;
                  const title = it?.name || sid || 'Untitled Project';
                  const preview = it?.last_message_preview || '';
                  const status = it?.status || 'draft';
                  const ts = it?.timestamp || it?.created_at || it?.created || '';
                  const score = it?.market_iq_score || null;
                  const npv = it?.npv || null;
                  const irr = it?.irr || null;
                  const payback = it?.payback_period || null;

                  return (
                    <tr key={sid}>
                      {/* Project */}
                      <td>
                        <div className="project-name">{title}</div>
                        {preview && (
                          <div className="project-meta">{preview}</div>
                        )}
                      </td>

                      {/* Score */}
                      <td className="score-cell">
                        <div className="score-badge">
                          {score || '--'}
                        </div>
                        <div className="score-label">{getScoreLabel(score)}</div>
                      </td>

                      {/* NPV */}
                      <td>
                        <div className="metric-value">{formatCurrency(npv)}</div>
                        <div className="metric-label">
                          {npv > 0 ? 'Value Creation' : npv < 0 ? 'Value Destruction' : 'Pending'}
                        </div>
                      </td>

                      {/* IRR */}
                      <td>
                        <div className="metric-value">{formatPercent(irr)}</div>
                        <div className="metric-label">
                          {irr > 12 ? 'Above Hurdle' : irr > 0 ? 'Below Hurdle' : 'Pending'}
                        </div>
                      </td>

                      {/* Payback */}
                      <td>
                        <div className="metric-value">
                          {payback ? `${payback.toFixed(1)} yrs` : '--'}
                        </div>
                        <div className="metric-label">
                          {payback <= 3 ? 'Fast Recovery' : payback > 0 ? 'Moderate' : 'Pending'}
                        </div>
                      </td>

                      {/* Status */}
                      <td>
                        <span className={`status-pill status-${status.toLowerCase().replace(/\s+/g, '-')}`}>
                          {status.charAt(0).toUpperCase() + status.slice(1)}
                        </span>
                      </td>

                      {/* Created */}
                      <td>
                        <div style={{ fontSize: '13px', color: '#475569' }}>
                          {fmtTime(ts)}
                        </div>
                        <div style={{ fontSize: '11px', color: '#94a3b8' }}>
                          {fmtRelativeTime(ts)}
                        </div>
                      </td>

                      {/* Actions */}
                      <td>
                        <button
                          className="action-btn"
                          onClick={() => handleOpen(sid)}
                          disabled={!sid || openingId === sid}
                        >
                          {openingId === sid ? 'Opening...' : status === 'completed' ? 'View' : 'Continue'}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
