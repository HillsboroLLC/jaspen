import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faTable,
  faThLarge,
  faArrowUpRightFromSquare,
  faBoxArchive,
  faDownload,
} from '@fortawesome/free-solid-svg-icons';
import { API_BASE } from '../../config/apiBase';
import './Projects.css';

const STATUS_OPTIONS = ['All', 'Active', 'Completed', 'Archived'];
const GROUP_OPTIONS = ['None', 'Category', 'Status'];

function authHeaders() {
  const token = localStorage.getItem('access_token') || localStorage.getItem('token');
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

function parseDateValue(value) {
  const ts = new Date(value || 0).getTime();
  return Number.isFinite(ts) ? ts : 0;
}

function scoreCategory(score) {
  if (!Number.isFinite(score)) return 'Unknown';
  if (score >= 80) return 'Excellent';
  if (score >= 60) return 'Good';
  if (score >= 40) return 'Fair';
  return 'At Risk';
}

function categoryClass(category) {
  const normalized = String(category || '').toLowerCase();
  if (normalized === 'excellent') return 'is-excellent';
  if (normalized === 'good') return 'is-good';
  if (normalized === 'fair') return 'is-fair';
  if (normalized === 'at risk') return 'is-risk';
  return 'is-unknown';
}

function normalizeStatus(raw) {
  const status = String(raw || '').trim().toLowerCase();
  if (status === 'archived') return 'Archived';
  if (status === 'completed') return 'Completed';
  return 'Active';
}

function extractScore(session) {
  const result = session?.result && typeof session.result === 'object' ? session.result : {};
  const compat = result?.compat && typeof result.compat === 'object' ? result.compat : {};
  const candidates = [
    session?.score,
    session?.jaspen_score,
    result?.jaspen_score,
    result?.overall_score,
    result?.score,
    compat?.score,
  ];
  for (const value of candidates) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return Math.round(parsed);
  }
  return null;
}

function csvEscape(value) {
  return `"${String(value ?? '').replace(/"/g, '""')}"`;
}

