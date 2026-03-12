import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { API_BASE } from '../../config/apiBase';
import './Scores.css';

const CATEGORY_OPTIONS = ['All', 'Excellent', 'Good', 'Fair', 'At Risk'];

function categoryFromScore(score) {
  const n = Number(score);
  if (!Number.isFinite(n)) return 'Unscored';
  if (n >= 80) return 'Excellent';
  if (n >= 60) return 'Good';
  if (n >= 40) return 'Fair';
  return 'At Risk';
}

function parseScore(result = {}, fallback = null) {
  const candidates = [
    result?.jaspen_score,
    result?.overall_score,
    result?.score,
    result?.compat?.score,
    fallback,
  ];
  for (const candidate of candidates) {
    const n = Number(candidate);
    if (Number.isFinite(n)) return Math.round(n);
  }
  return null;
}

function toIsoDate(value) {
  if (!value) return null;
  const ts = new Date(value).getTime();
  if (!Number.isFinite(ts)) return null;
  return new Date(ts).toISOString();
}

function toLocalDate(value) {
  if (!value) return '—';
  const d = new Date(value);
  if (!Number.isFinite(d.getTime())) return '—';
  return d.toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

function sortRows(rows, key, dir) {
  const mult = dir === 'asc' ? 1 : -1;
  const out = [...rows];
  out.sort((a, b) => {
    if (key === 'score') return ((a.score ?? -1) - (b.score ?? -1)) * mult;
    if (key === 'date') return ((a.dateMs ?? 0) - (b.dateMs ?? 0)) * mult;
    if (key === 'project') return String(a.projectName || '').localeCompare(String(b.projectName || '')) * mult;
    if (key === 'category') return String(a.category || '').localeCompare(String(b.category || '')) * mult;
    if (key === 'adopted') return (Number(a.isAdopted) - Number(b.isAdopted)) * mult;
    return 0;
  });
  return out;
}

function Sparkline({ points = [] }) {
  const usable = points.filter((p) => Number.isFinite(p.score)).sort((a, b) => a.dateMs - b.dateMs);
  if (usable.length < 2) return <span className="scores-sparkline-empty">—</span>;

  const width = 84;
  const height = 22;
  const min = Math.min(...usable.map((p) => p.score));
  const max = Math.max(...usable.map((p) => p.score));
  const range = Math.max(1, max - min);
  const xStep = usable.length === 1 ? 0 : width / (usable.length - 1);
  const poly = usable
    .map((p, idx) => {
      const x = idx * xStep;
      const y = height - ((p.score - min) / range) * height;
      return `${x},${y}`;
    })
    .join(' ');

  return (
    <svg className="scores-sparkline" width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-label="Score trend">
      <polyline points={poly} fill="none" stroke="currentColor" strokeWidth="2" />
    </svg>
  );
}

function normalizeAnalyses(session = {}, detail = {}) {
  const fromDetail = Array.isArray(detail?.analyses)
    ? detail.analyses
    : Array.isArray(detail?.analysis_history)
      ? detail.analysis_history
      : [];
  if (fromDetail.length > 0) return fromDetail;

  const fromSession = Array.isArray(session?.analysis_history)
    ? session.analysis_history
    : Array.isArray(session?.analyses)
      ? session.analyses
      : [];
  if (fromSession.length > 0) return fromSession;

  if (session?.result && typeof session.result === 'object') {
    return [{
      analysis_id: session?.result?.analysis_id || session?.result?.id || session?.session_id,
      created_at: session?.result?.timestamp || session?.timestamp || session?.created,
      result: session.result,
    }];
  }
  return [];
}

async function fetchWithAuth(path) {
  const token = localStorage.getItem('access_token') || localStorage.getItem('token');
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: 'include',
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });
  if (!response.ok) {
    const text = await response.text().catch(() => '');
    throw new Error(`${path} -> ${response.status} ${text}`.trim());
  }
  return response.json();
}

