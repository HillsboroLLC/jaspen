import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faArrowTrendUp,
  faBug,
  faCircleExclamation,
  faCloudArrowUp,
  faLightbulb,
  faSpinner,
} from '@fortawesome/free-solid-svg-icons';
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
import { Jaspen } from '../Workspace/JaspenClient';
import ConfirmDialog from '../../shared/components/ConfirmDialog';
import SkeletonBlock from '../../shared/components/SkeletonLoader';
import EmptyState from '../../homeSections/homeUi/EmptyState';
import { API_BASE } from '../../config/apiBase';
import { buildAuthHeaders } from '../../shared/auth/http';
import './Insights.css';
import AppMenu from '../shared/AppMenu';
import JaspenAiDrawer from '../Workspace/JaspenAiDrawer';

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

function formatDate(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function formatMonth(value) {
  const match = /^(\d{4})-(\d{2})$/.exec(String(value || ''));
  if (!match) return String(value || '');
  const date = new Date(Number(match[1]), Number(match[2]) - 1, 1);
  return date.toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
}

function safeList(value) {
  return Array.isArray(value) ? value : [];
}

function projectHref(threadId) {
  return `/new?session_id=${encodeURIComponent(String(threadId || ''))}`;
}

function updatedLabel(updatedAt, now) {
  if (!updatedAt) return '';
  const minutes = Math.max(0, Math.floor((now - updatedAt) / 60000));
  if (minutes === 0) return 'Updated just now';
  return `Updated ${minutes} min ago`;
}

export function DecisionIntelligenceOverview({ navigate }) {
  const storageKey = 'jaspen:decision-dashboard:v1';
  const saved = useMemo(() => {
    try { return JSON.parse(window.localStorage.getItem(storageKey) || '{}'); } catch (_) { return {}; }
  }, []);
  const emptyFilters = {
    range: 'all', statuses: [], typeKit: '', member: '', tag: '', search: '', quick: '', gap: '',
  };
  const [scope, setScope] = useState(saved.scope === 'mine' ? 'mine' : 'organization');
  const [filters, setFilters] = useState({ ...emptyFilters, ...(saved.filters || {}) });
  const [overview, setOverview] = useState(null);
  const [overviewLoading, setOverviewLoading] = useState(true);
  const [overviewError, setOverviewError] = useState('');
  const [lastUpdatedAt, setLastUpdatedAt] = useState(null);
  const [relativeTimeNow, setRelativeTimeNow] = useState(() => Date.now());
  const [reloadKey, setReloadKey] = useState(0);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [sort, setSort] = useState({ key: 'created_at', direction: 'desc' });
  const [page, setPage] = useState(1);
  const [expanded, setExpanded] = useState('');
  const requestGeneration = useRef(0);

  useEffect(() => {
    const generation = ++requestGeneration.current;
    let active = true;
    let inFlight = false;
    let refreshTimer = null;
    let abortController = null;

    const stopTimer = () => {
      if (refreshTimer) window.clearInterval(refreshTimer);
      refreshTimer = null;
    };
    const load = async ({ initial = false } = {}) => {
      if (inFlight) return;
      inFlight = true;
      if (initial) {
        setOverviewLoading(true);
        setOverviewError('');
      }
      abortController = new AbortController();
      try {
        const response = await fetch(`${API_BASE}/api/v1/insights/overview?scope=${encodeURIComponent(scope)}`, {
          method: 'GET', headers: buildAuthHeaders({}, 'GET'), credentials: 'include', signal: abortController.signal,
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload?.error || 'Unable to load decision insights.');
        if (active && requestGeneration.current === generation) {
          const completedAt = Date.now();
          setOverview(payload);
          setOverviewError('');
          setLastUpdatedAt(completedAt);
          setRelativeTimeNow(completedAt);
          if (payload?.scope && payload.scope !== scope) setScope(payload.scope);
        }
      } catch (err) {
        if (active && requestGeneration.current === generation && initial && err?.name !== 'AbortError') {
          setOverviewError(err?.message || 'Unable to load decision insights.');
        }
      } finally {
        if (active && requestGeneration.current === generation) {
          inFlight = false;
          setRelativeTimeNow(Date.now());
          if (initial) setOverviewLoading(false);
        }
      }
    };

    const startTimer = () => {
      stopTimer();
      if (document.visibilityState === 'visible') {
        refreshTimer = window.setInterval(() => load(), 60000);
      }
    };
    const refreshWhenVisible = () => {
      if (document.visibilityState !== 'visible') return;
      load();
      startTimer();
    };
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') refreshWhenVisible();
      else stopTimer();
    };

    load({ initial: true });
    startTimer();
    document.addEventListener('visibilitychange', handleVisibilityChange);
    window.addEventListener('focus', refreshWhenVisible);
    return () => {
      active = false;
      requestGeneration.current += 1;
      stopTimer();
      abortController?.abort();
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      window.removeEventListener('focus', refreshWhenVisible);
    };
  }, [scope, reloadKey]);

  useEffect(() => {
    try { window.localStorage.setItem(storageKey, JSON.stringify({ scope, filters })); } catch (_) { /* convenience only */ }
  }, [scope, filters]);

  const rows = safeList(overview?.rows);
  const setFilter = (key, value) => {
    setFilters((current) => ({ ...current, [key]: value }));
    setPage(1);
  };
  const dateFloor = useMemo(() => {
    const now = new Date();
    if (filters.range === '30') return new Date(now.getTime() - (30 * 86400000));
    if (filters.range === '90') return new Date(now.getTime() - (90 * 86400000));
    if (filters.range === 'year') return new Date(now.getFullYear(), 0, 1);
    return null;
  }, [filters.range]);
  const filteredRows = useMemo(() => rows.filter((row) => {
    const created = row.created_at ? new Date(row.created_at) : null;
    if (dateFloor && (!created || created < dateFloor)) return false;
    if (filters.statuses.length && !filters.statuses.includes(row.status)) return false;
    if (filters.typeKit && row.decision_type !== filters.typeKit && row.decision_kit !== filters.typeKit) return false;
    if (filters.member && row.owner?.id !== filters.member) return false;
    if (filters.tag && !safeList(row.tags).includes(filters.tag)) return false;
    const haystack = [row.title, row.owner?.name, ...safeList(row.chosen_options), ...safeList(row.tags)].join(' ').toLowerCase();
    if (filters.search && !haystack.includes(filters.search.trim().toLowerCase())) return false;
    if (filters.quick === 'decided' && !['decided', 'outcome_recorded'].includes(row.status)) return false;
    if (filters.quick === 'open' && !['in_analysis', 'recorded'].includes(row.status)) return false;
    if (filters.quick === 'attention' && !Number(row.gaps?.failed_gates)) return false;
    if (filters.quick === 'plans' && !(Number(row.plan?.tasks_total) > Number(row.plan?.tasks_completed))) return false;
    if (filters.quick === 'learning' && !(Number(row.lesson_count) + Number(row.outcome_count))) return false;
    if (filters.quick === 'timed' && row.days_to_decide == null) return false;
    if (filters.gap && !Number(row.gaps?.[filters.gap])) return false;
    return true;
  }), [rows, dateFloor, filters]);

  const decidedRows = filteredRows.filter((row) => ['decided', 'outcome_recorded'].includes(row.status));
  const openRows = filteredRows.filter((row) => ['in_analysis', 'recorded'].includes(row.status));
  const attentionRows = filteredRows.filter((row) => Number(row.gaps?.failed_gates));
  const planRows = filteredRows.filter((row) => Number(row.plan?.tasks_total) > Number(row.plan?.tasks_completed));
  const planTasks = planRows.reduce((sum, row) => sum + Number(row.plan?.tasks_total || 0), 0);
  const completedTasks = planRows.reduce((sum, row) => sum + Number(row.plan?.tasks_completed || 0), 0);
  const learningCount = filteredRows.reduce((sum, row) => sum + Number(row.lesson_count || 0) + Number(row.outcome_count || 0), 0);
  const decisionDays = filteredRows.map((row) => row.days_to_decide).filter((value) => value != null).sort((a, b) => a - b);
  const medianDays = decisionDays.length ? (decisionDays.length % 2
    ? decisionDays[(decisionDays.length - 1) / 2]
    : Math.round((decisionDays[(decisionDays.length / 2) - 1] + decisionDays[decisionDays.length / 2]) / 2)) : null;

  const statusLabels = [...new Set(filteredRows.map((row) => row.status))].sort();
  const statusColors = ['#1B2342', '#A0036C', '#2E7D72', '#B56A12', '#6A5A8C', '#68728F'];
  const statusChart = {
    labels: statusLabels,
    datasets: [{ data: statusLabels.map((status) => filteredRows.filter((row) => row.status === status).length), backgroundColor: statusLabels.map((_, index) => statusColors[index % statusColors.length]) }],
  };
  const typeLabels = [...new Set(filteredRows.flatMap((row) => [row.decision_kit || row.decision_type].filter(Boolean)))].sort();
  const typeChart = { labels: typeLabels, datasets: [{ label: 'Decisions', data: typeLabels.map((label) => filteredRows.filter((row) => (row.decision_kit || row.decision_type) === label).length), backgroundColor: '#A0036C' }] };
  const gapDefinitions = [
    ['failed_gates', 'Failed gates'], ['open_assumptions', 'Assumptions'], ['missing_evidence', 'Missing evidence'],
  ];
  const gapLabels = [];
  const gapKinds = [];
  const gapCounts = {};
  filteredRows.forEach((row) => gapDefinitions.forEach(([key, label]) => {
    safeList(row.gaps?.items?.[key]).forEach((item) => {
      const name = item.label || label;
      const identity = `${key}:${name}`;
      gapCounts[identity] = (gapCounts[identity] || 0) + 1;
    });
  }));
  Object.entries(gapCounts).sort((a, b) => b[1] - a[1]).slice(0, 8).forEach(([identity]) => {
    const split = identity.indexOf(':'); gapKinds.push(identity.slice(0, split)); gapLabels.push(identity.slice(split + 1));
  });
  const gapChart = { labels: gapLabels, datasets: [{ label: 'Records', data: gapLabels.map((_, index) => gapCounts[`${gapKinds[index]}:${gapLabels[index]}`]), backgroundColor: '#B56A12' }] };

  const bucketRows = {};
  const weekly = ['30', '90'].includes(filters.range);
  filteredRows.forEach((row) => {
    const date = row.created_at ? new Date(row.created_at) : null;
    if (!date || Number.isNaN(date.getTime())) return;
    if (weekly) date.setDate(date.getDate() - date.getDay());
    const key = weekly ? date.toISOString().slice(0, 10) : date.toISOString().slice(0, 7);
    bucketRows[key] = bucketRows[key] || {};
    bucketRows[key][row.status] = (bucketRows[key][row.status] || 0) + 1;
  });
  const timeLabels = Object.keys(bucketRows).sort();
  const timeChart = { labels: timeLabels.map((label) => weekly ? formatDate(label) : formatMonth(label)), datasets: statusLabels.map((status, index) => ({ label: status, data: timeLabels.map((label) => bucketRows[label][status] || 0), backgroundColor: statusColors[index % statusColors.length] })) };
  const memberLabels = safeList(overview?.facets?.members).filter((member) => filteredRows.some((row) => row.owner?.id === member.id));
  const memberChart = { labels: memberLabels.map((member) => member.name), datasets: [{ label: 'Decisions', data: memberLabels.map((member) => filteredRows.filter((row) => row.owner?.id === member.id).length), backgroundColor: '#2E7D72' }] };
  const rootStyles = getComputedStyle(document.documentElement);
  const chartText = rootStyles.getPropertyValue('--color-text-secondary').trim() || '#5B6280';
  const chartGrid = rootStyles.getPropertyValue('--color-border-default').trim() || '#E4E6EE';
  const chartSurface = rootStyles.getPropertyValue('--color-surface-default').trim() || '#FFFFFF';
  const chartInk = rootStyles.getPropertyValue('--color-text-primary').trim() || '#1B2342';
  const chartBase = { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom', labels: { color: chartText } }, tooltip: { backgroundColor: chartSurface, bodyColor: chartInk, titleColor: chartInk, borderColor: chartGrid, borderWidth: 1 } } };
  const axis = { ticks: { color: chartText, precision: 0 }, grid: { color: chartGrid } };
  const stackedOptions = { ...chartBase, onClick: (_, elements) => elements[0] && setFilter('statuses', [statusLabels[elements[0].datasetIndex]]), scales: { x: { ...axis, stacked: true }, y: { ...axis, stacked: true, beginAtZero: true } } };
  const barOptions = { ...chartBase, scales: { x: axis, y: { ...axis, beginAtZero: true } } };

  const sortValue = (row, key) => {
    if (key === 'owner') return row.owner?.name || '';
    if (key === 'chosen') return safeList(row.chosen_options).join(', ');
    if (key === 'score') return row.top_option_score ?? -1;
    if (key === 'gaps') return Number(row.gaps?.failed_gates || 0) + Number(row.gaps?.not_assessed_gates || 0) + Number(row.gaps?.open_assumptions || 0) + Number(row.gaps?.missing_evidence || 0);
    return row[key] ?? '';
  };
  const sortedRows = [...filteredRows].sort((a, b) => {
    const left = sortValue(a, sort.key); const right = sortValue(b, sort.key);
    return (typeof left === 'number' ? left - right : String(left).localeCompare(String(right))) * (sort.direction === 'asc' ? 1 : -1);
  });
  const pageCount = Math.max(1, Math.ceil(sortedRows.length / 25));
  const tableRows = sortedRows.slice((page - 1) * 25, page * 25);
  const toggleSort = (key) => setSort((current) => ({ key, direction: current.key === key && current.direction === 'asc' ? 'desc' : 'asc' }));
  const clearFilters = () => { setFilters(emptyFilters); setPage(1); };
  const chips = [
    filters.range !== 'all' && ['range', { 30: 'Last 30 days', 90: 'Last 90 days', year: 'This year' }[filters.range]],
    ...filters.statuses.map((value) => ['status', value]), filters.typeKit && ['typeKit', filters.typeKit],
    filters.member && ['member', safeList(overview?.facets?.members).find((item) => item.id === filters.member)?.name],
    filters.tag && ['tag', filters.tag], filters.search && ['search', `Search: ${filters.search}`],
    filters.quick && ['quick', { decided: 'Decided', open: 'Open', attention: 'Needs attention', plans: 'Plans in execution', learning: 'Lessons and outcomes recorded', timed: 'Has decision timing' }[filters.quick]],
    filters.gap && ['gap', gapDefinitions.find(([key]) => key === filters.gap)?.[1]],
  ].filter(Boolean);
  const removeChip = (key, value) => {
    if (key === 'status') setFilter('statuses', filters.statuses.filter((item) => item !== value));
    else setFilter(key, key === 'range' ? 'all' : '');
  };
  const hasRecords = rows.length > 0;

  return (
    <section className="di-overview" aria-labelledby="di-overview-title">
      <div className="di-masthead">
        <div>
          <p className="di-kicker">{overview?.calculation_label || 'Calculated insights'}</p>
          <h2 id="di-overview-title">Decision dashboard</h2>
        </div>
        {overview?.can_view_organization && (
          <div className="di-scope-switch" role="group" aria-label="Decision insight scope">
            <button type="button" className={scope === 'organization' ? 'is-active' : ''} aria-pressed={scope === 'organization'} onClick={() => setScope('organization')}>Organization</button>
            <button type="button" className={scope === 'mine' ? 'is-active' : ''} aria-pressed={scope === 'mine'} onClick={() => setScope('mine')}>My activity</button>
          </div>
        )}
      </div>

      {overviewLoading && <div className="di-state" role="status">Loading your decision dashboard…</div>}
      {!overviewLoading && overviewError && (
        <div className="di-state di-state-error" role="alert">
          <p>{overviewError}</p>
          <button type="button" className="int-btn int-btn-ghost" onClick={() => setReloadKey((value) => value + 1)}>Try again</button>
        </div>
      )}
      {!overviewLoading && !overviewError && !hasRecords && (
        <div className="di-empty">
          <h3>No decision records yet</h3>
          <p>Your decisions, open questions, outcomes, and lessons will appear here as they are recorded.</p>
          <div className="di-actions">
            <button type="button" className="int-btn int-btn-primary" onClick={() => navigate('/new')}>Start a decision</button>
          </div>
        </div>
      )}
      {!overviewLoading && !overviewError && hasRecords && (
        <>
          <div className="di-filter-shell">
            <button type="button" className="di-filter-toggle" aria-expanded={filtersOpen} onClick={() => setFiltersOpen((value) => !value)}>Filters {chips.length ? `(${chips.length})` : ''}</button>
            <div className={`di-filters ${filtersOpen ? 'is-open' : ''}`}>
              <label>Date range<select aria-label="Date range" value={filters.range} onChange={(event) => setFilter('range', event.target.value)}><option value="30">Last 30 days</option><option value="90">Last 90 days</option><option value="year">This year</option><option value="all">All time</option></select></label>
              <label>Status<select aria-label="Status" multiple value={filters.statuses} onChange={(event) => setFilter('statuses', [...event.target.selectedOptions].map((option) => option.value))}>{safeList(overview?.facets?.statuses).map((value) => <option key={value}>{value}</option>)}</select></label>
              {safeList(overview?.facets?.types_kits).length > 0 && <label>Type / kit<select aria-label="Decision type or kit" value={filters.typeKit} onChange={(event) => setFilter('typeKit', event.target.value)}><option value="">All</option>{overview.facets.types_kits.map((value) => <option key={value}>{value}</option>)}</select></label>}
              {scope === 'organization' && <label>Member<select aria-label="Member" value={filters.member} onChange={(event) => setFilter('member', event.target.value)}><option value="">All</option>{safeList(overview?.facets?.members).map((member) => <option key={member.id} value={member.id}>{member.name}</option>)}</select></label>}
              {safeList(overview?.facets?.tags).length > 0 && <label>Tag<select aria-label="Tag" value={filters.tag} onChange={(event) => setFilter('tag', event.target.value)}><option value="">All</option>{overview.facets.tags.map((value) => <option key={value}>{value}</option>)}</select></label>}
              <label className="di-search">Search<input type="search" aria-label="Search decisions" value={filters.search} onChange={(event) => setFilter('search', event.target.value)} placeholder="Decision, option, owner…" /></label>
              <button type="button" className="di-clear" onClick={clearFilters}>Clear filters</button>
            </div>
            <p className="di-updated" aria-live="polite">{updatedLabel(lastUpdatedAt, relativeTimeNow)}</p>
            {chips.length > 0 && <div className="di-chips" aria-label="Active filters">{chips.map(([key, label], index) => <button type="button" key={`${key}:${label}:${index}`} onClick={() => removeChip(key, key === 'status' ? label : '')}>{label} <span aria-hidden="true">×</span><span className="sr-only">Remove filter</span></button>)}</div>}
          </div>

          <div className="di-kpis" aria-label="Dashboard metrics">
            {[
              ['decisions', 'Decisions', filteredRows.length, ''], ['decided', 'Decided', decidedRows.length, 'decided'], ['open', 'Open', openRows.length, 'open'],
              ['attention', 'Needs attention', attentionRows.length, 'attention'], ['median', 'Median days to decide', medianDays ?? '—', 'timed'],
              ['plans', 'Plans in execution', `${planRows.length}${planTasks ? ` · ${Math.round((completedTasks / planTasks) * 100)}%` : ''}`, 'plans'],
              ['learning', 'Lessons and outcomes recorded', learningCount, 'learning'],
            ].map(([id, label, value, quick]) => <button type="button" key={id} className={filters.quick === quick && quick ? 'is-active' : ''} onClick={() => (id === 'decisions' ? clearFilters() : setFilter('quick', filters.quick === quick ? '' : quick))}><span>{label}</span><strong>{value}</strong></button>)}
          </div>

          {filteredRows.length === 0 ? <div className="di-empty di-filtered-empty"><h3>No decisions match these filters</h3><p>Clear or remove a filter to bring your decision history back into view.</p><button type="button" className="int-btn int-btn-primary" onClick={clearFilters}>Clear filters</button></div> : <>
            <div className="di-dashboard-grid">
              <section className="di-card di-card-wide"><h3>Decisions over time</h3><div className="di-chart-canvas"><Bar data={timeChart} options={stackedOptions} /></div><p className="sr-only">{timeLabels.map((label) => `${label}: ${Object.values(bucketRows[label]).reduce((a, b) => a + b, 0)}`).join('; ')}</p></section>
              <section className="di-card"><h3>Status mix</h3><div className="di-chart-canvas"><Pie data={statusChart} options={{ ...chartBase, onClick: (_, elements) => elements[0] && setFilter('statuses', [statusLabels[elements[0].index]]) }} /></div><p className="sr-only">{statusLabels.map((label, index) => `${label}: ${statusChart.datasets[0].data[index]}`).join('; ')}</p></section>
              {typeLabels.length > 0 && <section className="di-card"><h3>By decision type / kit</h3><div className="di-chart-canvas"><Bar data={typeChart} options={{ ...barOptions, onClick: (_, elements) => elements[0] && setFilter('typeKit', typeLabels[elements[0].index]) }} /></div><p className="sr-only">{typeLabels.map((label, index) => `${label}: ${typeChart.datasets[0].data[index]}`).join('; ')}</p></section>}
              {gapLabels.length > 0 && <section className="di-card"><h3>Most common gaps</h3><div className="di-chart-canvas"><Bar data={gapChart} options={{ ...barOptions, indexAxis: 'y', onClick: (_, elements) => elements[0] && setFilter('gap', gapKinds[elements[0].index]) }} /></div><p className="sr-only">{gapLabels.map((label, index) => `${label}: ${gapChart.datasets[0].data[index]}`).join('; ')}</p></section>}
              {scope === 'organization' && memberLabels.length > 0 && <section className="di-card"><h3>Activity by member</h3><div className="di-chart-canvas"><Bar data={memberChart} options={{ ...barOptions, onClick: (_, elements) => elements[0] && setFilter('member', memberLabels[elements[0].index].id) }} /></div><p className="sr-only">{memberLabels.map((member, index) => `${member.name}: ${memberChart.datasets[0].data[index]}`).join('; ')}</p></section>}
            </div>

            <section className="di-table-card" aria-labelledby="di-table-title"><div className="di-table-head"><div><p className="di-kicker">Current records</p><h3 id="di-table-title">Decisions</h3></div><span>{filteredRows.length} result{filteredRows.length === 1 ? '' : 's'}</span></div><div className="di-table-wrap"><table><thead><tr>{[
              ['title', 'Decision'], ...(scope === 'organization' ? [['owner', 'Owner']] : []), ['status', 'Status'], ['chosen', 'Chosen option'], ['score', 'Score'], ['gaps', 'Gaps'], ['created_at', 'Created'], ['decided_at', 'Decided'],
            ].map(([key, label]) => <th key={key}><button type="button" onClick={() => toggleSort(key)}>{label}{sort.key === key ? (sort.direction === 'asc' ? ' ↑' : ' ↓') : ''}</button></th>)}</tr></thead><tbody>{tableRows.map((row) => <React.Fragment key={row.id}><tr><td><button type="button" className="di-expand" aria-expanded={expanded === row.id} onClick={() => setExpanded(expanded === row.id ? '' : row.id)}>{row.title}</button></td>{scope === 'organization' && <td>{row.owner?.name || '—'}</td>}<td>{row.status}</td><td>{safeList(row.chosen_options).join(', ') || '—'}</td><td>{row.top_option_score ?? '—'}</td><td>{Number(row.gaps?.failed_gates || 0) + Number(row.gaps?.not_assessed_gates || 0) + Number(row.gaps?.open_assumptions || 0) + Number(row.gaps?.missing_evidence || 0)}</td><td>{formatDate(row.created_at)}</td><td>{formatDate(row.decided_at)}</td></tr>{expanded === row.id && <tr className="di-detail-row"><td colSpan={scope === 'organization' ? 8 : 7}><div><h4>Top gaps</h4><ul>{[['failed_gates', 'Failed gates'], ['not_assessed_gates', 'Not yet assessed'], ['open_assumptions', 'Assumptions'], ['missing_evidence', 'Missing evidence']].flatMap(([key, label]) => safeList(row.gaps?.items?.[key]).slice(0, 3).map((item, index) => <li key={`${key}:${index}`}><strong>{label}:</strong> {item.label}</li>))}{!Object.values(row.gaps?.items || {}).some((items) => safeList(items).length) && <li>No open gaps recorded.</li>}</ul></div><div><h4>Lessons and outcomes</h4><ul>{[...safeList(row.lessons), ...safeList(row.outcomes)].slice(0, 6).map((item, index) => <li key={index}>{item.text}</li>)}{!(row.lesson_count + row.outcome_count) && <li>Nothing recorded yet.</li>}</ul></div><a href={projectHref(row.thread_id)}>Open project →</a></td></tr>}</React.Fragment>)}</tbody></table></div><div className="di-pagination"><button type="button" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>Previous</button><span>Page {page} of {pageCount}</span><button type="button" disabled={page >= pageCount} onClick={() => setPage((value) => value + 1)}>Next</button></div></section>
          </>}
        </>
      )}
    </section>
  );
}

function normalizeChartPayload(chart = {}) {
  const labels = safeList(chart?.data?.labels).map((item) => String(item ?? ''));
  const values = safeList(chart?.data?.values).map((value) => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  });
  return { labels, values };
}

function chartDataFor(chart = {}, idx = 0) {
  const { labels, values } = normalizeChartPayload(chart);
  const palette = [
    '#3451b2',
    '#5f76cc',
    '#7d92da',
    '#9bafe9',
    '#b7c8f2',
    '#d3e0f9',
  ];
  const barColor = palette[idx % palette.length];
  return {
    labels,
    datasets: [
      {
        label: chart?.title || 'Series',
        data: values,
        backgroundColor: chart?.type === 'pie' ? labels.map((_, i) => palette[i % palette.length]) : barColor,
        borderColor: barColor,
        borderWidth: 1.5,
        tension: 0.25,
        fill: false,
      },
    ],
  };
}

export default function Insights() {
  const navigate = useNavigate();
  const fileInputRef = useRef(null);
  const [datasets, setDatasets] = useState([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [deletingDatasetId, setDeletingDatasetId] = useState('');
  const [error, setError] = useState('');
  const [question, setQuestion] = useState('');
  const [analysis, setAnalysis] = useState(null);
  const [activeDatasetId, setActiveDatasetId] = useState('');
  const [themeVersion, setThemeVersion] = useState(0);
  const [confirmDialog, setConfirmDialog] = useState(null);
  const [connectors, setConnectors] = useState([]);
  const [activeConnectorId, setActiveConnectorIdForIdeas] = useState('');
  const [ideasFocus, setIdeasFocus] = useState('');
  const [ideasObjective, setIdeasObjective] = useState('balanced');
  const [generatingIdeas, setGeneratingIdeas] = useState(false);
  const [generatedIdeas, setGeneratedIdeas] = useState([]);
  const [ideasError, setIdeasError] = useState('');
  const [isEnterprise, setIsEnterprise] = useState(false);
  const [queryConnectorId, setQueryConnectorId] = useState('');
  const [queryTable, setQueryTable] = useState('');
  const [queryLimit, setQueryLimit] = useState(50);
  const [queryBusy, setQueryBusy] = useState(false);
  const [queryError, setQueryError] = useState('');
  const [queryResult, setQueryResult] = useState(null);
  const [jaspenOpen, setJaspenOpen] = useState(false);
  const [assistantInput, setAssistantInput] = useState('');
  const [assistantMessages, setAssistantMessages] = useState([
    {
      role: 'assistant',
      text: 'I can interpret these insights and suggest what to score next.',
    },
  ]);
  const [assistantBusy, setAssistantBusy] = useState(false);
  const [assistantSessionId, setAssistantSessionId] = useState(null);
  const assistantAbortRef = useRef(null);

  useEffect(() => {
    const root = document.documentElement;
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const bump = () => setThemeVersion((prev) => prev + 1);
    const observer = new MutationObserver(bump);
    observer.observe(root, { attributes: true, attributeFilter: ['data-theme'] });
    if (typeof media.addEventListener === 'function') media.addEventListener('change', bump);
    else media.addListener(bump);
    return () => {
      observer.disconnect();
      if (typeof media.removeEventListener === 'function') media.removeEventListener('change', bump);
      else media.removeListener(bump);
    };
  }, []);

  const chartOptions = (() => {
    const styles = getComputedStyle(document.documentElement);
    const textColor = styles.getPropertyValue('--color-text-secondary').trim() || '#475569';
    const gridColor = styles.getPropertyValue('--color-border-default').trim() || '#dbe3ee';
    const tooltipBg = styles.getPropertyValue('--color-surface-default').trim() || '#ffffff';
    const tooltipText = styles.getPropertyValue('--color-text-primary').trim() || '#161f3b';
    return {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: {
          ticks: { color: textColor },
          grid: { color: gridColor },
        },
        y: {
          ticks: { color: textColor },
          grid: { color: gridColor },
        },
      },
      plugins: {
        legend: {
          display: true,
          position: 'bottom',
          labels: { color: textColor },
        },
        tooltip: {
          backgroundColor: tooltipBg,
          titleColor: tooltipText,
          bodyColor: tooltipText,
          borderColor: gridColor,
          borderWidth: 1,
        },
      },
    };
  })();

  const loadDatasets = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await Jaspen.listInsightsDatasets();
      setDatasets(safeList(res?.datasets));
    } catch (err) {
      setError(err?.message || 'Failed to load datasets');
      setDatasets([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadDatasets();
  }, [loadDatasets]);

  useEffect(() => {
    const loadConnectors = async () => {
      try {
        const headers = buildAuthHeaders({}, 'GET');
        const response = await fetch(`${API_BASE}/api/v1/connectors/status`, {
          method: 'GET',
          headers,
          credentials: 'include',
        });
        if (!response.ok) return;
        const data = await response.json().catch(() => ({}));
        const ideaConnectors = (Array.isArray(data?.connectors) ? data.connectors : []).filter((item) => (
          item?.connected
          && ['salesforce_insights', 'snowflake_insights', 'servicenow_insights', 'netsuite_insights', 'oracle_fusion_insights'].includes(item.id)
        ));
        setConnectors(ideaConnectors);
        // All plans (free and above) can use connector-powered features
        const isEnt = ['free', 'starter', 'essential', 'team', 'business'].includes(data?.plan_key);
        setIsEnterprise(Boolean(isEnt));
        if (ideaConnectors.length > 0) {
          setActiveConnectorIdForIdeas(String(ideaConnectors[0].id));
          const queryable = ideaConnectors.find((item) => ['snowflake_insights', 'salesforce_insights'].includes(item.id));
          if (queryable?.id) setQueryConnectorId(String(queryable.id));
        }
      } catch {}
    };
    loadConnectors();
  }, []);

  const activeDataset = useMemo(
    () => datasets.find((row) => String(row?.id || '') === String(activeDatasetId || '')) || null,
    [datasets, activeDatasetId]
  );

  const onUpload = useCallback(async (file) => {
    if (!file) return;
    setUploading(true);
    setError('');
    try {
      const res = await Jaspen.uploadInsightsDataset(file);
      await loadDatasets();
      if (res?.dataset_id) setActiveDatasetId(String(res.dataset_id));
    } catch (err) {
      setError(err?.message || 'Upload failed');
    } finally {
      setUploading(false);
    }
  }, [loadDatasets]);

  const onDrop = useCallback((event) => {
    event.preventDefault();
    const file = event.dataTransfer?.files?.[0];
    if (file) onUpload(file);
  }, [onUpload]);

  const onAnalyze = useCallback(async (datasetId) => {
    const id = String(datasetId || '').trim();
    if (!id) return;
    setAnalyzing(true);
    setError('');
    setActiveDatasetId(id);
    try {
      const res = await Jaspen.analyzeInsightsDataset({ dataset_id: id, question });
      setAnalysis(res || null);
    } catch (err) {
      setError(err?.message || 'Analysis failed');
      setAnalysis(null);
    } finally {
      setAnalyzing(false);
    }
  }, [question]);

  const onDeleteDataset = useCallback(async (datasetId) => {
    const id = String(datasetId || '').trim();
    if (!id) return;
    const target = datasets.find((row) => String(row?.id || '') === id);
    const targetName = target?.filename || 'this dataset';
    setConfirmDialog({
      title: 'Delete dataset',
      message: `Delete ${targetName}? This cannot be undone.`,
      confirmLabel: 'Delete dataset',
      confirmVariant: 'danger',
      onConfirm: async () => {
        setConfirmDialog(null);
        setDeletingDatasetId(id);
        setError('');
        try {
          await Jaspen.deleteInsightsDataset(id);
          if (String(activeDatasetId || '') === id) {
            setActiveDatasetId('');
            setAnalysis(null);
          }
          await loadDatasets();
        } catch (err) {
          setError(err?.message || 'Delete failed');
        } finally {
          setDeletingDatasetId('');
        }
      },
    });
  }, [activeDatasetId, datasets, loadDatasets]);

  const buildOpportunityStatement = useCallback((analysisResult, dataset) => {
    const filename = dataset?.filename ? `"${dataset.filename}"` : 'the uploaded dataset';
    const summary = String(analysisResult?.summary || '').trim();
    const topOpportunity = Array.isArray(analysisResult?.opportunities) ? analysisResult.opportunities[0] : '';
    const topRisk = Array.isArray(analysisResult?.risks) ? analysisResult.risks[0] : '';
    const parts = [`I've analyzed ${filename} and found the following insights.`];
    if (summary) parts.push(summary);
    if (topOpportunity) parts.push(`Top opportunity: ${topOpportunity}`);
    if (topRisk) parts.push(`Key risk to address: ${topRisk}`);
    parts.push('I would like to score this opportunity.');
    return parts.join(' ');
  }, []);

  const buildInsightsContextStatement = useCallback((analysisResult, dataset) => {
    const filename = dataset?.filename ? `"${dataset.filename}"` : 'the current dataset';
    const summary = String(analysisResult?.summary || '').trim();
    const trends = safeList(analysisResult?.trends).slice(0, 3);
    const opportunities = safeList(analysisResult?.opportunities).slice(0, 3);
    const risks = safeList(analysisResult?.risks).slice(0, 3);
    const lines = [
      `[Insights Context]`,
      `Source: ${filename}`,
    ];
    if (summary) lines.push(`Summary: ${summary}`);
    if (trends.length > 0) lines.push(`Trends:\n${trends.map((item) => `- ${item}`).join('\n')}`);
    if (opportunities.length > 0) lines.push(`Opportunities:\n${opportunities.map((item) => `- ${item}`).join('\n')}`);
    if (risks.length > 0) lines.push(`Risks:\n${risks.map((item) => `- ${item}`).join('\n')}`);
    lines.push('Use this as context for my current strategy session.');
    return lines.join('\n\n');
  }, []);

  const handleGenerateIdeas = useCallback(async () => {
    if (!activeConnectorId) return;
    setGeneratingIdeas(true);
    setIdeasError('');
    setGeneratedIdeas([]);
    try {
      const headers = buildAuthHeaders({ 'Content-Type': 'application/json' }, 'POST');
      const response = await fetch(`${API_BASE}/api/v1/connectors/generate-ideas`, {
        method: 'POST',
        headers,
        credentials: 'include',
        body: JSON.stringify({
          connector_id: activeConnectorId,
          focus: ideasFocus,
          objective: ideasObjective,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data?.error || 'Failed to generate ideas');
      setGeneratedIdeas(Array.isArray(data?.ideas) ? data.ideas : []);
    } catch (err) {
      setIdeasError(err?.message || 'Failed to generate ideas. Check your connector connection.');
    } finally {
      setGeneratingIdeas(false);
    }
  }, [activeConnectorId, ideasFocus, ideasObjective]);

  const buildConnectorContextStatement = useCallback((connectorId, result) => {
    if (connectorId === 'snowflake_insights') {
      const summary = result?.summary || {};
      const rows = Array.isArray(result?.rows) ? result.rows.slice(0, 10) : [];
      return [
        '[Connector Context]',
        `Source: Snowflake`,
        `Table: ${summary?.table || queryTable || 'unknown'}`,
        `Rows returned: ${summary?.returned_rows ?? rows.length}`,
        `Columns used: ${Array.isArray(summary?.used_columns) ? summary.used_columns.join(', ') : 'unknown'}`,
        `Data preview:`,
        ...rows.map((row) => JSON.stringify(row)),
        '',
        'Use this data context in the strategy analysis.',
      ].join('\n');
    }
    if (connectorId === 'salesforce_insights') {
      const summary = result?.summary || {};
      const records = Array.isArray(result?.records) ? result.records.slice(0, 10) : [];
      const opptyCount = summary?.opportunity_count ?? records.length;
      const stageRows = Array.isArray(summary?.stage_breakdown) ? summary.stage_breakdown.slice(0, 6) : [];
      return [
        '[Connector Context]',
        'Source: Salesforce',
        `Opportunity count: ${opptyCount}`,
        `Open: ${Number(summary?.open_count || 0)} | Closed: ${Number(summary?.closed_count || 0)}`,
        `Total amount: ${Number(summary?.total_amount || 0)} | Weighted amount: ${Number(summary?.weighted_amount || 0)}`,
        stageRows.length ? `Stage breakdown: ${stageRows.map((row) => `${row?.stage || 'Unknown'}(${Number(row?.count || 0)})`).join(', ')}` : '',
        'Data preview:',
        ...records.map((row) => JSON.stringify(row)),
        'Use this data context in the strategy analysis.',
      ].filter(Boolean).join('\n');
    }
    return '[Connector Context]\nUse connected data context in this analysis.';
  }, [queryTable]);

  const runConnectorQuery = useCallback(async () => {
    if (!queryConnectorId) return;
    setQueryBusy(true);
    setQueryError('');
    setQueryResult(null);
    try {
      const headersGet = buildAuthHeaders({}, 'GET');
      const headersPost = buildAuthHeaders({ 'Content-Type': 'application/json' }, 'POST');
      if (queryConnectorId === 'snowflake_insights') {
        const table = String(queryTable || '').trim();
        if (!table) throw new Error('Enter a Snowflake table (for example: tpch_sf1.lineitem).');
        const response = await fetch(`${API_BASE}/api/v1/connectors/snowflake/query`, {
          method: 'POST',
          headers: headersPost,
          credentials: 'include',
          body: JSON.stringify({
            table,
            limit: Number.isFinite(Number(queryLimit)) ? Number(queryLimit) : 50,
          }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data?.error || 'Snowflake query failed');
        setQueryResult(data);
      } else if (queryConnectorId === 'salesforce_insights') {
        const response = await fetch(`${API_BASE}/api/v1/connectors/salesforce/pipeline/summary?days=90&limit=100`, {
          method: 'GET',
          headers: headersGet,
          credentials: 'include',
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data?.error || 'Salesforce pipeline query failed');
        setQueryResult(data);
      } else {
        throw new Error('This connector query flow is not available yet.');
      }
    } catch (err) {
      setQueryError(err?.message || 'Connector query failed');
    } finally {
      setQueryBusy(false);
    }
  }, [queryConnectorId, queryLimit, queryTable]);

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

  const sendAssistant = useCallback(async () => {
    const text = String(assistantInput || '').trim();
    if (!text || assistantBusy) return;
    const assistantIndex = assistantMessages.length + 1;
    setAssistantMessages((prev) => [
      ...prev,
      { role: 'user', text },
      { role: 'assistant', text: '', streaming: true },
    ]);
    setAssistantInput('');
    setAssistantBusy(true);
    const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
    assistantAbortRef.current = controller;
    let replyText = '';
    const activeConnector = connectors.find((item) => item.id === activeConnectorId);
    const view_context = {
      current_view: 'insights',
      page_facts: [
        `Datasets visible: ${datasets.length}.`,
        activeDataset ? `Active dataset: ${activeDataset.filename || activeDataset.name || activeDataset.id}.` : '',
        activeConnector ? `Active insight connector: ${activeConnector.label || activeConnector.id}.` : '',
        `Generated opportunity ideas visible: ${generatedIdeas.length}.`,
        queryResult ? 'A connector query result is visible.' : '',
      ].filter(Boolean).join(' '),
    };

    try {
      const streamArgs = {
        view_context,
        abortSignal: controller?.signal,
        onDelta: (delta) => {
          replyText += delta || '';
          setAssistantMessages((prev) => prev.map((msg, idx) => (
            idx === assistantIndex ? { ...msg, text: replyText, streaming: true } : msg
          )));
        },
        onDone: (payload) => {
          const finalText = payload?.reply || payload?.message || replyText;
          setAssistantMessages((prev) => prev.map((msg, idx) => (
            idx === assistantIndex ? { ...msg, text: finalText, streaming: false } : msg
          )));
        },
      };
      if (assistantSessionId) {
        await Jaspen.streamConversation({ ...streamArgs, session_id: assistantSessionId, user_message: text });
      } else {
        let nextSessionId = null;
        await Jaspen.streamConversationStart({
          ...streamArgs,
          description: text,
          onDone: (payload) => {
            nextSessionId = payload?.thread_id || payload?.session_id || null;
            streamArgs.onDone(payload);
          },
        });
        if (nextSessionId) setAssistantSessionId(nextSessionId);
      }
    } catch (error) {
      if (error?.name === 'AbortError' || controller?.signal?.aborted) {
        setAssistantMessages((prev) => prev.map((msg, idx) => (
          idx === assistantIndex ? { ...msg, text: 'Stopped.', streaming: false } : msg
        )));
        return;
      }
      setAssistantMessages((prev) => prev.map((msg, idx) => (
        idx === assistantIndex
          ? { ...msg, text: error?.message || 'Something went wrong. Please try again.', streaming: false, error: true }
          : msg
      )));
    } finally {
      if (assistantAbortRef.current === controller) {
        assistantAbortRef.current = null;
      }
      setAssistantBusy(false);
    }
  }, [activeConnectorId, activeDataset, assistantBusy, assistantInput, assistantMessages.length, assistantSessionId, connectors, datasets.length, generatedIdeas.length, queryResult]);

  const stopAssistant = useCallback(() => {
    try {
      assistantAbortRef.current?.abort();
    } catch (_) { /* no-op */ }
    assistantAbortRef.current = null;
    setAssistantBusy(false);
    setAssistantMessages((prev) => {
      if (!Array.isArray(prev) || prev.length === 0) return prev;
      const next = prev.slice();
      const last = next[next.length - 1];
      if (last?.streaming) {
        next[next.length - 1] = { ...last, text: String(last.text || '').trim() || 'Stopped.', streaming: false };
      }
      return next;
    });
  }, []);

  return (
    <div className={`insights-page int-page${jaspenOpen ? ' drawer-open' : ''}`}>
      <AppMenu />
      <div className="insights-inner int-page-inner">
      <header className="insights-header int-page-head">
        <div>
          <p className="int-eyebrow">Insights</p>
          <h1>Insights</h1>
          <p>See what you’ve decided, what remains open, what you’ve learned, and how the work is progressing.</p>
        </div>
      </header>

      <DecisionIntelligenceOverview navigate={navigate} />

      <div className="insights-data-heading">
        <p className="di-kicker">Data analysis</p>
        <h2>Analyze your data</h2>
        <p>Upload company datasets, run AI analysis, and review trends, anomalies, opportunities, and risks.</p>
      </div>

      {isEnterprise && connectors.length > 0 && (
        <section className="insights-section insights-ideas-section">
          <div className="insights-row-head">
            <div>
              <h2>AI-Generated Initiative Ideas</h2>
              <p className="insights-muted">Jaspen analyzes your connected data and surfaces strategic opportunities worth scoring.</p>
            </div>
          </div>

          <div className="insights-ideas-config">
            <div className="insights-ideas-connectors">
              <span className="insights-ideas-config-label">Data source</span>
              {connectors.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={`insights-connector-chip ${activeConnectorId === item.id ? 'active' : ''}`}
                  onClick={() => setActiveConnectorIdForIdeas(item.id)}
                >
                  {item.label}
                </button>
              ))}
            </div>
            <div className="insights-ideas-objective">
              <span className="insights-ideas-config-label">Objective</span>
              {[
                { key: 'balanced', label: 'Balanced' },
                { key: 'cost', label: 'Cost Reduction' },
                { key: 'speed', label: 'Speed to Market' },
                { key: 'growth', label: 'Growth' },
              ].map((obj) => (
                <button
                  key={obj.key}
                  type="button"
                  className={`insights-connector-chip ${ideasObjective === obj.key ? 'active' : ''}`}
                  onClick={() => setIdeasObjective(obj.key)}
                >
                  {obj.label}
                </button>
              ))}
            </div>
            <div className="insights-ideas-focus-row">
              <input
                type="text"
                className="insights-ideas-focus-input"
                placeholder="Optional focus (e.g. reduce churn, expand APAC, cut logistics cost)"
                value={ideasFocus}
                onChange={(event) => setIdeasFocus(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault();
                    void handleGenerateIdeas();
                  }
                }}
              />
              <button
                type="button"
                className="int-btn int-btn-primary"
                onClick={() => { void handleGenerateIdeas(); }}
                disabled={!activeConnectorId || generatingIdeas}
              >
                {generatingIdeas ? <><FontAwesomeIcon icon={faSpinner} spin /> Analyzing…</> : 'Find opportunities'}
              </button>
            </div>
          </div>

          {generatingIdeas && (
            <div className="insights-ideas-loading">
              <div className="insights-progress-track">
                <div className="insights-progress-bar insights-progress-bar-indeterminate" />
              </div>
              <span>
                Jaspen is analyzing your {connectors.find((item) => item.id === activeConnectorId)?.label} data for strategic opportunities…
              </span>
            </div>
          )}

          {ideasError && <div className="insights-error"><p>{ideasError}</p></div>}

          {generatedIdeas.length > 0 && (
            <div className="insights-idea-cards">
              {generatedIdeas.map((idea) => (
                <article key={idea.id} className="insights-idea-card">
                  <div className="insights-idea-header">
                    <span className={`insights-idea-category-badge cat-${idea.category || 'balanced'}`}>
                      {String(idea.category || 'initiative').replace(/_/g, ' ')}
                    </span>
                    <div className="insights-idea-meta">
                      {idea.effort_level && <span className="insights-idea-chip">Effort: {idea.effort_level}</span>}
                      {idea.time_to_impact && <span className="insights-idea-chip">{idea.time_to_impact}</span>}
                    </div>
                  </div>
                  <h3 className="insights-idea-title">{idea.title}</h3>
                  <p className="insights-idea-desc">{idea.description}</p>
                  {idea.data_signal && (
                    <div className="insights-idea-signal">
                      <FontAwesomeIcon icon={faArrowTrendUp} />
                      <span>{idea.data_signal}</span>
                    </div>
                  )}
                  {idea.estimated_roi_band && (
                    <div className="insights-idea-roi">Estimated: {idea.estimated_roi_band}</div>
                  )}
                  <button
                    type="button"
                    className="int-btn int-btn-primary insights-idea-score-btn"
                    onClick={() => navigate('/new', { state: { prefillMessage: idea.prefill_statement } })}
                  >
                    Score this idea →
                  </button>
                </article>
              ))}
            </div>
          )}
        </section>
      )}

      {isEnterprise && connectors.some((item) => ['snowflake_insights', 'salesforce_insights'].includes(item.id)) && (
        <section className="insights-section insights-query-section">
          <div className="insights-row-head">
            <div>
              <h2>Query Connected Data</h2>
              <p className="insights-muted">Run a live connector query and send the results into your strategy chat context.</p>
            </div>
          </div>
          <div className="insights-query-controls">
            <div className="insights-query-source">
              <span className="insights-ideas-config-label">Source</span>
              {connectors
                .filter((item) => ['snowflake_insights', 'salesforce_insights'].includes(item.id))
                .map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    className={`insights-connector-chip ${queryConnectorId === item.id ? 'active' : ''}`}
                    onClick={() => setQueryConnectorId(item.id)}
                  >
                    {item.label}
                  </button>
                ))}
            </div>
            {queryConnectorId === 'snowflake_insights' && (
              <div className="insights-query-input-row">
                <input
                  type="text"
                  className="insights-ideas-focus-input"
                  placeholder="Table (for example: tpch_sf1.lineitem)"
                  value={queryTable}
                  onChange={(event) => setQueryTable(event.target.value)}
                />
                <input
                  type="number"
                  min={1}
                  max={200}
                  className="insights-query-limit"
                  value={queryLimit}
                  onChange={(event) => setQueryLimit(Number(event.target.value || 50))}
                />
              </div>
            )}
            <div className="insights-query-actions">
              <button
                type="button"
                className="int-btn int-btn-primary"
                onClick={() => { void runConnectorQuery(); }}
                disabled={!queryConnectorId || queryBusy}
              >
                {queryBusy ? <><FontAwesomeIcon icon={faSpinner} spin /> Querying…</> : 'Run connector query'}
              </button>
            </div>
          </div>
          {queryError && <div className="insights-error"><p>{queryError}</p></div>}
          {queryResult && (
            <div className="insights-query-result">
              <pre>{JSON.stringify(queryResult?.summary || queryResult, null, 2)}</pre>
              <button
                type="button"
                className="int-btn int-btn-ghost"
                onClick={() => navigate('/new', {
                  state: { prefillMessage: buildConnectorContextStatement(queryConnectorId, queryResult) },
                })}
              >
                Use in chat →
              </button>
            </div>
          )}
        </section>
      )}

      <section className="insights-section">
        <h2>Upload Data</h2>
        <div
          className={`insights-dropzone ${uploading ? 'busy' : ''}`}
          onDragOver={(event) => event.preventDefault()}
          onDrop={onDrop}
          onClick={() => fileInputRef.current?.click()}
          role="button"
          tabIndex={0}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault();
              fileInputRef.current?.click();
            }
          }}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv,.xlsx,.xls"
            hidden
            onChange={(event) => onUpload(event.target.files?.[0])}
          />
          <FontAwesomeIcon icon={uploading ? faSpinner : faCloudArrowUp} spin={uploading} />
          <div>
            {uploading ? 'Uploading dataset…' : 'Drag and drop CSV/Excel, or click to upload'}
          </div>
          <small>Max 10MB</small>
        </div>
        {uploading && (
          <div className="insights-progress" role="status" aria-live="polite" aria-label="Uploading dataset">
            <div className="insights-progress-track">
              <div className="insights-progress-bar insights-progress-bar-indeterminate" />
            </div>
            <span>Uploading dataset...</span>
          </div>
        )}
      </section>

      <section className="insights-section">
        <div className="insights-row-head">
          <h2>Datasets</h2>
        </div>
        {loading ? (
          <div className="insights-datasets-skeleton" role="status" aria-live="polite" aria-label="Loading datasets">
            <SkeletonBlock width="26%" height={12} />
            {Array.from({ length: 5 }).map((_, idx) => (
              <div key={`insights-skeleton-${idx}`} className="insights-datasets-skeleton-row">
                <SkeletonBlock width="32%" height={14} />
                <SkeletonBlock width="12%" height={14} />
                <SkeletonBlock width="28%" height={14} />
                <SkeletonBlock width="20%" height={14} />
                <SkeletonBlock width="16%" height={30} />
              </div>
            ))}
          </div>
        ) : (
          datasets.length === 0 ? (
            <EmptyState
              className="insights-empty-state"
              title="No datasets yet"
              description="Upload your first CSV or Excel dataset to start AI analysis."
              icon={<FontAwesomeIcon icon={faCloudArrowUp} />}
              action={(
                <button type="button" className="int-btn int-btn-primary" onClick={() => fileInputRef.current?.click()}>
                  Upload dataset
                </button>
              )}
            />
          ) : (
            <div className="insights-table-wrap">
              <table className="insights-table">
                <thead>
                  <tr>
                    <th>Filename</th>
                    <th>Rows</th>
                    <th>Columns</th>
                    <th>Date</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {datasets.map((row) => (
                    <tr key={row.id} className={String(activeDatasetId) === String(row.id) ? 'active' : ''}>
                      <td>{row.filename || 'dataset'}</td>
                      <td>{row.row_count ?? '—'}</td>
                      <td>{safeList(row.column_names).join(', ') || '—'}</td>
                      <td>{formatDate(row.created_at)}</td>
                      <td>
                        <div className="insights-actions">
                          <button
                            type="button"
                            className="insights-btn"
                            onClick={() => onAnalyze(row.id)}
                            disabled={analyzing || Boolean(deletingDatasetId)} aria-disabled={analyzing || Boolean(deletingDatasetId)}
                          >
                            {analyzing && String(activeDatasetId) === String(row.id) ? 'Analyzing…' : 'Analyze'}
                          </button>
                          <button
                            type="button"
                            className="insights-btn danger"
                            onClick={() => onDeleteDataset(row.id)}
                            disabled={analyzing || deletingDatasetId === String(row.id)} aria-disabled={analyzing || deletingDatasetId === String(row.id)}
                          >
                            {deletingDatasetId === String(row.id) ? 'Deleting…' : 'Delete'}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        )}
      </section>

      <section className="insights-section">
        <div className="insights-row-head">
          <h2>Analysis Results</h2>
          {activeDataset && <span className="insights-muted">Dataset: {activeDataset.filename}</span>}
        </div>

        <div className="insights-question-row">
          <input
            type="text"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="Optional focus question (for example: Which KPI trends signal execution risk?)"
          />
          <button
            type="button"
            className="insights-btn primary"
            onClick={() => onAnalyze(activeDatasetId)}
            disabled={!activeDatasetId || analyzing} aria-disabled={!activeDatasetId || analyzing}
          >
            {analyzing ? 'Analyzing…' : 'Analyze'}
          </button>
        </div>
        {analyzing && (
          <div className="insights-progress" role="status" aria-live="polite" aria-label="Analyzing dataset">
            <div className="insights-progress-track">
              <div className="insights-progress-bar insights-progress-bar-indeterminate" />
            </div>
            <span>Analyzing dataset...</span>
          </div>
        )}

        {error && (
          <div className="insights-error" role="status" aria-live="polite">
            <p>{error}</p>
            <button
              type="button"
              className="int-btn int-btn-ghost insights-retry-btn"
              onClick={loadDatasets}
              disabled={loading || uploading || analyzing}
              aria-disabled={loading || uploading || analyzing}
            >
              Retry
            </button>
          </div>
        )}

        {!analysis ? (
          <EmptyState
            className="insights-empty-state"
            title="No analysis yet"
            description="Select a dataset and run analysis to generate trends, anomalies, opportunities, and risks."
            icon={<FontAwesomeIcon icon={faLightbulb} />}
            action={(
              <button
                type="button"
                className="int-btn int-btn-primary"
                onClick={() => onAnalyze(activeDatasetId || datasets[0]?.id)}
                disabled={!activeDatasetId && !datasets[0]?.id}
                aria-disabled={!activeDatasetId && !datasets[0]?.id}
              >
                Analyze now
              </button>
            )}
          />
        ) : (
          <div className="insights-results">
            <article className="insights-card full">
              <h3>Summary</h3>
              <p>{analysis.summary || 'No summary available.'}</p>
            </article>
            <article className="insights-card">
              <h3><FontAwesomeIcon icon={faArrowTrendUp} /> Trends</h3>
              <ul>{safeList(analysis.trends).map((item, idx) => <li key={`trend_${idx}`}>{item}</li>)}</ul>
            </article>
            <article className="insights-card">
              <h3><FontAwesomeIcon icon={faBug} /> Anomalies</h3>
              <ul>{safeList(analysis.anomalies).map((item, idx) => <li key={`anomaly_${idx}`}>{item}</li>)}</ul>
            </article>
            <article className="insights-card">
              <h3><FontAwesomeIcon icon={faLightbulb} /> Opportunities</h3>
              <ul>{safeList(analysis.opportunities).map((item, idx) => <li key={`opp_${idx}`}>{item}</li>)}</ul>
            </article>
            <article className="insights-card">
              <h3><FontAwesomeIcon icon={faCircleExclamation} /> Risks</h3>
              <ul>{safeList(analysis.risks).map((item, idx) => <li key={`risk_${idx}`}>{item}</li>)}</ul>
            </article>

            {safeList(analysis.charts).length > 0 && (
              <section className="insights-charts">
                <h3>Visualizations</h3>
                <div className="insights-chart-grid">
                  {safeList(analysis.charts).map((chart, idx) => {
                    const chartType = String(chart?.type || '').toLowerCase();
                    const data = chartDataFor(chart, idx);
                    const canRender = safeList(data.labels).length > 0 && safeList(data.datasets?.[0]?.data).length > 0;
                    return (
                      <div key={`chart_${idx}_${themeVersion}`} className="insights-chart-card">
                        <h4>{chart?.title || `Chart ${idx + 1}`}</h4>
                        {!canRender && <div className="insights-chart-empty">No chart data available.</div>}
                        {canRender && (
                          <div className="insights-chart-frame">
                            {chartType === 'bar' && <Bar data={data} options={chartOptions} />}
                            {chartType === 'line' && <Line data={data} options={chartOptions} />}
                            {chartType === 'pie' && <Pie data={data} options={chartOptions} />}
                            {!['bar', 'line', 'pie'].includes(chartType) && (
                              <div className="insights-chart-empty">Unsupported chart type: {chartType || 'unknown'}.</div>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </section>
            )}
          </div>
        )}
      </section>

      {analysis && (
        <section className="insights-section insights-score-cta-section">
          <article className="insights-card full insights-score-cta">
            <div className="insights-score-cta-copy">
              <FontAwesomeIcon icon={faArrowTrendUp} />
              <div>
                <h3>Ready to score this opportunity?</h3>
                <p>
                  Turn these insights into a strategic Jaspen Score with financial analysis, risk
                  assessment, and an AI-generated recommendation.
                </p>
              </div>
            </div>
            <div className="insights-score-cta-actions">
              <button
                type="button"
                className="int-btn int-btn-ghost"
                onClick={() => navigate('/new', {
                  state: { prefillMessage: buildInsightsContextStatement(analysis, activeDataset) },
                })}
              >
                Use as context →
              </button>
              <button
                type="button"
                className="int-btn int-btn-primary"
                onClick={() => navigate('/new', {
                  state: { prefillMessage: buildOpportunityStatement(analysis, activeDataset) },
                })}
              >
                Score this opportunity →
              </button>
            </div>
          </article>
        </section>
      )}
      <ConfirmDialog
        isOpen={Boolean(confirmDialog)}
        title={confirmDialog?.title}
        message={confirmDialog?.message}
        confirmLabel={confirmDialog?.confirmLabel}
        confirmVariant={confirmDialog?.confirmVariant}
        pending={Boolean(deletingDatasetId)}
        onCancel={() => setConfirmDialog(null)}
        onConfirm={() => confirmDialog?.onConfirm?.()}
      />
      </div>
      <JaspenAiDrawer
        isOpen={jaspenOpen}
        onOpen={openJaspen}
        onClose={() => setJaspenOpen(false)}
        messages={assistantMessages}
        input={assistantInput}
        onInputChange={setAssistantInput}
        onSend={sendAssistant}
        onStop={stopAssistant}
        busy={assistantBusy}
        starterPrompts={[
          'What are the top risks in this dataset?',
          'What opportunity should I score next?',
        ]}
        placeholder="Ask Jaspen about insights..."
      />
    </div>
  );
}
