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
  return date.toLocaleString();
}

function safeList(value) {
  return Array.isArray(value) ? value : [];
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
        const isEnt = ['free', 'essential', 'team', 'enterprise'].includes(data?.plan_key);
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
          <p>Upload company datasets, run AI analysis, and review trends, anomalies, opportunities, and risks.</p>
        </div>
      </header>

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