export default function Scores() {
  const navigate = useNavigate();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('All');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [scoreMin, setScoreMin] = useState('');
  const [scoreMax, setScoreMax] = useState('');
  const [sort, setSort] = useState({ key: 'date', dir: 'desc' });
  const [expandedRow, setExpandedRow] = useState(null);

  useEffect(() => {
    let mounted = true;
    async function load() {
      setLoading(true);
      setError('');
      try {
        const data = await fetchWithAuth('/api/ai-agent/threads');
        const sessions = Array.isArray(data?.sessions) ? data.sessions : [];
        const details = await Promise.all(
          sessions.map(async (session) => {
            const sid = session?.session_id;
            if (!sid) return null;
            try {
              return await fetchWithAuth(`/api/ai-agent/threads/${encodeURIComponent(sid)}`);
            } catch {
              return null;
            }
          })
        );

        const flat = [];
        sessions.forEach((session, idx) => {
          const detail = details[idx] || {};
          const threadId = session?.session_id || detail?.thread?.session_id;
          if (!threadId) return;

          const adoptedAnalysisId = detail?.adopted_analysis_id || session?.adopted_analysis_id || null;
          const analyses = normalizeAnalyses(session, detail);

          analyses.forEach((analysis) => {
            const analysisId = String(analysis?.analysis_id || analysis?.id || `${threadId}-result`);
            const result = analysis?.result && typeof analysis.result === 'object'
              ? analysis.result
              : (analysis && typeof analysis === 'object' ? analysis : {});
            const score = parseScore(result, session?.score);
            if (!Number.isFinite(score)) return;

            const isoDate = toIsoDate(
              analysis?.created_at ||
              analysis?.timestamp ||
              result?.timestamp ||
              session?.timestamp ||
              session?.created
            );
            const categoryLabel = result?.score_category || categoryFromScore(score);
            const projectName =
              result?.project_name ||
              result?.name ||
              result?.title ||
              result?.compat?.title ||
              session?.name ||
              `Thread ${threadId}`;
            const isAdopted = adoptedAnalysisId && String(adoptedAnalysisId) === analysisId;
            const componentScores = result?.component_scores || result?.scores || {};
            const financialImpact = result?.financial_impact || {};

            flat.push({
              id: `${threadId}:${analysisId}`,
              threadId,
              analysisId,
              projectName,
              score,
              category: categoryLabel,
              isAdopted: Boolean(isAdopted),
              adoptedLabel: isAdopted
                ? (result?.label || analysis?.label || result?.scenario_id || 'Adopted')
                : '—',
              dateIso: isoDate,
              dateMs: isoDate ? new Date(isoDate).getTime() : 0,
              componentScores,
              financialImpact,
              result,
            });
          });
        });

        if (mounted) setRows(flat);
      } catch (err) {
        if (mounted) setError(err?.message || 'Failed to load completed scores');
      } finally {
        if (mounted) setLoading(false);
      }
    }
    load();
    return () => {
      mounted = false;
    };
  }, []);

  const trendsByProject = useMemo(() => {
    const map = new Map();
    rows.forEach((row) => {
      const key = String(row.projectName || '').trim() || 'Untitled';
      if (!map.has(key)) map.set(key, []);
      map.get(key).push({ dateMs: row.dateMs, score: row.score });
    });
    map.forEach((points, key) => {
      map.set(key, points.sort((a, b) => a.dateMs - b.dateMs));
    });
    return map;
  }, [rows]);

  const filteredSortedRows = useMemo(() => {
    const q = search.trim().toLowerCase();
    const fromTs = dateFrom ? new Date(`${dateFrom}T00:00:00`).getTime() : null;
    const toTs = dateTo ? new Date(`${dateTo}T23:59:59`).getTime() : null;
    const min = scoreMin === '' ? null : Number(scoreMin);
    const max = scoreMax === '' ? null : Number(scoreMax);

    const filtered = rows.filter((row) => {
      if (q && !String(row.projectName || '').toLowerCase().includes(q)) return false;
      if (category !== 'All' && row.category !== category) return false;
      if (Number.isFinite(fromTs) && row.dateMs < fromTs) return false;
      if (Number.isFinite(toTs) && row.dateMs > toTs) return false;
      if (Number.isFinite(min) && row.score < min) return false;
      if (Number.isFinite(max) && row.score > max) return false;
      return true;
    });

    return sortRows(filtered, sort.key, sort.dir);
  }, [rows, search, category, dateFrom, dateTo, scoreMin, scoreMax, sort]);

  const projectComparison = useMemo(() => {
    const grouped = new Map();
    filteredSortedRows.forEach((row) => {
      const key = row.projectName;
      if (!grouped.has(key)) grouped.set(key, []);
      grouped.get(key).push(row.score);
    });
    return [...grouped.entries()]
      .map(([project, scores]) => ({
        project,
        count: scores.length,
        avg: Math.round(scores.reduce((sum, s) => sum + s, 0) / Math.max(1, scores.length)),
      }))
      .sort((a, b) => b.avg - a.avg);
  }, [filteredSortedRows]);

  function toggleSort(key) {
    setSort((prev) => (
      prev.key === key
        ? { key, dir: prev.dir === 'asc' ? 'desc' : 'asc' }
        : { key, dir: key === 'date' ? 'desc' : 'asc' }
    ));
  }

  function exportCsv() {
    const headers = [
      'Project Name',
      'Jaspen Score',
      'Category',
      'Adopted Scenario',
      'Analysis ID',
      'Thread ID',
      'Date',
    ];
    const lines = filteredSortedRows.map((row) => [
      row.projectName,
      row.score,
      row.category,
      row.isAdopted ? row.adoptedLabel : 'No',
      row.analysisId,
      row.threadId,
      row.dateIso || '',
    ]);
    const csv = [headers, ...lines]
      .map((line) => line.map((cell) => `"${String(cell ?? '').replace(/"/g, '""')}"`).join(','))
      .join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `jaspen-scores-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  async function exportPdf() {
    try {
      const [{ jsPDF }, { default: autoTable }] = await Promise.all([
        import('jspdf'),
        import('jspdf-autotable'),
      ]);

      const doc = new jsPDF({ orientation: 'landscape', unit: 'pt', format: 'a4' });
      const title = 'Jaspen Completed Scores';
      const exportedAt = `Exported ${new Date().toLocaleString()}`;
      const headers = [[
        'Project Name',
        'Jaspen Score',
        'Category',
        'Adopted Scenario',
        'Analysis ID',
        'Thread ID',
        'Date',
      ]];
      const body = filteredSortedRows.map((row) => [
        row.projectName,
        String(row.score ?? ''),
        row.category,
        row.isAdopted ? row.adoptedLabel : 'No',
        row.analysisId,
        row.threadId,
        row.dateIso ? toLocalDate(row.dateIso) : '',
      ]);

      doc.setFontSize(14);
      doc.text(title, 40, 34);
      doc.setFontSize(10);
      doc.text(exportedAt, 40, 52);

      autoTable(doc, {
        startY: 66,
        head: headers,
        body,
        styles: { fontSize: 8, cellPadding: 4 },
        headStyles: { fillColor: [14, 27, 63] },
        margin: { left: 32, right: 32 },
        didDrawPage: ({ pageNumber }) => {
          doc.setFontSize(9);
          doc.text(`Page ${pageNumber}`, doc.internal.pageSize.getWidth() - 70, doc.internal.pageSize.getHeight() - 14);
        },
      });

      doc.save(`jaspen-scores-${new Date().toISOString().slice(0, 10)}.pdf`);
    } catch (err) {
      setError(err?.message || 'Failed to export PDF');
    }
  }

  return (
    <div className="scores-page">
      <div className="scores-topbar">
        <button type="button" className="scores-btn ghost" onClick={() => navigate('/new')}>
          Back to Jaspen
        </button>
      </div>
      <div className="scores-header">
        <div>
          <h1>Completed Scores</h1>
          <p>All completed analyses with history, adopted scenarios, and trends.</p>
        </div>
        <div className="scores-header-actions">
          <button type="button" className="scores-btn" onClick={exportPdf} disabled={filteredSortedRows.length === 0}>
            Export PDF
          </button>
          <button type="button" className="scores-btn" onClick={exportCsv} disabled={filteredSortedRows.length === 0}>
            Export CSV
          </button>
        </div>
      </div>

      <div className="scores-filters">
        <input
          type="text"
          placeholder="Search project name"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select value={category} onChange={(e) => setCategory(e.target.value)}>
          {CATEGORY_OPTIONS.map((opt) => (
            <option key={opt} value={opt}>{opt}</option>
          ))}
        </select>
        <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
        <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        <input
          type="number"
          min="0"
          max="100"
          placeholder="Min score"
          value={scoreMin}
          onChange={(e) => setScoreMin(e.target.value)}
        />
        <input
          type="number"
          min="0"
          max="100"
          placeholder="Max score"
          value={scoreMax}
          onChange={(e) => setScoreMax(e.target.value)}
        />
      </div>

      {projectComparison.length > 1 && (
        <div className="scores-compare">
          <h2>Project Comparison</h2>
          <div className="scores-compare-list">
            {projectComparison.slice(0, 6).map((item) => (
              <div key={item.project} className="scores-compare-item">
                <span className="scores-compare-name">{item.project}</span>
                <span className="scores-compare-meta">Avg {item.avg} ({item.count})</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {loading && <div className="scores-state">Loading completed analyses…</div>}
      {!loading && error && <div className="scores-state error">{error}</div>}
      {!loading && !error && filteredSortedRows.length === 0 && (
        <div className="scores-state">No completed analyses match your filters.</div>
      )}

      {!loading && !error && filteredSortedRows.length > 0 && (
        <div className="scores-table-wrap">
          <table className="scores-table">
            <thead>
              <tr>
                <th onClick={() => toggleSort('project')}>Project Name</th>
                <th onClick={() => toggleSort('score')}>Jaspen Score</th>
                <th onClick={() => toggleSort('category')}>Category</th>
                <th onClick={() => toggleSort('adopted')}>Adopted Scenario</th>
                <th>Trend</th>
                <th onClick={() => toggleSort('date')}>Date</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredSortedRows.map((row) => {
                const expanded = expandedRow === row.id;
                return (
                  <React.Fragment key={row.id}>
                    <tr>
                      <td>{row.projectName}</td>
                      <td>{row.score}</td>
                      <td>{row.category}</td>
                      <td>{row.isAdopted ? row.adoptedLabel : 'No'}</td>
                      <td><Sparkline points={trendsByProject.get(row.projectName) || []} /></td>
                      <td>{toLocalDate(row.dateIso)}</td>
                      <td>
                        <div className="scores-actions">
                          <button
                            type="button"
                            className="scores-btn small ghost"
                            onClick={() => navigate(`/sessions?view=review&session_id=${encodeURIComponent(row.threadId)}`)}
                          >
                            Open
                          </button>
                          <button
                            type="button"
                            className="scores-btn small"
                            onClick={() => setExpandedRow(expanded ? null : row.id)}
                          >
                            {expanded ? 'Hide' : 'Expand'}
                          </button>
                        </div>
                      </td>
                    </tr>
                    {expanded && (
                      <tr className="scores-expanded">
                        <td colSpan={7}>
                          <div className="scores-expanded-grid">
                            <div>
                              <h4>Adopted Scenario Details</h4>
                              <p><strong>Analysis ID:</strong> {row.analysisId}</p>
                              <p><strong>Thread ID:</strong> {row.threadId}</p>
                              <p><strong>Adopted:</strong> {row.isAdopted ? row.adoptedLabel : 'No'}</p>
                            </div>
                            <div>
                              <h4>Component Scores</h4>
                              {Object.keys(row.componentScores || {}).length === 0 ? (
                                <p>None available</p>
                              ) : (
                                <ul>
                                  {Object.entries(row.componentScores).map(([k, v]) => (
                                    <li key={k}>{k}: {String(v)}</li>
                                  ))}
                                </ul>
                              )}
                            </div>
                            <div>
                              <h4>Financial Impact</h4>
                              {Object.keys(row.financialImpact || {}).length === 0 ? (
                                <p>None available</p>
                              ) : (
                                <ul>
                                  {Object.entries(row.financialImpact).map(([k, v]) => (
                                    <li key={k}>{k}: {String(v)}</li>
                                  ))}
                                </ul>
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
    </div>
  );
}
