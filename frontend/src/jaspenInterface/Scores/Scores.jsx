import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faArrowUpRightFromSquare, faChartLine, faDownload, faChevronDown, faChevronUp, faTimes, faTrash } from '@fortawesome/free-solid-svg-icons';
import { List } from 'react-window';
import { API_BASE } from '../../config/apiBase';
import { authFetch, buildAuthHeaders } from '../../shared/auth/http';
import ConfirmDialog from '../../shared/components/ConfirmDialog';
import EmptyState from '../../homeSections/homeUi/EmptyState';
import './Scores.css';
import AppMenu from '../shared/AppMenu';

const CATEGORY_OPTIONS = ['All', 'Excellent', 'Good', 'Fair', 'At Risk'];
const PAGE_LIMIT = 200;
const SCORES_VIRTUALIZE_THRESHOLD = 80;
const SCORE_ROW_BASE_HEIGHT = 106;
const SCORE_ROW_EXPANDED_HEIGHT = 356;
const PORTFOLIO_STARTER_PROMPTS = [
  'Which scored project should I do next?',
  'Rank my top 3 next-best projects and explain why.',
  'Which project is strongest for growth right now?',
  'What should I pause, and what should I do first instead?',
];

function getScoreBadgeClass(category) {
  if (category === 'Excellent') return 'scores-badge excellent';
  if (category === 'Good') return 'scores-badge good';
  if (category === 'Fair') return 'scores-badge fair';
  return 'scores-badge risk';
}

function parseTimestamp(value) {
  const text = String(value || '').trim();
  const normalized = text && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(text)
    ? `${text}Z`
    : value;
  const ts = new Date(normalized || 0).getTime();
  return Number.isFinite(ts) ? ts : 0;
}