export default function Projects() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [projects, setProjects] = useState([]);
  const [viewMode, setViewMode] = useState('card');
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('All');
  const [groupBy, setGroupBy] = useState('None');
  const [sortBy, setSortBy] = useState('updated');
  const [sortDir, setSortDir] = useState('desc');
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);

  const loadProjects = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`${API_BASE}/api/ai-agent/threads`, {
        credentials: 'include',
        headers: authHeaders(),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data?.success) {
        throw new Error(data?.error || `Failed to load projects (${res.status})`);
      }

      const rows = (Array.isArray(data.sessions) ? data.sessions : []).map((session) => {
        const threadId = String(session?.session_id || '').trim();
        const score = extractScore(session);
        const category = scoreCategory(score);
        const status = normalizeStatus(session?.status);
        const updatedAt = parseDateValue(session?.timestamp || session?.updated_at || session?.created);
        return {
          threadId,
          name: String(session?.name || session?.result?.project_name || `Thread ${threadId}`).trim(),
          score,
          category,
          status,
          updatedAt,
          updatedAtLabel: session?.timestamp || session?.updated_at || session?.created || null,
        };
      }).filter((item) => item.threadId);

      setProjects(rows);
      setSelectedIds(new Set());
    } catch (err) {
      setError(err?.message || 'Failed to load projects.');
      setProjects([]);
      setSelectedIds(new Set());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadProjects();
  }, [loadProjects]);

  const filtered = useMemo(() => {
    let rows = [...projects];
    const query = search.trim().toLowerCase();
    if (query) rows = rows.filter((item) => item.name.toLowerCase().includes(query));
    if (statusFilter !== 'All') rows = rows.filter((item) => item.status === statusFilter);

    rows.sort((a, b) => {
      let left = '';
      let right = '';
      if (sortBy === 'name') {
        left = a.name.toLowerCase();
        right = b.name.toLowerCase();
      } else if (sortBy === 'score') {
        left = Number.isFinite(a.score) ? a.score : -1;
        right = Number.isFinite(b.score) ? b.score : -1;
      } else if (sortBy === 'status') {
        left = a.status;
        right = b.status;
      } else if (sortBy === 'category') {
        left = a.category;
        right = b.category;
      } else {
        left = a.updatedAt;
        right = b.updatedAt;
      }
      if (left < right) return sortDir === 'asc' ? -1 : 1;
      if (left > right) return sortDir === 'asc' ? 1 : -1;
      return 0;
    });
    return rows;
  }, [projects, search, statusFilter, sortBy, sortDir]);

  const grouped = useMemo(() => {
    if (groupBy === 'None') {
      return [{ key: 'all', label: 'All Projects', rows: filtered }];
    }
    const bucket = new Map();
    filtered.forEach((row) => {
      const key = groupBy === 'Category' ? row.category : row.status;
      if (!bucket.has(key)) bucket.set(key, []);
      bucket.get(key).push(row);
    });
    return Array.from(bucket.entries()).map(([key, rows]) => ({ key, label: key, rows }));
  }, [filtered, groupBy]);

  function toggleSort(column) {
    if (sortBy === column) {
      setSortDir((prev) => (prev === 'asc' ? 'desc' : 'asc'));
      return;
    }
    setSortBy(column);
    setSortDir(column === 'updated' || column === 'score' ? 'desc' : 'asc');
  }

  function openProject(threadId) {
    const encoded = encodeURIComponent(String(threadId || '').trim());
    navigate(`/new?session_id=${encoded}&sid=${encoded}`);
  }

  function toggleSelected(threadId, checked) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (checked) next.add(threadId);
      else next.delete(threadId);
      return next;
    });
  }

  function toggleSelectAll(checked) {
    if (!checked) {
      setSelectedIds(new Set());
      return;
    }
    setSelectedIds(new Set(filtered.map((row) => row.threadId)));
  }

  async function archiveSelected() {
    if (!selectedIds.size) return;
    setBulkBusy(true);
    setError('');
    try {
      const updates = Array.from(selectedIds).map((threadId) =>
        fetch(`${API_BASE}/api/ai-agent/threads/${encodeURIComponent(threadId)}`, {
          method: 'PATCH',
          credentials: 'include',
          headers: authHeaders(),
          body: JSON.stringify({ status: 'archived' }),
        })
      );
      const responses = await Promise.all(updates);
      const failed = responses.filter((res) => !res.ok);
      if (failed.length) {
        throw new Error(`Failed to archive ${failed.length} project(s).`);
      }
      await loadProjects();
    } catch (err) {
      setError(err?.message || 'Bulk archive failed.');
    } finally {
      setBulkBusy(false);
    }
  }

  async function archiveSingle(threadId) {
    if (!threadId) return;
    setBulkBusy(true);
    setError('');
    try {
      const res = await fetch(`${API_BASE}/api/ai-agent/threads/${encodeURIComponent(threadId)}`, {
        method: 'PATCH',
        credentials: 'include',
        headers: authHeaders(),
        body: JSON.stringify({ status: 'archived' }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data?.error || `Failed to archive project (${res.status})`);
      }
      await loadProjects();
    } catch (err) {
      setError(err?.message || 'Archive failed.');
    } finally {
      setBulkBusy(false);
    }
  }

  function exportSelected() {
    const selected = filtered.filter((row) => selectedIds.has(row.threadId));
    if (!selected.length) return;

    const header = ['Project Name', 'Thread ID', 'Jaspen Score', 'Category', 'Status', 'Last Updated'];
    const lines = selected.map((row) => [
      row.name,
      row.threadId,
      Number.isFinite(row.score) ? row.score : '',
      row.category,
      row.status,
      row.updatedAtLabel || '',
    ]);

    const csv = [header, ...lines]
      .map((line) => line.map(csvEscape).join(','))
      .join('\n');

    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `jaspen-projects-${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  const allVisibleSelected = filtered.length > 0 && filtered.every((row) => selectedIds.has(row.threadId));

  return (
    <div className="projects-page">
      <header className="projects-header">
        <div>
          <h1>Projects</h1>
          <p>Portfolio view of active and completed strategy projects.</p>
        </div>
        <div className="projects-header-actions">
          <button
            type="button"
            className={`projects-view-toggle ${viewMode === 'card' ? 'is-active' : ''}`}
            onClick={() => setViewMode('card')}
            aria-label="Card view"
          >
            <FontAwesomeIcon icon={faThLarge} />
          </button>
          <button
            type="button"
            className={`projects-view-toggle ${viewMode === 'table' ? 'is-active' : ''}`}
            onClick={() => setViewMode('table')}
            aria-label="Table view"
          >
            <FontAwesomeIcon icon={faTable} />
          </button>
        </div>
      </header>

      <section className="projects-filters">
        <input
          type="text"
          placeholder="Search by project name"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
          {STATUS_OPTIONS.map((option) => <option key={option} value={option}>{option}</option>)}
        </select>
        <select value={groupBy} onChange={(event) => setGroupBy(event.target.value)}>
          {GROUP_OPTIONS.map((option) => <option key={option} value={option}>{option}</option>)}
        </select>
      </section>

      <section className="projects-bulk-actions">
        <label className="projects-select-all">
          <input
            type="checkbox"
            checked={allVisibleSelected}
            onChange={(event) => toggleSelectAll(event.target.checked)}
          />
          Select visible
        </label>
        <button type="button" onClick={archiveSelected} disabled={!selectedIds.size || bulkBusy}>
          <FontAwesomeIcon icon={faBoxArchive} /> Archive
        </button>
        <button type="button" onClick={exportSelected} disabled={!selectedIds.size}>
          <FontAwesomeIcon icon={faDownload} /> Export
        </button>
      </section>

      {loading && <div className="projects-state">Loading projects...</div>}
      {!loading && error && <div className="projects-state projects-state-error">{error}</div>}
      {!loading && !error && filtered.length === 0 && (
        <div className="projects-state">No projects found for this filter.</div>
      )}

      {!loading && !error && filtered.length > 0 && grouped.map((group) => (
        <section key={group.key} className="projects-group">
          {groupBy !== 'None' && <h2>{group.label}</h2>}

          {viewMode === 'card' ? (
            <div className="projects-card-grid">
              {group.rows.map((row) => (
                <article key={row.threadId} className="project-card">
                  <div className="project-card-top">
                    <label>
                      <input
                        type="checkbox"
                        checked={selectedIds.has(row.threadId)}
                        onChange={(event) => toggleSelected(row.threadId, event.target.checked)}
                      />
                    </label>
                    <span className={`project-status ${row.status.toLowerCase()}`}>{row.status}</span>
                  </div>
                  <h3>{row.name}</h3>
                  <p className="project-updated">Updated {row.updatedAtLabel ? new Date(row.updatedAtLabel).toLocaleString() : 'N/A'}</p>
                  <div className="project-card-meta">
                    <span className={`project-score-badge ${categoryClass(row.category)}`}>
                      {Number.isFinite(row.score) ? row.score : '—'}
                    </span>
                    <span>{row.category}</span>
                  </div>
                  <div className="project-card-actions">
                    <button type="button" onClick={() => openProject(row.threadId)}>
                      <FontAwesomeIcon icon={faArrowUpRightFromSquare} /> Open
                    </button>
                    <button
                      type="button"
                      onClick={() => archiveSingle(row.threadId)}
                      disabled={bulkBusy}
                    >
                      <FontAwesomeIcon icon={faBoxArchive} /> Archive
                    </button>
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <div className="projects-table-wrap">
              <table className="projects-table">
                <thead>
                  <tr>
                    <th></th>
                    <th onClick={() => toggleSort('name')}>Name</th>
                    <th onClick={() => toggleSort('score')}>Score</th>
                    <th onClick={() => toggleSort('status')}>Status</th>
                    <th onClick={() => toggleSort('category')}>Category</th>
                    <th onClick={() => toggleSort('updated')}>Last Updated</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {group.rows.map((row) => (
                    <tr key={row.threadId}>
                      <td>
                        <input
                          type="checkbox"
                          checked={selectedIds.has(row.threadId)}
                          onChange={(event) => toggleSelected(row.threadId, event.target.checked)}
                        />
                      </td>
                      <td>{row.name}</td>
                      <td>
                        <span className={`project-score-badge ${categoryClass(row.category)}`}>
                          {Number.isFinite(row.score) ? row.score : '—'}
                        </span>
                      </td>
                      <td><span className={`project-status ${row.status.toLowerCase()}`}>{row.status}</span></td>
                      <td>{row.category}</td>
                      <td>{row.updatedAtLabel ? new Date(row.updatedAtLabel).toLocaleString() : 'N/A'}</td>
                      <td>
                        <button className="projects-link" type="button" onClick={() => openProject(row.threadId)}>Open</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      ))}
    </div>
  );
}
