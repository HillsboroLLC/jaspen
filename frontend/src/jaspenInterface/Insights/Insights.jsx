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

function overviewSummary(metrics = {}) {
  const decisions = Number(metrics.decisions_made || 0);
  const open = Number(metrics.in_progress || 0);
  const lessons = Number(metrics.lessons_recorded || 0);
  if (!Number(metrics.decision_records || 0)) return 'Your decision history will take shape here as you work with Jaspen.';
  const decisionText = `${decisions} decision${decisions === 1 ? '' : 's'} made`;
  const openText = `${open} still ${open === 1 ? 'needs' : 'need'} attention`;
  const learningText = lessons ? `, with ${lessons} lesson${lessons === 1 ? '' : 's'} recorded` : '';
  return `${decisionText}; ${openText}${learningText}.`;
}

function ShowAllList({ items, renderItem, label, className }) {
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? items : items.slice(0, 5);
  return (
    <>
      <ul className={className}>{visible.map(renderItem)}</ul>
      {items.length > 5 && (
        <button type="button" className="di-show-all" aria-expanded={expanded} onClick={() => setExpanded((value) => !value)}>
          {expanded ? 'Show less' : 'Show all'}<span className="sr-only"> {label}</span>
        </button>
      )}
    </>
  );
}

function pluralCount(count, singular, plural = `${singular}s`) {
  return `${count} ${count === 1 ? singular : plural}`;
}

function AttentionItems({ item }) {
  const [expanded, setExpanded] = useState(false);
  const unresolved = item.unresolved || {};
  const gates = safeList(unresolved.gates);
  const failedGates = gates.filter((gap) => gap.status !== 'unknown');
  const unassessedGates = gates.filter((gap) => gap.status === 'unknown');
  const assumptions = safeList(unresolved.assumptions);
  const evidence = safeList(unresolved.missing_evidence);
  const decided = ['decided', 'outcome_recorded'].includes(item.status);
  const counts = [
    failedGates.length ? pluralCount(failedGates.length, 'failed gate') : '',
    unassessedGates.length ? `${unassessedGates.length} not yet assessed` : '',
    assumptions.length ? pluralCount(assumptions.length, 'assumption') : '',
    evidence.length ? pluralCount(evidence.length, 'evidence gap') : '',
  ].filter(Boolean);
  const details = [
    ...failedGates.map((gap) => ({ ...gap, kind: decided ? 'Watch' : 'Failed gate' })),
    ...assumptions.map((gap) => ({ ...gap, kind: 'Assumption' })),
    ...evidence.map((gap) => ({ ...gap, kind: 'Missing evidence' })),
  ];
  const visible = expanded ? details : details.slice(0, 3);
  const title = String(item.title || '').trim().toLocaleLowerCase();
  return (
    <>
      <strong>{counts.length ? counts.join(' · ') : 'Decision still in progress'}</strong>
      {visible.length > 0 && <ul className="di-gap-list">{visible.map((gap, index) => {
        const option = String(gap.option || '').trim();
        const showOption = option && option.toLocaleLowerCase() !== title;
        return <li key={`${gap.kind}:${gap.label}:${index}`}><span>{gap.kind}</span>{showOption ? `${option}: ` : ''}{gap.label}</li>;
      })}</ul>}
      {details.length > 3 && (
        <button type="button" className="di-show-all di-gap-toggle" aria-expanded={expanded} onClick={() => setExpanded((value) => !value)}>
          {expanded ? 'Show less' : 'Show all'}<span className="sr-only"> attention items for {item.title}</span>
        </button>
      )}
    </>
  );
}