function formatFullDate(value) {
  if (!value) return 'Unknown date';
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return String(value);
  return date.toLocaleString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatRelativeTime(value) {
  const ts = parseTimestamp(value);
  if (!ts) return 'Unknown';
  const now = Date.now();
  const diffMs = ts - now;
  const past = diffMs < 0;
  const absMs = Math.abs(diffMs);

  const minute = 60 * 1000;
  const hour = 60 * minute;
  const day = 24 * hour;
  const week = 7 * day;
  const month = 30 * day;
  const year = 365 * day;

  let count = 0;
  let unit = 'minute';
  if (absMs >= year) {
    count = Math.floor(absMs / year);
    unit = 'year';
  } else if (absMs >= month) {
    count = Math.floor(absMs / month);
    unit = 'month';
  } else if (absMs >= week) {
    count = Math.floor(absMs / week);
    unit = 'week';
  } else if (absMs >= day) {
    count = Math.floor(absMs / day);
    unit = 'day';
  } else if (absMs >= hour) {
    count = Math.floor(absMs / hour);
    unit = 'hour';
  } else {
    count = Math.max(1, Math.floor(absMs / minute));
    unit = 'minute';
  }

  const suffix = count === 1 ? unit : `${unit}s`;
  return past ? `${count} ${suffix} ago` : `in ${count} ${suffix}`;
}

function toCsvCell(value) {
  return `"${String(value ?? '').replace(/"/g, '""')}"`;
}

async function apiFetch(path) {
  const response = await authFetch(`${API_BASE}${path}`, {
    credentials: 'include',
    headers: buildAuthHeaders({}, 'GET'),
  });

  if (!response.ok) {
    const message = await response.text().catch(() => '');
    throw new Error(message || `Request failed (${response.status})`);
  }

  return response.json();
}

function Sparkline({ points = [] }) {
  const usable = points
    .filter((point) => Number.isFinite(point?.score))
    .sort((a, b) => a.ts - b.ts);

  if (usable.length < 2) {
    return <span className="scores-sparkline-empty">-</span>;
  }

  const width = 86;
  const height = 24;
  const min = Math.min(...usable.map((point) => point.score));
  const max = Math.max(...usable.map((point) => point.score));
  const range = Math.max(1, max - min);
  const step = usable.length === 1 ? 0 : width / (usable.length - 1);

  const polyline = usable
    .map((point, index) => {
      const x = index * step;
      const y = height - ((point.score - min) / range) * height;
      return `${x},${y}`;
    })
    .join(' ');

  return (
    <svg className="scores-sparkline" width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-label="Score trend">
      <polyline points={polyline} fill="none" stroke="currentColor" strokeWidth="2" />
    </svg>
  );
}

export default function Scores() {
  const navigate = useNavigate();

  const [scores, setScores] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('All');
  const [sortBy, setSortBy] = useState('date');
  const [sortDir, setSortDir] = useState('desc');
  const [offset, setOffset] = useState(0);
  const [pageInput, setPageInput] = useState('');

  const [expandedRows, setExpandedRows] = useState({});
  const [exportingCsv, setExportingCsv] = useState(false);
  const [portfolioDrawerOpen, setPortfolioDrawerOpen] = useState(false);
  const [portfolioMessages, setPortfolioMessages] = useState([]);
  const [portfolioInput, setPortfolioInput] = useState('');
  const [portfolioBusy, setPortfolioBusy] = useState(false);
  const [portfolioError, setPortfolioError] = useState('');
  const [portfolioMeta, setPortfolioMeta] = useState(null);
  const [deletingRowKey, setDeletingRowKey] = useState('');
  const [confirmDialog, setConfirmDialog] = useState(null);
  const [selectedForCompare, setSelectedForCompare] = useState(new Set());
  const [compareModalOpen, setCompareModalOpen] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSearch(searchInput.trim());
      setOffset(0);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  const loadScores = useCallback(async () => {
    setLoading(true);
    setError('');

    try {
      const params = new URLSearchParams({
        sort_by: sortBy,
        sort_dir: sortDir,
        limit: String(PAGE_LIMIT),
        offset: String(offset),
      });
      if (category !== 'All') params.set('category', category);
      if (search) params.set('search', search);

      const data = await apiFetch(`/api/v1/strategy/scores?${params.toString()}`);
      const rows = Array.isArray(data?.scores) ? data.scores : [];
      setScores(rows);
      setTotal(Number(data?.total) || 0);
    } catch (err) {
      setError(err?.message || 'Failed to load completed scores.');
      setScores([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [category, offset, search, sortBy, sortDir]);

  useEffect(() => {
    loadScores();
  }, [loadScores]);

  const trendByProject = useMemo(() => {
    const map = new Map();
    scores.forEach((row) => {
      const project = String(row?.base_project_name || row?.project_name || '').trim() || 'Untitled';
      const scoreValue = Number(row?.jaspen_score);
      const ts = parseTimestamp(row?.created_at || row?.updated_at);
      if (!Number.isFinite(scoreValue) || !ts) return;
      if (!map.has(project)) map.set(project, []);
      map.get(project).push({ score: scoreValue, ts });
    });
    return map;
  }, [scores]);

  const scoreSummary = useMemo(() => {
    const valid = scores
      .map((row) => Number(row?.jaspen_score))
      .filter((value) => Number.isFinite(value));
    const topScore = valid.length ? Math.max(...valid) : null;
    const avgScore = valid.length
      ? Math.round(valid.reduce((sum, value) => sum + value, 0) / valid.length)
      : null;
    const goodOrBetter = scores.filter((row) => {
      const categoryValue = String(row?.score_category || '').toLowerCase();
      return categoryValue === 'excellent' || categoryValue === 'good';
    }).length;
    const latestProject = [...scores]
      .sort((a, b) => parseTimestamp(b?.created_at || b?.updated_at) - parseTimestamp(a?.created_at || a?.updated_at))[0];

    return {
      topScore,
      avgScore,
      goodOrBetter,
      latestProjectName: latestProject?.project_name || '—',
      latestProjectTime: latestProject ? formatFullDate(latestProject?.created_at || latestProject?.updated_at) : '—',
      latestProjectRelative: latestProject ? formatRelativeTime(latestProject?.created_at || latestProject?.updated_at) : '',
    };
  }, [scores]);

  const start = total === 0 ? 0 : offset + 1;
  const end = total === 0 ? 0 : Math.min(offset + scores.length, total);
  const hasPrevious = offset > 0;
  const hasNext = offset + scores.length < total;
  const totalPages = total > 0 ? Math.ceil(total / PAGE_LIMIT) : 0;
  const currentPage = total > 0 ? Math.floor(offset / PAGE_LIMIT) + 1 : 0;
  const useVirtualRows = scores.length > SCORES_VIRTUALIZE_THRESHOLD;

  const getRowKey = useCallback((row, index) => `${row?.thread_id || 'thread'}:${row?.snapshot_id || index}`, []);

  const getVirtualRowHeight = useCallback((index) => {
    const row = scores[index];
    const rowKey = getRowKey(row, index);
    return expandedRows[rowKey] ? SCORE_ROW_EXPANDED_HEIGHT : SCORE_ROW_BASE_HEIGHT;
  }, [expandedRows, getRowKey, scores]);

  const virtualListHeight = useMemo(() => {
    if (!scores.length) return 0;
    const totalHeight = scores.reduce((height, _row, index) => height + getVirtualRowHeight(index), 0);
    return Math.min(640, Math.max(280, totalHeight));
  }, [scores, getVirtualRowHeight]);

  function toggleSort(column) {
    if (sortBy === column) {
      setSortDir((prev) => (prev === 'asc' ? 'desc' : 'asc'));
      return;
    }
    setSortBy(column);
    setSortDir(column === 'date' || column === 'score' ? 'desc' : 'asc');
    setOffset(0);
  }

  function sortIndicator(column) {
    if (sortBy !== column) return null;
    return sortDir === 'asc' ? ' ↑' : ' ↓';
  }

  function toggleExpanded(rowKey) {
    setExpandedRows((prev) => ({ ...prev, [rowKey]: !prev[rowKey] }));
  }

  function goToPage(rawValue) {
    if (totalPages <= 0) return;
    const parsed = Number.parseInt(String(rawValue || '').trim(), 10);
    if (!Number.isFinite(parsed)) return;
    const nextPage = Math.min(totalPages, Math.max(1, parsed));
    setOffset((nextPage - 1) * PAGE_LIMIT);
    setPageInput(String(nextPage));
  }

  function openAnalysis(threadId) {
    const encoded = encodeURIComponent(String(threadId || ''));
    navigate(`/new?session_id=${encoded}&sid=${encoded}`);
  }

  function toggleCompareSelection(rowKey, checked) {
    setSelectedForCompare((prev) => {
      const next = new Set(prev);
      if (checked) {
        if (next.size < 2 || next.has(rowKey)) next.add(rowKey);
      } else {
        next.delete(rowKey);
      }
      return next;
    });
  }

  function exportRowReport(row) {
    const payload = {
      project_name: row?.project_name || '',
      thread_id: row?.thread_id || '',
      snapshot_id: row?.snapshot_id || '',
      variant_label: row?.variant_label || '',
      is_baseline: row?.is_baseline || false,
      jaspen_score: row?.jaspen_score,
      score_category: row?.score_category || '',
      component_scores: row?.component_scores || {},
      financial_impact: row?.financial_impact || {},
      created_at: row?.created_at || null,
      updated_at: row?.updated_at || null,
    };

    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${String(row?.project_name || 'analysis').replace(/\s+/g, '-').toLowerCase()}-report.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  async function deleteScoreEntry(row) {
    const label = row?.project_name || 'this entry';
    const rowKey = `${row?.thread_id || ''}:${row?.snapshot_id || ''}`;
    setConfirmDialog({
      title: 'Delete score entry',
      message: `Delete "${label}"? This cannot be undone.`,
      confirmLabel: 'Delete score',
      confirmVariant: 'danger',
      onConfirm: async () => {
        setConfirmDialog(null);
        setDeletingRowKey(rowKey);
        try {
          const threadId = encodeURIComponent(row?.thread_id || '');
          const snapshotId = encodeURIComponent(row?.snapshot_id || '');
          const response = await authFetch(`${API_BASE}/api/v1/strategy/scores/${threadId}/${snapshotId}`, {
            method: 'DELETE',
            credentials: 'include',
            headers: buildAuthHeaders({}, 'DELETE'),
          });
          if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            throw new Error(data?.error || `Delete failed (${response.status})`);
          }
          loadScores();
        } catch (err) {
          setError(err?.message || 'Failed to delete score entry.');
        } finally {
          setDeletingRowKey('');
        }
      },
    });
  }

  async function exportCsv() {
    setExportingCsv(true);
    setError('');

    try {
      const rows = [];
      let nextOffset = 0;
      const batchLimit = 250;

      for (;;) {
        const params = new URLSearchParams({
          sort_by: sortBy,
          sort_dir: sortDir,
          limit: String(batchLimit),
          offset: String(nextOffset),
        });
        if (category !== 'All') params.set('category', category);
        if (search) params.set('search', search);

        const data = await apiFetch(`/api/v1/strategy/scores?${params.toString()}`);
        const chunk = Array.isArray(data?.scores) ? data.scores : [];
        rows.push(...chunk);

        if (chunk.length < batchLimit) break;
        nextOffset += batchLimit;
      }

      const csvHeader = ['Project Name', 'Jaspen Score', 'Category', 'Variant', 'Date'];
      const csvRows = rows.map((row) => [
        row?.project_name || '',
        row?.jaspen_score ?? '',
        row?.score_category || '',
        row?.variant_label || (row?.is_baseline ? 'Baseline' : '—'),
        row?.created_at || row?.updated_at || '',
      ]);

      const csv = [csvHeader, ...csvRows]
        .map((line) => line.map(toCsvCell).join(','))
        .join('\n');

      const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `jaspen-completed-scores-${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err?.message || 'Failed to export CSV.');
    } finally {
      setExportingCsv(false);
    }
  }

  async function submitPortfolioPrompt(rawPrompt) {
    const prompt = String(rawPrompt || '').trim();
    if (!prompt || portfolioBusy) return;

    const priorMessages = portfolioMessages
      .filter((entry) => entry && (entry.role === 'user' || entry.role === 'assistant'))
      .map((entry) => ({ role: entry.role, content: entry.content }));

    setPortfolioDrawerOpen(true);
    setPortfolioBusy(true);
    setPortfolioError('');
    setPortfolioInput('');
    setPortfolioMessages((prev) => [...prev, { role: 'user', content: prompt }]);

    try {
      const response = await authFetch(`${API_BASE}/api/v1/strategy/scores/portfolio-agent`, {
        method: 'POST',
        credentials: 'include',
        headers: buildAuthHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({
          message: prompt,
          messages: priorMessages,
          category,
          search,
          sort_by: sortBy,
          sort_dir: sortDir,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data?.error || `Request failed (${response.status})`);
      }
      setPortfolioMeta(data?.context || null);
      setPortfolioMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: String(data?.reply || '').trim() || 'I could not produce a recommendation from the current score set.',
        },
      ]);
    } catch (err) {
      const message = err?.message || 'Portfolio agent failed.';
      setPortfolioError(message);
      setPortfolioMessages((prev) => [
        ...prev,
        { role: 'assistant', content: 'I hit an issue while reviewing your scored portfolio. Please try again.' },
      ]);
    } finally {
      setPortfolioBusy(false);
    }
  }

  const portfolioScopeLabel = useMemo(() => {
    const totalMatching = Number(portfolioMeta?.total_matching);
    const count = Number.isFinite(totalMatching) && totalMatching >= 0 ? totalMatching : total;
    const parts = [`${count || 0} scored project${count === 1 ? '' : 's'}`];
    if (category !== 'All') parts.push(category);
    if (search) parts.push(`matching "${search}"`);
    return parts.join(' • ');
  }, [portfolioMeta, total, category, search]);

  const compareRows = useMemo(() => {
    const keys = Array.from(selectedForCompare);
    return keys
      .map((rowKey) => {
        const [threadId, snapshotId] = rowKey.split(':');
        return scores.find((row, index) => {
          const key = getRowKey(row, index);
          return key === `${threadId}:${snapshotId}`;
        });
      })
      .filter(Boolean);
  }, [selectedForCompare, scores, getRowKey]);

  const compareMetricRows = useMemo(() => {
    if (compareRows.length !== 2) return [];
    const [a, b] = compareRows;
    const aScores = a?.component_scores || {};
    const bScores = b?.component_scores || {};
    const labels = [
      'financial_health',
      'operational_efficiency',
      'market_position',
      'execution_readiness',
    ];
    return labels.map((key) => {
      const av = Number(aScores[key]);
      const bv = Number(bScores[key]);
      const safeA = Number.isFinite(av) ? av : 0;
      const safeB = Number.isFinite(bv) ? bv : 0;
      return {
        key,
        label: key.replace(/_/g, ' '),
        a: safeA,
        b: safeB,
        delta: safeA - safeB,
      };
    });
  }, [compareRows]);

  const renderVirtualScoreRow = ({ index, style, rows, expandedRowsMap, deletingRowKeyValue, trendByProjectMap, ariaAttributes }) => {
    const row = rows[index];
    if (!row) return null;

    const rowKey = getRowKey(row, index);
    const expanded = Boolean(expandedRowsMap[rowKey]);
    const scoreValue = Number(row?.jaspen_score);
    const projectName = row?.project_name || 'Untitled project';
    const variantLabel = row?.variant_label || (row?.is_baseline ? 'Baseline' : '—');
    const baseProject = row?.base_project_name || projectName;
    const trendPoints = trendByProjectMap.get(baseProject) || [];
    const compareChecked = selectedForCompare.has(rowKey);
    const compareDisabled = selectedForCompare.size >= 2 && !compareChecked;

    return (
      <div style={style} {...ariaAttributes}>
        <article className={`scores-virtual-row${expanded ? ' is-expanded' : ''}`}>
          <div className="scores-virtual-main">
            <div className="scores-virtual-col compare">
              <input
                type="checkbox"
                checked={compareChecked}
                onChange={(event) => toggleCompareSelection(rowKey, event.target.checked)}
                disabled={compareDisabled}
                aria-label={`Select ${projectName} for compare`}
              />
            </div>
            <div className="scores-virtual-col project">
              <button
                type="button"
                className="scores-link-btn"
                onClick={() => openAnalysis(row?.thread_id)}
                title="Open analysis in workspace"
              >
                {projectName}
              </button>
              <div className="scores-trend-row">
                <span className="scores-trend-label">Trend</span>
                <Sparkline points={trendPoints} />
              </div>
              <div className="scores-rubric-chip">Rubric {row?.scoring_rubric_version || 'v3'}</div>
            </div>
            <div className="scores-virtual-col score">
              <span className={getScoreBadgeClass(row?.score_category)}>
                {Number.isFinite(scoreValue) ? scoreValue : '—'}
              </span>
            </div>
            <div className="scores-virtual-col category">
              <span className={getScoreBadgeClass(row?.score_category)}>
                {row?.score_category || 'At Risk'}
              </span>
            </div>
            <div className="scores-virtual-col meta">
              <span className="scores-virtual-label">Variant</span>
              <span>{variantLabel}</span>
            </div>
            <div className="scores-virtual-col meta">
              <span className="scores-virtual-label">Date</span>
              <span>{formatFullDate(row?.created_at || row?.updated_at)}</span>
            </div>
            <div className="scores-actions">
              <button
                type="button"
                className="scores-expand-btn"
                onClick={() => toggleExpanded(rowKey)}
                aria-expanded={expanded}
              >
                {expanded ? 'Hide' : 'View'} details <FontAwesomeIcon icon={expanded ? faChevronUp : faChevronDown} />
              </button>
              <button
                type="button"
                className="scores-icon-btn"
                title="View analysis"
                onClick={() => openAnalysis(row?.thread_id)}
              >
                <FontAwesomeIcon icon={faArrowUpRightFromSquare} />
              </button>
              <button
                type="button"
                className="scores-icon-btn"
                title="Export individual report"
                onClick={() => exportRowReport(row)}
              >
                <FontAwesomeIcon icon={faDownload} />
              </button>
              <button
                type="button"
                className="scores-icon-btn scores-delete-btn"
                title={row?.is_baseline ? 'Delete project and all variants' : 'Delete this variant'}
                onClick={() => deleteScoreEntry(row)}
                disabled={Boolean(deletingRowKeyValue)}
                aria-disabled={Boolean(deletingRowKeyValue)}
              >
                <FontAwesomeIcon icon={faTrash} />
              </button>
            </div>
          </div>

          {expanded && (
            <div className="scores-expanded-grid">
              <div>
                <h4>Variant</h4>
                <p>{variantLabel}{row?.is_baseline ? ' (Baseline)' : ''}</p>
                <h4 style={{ marginTop: 12 }}>All Variants</h4>
                <ul>
                  {rows
                    .filter((s) => s?.thread_id === row?.thread_id)
                    .map((s, si) => (
                      <li key={`sibling-virtual-${rowKey}-${si}`}>
                        {s?.project_name || 'Untitled'} — {s?.jaspen_score ?? '—'}
                      </li>
                    ))}
                </ul>
              </div>
              <div>
                <h4>Component Scores</h4>
                {row?.component_scores && Object.keys(row.component_scores).length > 0 ? (
                  <ul>
                    {Object.entries(row.component_scores)
                      .filter(([, value]) => value != null && typeof value !== 'object')
                      .map(([key, value]) => (
                        <li key={`component-virtual-${rowKey}-${key}`}>{key}: {String(value)}</li>
                      ))}
                  </ul>
                ) : (
                  <p>No component scores available.</p>
                )}
              </div>
              <div>
                <h4>Financial Impact</h4>
                {row?.financial_impact && Object.keys(row.financial_impact).length > 0 ? (
                  <ul>
                    {Object.entries(row.financial_impact)
                      .filter(([, value]) => value != null && typeof value !== 'object')
                      .map(([key, value]) => (
                        <li key={`financial-virtual-${rowKey}-${key}`}>{key}: {String(value)}</li>
                      ))}
                  </ul>
                ) : (
                  <p>No financial impact data.</p>
                )}
              </div>
            </div>
          )}
        </article>
      </div>
    );
  };

  return (
    <div className={`scores-container int-page int-page-inner ${portfolioDrawerOpen ? 'drawer-open' : ''}`}>
      <AppMenu />
      {!portfolioDrawerOpen && (
        <button
          type="button"
          className="scores-agent-tab"
          onClick={() => setPortfolioDrawerOpen(true)}
          aria-label="Open Jaspen drawer"
          aria-expanded={portfolioDrawerOpen}
          aria-controls="scores-portfolio-agent-drawer"
        >
          JASPEN
        </button>
      )}

      <aside
        id="scores-portfolio-agent-drawer"
        className={`scores-agent-drawer ${portfolioDrawerOpen ? 'open' : ''}`}
        aria-label="Jaspen drawer"
      >
        <div className="scores-agent-header">
          <div>
            <div className="scores-agent-title">Jaspen</div>
            <div className="scores-agent-subtitle">{portfolioScopeLabel}</div>
          </div>
          <button
            type="button"
            className="scores-agent-close"
            onClick={() => setPortfolioDrawerOpen(false)}
            aria-label="Close Jaspen drawer"
          >
            <FontAwesomeIcon icon={faTimes} />
          </button>
        </div>

        <div className="scores-agent-body">
          {portfolioMessages.length === 0 ? (
            <div className="scores-agent-empty">
              <p>
                Ask Jaspen to look across your scored portfolio and recommend what to do next.
                It will weigh score alongside readiness, execution path, and upside instead of blindly picking the top score.
              </p>
              <div className="scores-agent-starters">
                {PORTFOLIO_STARTER_PROMPTS.map((prompt) => (
                  <button
                    key={prompt}
                    type="button"
                    className="scores-agent-starter"
                    onClick={() => submitPortfolioPrompt(prompt)}
                    disabled={portfolioBusy || loading || total === 0} aria-disabled={portfolioBusy || loading || total === 0}
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="scores-agent-messages">
              {portfolioMessages.map((entry, index) => (
                <div key={`${entry.role}-${index}`} className={`scores-agent-message ${entry.role}`}>
                  <div className="scores-agent-message-content">{entry.content}</div>
                </div>
              ))}
            </div>
          )}
          {portfolioError && <div className="scores-agent-error">{portfolioError}</div>}
        </div>

        <div className="scores-agent-input-area">
          <div className="scores-agent-input-hint">Using your current Scores filters as context.</div>
          <div className="scores-agent-input-row">
            <textarea
              className="scores-agent-input"
              rows={3}
              placeholder="Ask which project you should do next and why."
              value={portfolioInput}
              onChange={(event) => setPortfolioInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault();
                  submitPortfolioPrompt(portfolioInput);
                }
              }}
              disabled={portfolioBusy || loading || total === 0}
            />
            <button
              type="button"
              className="scores-primary-btn scores-agent-send int-btn int-btn-primary"
              onClick={() => submitPortfolioPrompt(portfolioInput)}
              disabled={portfolioBusy || loading || total === 0 || !portfolioInput.trim()} aria-disabled={portfolioBusy || loading || total === 0 || !portfolioInput.trim()}
            >
              {portfolioBusy ? 'Thinking…' : 'Send'}
            </button>
          </div>
        </div>
      </aside>

      <div className="scores-card">
        <div className="scores-toolbar int-page-head">
          <div>
            <p className="int-eyebrow">Scores</p>
            <h1>Completed Scores</h1>
            <p>All completed analyses and adopted scenarios</p>
          </div>
          <div className="scores-toolbar-actions">
            <button type="button" className="scores-secondary-btn int-btn int-btn-ghost" onClick={() => navigate('/new')}>
              Back to Jaspen
            </button>
            <button type="button" className="scores-primary-btn int-btn int-btn-primary" onClick={exportCsv} disabled={exportingCsv || loading || total === 0} aria-disabled={exportingCsv || loading || total === 0}>
              {exportingCsv ? 'Exporting...' : 'Export CSV'}
            </button>
          </div>
        </div>

        {!loading && !error && total > 0 && (
          <section className="scores-summary-grid" aria-label="Portfolio summary">
            <article className="scores-summary-card">
              <h2>Top Score</h2>
              <p>{scoreSummary.topScore != null ? scoreSummary.topScore : '—'}</p>
            </article>
            <article className="scores-summary-card">
              <h2>Average Score</h2>
              <p>{scoreSummary.avgScore != null ? scoreSummary.avgScore : '—'}</p>
            </article>
            <article className="scores-summary-card">
              <h2>Good or Better</h2>
              <p>{scoreSummary.goodOrBetter} of {scores.length}</p>
            </article>
            <article className="scores-summary-card">
              <h2>Latest Project</h2>
              <p>{scoreSummary.latestProjectName}</p>
              <span>
                {scoreSummary.latestProjectTime}
                {scoreSummary.latestProjectRelative ? ` (${scoreSummary.latestProjectRelative})` : ''}
              </span>
            </article>
          </section>
        )}

        <div className="scores-filters">
          <input
            type="text"
            placeholder="Search by project name..."
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
          />
          <select
            value={category}
            onChange={(event) => {
              setCategory(event.target.value);
              setOffset(0);
            }}
          >
            {CATEGORY_OPTIONS.map((option) => (
              <option key={option} value={option}>{option}</option>
            ))}
          </select>
        </div>

        {selectedForCompare.size === 2 && (
          <div className="scores-compare-cta">
            <button type="button" className="int-btn int-btn-primary" onClick={() => setCompareModalOpen(true)}>
              Compare selected ideas →
            </button>
          </div>
        )}

        {loading && <div className="scores-state">Loading completed analyses...</div>}
        {!loading && error && (
          <div className="scores-state scores-state-error" role="status" aria-live="polite">
            <p>{error}</p>
            <button type="button" className="int-btn int-btn-ghost scores-retry-btn" onClick={loadScores}>
              Retry
            </button>
          </div>
        )}
        {!loading && !error && total === 0 && (
          <EmptyState
            className="scores-empty-state"
            title="No completed scores yet"
            description="Start your first project in Jaspen and complete an analysis to populate this page."
            icon={<FontAwesomeIcon icon={faChartLine} />}
            action={(
              <button type="button" className="int-btn int-btn-primary" onClick={() => navigate('/new')}>
                Start first project
              </button>
            )}
          />
        )}

        {!loading && !error && total > 0 && (
          <>
            {useVirtualRows ? (
              <div className="scores-virtual-wrap">
                <div className="scores-virtual-head">
                  <span>Compare</span>
                  <span>Project</span>
                  <span>Score</span>
                  <span>Category</span>
                  <span>Variant</span>
                  <span>Date</span>
                  <span>Actions</span>
                </div>
                <List
                  className="scores-virtual-list"
                  style={{ height: virtualListHeight }}
                  rowCount={scores.length}
                  rowHeight={(index, rowProps) => {
                    const row = rowProps.rows[index];
                    const rowKey = getRowKey(row, index);
                    return rowProps.expandedRowsMap[rowKey] ? SCORE_ROW_EXPANDED_HEIGHT : SCORE_ROW_BASE_HEIGHT;
                  }}
                  rowComponent={renderVirtualScoreRow}
                  rowProps={{
                    rows: scores,
                    expandedRowsMap: expandedRows,
                    deletingRowKeyValue: deletingRowKey,
                    trendByProjectMap: trendByProject,
                  }}
                />
              </div>
            ) : (
              <div className="scores-table-wrap">
                <table className="scores-table">
                  <thead>
                    <tr>
                      <th>Compare</th>
                      <th onClick={() => toggleSort('name')}>Project Name{sortIndicator('name')}</th>
                      <th onClick={() => toggleSort('score')}>Jaspen Score{sortIndicator('score')}</th>
                      <th onClick={() => toggleSort('category')}>Category{sortIndicator('category')}</th>
                      <th>Variant</th>
                      <th>Component Scores</th>
                      <th onClick={() => toggleSort('date')}>Date{sortIndicator('date')}</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {scores.map((row, index) => {
                      const rowKey = getRowKey(row, index);
                      const expanded = Boolean(expandedRows[rowKey]);
                      const scoreValue = Number(row?.jaspen_score);
                      const projectName = row?.project_name || 'Untitled project';
                      const variantLabel = row?.variant_label || (row?.is_baseline ? 'Baseline' : '—');
                      const baseProject = row?.base_project_name || projectName;
                      const trendPoints = trendByProject.get(baseProject) || [];
                      return (
                        <React.Fragment key={rowKey}>
                          <tr>
                            <td>
                              <input
                                type="checkbox"
                                checked={selectedForCompare.has(rowKey)}
                                onChange={(event) => toggleCompareSelection(rowKey, event.target.checked)}
                                disabled={selectedForCompare.size >= 2 && !selectedForCompare.has(rowKey)}
                                aria-label={`Select ${projectName} for compare`}
                              />
                            </td>
                            <td>
                              <button
                                type="button"
                                className="scores-link-btn"
                                onClick={() => openAnalysis(row?.thread_id)}
                                title="Open analysis in workspace"
                              >
                                {projectName}
                              </button>
                              <div className="scores-trend-row">
                                <span className="scores-trend-label">Trend</span>
                                <Sparkline points={trendPoints} />
                              </div>
                              <div className="scores-rubric-chip">Rubric {row?.scoring_rubric_version || 'v3'}</div>
                            </td>
                            <td>
                              <span className={getScoreBadgeClass(row?.score_category)}>
                                {Number.isFinite(scoreValue) ? scoreValue : '—'}
                              </span>
                            </td>
                            <td>
                              <span className={getScoreBadgeClass(row?.score_category)}>
                                {row?.score_category || 'At Risk'}
                              </span>
                            </td>
                            <td>{variantLabel}</td>
                            <td>
                              <button
                                type="button"
                                className="scores-expand-btn"
                                onClick={() => toggleExpanded(rowKey)}
                                aria-expanded={expanded}
                              >
                                {expanded ? 'Hide' : 'View'} details{' '}
                                <FontAwesomeIcon icon={expanded ? faChevronUp : faChevronDown} />
                              </button>
                            </td>
                            <td>
                              {formatFullDate(row?.created_at || row?.updated_at)}
                            </td>
                            <td>
                              <div className="scores-actions">
                                <button
                                  type="button"
                                  className="scores-icon-btn"
                                  title="View analysis"
                                  onClick={() => openAnalysis(row?.thread_id)}
                                >
                                  <FontAwesomeIcon icon={faArrowUpRightFromSquare} />
                                </button>
                                <button
                                  type="button"
                                  className="scores-icon-btn"
                                  title="Export individual report"
                                  onClick={() => exportRowReport(row)}
                                >
                                  <FontAwesomeIcon icon={faDownload} />
                                </button>
                                <button
                                  type="button"
                                  className="scores-icon-btn scores-delete-btn"
                                  title={row?.is_baseline ? 'Delete project and all variants' : 'Delete this variant'}
                                  onClick={() => deleteScoreEntry(row)}
                                  disabled={Boolean(deletingRowKey)}
                                  aria-disabled={Boolean(deletingRowKey)}
                                >
                                  <FontAwesomeIcon icon={faTrash} />
                                </button>
                              </div>
                            </td>
                          </tr>
                          {expanded && (
                            <tr className="scores-expanded-row">
                              <td colSpan={8}>
                                <div className="scores-expanded-grid">
                                  <div>
                                    <h4>Variant</h4>
                                    <p>{variantLabel}{row?.is_baseline ? ' (Baseline)' : ''}</p>
                                    <h4 style={{ marginTop: 12 }}>All Variants</h4>
                                    <ul>
                                      {scores
                                        .filter((s) => s?.thread_id === row?.thread_id)
                                        .map((s, si) => (
                                          <li key={`sibling-${rowKey}-${si}`}>
                                            {s?.project_name || 'Untitled'} — {s?.jaspen_score ?? '—'}
                                          </li>
                                        ))}
                                    </ul>
                                  </div>
                                  <div>
                                    <h4>Component Scores</h4>
                                    {row?.component_scores && Object.keys(row.component_scores).length > 0 ? (
                                      <ul>
                                        {Object.entries(row.component_scores)
                                          .filter(([, value]) => value != null && typeof value !== 'object')
                                          .map(([key, value]) => (
                                            <li key={`component-${rowKey}-${key}`}>{key}: {String(value)}</li>
                                          ))}
                                      </ul>
                                    ) : (
                                      <p>No component scores available.</p>
                                    )}
                                  </div>
                                  <div>
                                    <h4>Financial Impact</h4>
                                    {row?.financial_impact && Object.keys(row.financial_impact).length > 0 ? (
                                      <ul>
                                        {Object.entries(row.financial_impact)
                                          .filter(([, value]) => value != null && typeof value !== 'object')
                                          .map(([key, value]) => (
                                            <li key={`financial-${rowKey}-${key}`}>{key}: {String(value)}</li>
                                          ))}
                                      </ul>
                                    ) : (
                                      <p>No financial impact data.</p>
                                    )}
                                  </div>
                                </div>
                              </td>
                            </tr>
                          )}
                        </React.Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}

            <div className="scores-pagination">
              <span>Showing {start}-{end} of {total}</span>
              <div className="scores-pagination-actions">
                <form
                  className="scores-pagination-go"
                  onSubmit={(event) => {
                    event.preventDefault();
                    goToPage(pageInput);
                  }}
                >
                  <label htmlFor="scores-go-to-page">Go to page</label>
                  <input
                    id="scores-go-to-page"
                    type="number"
                    min="1"
                    max={Math.max(1, totalPages)}
                    value={pageInput}
                    onChange={(event) => setPageInput(event.target.value)}
                    placeholder={currentPage ? String(currentPage) : '1'}
                  />
                  <button
                    type="submit"
                    className="scores-secondary-btn int-btn int-btn-ghost"
                    disabled={totalPages <= 1}
                    aria-disabled={totalPages <= 1}
                  >
                    Go
                  </button>
                </form>
                <button
                  type="button"
                  className="scores-secondary-btn int-btn int-btn-ghost"
                  onClick={() => setOffset((prev) => Math.max(0, prev - PAGE_LIMIT))}
                  disabled={!hasPrevious} aria-disabled={!hasPrevious}
                >
                  Previous
                </button>
                <button
                  type="button"
                  className="scores-secondary-btn int-btn int-btn-ghost"
                  onClick={() => setOffset((prev) => prev + PAGE_LIMIT)}
                  disabled={!hasNext} aria-disabled={!hasNext}
                >
                  Next
                </button>
              </div>
            </div>
          </>
        )}
      </div>

      {compareModalOpen && compareRows.length === 2 && (
        <div className="scores-compare-modal-overlay" role="dialog" aria-modal="true" aria-label="Compare selected ideas">
          <div className="scores-compare-modal">
            <div className="scores-compare-head">
              <h3>Compare Ideas</h3>
              <button type="button" className="scores-agent-close" onClick={() => setCompareModalOpen(false)} aria-label="Close compare modal">
                <FontAwesomeIcon icon={faTimes} />
              </button>
            </div>
            <div className="scores-compare-subhead">
              <strong>{compareRows[0]?.project_name || 'Idea A'}</strong>
              <strong>{compareRows[1]?.project_name || 'Idea B'}</strong>
            </div>
            <div className="scores-compare-grid">
              {compareMetricRows.map((metric) => (
                <div key={metric.key} className="scores-compare-row">
                  <div className="scores-compare-label">{metric.label}</div>
                  <div>{metric.a}</div>
                  <div>{metric.b}</div>
                  <div className={metric.delta >= 0 ? 'delta-positive' : 'delta-negative'}>
                    {metric.delta >= 0 ? '+' : ''}{metric.delta}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
      <ConfirmDialog
        isOpen={Boolean(confirmDialog)}
        title={confirmDialog?.title}
        message={confirmDialog?.message}
        confirmLabel={confirmDialog?.confirmLabel}
        confirmVariant={confirmDialog?.confirmVariant}
        pending={Boolean(deletingRowKey)}
        onCancel={() => setConfirmDialog(null)}
        onConfirm={() => confirmDialog?.onConfirm?.()}
      />
    </div>
  );
}
