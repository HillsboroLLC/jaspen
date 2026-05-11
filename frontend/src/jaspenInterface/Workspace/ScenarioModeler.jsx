// ============================================================================
// File: src/pages/Jaspen/ScenarioModeler.jsx
// Purpose: DYNAMIC - Extracts fields from baseline, displays in 3 columns
//          NOW WIRED to backend scenario endpoints (no mockResult / no delays)
// ============================================================================
import React, { useState, useMemo, useEffect, useCallback, useRef, forwardRef, useImperativeHandle } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faSpinner, faPlay, faCheck } from '@fortawesome/free-solid-svg-icons';
import { Jaspen } from './JaspenClient';
import Button from './workspaceUi/components/Button';
import { ScenarioModelerSkeleton } from '../../shared/components/SkeletonLoader';

// ============================================================================
// HELPER: Extract editable levers from baseAnalysis
// ============================================================================
function parseAssumptionToLever(text) {
  if (!text || typeof text !== 'string') return null;
  const s = text.trim();
  let value = null;
  let type = 'number';

  const currMatch = s.match(/\$\s*([\d,]+(?:\.\d+)?)\s*([KkMmBb]?)/);
  if (currMatch) {
    value = parseFloat(currMatch[1].replace(/,/g, ''));
    const suf = currMatch[2].toUpperCase();
    if (suf === 'K') value *= 1e3;
    else if (suf === 'M') value *= 1e6;
    else if (suf === 'B') value *= 1e9;
    type = 'currency';
  }

  if (value === null) {
    const m = s.match(/([\d,]+(?:\.\d+)?)\s*(?:%|percent)/i);
    if (m) {
      value = parseFloat(m[1].replace(/,/g, ''));
      type = 'percentage';
    }
  }

  if (value === null) {
    const m = s.match(/([\d,]+(?:\.\d+)?)\s*(?:months?|weeks?)/i);
    if (m) {
      value = parseFloat(m[1].replace(/,/g, ''));
      type = 'months';
    }
  }

  if (value === null) {
    const m = s.match(/([\d,]+(?:\.\d+)?)\s*(?:FTEs?|engineers?|developers?|people|members?|users?|customers?|licenses?|seats?|units?)/i);
    if (m) {
      value = parseFloat(m[1].replace(/,/g, ''));
      type = 'number';
    }
  }

  if (value === null || !isFinite(value) || value <= 0) return null;

  const key = `assump_${s.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').substring(0, 35)}`;
  const label = s.length > 55 ? `${s.substring(0, 55).replace(/[,.:;]$/, '')}...` : s.replace(/[,.:;]$/, '');
  return { key, label, value, type, source: 'observed', description: s };
}

function extractLevers(baseAnalysis, outputMetrics = []) {
  if (!baseAnalysis) return [];

  const inputs = baseAnalysis.inputs || {};
  const compat = baseAnalysis.compat || {};
  const combined = { ...compat, ...inputs };

  // Fields to exclude (calculated outputs, not inputs)
  const EXCLUDED = [
    'jaspen_score',
    'npv', 'irr', 'roi',
    'revenue_y1', 'revenue_after', 'revenue_before',
    'ebitda_after', 'ebitda_before',
    'enterprise_value', 'ebitda_multiple',
    'clv', 'payback_months', 'payback_period',
    'roi_opportunity', 'projected_ebitda', 'ebitda_at_risk'
  ];
  const excluded = new Set([...EXCLUDED, ...(Array.isArray(outputMetrics) ? outputMetrics : [])]);

  const levers = [];
  const seen = new Set();

  for (const [key, value] of Object.entries(combined)) {
    if (excluded.has(key)) continue;
    if (typeof value === 'number' && !isNaN(value)) {
      seen.add(key);
      levers.push({
        key,
        label: formatLabel(key),
        value,
        type: inferType(key, value),
      });
    }
  }

  if (levers.length < 4) {
    const assumptionTexts = Array.isArray(baseAnalysis.assumptions) ? baseAnalysis.assumptions : [];
    for (const text of assumptionTexts) {
      const lever = parseAssumptionToLever(String(text || ''));
      if (lever && !seen.has(lever.key)) {
        seen.add(lever.key);
        levers.push(lever);
        if (levers.length >= 8) break;
      }
    }
  }

  return levers;
}

// ============================================================================
// HELPER: Normalize scenario levers from backend
// ============================================================================
function normalizeScenarioLevers(scenarioLevers = []) {
  if (!Array.isArray(scenarioLevers)) return [];

  return scenarioLevers
    .map((lever) => {
      if (!lever || !lever.key) return null;
      const displayMultiplier = Number(lever.display_multiplier) || 1;
      const rawValue = lever.current ?? lever.value ?? 0;
      const value = rawValue * displayMultiplier;

      return {
        key: lever.key,
        label: lever.label || formatLabel(lever.key),
        value,
        min: lever.min != null ? lever.min * displayMultiplier : undefined,
        max: lever.max != null ? lever.max * displayMultiplier : undefined,
        step: lever.step != null ? lever.step * displayMultiplier : undefined,
        type: lever.type || inferType(lever.key, value),
        scale: lever.scale || null,
        ui_scale: lever.ui_scale || null,
        display_multiplier: displayMultiplier,
        description: lever.description || '',
        source: lever.source || 'estimated',
      };
    })
    .filter(Boolean);
}

// ============================================================================
// HELPER: Format field names into readable labels
// ============================================================================
function formatLabel(key) {
  const SPECIAL_LABELS = {
    'cac': 'CAC',
    'npv': 'NPV',
    'irr': 'IRR',
    'roi': 'ROI',
    'clv': 'CLV',
    'ebitda': 'EBITDA',
  };

  if (SPECIAL_LABELS[key.toLowerCase()]) return SPECIAL_LABELS[key.toLowerCase()];

  return key
    .replace(/_/g, ' ')
    .replace(/([A-Z])/g, ' $1')
    .split(' ')
    .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(' ')
    .trim();
}