export function DecisionIntelligenceOverview({ navigate }) {
  const [scope, setScope] = useState('organization');
  const [overview, setOverview] = useState(null);
  const [overviewLoading, setOverviewLoading] = useState(true);
  const [overviewError, setOverviewError] = useState('');
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;
    const load = async () => {
      setOverviewLoading(true);
      setOverviewError('');
      try {
        const response = await fetch(`${API_BASE}/api/v1/insights/overview?scope=${encodeURIComponent(scope)}`, {
          method: 'GET', headers: buildAuthHeaders({}, 'GET'), credentials: 'include',
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload?.error || 'Unable to load decision insights.');
        if (active) {
          setOverview(payload);
          if (payload?.can_manage && payload?.scope && payload.scope !== scope) setScope(payload.scope);
        }
      } catch (err) {
        if (active) setOverviewError(err?.message || 'Unable to load decision insights.');
      } finally {
        if (active) setOverviewLoading(false);
      }
    };
    load();
    return () => { active = false; };
  }, [scope, reloadKey]);

  const metrics = overview?.metrics || {};
  const months = safeList(overview?.progress?.monthly);
  const chartMax = Math.max(1, ...months.flatMap((item) => [Number(item.records_created || 0), Number(item.decisions_made || 0)]));
  const hasRecords = Number(metrics.decision_records || 0) > 0;

  return (
    <section className="di-overview" aria-labelledby="di-overview-title">
      <div className="di-masthead">
        <div>
          <p className="di-kicker">{overview?.calculation_label || 'Calculated insights'}</p>
          <h2 id="di-overview-title">Your decisions, in view</h2>
        </div>
        {overview?.can_manage && (
          <div className="di-scope-switch" role="group" aria-label="Decision insight scope">
            <button type="button" className={scope === 'organization' ? 'is-active' : ''} aria-pressed={scope === 'organization'} onClick={() => setScope('organization')}>Organization</button>
            <button type="button" className={scope === 'mine' ? 'is-active' : ''} aria-pressed={scope === 'mine'} onClick={() => setScope('mine')}>My activity</button>
          </div>
        )}
      </div>

      {overviewLoading && <div className="di-state" role="status">Calculating your decision overview…</div>}
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
          <div className="di-summary">
            <p>{overviewSummary(metrics)}</p>
            <dl>
              <div><dt>Decisions made</dt><dd>{metrics.decisions_made || 0}</dd></div>
              <div><dt>Still open</dt><dd>{metrics.in_progress || 0}</dd></div>
              <div><dt>Plans in execution</dt><dd>{metrics.plans_in_execution || 0}</dd></div>
            </dl>
          </div>

          <div className="di-columns">
            <section className="di-panel" aria-labelledby="di-decisions-title">
              <p className="di-kicker">Decided</p><h3 id="di-decisions-title">Choices on record</h3>
              {safeList(overview?.decisions).length ? (
                <ShowAllList className="di-list" items={safeList(overview.decisions)} label="decisions" renderItem={(item) => (
                  <li key={item.id || `${item.record_id}:${item.decided_at || item.chosen_option}`}>
                    <a href={projectHref(item.thread_id)}>{item.title}</a>
                    <strong>{item.chosen_option}</strong>
                    <span>{item.decided_at ? formatDate(item.decided_at) : 'Decision date not recorded'}</span>
                  </li>
                )} />
              ) : <div className="di-panel-empty"><p>No final decision is recorded yet.</p><button type="button" onClick={() => navigate('/new')}>Record a decision →</button></div>}
            </section>

            <section className="di-panel" aria-labelledby="di-open-title">
              <p className="di-kicker">Unresolved</p><h3 id="di-open-title">What still needs attention</h3>
              {safeList(overview?.open_items).length ? (
                <ul className="di-list">{safeList(overview.open_items).map((item) => (
                  <li key={item.record_id}><a href={projectHref(item.thread_id)}>{item.title}</a><AttentionItems item={item} /></li>
                ))}</ul>
              ) : <div className="di-panel-empty"><p>Nothing is marked as open.</p><button type="button" onClick={() => navigate('/new')}>Start a decision →</button></div>}
            </section>
          </div>

          <section className="di-learning" aria-labelledby="di-learning-title">
            <div><p className="di-kicker">Organizational memory</p><h3 id="di-learning-title">What you’ve learned</h3></div>
            <div className="di-learning-columns">
              <div><h4>Lessons</h4>{safeList(overview?.learning?.lessons).length ? <ShowAllList items={safeList(overview.learning.lessons)} label="lessons" renderItem={(item, index) => <li key={`${item.record_id}:lesson:${index}`}><a href={projectHref(item.thread_id)}>{item.title}</a><span>{item.text}</span></li>} /> : <p>No lessons recorded yet. Revisit a decision after results are known.</p>}</div>
              <div><h4>Outcomes</h4>{safeList(overview?.learning?.outcomes).length ? <ShowAllList items={safeList(overview.learning.outcomes)} label="outcomes" renderItem={(item, index) => <li key={`${item.record_id}:outcome:${index}`}><a href={projectHref(item.thread_id)}>{item.title}</a><span>{item.text}</span></li>} /> : <p>No outcomes recorded yet. Add an outcome when the real-world result is clear.</p>}</div>
            </div>
          </section>

          <section className="di-progress" aria-labelledby="di-progress-title">
            <div><p className="di-kicker">Progress</p><h3 id="di-progress-title">Decision activity over time</h3></div>
            {months.length ? <div className="di-chart" role="group" aria-label="Decision records created and decisions made by month, starting at zero">
              <div className="di-chart-scale"><span>0</span><span>{chartMax}</span></div>
              {months.map((item) => <div className="di-chart-row" key={item.month}><span>{formatMonth(item.month)}</span><div><i className="is-record" style={{ width: `${(Number(item.records_created || 0) / chartMax) * 100}%` }} /><b>{item.records_created || 0} records</b></div><div><i className="is-decision" style={{ width: `${(Number(item.decisions_made || 0) / chartMax) * 100}%` }} /><b>{item.decisions_made || 0} decisions</b></div></div>)}
            </div> : <p className="di-muted">Progress appears once a decision record has a stored date.</p>}
            <div className="di-plan-block">
              <h4>Plans in execution</h4>
              {safeList(overview?.progress?.plans_in_execution).length ? <ShowAllList items={safeList(overview.progress.plans_in_execution)} label="plans" renderItem={(plan) => <li key={plan.record_id}><a href={projectHref(plan.thread_id)}>{plan.title}</a><span>{plan.tasks_total ? `${plan.tasks_completed} of ${plan.tasks_total} tasks completed` : 'Plan recorded; task progress is not available'}</span></li>} /> : <p className="di-muted">No execution plans are currently in progress.</p>}
            </div>
          </section>

          {scope === 'organization' && overview?.can_manage && safeList(overview?.activity_by_member).length > 0 && (
            <section className="di-members" aria-labelledby="di-members-title"><p className="di-kicker">Organization</p><h3 id="di-members-title">Activity by member</h3><div className="di-member-grid">{overview.activity_by_member.map((member) => <div key={member.user_id}><strong>{member.name}</strong><span>{member.decisions} decisions · {member.open} open · {member.records} records</span></div>)}</div></section>
          )}
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