// ============================================================================
// HELPER: Infer display type from field name
// ============================================================================
function inferType(key) {
  const lowerKey = key.toLowerCase();

  if (
    lowerKey.includes('budget') ||
    lowerKey.includes('investment') ||
    lowerKey.includes('cost') ||
    lowerKey.includes('price') ||
    lowerKey.includes('revenue') ||
    lowerKey.includes('value') ||
    lowerKey.includes('ebitda') ||
    lowerKey.includes('npv')
  ) return 'currency';

  if (
    lowerKey.includes('month') ||
    lowerKey.includes('timeline') ||
    lowerKey.includes('period') ||
    lowerKey.includes('duration')
  ) return 'months';

  if (
    lowerKey.includes('percent') ||
    lowerKey.includes('rate') ||
    lowerKey.includes('margin') ||
    lowerKey.includes('roi') ||
    lowerKey.includes('irr') ||
    lowerKey.includes('adoption')
  ) return 'percentage';

  return 'number';
}

// ============================================================================
// HELPER: Format value based on type
// ============================================================================
function formatValue(value, type) {
  if (value == null || value === '' || isNaN(Number(value))) return '—';
  const n = Number(value);

  switch (type) {
    case 'currency':
      if (Math.abs(n) >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
      if (Math.abs(n) >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
      if (Math.abs(n) >= 1e3) return `$${(n / 1e3).toFixed(1)}K`;
      return `$${n.toLocaleString()}`;
    case 'months':
      return `${n} ${n === 1 ? 'month' : 'months'}`;
    case 'percentage':
      return `${Number.isInteger(n) ? n : n.toFixed(1)}%`;
    default:
      return n.toLocaleString();
  }
}

function formatDeltaValue(currentValue, baselineValue, type) {
  if (baselineValue == null || currentValue == null) return '—';
  const diff = Number(currentValue) - Number(baselineValue);
  if (!Number.isFinite(diff)) return '—';
  if (diff === 0) {
    if (type === 'months') return '0 mo';
    if (type === 'percentage') return '0pp';
    return '0';
  }
  if (type === 'percentage') {
    return `${diff > 0 ? '+' : ''}${Number.isInteger(diff) ? diff : diff.toFixed(1)}pp`;
  }
  const formatted = formatValue(Math.abs(diff), type);
  return `${diff > 0 ? '+' : '-'}${formatted}`;
}

const SCENARIO_RESULT_METRICS = [
  { key: 'roi_opportunity', label: 'ROI Opportunity', type: 'percentage' },
  { key: 'projected_ebitda', label: 'Projected EBITDA', type: 'currency' },
  { key: 'expected_annual_return', label: 'Expected Annual Return', type: 'currency' },
  { key: 'npv_3_year', label: '3-Year NPV', type: 'currency' },
  { key: 'irr', label: 'IRR', type: 'percentage' },
  { key: 'payback_period', label: 'Payback Period', type: 'months' },
  { key: 'break_even_month', label: 'Break-Even Month', type: 'months' },
  { key: 'enterprise_value', label: 'Enterprise Value', type: 'currency' },
  { key: 'ebitda_at_risk', label: 'EBITDA At Risk', type: 'percentage' },
  { key: 'potential_loss', label: 'Potential Loss', type: 'currency' },
  { key: 'cost_of_inaction', label: 'Cost of Inaction', type: 'currency' },
  { key: 'time_to_market_impact', label: 'Time to Market Impact', type: 'months' },
  { key: 'jaspen_score', label: 'Jaspen Score', type: 'number' },
];

const SCENARIO_RUN_STAGES = [
  'Validating lever updates…',
  'Saving scenario draft…',
  'Running financial model…',
  'Building projected scorecard…',
];

function parseMetricNumber(value) {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value !== 'string') return null;
  const cleaned = value.replace(/[^\d.-]/g, '');
  if (!cleaned) return null;
  const parsed = Number(cleaned);
  return Number.isFinite(parsed) ? parsed : null;
}

function metricContainers(result = {}) {
  return [
    result?.financial_analysis,
    result?.financial_impact,
    result?.npv_irr_analysis,
    result?.investment_analysis,
    result?.valuation,
    result?.metrics,
    result?.compat?.financials,
  ].filter((x) => x && typeof x === 'object');
}

function getMetricValue(result = {}, key = '') {
  for (const box of metricContainers(result)) {
    if (Object.prototype.hasOwnProperty.call(box, key)) {
      const parsed = parseMetricNumber(box[key]);
      if (parsed != null) return parsed;
    }
  }
  return null;
}

function buildMetricRows(result = {}) {
  const rows = new Map();
  const blocked = ['score', 'category', 'label', 'id', 'analysis', 'thread', 'project', 'name', 'risk', 'source', 'version', 'status'];
  const priority = [
    'npv', 'irr', 'payback', 'payback_period', 'payback_months', 'roi', 'roi_opportunity',
    'potential_loss', 'ebitda_at_risk', 'projected_ebitda', 'enterprise_value', 'initial_investment',
  ];

  for (const box of metricContainers(result)) {
    for (const [key, rawValue] of Object.entries(box)) {
      const lower = String(key).toLowerCase();
      if (blocked.some((term) => lower.includes(term))) continue;
      const value = parseMetricNumber(rawValue);
      if (value == null) continue;
      if (!rows.has(key)) {
        rows.set(key, {
          key,
          label: formatLabel(key),
          type: inferType(key),
          value,
        });
      }
    }
  }

  return [...rows.values()]
    .sort((a, b) => {
      const ai = priority.indexOf(a.key);
      const bi = priority.indexOf(b.key);
      if (ai === -1 && bi === -1) return a.label.localeCompare(b.label);
      if (ai === -1) return 1;
      if (bi === -1) return -1;
      return ai - bi;
    })
    .slice(0, 6);
}

function buildScenarioMetricRows(result = {}) {
  if (!result) return [];
  return SCENARIO_RESULT_METRICS
    .map((metric) => {
      const value = metric.key === 'jaspen_score'
        ? (result?.overall_score ?? result?.jaspen_score ?? null)
        : getMetricValue(result, metric.key);
      if (value == null) return null;
      if (Number.isFinite(value) && Number(value) === 0) return null;
      return {
        ...metric,
        value,
      };
    })
    .filter(Boolean);
}

function splitNarrativeSentences(value = '') {
  return String(value || '')
    .split(/(?<=[.!?])\s+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function looksLikeFinancialContext(sentence = '') {
  const lower = String(sentence || '').toLowerCase();
  return (
    /[%$]/.test(lower) ||
    /\bq[1-4]\b/.test(lower) ||
    /\b\d+\s*(month|months|week|weeks|fte|tool|tools|phase|phases|user|users)\b/.test(lower) ||
    [
      'roi',
      'savings',
      'cost',
      'budget',
      'timeline',
      'migration',
      'adoption',
      'rollout',
      'spend',
      'ebitda',
      'revenue',
      'payback',
      'implementation',
      'platform',
    ].some((token) => lower.includes(token))
  );
}

function deriveBaselineContextSignals(baseAnalysis = {}) {
  const signals = [];
  const seen = new Set();
  const pushSignal = (source, text) => {
    const cleaned = String(text || '').replace(/\s+/g, ' ').trim();
    if (!cleaned) return;
    const key = `${source}:${cleaned.toLowerCase()}`;
    if (seen.has(key)) return;
    seen.add(key);
    signals.push({ key, source, text: cleaned });
  };

  const explicitAssumptions = Array.isArray(baseAnalysis?.assumptions) ? baseAnalysis.assumptions : [];
  explicitAssumptions.forEach((item) => pushSignal('Assumption', item));

  splitNarrativeSentences(baseAnalysis?.executive_summary)
    .filter(looksLikeFinancialContext)
    .slice(0, 3)
    .forEach((sentence) => pushSignal('Executive summary', sentence));

  const keyInsights = Array.isArray(baseAnalysis?.key_insights) ? baseAnalysis.key_insights : [];
  keyInsights
    .filter(looksLikeFinancialContext)
    .slice(0, 3)
    .forEach((item) => pushSignal('Key insight', item));

  const componentRationale = baseAnalysis?.component_rationale && typeof baseAnalysis.component_rationale === 'object'
    ? Object.values(baseAnalysis.component_rationale)
    : [];
  componentRationale
    .filter(looksLikeFinancialContext)
    .slice(0, 2)
    .forEach((item) => pushSignal('Score rationale', item));

  return signals.slice(0, 6);
}

// ============================================================================
// BASELINE COLUMN (Read-only)
// ============================================================================
function BaselineColumn({ metrics, assumptions, contextSignals }) {
  const rows = Array.isArray(metrics) ? metrics : [];
  const assumptionRows = Array.isArray(assumptions) ? assumptions : [];
  const contextRows = Array.isArray(contextSignals) ? contextSignals : [];
  const hasStructuredAssumptions = assumptionRows.length > 0;
  const hasContextSignals = contextRows.length > 0;
  return (
    <div className="jas-scenario-col">
      <div className="jas-scenario-header">
        Baseline
        <span className="jas-scenario-badge">Current</span>
      </div>
      <div className="jas-scenario-body">
        {rows.length > 0 ? (
          <>
            {rows.map((metric) => (
              <div key={metric.key} className="jas-scenario-field">
                <span className="jas-scenario-field-label">{metric.label}</span>
                <span className="jas-scenario-field-value">{formatValue(metric.value, metric.type)}</span>
              </div>
            ))}
            <div className="jas-scenario-baseline-note">
              {hasStructuredAssumptions
                ? 'These baseline metrics are grounded in structured assumptions captured for this analysis.'
                : hasContextSignals
                  ? 'These baseline metrics are estimated from the current scorecard context shown below.'
                  : 'These baseline metrics are directional estimates. Jaspen needs more financial detail to explain them rigorously.'}
            </div>
          </>
        ) : (
          <div className="jas-scenario-field">
            <span className="jas-scenario-field-label">No baseline financial metrics available</span>
            <span className="jas-scenario-field-value">—</span>
          </div>
        )}

        <div className="jas-scenario-assumptions">
          <div className="jas-scenario-section-title">Baseline Assumptions</div>
          <p className="jas-scenario-assumptions-copy">
            These assumptions are driving the current baseline projections. Adjust them in Scenario A or B to test more accurate or more ambitious outcomes.
          </p>
          {hasStructuredAssumptions ? (
            <div className="jas-scenario-assumption-list">
              {assumptionRows.map((assumption) => (
                <div key={assumption.key} className="jas-scenario-assumption-row">
                  <div className="jas-scenario-assumption-main">
                    <div className="jas-scenario-assumption-label-row">
                      <span className="jas-scenario-assumption-label">{assumption.label}</span>
                      <span className={`jas-scenario-assumption-source jas-scenario-assumption-source-${assumption.source || 'estimated'}`}>
                        {assumption.source === 'observed' ? 'Provided' : 'Estimated'}
                      </span>
                    </div>
                    {assumption.description ? (
                      <div className="jas-scenario-assumption-description">{assumption.description}</div>
                    ) : null}
                  </div>
                  <div className="jas-scenario-assumption-value">{formatValue(assumption.value, assumption.type)}</div>
                </div>
              ))}
            </div>
          ) : hasContextSignals ? (
            <div className="jas-scenario-context-list">
              {contextRows.map((signal) => (
                <div key={signal.key} className="jas-scenario-context-row">
                  <span className="jas-scenario-context-source">{signal.source}</span>
                  <p className="jas-scenario-context-text">{signal.text}</p>
                </div>
              ))}
            </div>
          ) : (
            <div className="jas-scenario-empty">
              <p>Jaspen does not yet have enough current-context signals to explain this baseline.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ============================================================================
// SCENARIO COLUMN (Editable)
// ============================================================================
function ScenarioColumn({
  title,
  levers,
  values,
  baselineResult,
  insufficientLevers,
  onRequestDeeperAnalysis,
  onChange,
  onRun,
  onAdopt,
  result,
  disabled,
  running,
  progressMessage,
}) {
  const scenarioMetricRows = useMemo(
    () => buildScenarioMetricRows(result),
    [result]
  );
  const baselineMetricMap = useMemo(
    () => new Map(buildScenarioMetricRows(baselineResult).map((metric) => [metric.key, metric])),
    [baselineResult]
  );

  return (
    <div className="jas-scenario-col">
      <div className="jas-scenario-header">{title}</div>

      <div className="jas-scenario-body jas-scenario-body-rich">
        <div className="jas-scenario-section">
          <div className="jas-scenario-section-title">Projected Outcomes</div>
          {running && progressMessage ? (
            <div className="jas-scenario-run-status" role="status" aria-live="polite">
              <FontAwesomeIcon icon={faSpinner} spin />
              <span>{progressMessage}</span>
            </div>
          ) : null}
          {result ? (
            <div className="results-box">
              {scenarioMetricRows.map((metric) => {
                const baselineMetric = baselineMetricMap.get(metric.key);
                return (
                  <div key={metric.key} className="result-row result-row-compare">
                    <span className="result-label">{metric.label}</span>
                    <div className="result-compare-values">
                      <span className="result-value result-value-before">
                        {baselineMetric ? formatValue(baselineMetric.value, baselineMetric.type) : '—'}
                      </span>
                      <span className="result-arrow">→</span>
                      <span className="result-value">{formatValue(metric.value, metric.type)}</span>
                      <span className="input-delta">
                        {baselineMetric ? formatDeltaValue(metric.value, baselineMetric.value, metric.type) : '—'}
                      </span>
                    </div>
                  </div>
                );
              })}
              {result?.rationale ? (
                <div className="jas-scenario-rationale">{result.rationale}</div>
              ) : null}
            </div>
          ) : (
            <div className="jas-scenario-empty">
              <p>Run this scenario to see projected ROI, EBITDA, return, NPV, payback, and score change.</p>
            </div>
          )}
        </div>

        {insufficientLevers ? (
          <div className="jas-scenario-empty">
            <p>Add specific numbers to your plan - a budget, timeline, or team size - then re-score. Those numbers become the levers here.</p>
            <Button variant="outline" size="sm" onClick={onRequestDeeperAnalysis} disabled={disabled}>
              Run deeper financial analysis
            </Button>
          </div>
        ) : (
          <div className="jas-scenario-section">
            <div className="jas-scenario-section-title">Adjustable Levers</div>
            {levers.map((lever) => {
              const currentValue = values[lever.key] ?? lever.value;
              const delta = formatDeltaValue(currentValue, lever.value, lever.type);
              const deltaClass = delta.startsWith('+')
                ? 'positive'
                : delta.startsWith('-') && delta !== '—'
                  ? 'negative'
                  : '';

              return (
                <div key={lever.key} className="input-group">
                  <label className="input-label">{lever.label}</label>
                  {lever.description ? (
                    <div className="jas-scenario-lever-help">{lever.description}</div>
                  ) : null}
                  <div className="input-wrapper">
                    <input
                      type="number"
                      className="input-field"
                      value={currentValue}
                      min={lever.min}
                      max={lever.max}
                      step={lever.step ?? (lever.type === 'currency' ? 1000 : lever.type === 'percentage' ? 1 : 1)}
                      onChange={(e) => onChange({ ...values, [lever.key]: Number(e.target.value) })}
                      disabled={disabled}
                    />
                    <span className={`input-delta ${deltaClass}`}>{delta}</span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="jas-scenario-actions">
        <Button variant="outline" size="sm" onClick={onRun} disabled={disabled || running}>
          {running ? (
            <>
              <FontAwesomeIcon icon={faSpinner} spin /> Running...
            </>
          ) : (
            <>
              <FontAwesomeIcon icon={faPlay} /> Run
            </>
          )}
        </Button>
        <Button variant="outline" size="sm" onClick={onAdopt} disabled={!result || disabled}>
          <FontAwesomeIcon icon={faCheck} /> Set Active
        </Button>
      </div>
    </div>
  );
}

// ============================================================================
// MAIN COMPONENT
// ============================================================================
const ScenarioModeler = forwardRef(function ScenarioModeler({
  analysisId,
  baseAnalysis,
  leverCatalog = [],
  outputMetrics = [],
  scenarioLevers = [],
  savedScenarios = [],
  refreshVersion = 0,
  onAdopt,
  onAdoptScenario = () => {},
  onScenarioSaved = () => {},
  onResultA = () => {},
  onResultB = () => {},
  onCompare,
  onRequestDeeperAnalysis = () => {},
  loading = false,
}, ref) {
  // Determine threadId robustly (keep backward compatibility)
  const threadId =
    baseAnalysis?.thread_id ||
    baseAnalysis?.session_id ||
    baseAnalysis?.meta?.thread_id ||
    analysisId;

  const baselineMetrics = useMemo(() => buildMetricRows(baseAnalysis), [baseAnalysis]);

  const levers = useMemo(() => {
    const normalizedCatalog = normalizeScenarioLevers(leverCatalog);
    if (normalizedCatalog.length > 0) return normalizedCatalog;
    const normalized = normalizeScenarioLevers(scenarioLevers);
    if (normalized.length > 0) return normalized;
    return extractLevers(baseAnalysis, outputMetrics);
  }, [leverCatalog, scenarioLevers, baseAnalysis, outputMetrics]);

  const insufficientLevers = levers.length === 0;
  const baselineAssumptions = useMemo(
    () => levers.map((lever) => ({
      key: lever.key,
      label: lever.label,
      value: lever.value,
      type: lever.type,
      description: lever.description,
      source: lever.source || 'estimated',
    })),
    [levers]
  );
  const baselineContextSignals = useMemo(
    () => deriveBaselineContextSignals(baseAnalysis),
    [baseAnalysis]
  );

  const initialValues = useMemo(() => {
    const vals = {};
    levers.forEach(lever => { vals[lever.key] = lever.value; });
    return vals;
  }, [levers]);

  const [scenarioA, setScenarioA] = useState(initialValues);
  const [scenarioB, setScenarioB] = useState(initialValues);

  const [resultA, setResultA] = useState(null);
  const [resultB, setResultB] = useState(null);
  // Track backend scenario IDs so subsequent Runs update instead of creating duplicates
  const [scenarioIdA, setScenarioIdA] = useState(null);
  const [scenarioIdB, setScenarioIdB] = useState(null);

  const [busy, setBusy] = useState(false);
  const [activeScenario, setActiveScenario] = useState(null);
  const [scenarioProgress, setScenarioProgress] = useState({});
  const [aiSuggestOpen, setAiSuggestOpen] = useState(false);
  const [aiSuggestPrompt, setAiSuggestPrompt] = useState('');
  const [aiSuggestBusy, setAiSuggestBusy] = useState(false);
  const [aiSuggestDraft, setAiSuggestDraft] = useState(null);
  const [aiSuggestError, setAiSuggestError] = useState('');
  const progressIntervalRef = useRef({});

  const clearScenarioProgress = useCallback((label) => {
    const key = String(label || '').trim();
    if (!key) return;
    if (progressIntervalRef.current[key]) {
      window.clearInterval(progressIntervalRef.current[key]);
      delete progressIntervalRef.current[key];
    }
    setScenarioProgress((prev) => {
      if (!prev[key]) return prev;
      const next = { ...prev };
      delete next[key];
      return next;
    });
  }, []);

  const setScenarioProgressStage = useCallback((label, stageMessage) => {
    const key = String(label || '').trim();
    const message = String(stageMessage || '').trim();
    if (!key || !message) return;
    setScenarioProgress((prev) => ({ ...prev, [key]: message }));
  }, []);

  const startScenarioProgress = useCallback((label) => {
    const key = String(label || '').trim();
    if (!key) return;
    clearScenarioProgress(key);
    setScenarioProgressStage(key, SCENARIO_RUN_STAGES[0]);
    let stageIndex = 0;
    progressIntervalRef.current[key] = window.setInterval(() => {
      stageIndex = Math.min(stageIndex + 1, SCENARIO_RUN_STAGES.length - 1);
      setScenarioProgressStage(key, SCENARIO_RUN_STAGES[stageIndex]);
    }, 1500);
  }, [clearScenarioProgress, setScenarioProgressStage]);

  const completeScenarioProgress = useCallback((label) => {
    const key = String(label || '').trim();
    if (!key) return;
    setScenarioProgressStage(key, 'Scenario ready.');
    if (progressIntervalRef.current[key]) {
      window.clearInterval(progressIntervalRef.current[key]);
      delete progressIntervalRef.current[key];
    }
    window.setTimeout(() => {
      clearScenarioProgress(key);
    }, 1100);
  }, [clearScenarioProgress, setScenarioProgressStage]);

  const savedScenarioByLabel = useMemo(() => {
    const entries = Array.isArray(savedScenarios) ? savedScenarios : [];
    const pickLatest = (label) => {
      const matches = entries
        .filter((entry) => String(entry?.label || '').trim().toLowerCase() === label.toLowerCase())
        .sort((a, b) => Number(b?.timestamp || 0) - Number(a?.timestamp || 0));
      return matches[0] || null;
    };
    return {
      a: pickLatest('Scenario A'),
      b: pickLatest('Scenario B'),
    };
  }, [savedScenarios]);

  const hydratedValues = useMemo(() => {
    const toDisplayValues = (entry) => {
      const nextValues = { ...initialValues };
      const rawValues = entry?.values && typeof entry.values === 'object' ? entry.values : {};
      Object.entries(rawValues).forEach(([key, rawValue]) => {
        const lever = levers.find((item) => String(item?.key || '') === String(key));
        const multiplier = Number(lever?.display_multiplier) || 1;
        const numeric = Number(rawValue);
        if (!Number.isFinite(numeric)) return;
        nextValues[key] = numeric * multiplier;
      });
      return nextValues;
    };
    return {
      a: savedScenarioByLabel.a ? toDisplayValues(savedScenarioByLabel.a) : initialValues,
      b: savedScenarioByLabel.b ? toDisplayValues(savedScenarioByLabel.b) : initialValues,
    };
  }, [initialValues, levers, savedScenarioByLabel]);

  useEffect(() => {
    setScenarioA(hydratedValues.a);
    setScenarioB(hydratedValues.b);
    setResultA(savedScenarioByLabel.a?.result || null);
    setResultB(savedScenarioByLabel.b?.result || null);
    setScenarioIdA(savedScenarioByLabel.a?.id || null);
    setScenarioIdB(savedScenarioByLabel.b?.id || null);
  }, [hydratedValues, savedScenarioByLabel, refreshVersion]);

  useEffect(() => () => {
    const timers = progressIntervalRef.current || {};
    Object.values(timers).forEach((timerId) => {
      window.clearInterval(timerId);
    });
    progressIntervalRef.current = {};
  }, []);

  // Expose imperative controls for interactive chat actions (Score → Scenarios)
  useImperativeHandle(ref, () => ({
    setScenarioInput: (payload = {}) => {
      try {
        const scenarioRaw = payload.scenario || payload.scenarioId || payload.target || 'A';
        const scenario = String(scenarioRaw).toLowerCase().includes('b') ? 'B' : 'A';
        const key = payload.key || payload.lever || payload.field;
        let value = payload.value;
        if (!key) return false;

        // Coerce numbers when possible
        if (typeof value === 'string') {
          const v = value.trim();
          if (v !== '' && !Number.isNaN(Number(v))) value = Number(v);
        }
        if (typeof value !== 'number' || !Number.isFinite(value)) return false;

        if (scenario === 'A') {
          setScenarioA(prev => ({ ...prev, [key]: value }));
        } else {
          setScenarioB(prev => ({ ...prev, [key]: value }));
        }
        return true;
      } catch {
        return false;
      }
    },

    runScenario: async (payload = {}) => {
      const scenarioRaw = payload.scenario || payload.scenarioId || payload.target || payload.label || 'A';
      const which = String(scenarioRaw).toLowerCase();
      if (which.includes('all')) return await runAllScenarios();
      if (which.includes('b')) return await runSingleScenario(scenarioB, setResultB, 'Scenario B');
      return await runSingleScenario(scenarioA, setResultA, 'Scenario A');
    },

    adoptScenario: async (payload = {}) => {
      const scenarioRaw = payload.scenario || payload.scenarioId || payload.target || payload.label || 'A';
      const which = String(scenarioRaw).toLowerCase();
      const label = which.includes('b') ? 'Scenario B' : 'Scenario A';
      const res = which.includes('b') ? resultB : resultA;
      if (!res) return null;

      try { onAdoptScenario?.(res, label); } catch {}

      return res;
    },
  }), [scenarioA, scenarioB, resultA, resultB, onAdoptScenario]);


  function normalizeApplied(res) {
    // Backend may return in different shapes:
    // { analysis: {...} } or { scenario: { scorecard: {...} } } or direct {...}
    
    const scorecard =
      res?.analysis ||
      res?.scenario?.scorecard ||
      res?.analysis_result ||
      res?.result ||
      res?.scorecard ||
      res?.data ||
      res;
      
    if (!scorecard || typeof scorecard !== 'object') return scorecard;
    
    // Extract ID from various possible locations
    const id =
      scorecard.analysis_id ||
      scorecard.id ||
      res?.analysis_id ||
      res?.id ||
      res?.scenario?.scenario_id ||
      res?.scenario?.id ||
      null;
    
    // Extract scores
    const overall_score = 
      scorecard.overall_score ?? 
      scorecard.jaspen_score ?? 
      res?.overall_score ?? 
      res?.jaspen_score ?? 
      0;
    
    const scores = scorecard.scores || res?.scores || {};
    
    // Extract financial analysis
    const financial_analysis = 
      scorecard.financial_analysis || 
      scorecard.meta?.financial_analysis ||
      res?.financial_analysis ||
      {};
    
    return {
      ...scorecard,
      id,
      analysis_id: id,
      overall_score,
      jaspen_score: overall_score,
      scores,
      financial_analysis,
    };
  }

  function buildDeltas(values) {
    // Only send changed fields to backend as "deltas"
    const deltas = {};
    for (const lever of levers) {
      const baseVal = lever.value;
      const curVal = values[lever.key];
      if (typeof curVal === 'number' && isFinite(curVal) && curVal !== baseVal) {
        const displayMultiplier = Number(lever.display_multiplier) || 1;
        const normalized = curVal / displayMultiplier;
        deltas[lever.key] = normalized; // absolute override value
      }
    }
    return deltas;
  }

  async function runScenario(values, setter, label) {
    if (!threadId) throw new Error('ScenarioModeler: threadId is required');
    setScenarioProgressStage(label, SCENARIO_RUN_STAGES[0]);

    const deltas = buildDeltas(values);

    // If nothing changed, just return baseline (avoid wasting calls)
    if (!deltas || Object.keys(deltas).length === 0) {
      const baseline = baseAnalysis || null;
      setter(baseline);
      return baseline;
    }

    // Resolve existing scenario_id for this slot so we UPDATE instead of creating a duplicate
    const isSlotA = label === 'Scenario A';
    const existingId = isSlotA ? scenarioIdA : scenarioIdB;
    const setSlotId = isSlotA ? setScenarioIdA : setScenarioIdB;

    let scenarioId = existingId;

    if (existingId) {
      // Update existing scenario with new deltas, then re-apply
      try {
        await Jaspen.updateScenario(existingId, {
          thread_id: threadId,
          deltas,
          label,
        });
      } catch (err) {
        console.warn('[ScenarioModeler] updateScenario failed, falling back to create:', err);
        scenarioId = null; // fall through to create path
      }
    }

    if (!scenarioId) {
      setScenarioProgressStage(label, SCENARIO_RUN_STAGES[1]);
      // Create new scenario record
      const created = await Jaspen.createScenario(threadId, {
        deltas,
        label,
        session_id: threadId,
        baseline: baseAnalysis,
      });
      scenarioId =
        created?.scenario_id ||
        created?.id ||
        created?.scenario?.scenario_id ||
        created?.scenario?.id;
      if (!scenarioId) {
        throw new Error('ScenarioModeler: createScenario returned no scenario_id');
      }
      setSlotId(scenarioId);
    } else {
      setScenarioProgressStage(label, SCENARIO_RUN_STAGES[1]);
    }

    // Apply scenario -> derived scorecard snapshot
    setScenarioProgressStage(label, SCENARIO_RUN_STAGES[2]);
    const applied = await Jaspen.applyScenario(scenarioId, threadId);
    const normalized = normalizeApplied(applied);
    setScenarioProgressStage(label, SCENARIO_RUN_STAGES[3]);
    const snapshot = normalized && typeof normalized === 'object'
      ? {
          ...normalized,
          id: normalized.id || normalized.analysis_id || scenarioId,
          label: label || normalized.label || 'Scenario',
        }
      : normalized;

    setter(snapshot);

    try {
      onScenarioSaved?.({
        label,
        snapshot,
        response: { ...applied, scenario_id: scenarioId },
      });
    } catch {}

    if (isSlotA) onResultA?.(snapshot);
    else onResultB?.(snapshot);
    // Running persists the scenario draft/result for this project; "Set Active" promotes it into the Score tab.
    return snapshot;
  }

  async function runSingleScenario(values, setter, label) {
    setBusy(true);
    setActiveScenario(label);
    startScenarioProgress(label);
    try {
      await runScenario(values, setter, label);
      completeScenarioProgress(label);
    } finally {
      setBusy(false);
      setActiveScenario(null);
      clearScenarioProgress(label);
    }
  }

  async function runAllScenarios() {
    setBusy(true);
    setActiveScenario('all');
    startScenarioProgress('Scenario A');
    startScenarioProgress('Scenario B');
    try {
      await Promise.all([
        runScenario(scenarioA, setResultA, 'Scenario A'),
        runScenario(scenarioB, setResultB, 'Scenario B'),
      ]);
      completeScenarioProgress('Scenario A');
      completeScenarioProgress('Scenario B');
    } finally {
      setBusy(false);
      setActiveScenario(null);
      clearScenarioProgress('Scenario A');
      clearScenarioProgress('Scenario B');
    }
  }

  function adoptScenario(result, label) {
    if (!result) return;

    if (typeof onAdoptScenario === 'function') {
      onAdoptScenario(result, label);
    }
  }

  function resetAllToBaseline() {
    setScenarioA(initialValues);
    setScenarioB(initialValues);
    setResultA(null);
    setResultB(null);
    setScenarioIdA(null);
    setScenarioIdB(null);
  }

  function aiScenarioSuggest() {
    setAiSuggestError('');
    setAiSuggestDraft(null);
    setAiSuggestPrompt('');
    setAiSuggestOpen(true);
  }

  async function submitAiSuggestPrompt() {
    const prompt = String(aiSuggestPrompt || '').trim();
    if (!threadId || !prompt || aiSuggestBusy) return;

    setAiSuggestBusy(true);
    setAiSuggestError('');
    try {
      const resp = await Jaspen.generateAiScenario(threadId, {
        prompt,
        commit: false,
        preview: true,
      });
      const suggestion = (resp?.suggestion && typeof resp.suggestion === 'object') ? resp.suggestion : {};
      const deltas = (suggestion?.deltas && typeof suggestion.deltas === 'object')
        ? suggestion.deltas
        : {};
      const rawAdjustments = Array.isArray(resp?.lever_adjustments) ? resp.lever_adjustments : [];
      const adjustments = rawAdjustments.map((row) => {
        const leverId = String(row?.lever_id || '').trim();
        const leverMeta = levers.find((item) => String(item?.key || '') === leverId);
        const label = leverMeta?.label || formatLabel(leverId || 'lever');
        return {
          lever_id: leverId,
          lever_label: label,
          old_value: row?.old_value,
          new_value: row?.new_value,
          reason: row?.reason || '',
          type: leverMeta?.type || inferType(leverId),
        };
      });

      setAiSuggestDraft({
        label: suggestion?.label || resp?.scenario?.label || 'AI Suggested Scenario',
        rationale: resp?.rationale || suggestion?.rationale || suggestion?.summary || '',
        deltas,
        adjustments,
      });
    } catch (err) {
      setAiSuggestError(err?.message || 'Failed to generate AI scenario suggestion');
      setAiSuggestDraft(null);
    } finally {
      setAiSuggestBusy(false);
    }
  }

  async function acceptAiSuggest() {
    if (!threadId || !aiSuggestDraft || aiSuggestBusy) return;
    setAiSuggestBusy(true);
    setAiSuggestError('');
    try {
      const resp = await Jaspen.generateAiScenario(threadId, {
        prompt: aiSuggestPrompt,
        label: aiSuggestDraft.label,
        deltas: aiSuggestDraft.deltas,
        commit: true,
        accept: true,
      });
      const createdScenario = resp?.scenario || null;
      const newScenarioId = resp?.scenario_id || createdScenario?.scenario_id || null;
      const scorecard = normalizeApplied(createdScenario?.result || resp?.preview_scorecard || {});

      // Apply the AI-suggested deltas to the visible lever inputs so the user
      // can see exactly what values were used (mirrors modifyAiSuggest logic).
      if (aiSuggestDraft.deltas && typeof aiSuggestDraft.deltas === 'object') {
        const nextValues = { ...scenarioA };
        Object.entries(aiSuggestDraft.deltas).forEach(([leverId, rawValue]) => {
          const lever = levers.find((item) => String(item?.key || '') === String(leverId));
          const multiplier = Number(lever?.display_multiplier) || 1;
          const numeric = Number(rawValue);
          if (!Number.isFinite(numeric)) return;
          nextValues[leverId] = numeric * multiplier;
        });
        setScenarioA(nextValues);
      }

      if (scorecard && typeof scorecard === 'object') {
        setResultA(scorecard);
        if (newScenarioId) setScenarioIdA(newScenarioId);
        onResultA?.(scorecard);
        try {
          onScenarioSaved?.({
            label: aiSuggestDraft.label || 'Scenario A',
            snapshot: scorecard,
            response: { ...resp, scenario_id: newScenarioId },
          });
        } catch {}
      }
      setAiSuggestOpen(false);
      setAiSuggestDraft(null);
    } catch (err) {
      setAiSuggestError(err?.message || 'Failed to create AI scenario');
    } finally {
      setAiSuggestBusy(false);
    }
  }

  function modifyAiSuggest() {
    if (!aiSuggestDraft || !aiSuggestDraft.deltas) return;
    const nextValues = { ...scenarioA };
    Object.entries(aiSuggestDraft.deltas).forEach(([leverId, rawValue]) => {
      const lever = levers.find((item) => String(item?.key || '') === String(leverId));
      const multiplier = Number(lever?.display_multiplier) || 1;
      const numeric = Number(rawValue);
      if (!Number.isFinite(numeric)) return;
      nextValues[leverId] = numeric * multiplier;
    });
    setScenarioA(nextValues);
    setAiSuggestOpen(false);
  }

  const runAllProgressSummary = useMemo(() => {
    if (activeScenario !== 'all') return '';
    const parts = ['Scenario A', 'Scenario B']
      .map((label) => scenarioProgress[label] ? `${label}: ${scenarioProgress[label]}` : '')
      .filter(Boolean);
    return parts.join(' • ');
  }, [activeScenario, scenarioProgress]);

  if (loading) {
    return <ScenarioModelerSkeleton />;
  }

  return (
    <div>
      <div
        style={{
          background: 'var(--jas-navy)',
          color: 'rgba(255,255,255,0.8)',
          padding: '16px 20px',
          fontSize: 'var(--jas-text-base)',
          lineHeight: 1.5,
          marginBottom: '24px',
        }}
      >
        Adjust key levers to model different scenarios. Run scenarios individually or all at once to
        see projected impact on your Jaspen score.
      </div>

      <div className="jas-scenario-cols" style={{ marginBottom: '24px' }}>
        <BaselineColumn
          metrics={baselineMetrics}
          assumptions={baselineAssumptions}
          contextSignals={baselineContextSignals}
        />

        <ScenarioColumn
          title="Scenario A"
          levers={levers}
          values={scenarioA}
          baselineResult={baseAnalysis}
          insufficientLevers={insufficientLevers}
          onRequestDeeperAnalysis={onRequestDeeperAnalysis}
          onChange={setScenarioA}
          onRun={() => runSingleScenario(scenarioA, setResultA, 'Scenario A')}
          onAdopt={() => adoptScenario(resultA, 'Scenario A')}
          result={resultA}
          disabled={busy}
          running={activeScenario === 'Scenario A'}
          progressMessage={scenarioProgress['Scenario A'] || ''}
        />

        <ScenarioColumn
          title="Scenario B"
          levers={levers}
          values={scenarioB}
          baselineResult={baseAnalysis}
          insufficientLevers={insufficientLevers}
          onRequestDeeperAnalysis={onRequestDeeperAnalysis}
          onChange={setScenarioB}
          onRun={() => runSingleScenario(scenarioB, setResultB, 'Scenario B')}
          onAdopt={() => adoptScenario(resultB, 'Scenario B')}
          result={resultB}
          disabled={busy}
          running={activeScenario === 'Scenario B'}
          progressMessage={scenarioProgress['Scenario B'] || ''}
        />
      </div>

      <div style={{ display: 'flex', gap: '12px', justifyContent: 'center', marginBottom: '20px' }}>
        <Button variant="outline" icon="fa-solid fa-rotate-left" onClick={resetAllToBaseline} disabled={busy}>
          Reset All to Baseline
        </Button>
        <Button variant="outline" icon="fa-solid fa-wand-magic-sparkles" onClick={aiScenarioSuggest} disabled={busy || aiSuggestBusy || !threadId}>
          AI Suggest
        </Button>
        <Button variant="primary" icon="fa-solid fa-play" onClick={runAllScenarios} disabled={busy}>
          {activeScenario === 'all' ? 'Running All...' : 'Run All Scenarios'}
        </Button>
        {(resultA || resultB) && onCompare && (
          <Button variant="outline" onClick={() => onCompare()}>
            Compare Scenarios
          </Button>
        )}
      </div>
      {runAllProgressSummary && (
        <div className="jas-scenario-runall-status" role="status" aria-live="polite">
          <FontAwesomeIcon icon={faSpinner} spin />
          <span>{runAllProgressSummary}</span>
        </div>
      )}

      <div
        style={{
          background: 'var(--jas-navy)',
          color: 'rgba(255,255,255,0.7)',
          padding: '14px 20px',
          fontSize: 'var(--jas-text-sm)',
          lineHeight: 1.5,
        }}
      >
        Adjust values in Scenario A and B, then click "Run" to save your scenario draft and see projected impact.
        <br />
        Scenario drafts are saved to this project automatically. Click "Set Active" only when you want a scenario to appear in the Score tab and drive the score dashboard.
      </div>

      {aiSuggestOpen && (
        <div className="jas-modal-overlay">
          <div className="jas-modal-card" style={{ maxWidth: 860, width: '96%' }}>
            <div className="jas-modal-head">
              <h3>AI Scenario Suggestion</h3>
              <button
                type="button"
                className="jas-ai-mini-btn secondary"
                onClick={() => setAiSuggestOpen(false)}
                disabled={aiSuggestBusy} aria-disabled={aiSuggestBusy}
              >
                Close
              </button>
            </div>

            {!aiSuggestDraft && (
              <div className="jas-modal-body">
                <label htmlFor="ai-suggest-prompt" style={{ display: 'block', fontWeight: 600, marginBottom: 8 }}>
                  Describe what you want to explore
                </label>
                <textarea
                  id="ai-suggest-prompt"
                  placeholder="Describe what you want to explore..."
                  rows={4}
                  value={aiSuggestPrompt}
                  onChange={(event) => setAiSuggestPrompt(event.target.value)}
                  disabled={aiSuggestBusy}
                  style={{ width: '100%' }}
                />
                {aiSuggestError && <p style={{ color: '#b91c1c', marginTop: 8 }}>{aiSuggestError}</p>}
                <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 12 }}>
                  <Button variant="primary" onClick={submitAiSuggestPrompt} disabled={aiSuggestBusy || !String(aiSuggestPrompt || '').trim()}>
                    {aiSuggestBusy ? (
                      <>
                        <FontAwesomeIcon icon={faSpinner} spin /> Generating...
                      </>
                    ) : 'Generate Suggestion'}
                  </Button>
                </div>
              </div>
            )}

            {aiSuggestDraft && (
              <div className="jas-modal-body">
                <div style={{ marginBottom: 10 }}>
                  <strong>{aiSuggestDraft.label}</strong>
                  {aiSuggestDraft.rationale && (
                    <p style={{ margin: '8px 0 0', color: 'var(--jas-gray-700)' }}>{aiSuggestDraft.rationale}</p>
                  )}
                </div>

                <div style={{ maxHeight: 300, overflow: 'auto', border: '1px solid var(--jas-gray-200)', borderRadius: 8 }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
                    <thead>
                      <tr style={{ background: 'var(--jas-gray-50)' }}>
                        <th style={{ textAlign: 'left', padding: 10 }}>Lever</th>
                        <th style={{ textAlign: 'left', padding: 10 }}>Change</th>
                        <th style={{ textAlign: 'left', padding: 10 }}>Reason</th>
                      </tr>
                    </thead>
                    <tbody>
                      {aiSuggestDraft.adjustments.map((row) => (
                        <tr key={row.lever_id}>
                          <td style={{ padding: 10, borderTop: '1px solid var(--jas-gray-200)' }}>{row.lever_label}</td>
                          <td style={{ padding: 10, borderTop: '1px solid var(--jas-gray-200)' }}>
                            {formatValue(row.old_value, row.type)} &rarr; {formatValue(row.new_value, row.type)}
                          </td>
                          <td style={{ padding: 10, borderTop: '1px solid var(--jas-gray-200)' }}>{row.reason || 'AI adjustment'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {aiSuggestError && <p style={{ color: '#b91c1c', marginTop: 8 }}>{aiSuggestError}</p>}
                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 12 }}>
                  <Button variant="outline" onClick={modifyAiSuggest} disabled={aiSuggestBusy}>
                    Modify
                  </Button>
                  <Button variant="primary" onClick={acceptAiSuggest} disabled={aiSuggestBusy}>
                    {aiSuggestBusy ? (
                      <>
                        <FontAwesomeIcon icon={faSpinner} spin /> Creating...
                      </>
                    ) : 'Accept & Create'}
                  </Button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
});

export default ScenarioModeler;
