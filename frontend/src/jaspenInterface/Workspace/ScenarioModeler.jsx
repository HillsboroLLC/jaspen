// ============================================================================
// File: src/pages/Jaspen/ScenarioModeler.jsx
// Purpose: DYNAMIC - Extracts fields from baseline, displays in 3 columns
//          NOW WIRED to backend scenario endpoints (no mockResult / no delays)
// ============================================================================
import React, { useState, useMemo, useEffect, forwardRef, useImperativeHandle } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faSpinner, faPlay, faCheck } from '@fortawesome/free-solid-svg-icons';
import { Jaspen } from './JaspenClient';
import Button from './workspaceUi/components/Button';
import { ScenarioModelerSkeleton } from '../../shared/components/SkeletonLoader';

// ============================================================================
// HELPER: Extract editable levers from baseAnalysis
// ============================================================================
function extractLevers(baseAnalysis) {
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

  const levers = [];
  const seen = new Set();

  for (const [key, value] of Object.entries(combined)) {
    if (EXCLUDED.includes(key)) continue;
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

  // Fallback: if backend inputs are sparse, allow editing of baseline metrics directly.
  if (levers.length === 0) {
    const baselineMetrics = buildMetricRows(baseAnalysis);
    baselineMetrics.forEach((metric) => {
      if (!metric?.key || seen.has(metric.key)) return;
      const value = Number(metric.value);
      if (!Number.isFinite(value)) return;

      const spread = metric.type === 'percentage'
        ? 10
        : Math.max(Math.abs(value) * 0.5, 1);

      const step = metric.type === 'currency'
        ? Math.max(100, Math.round((Math.abs(value) * 0.02) / 100) * 100 || 100)
        : metric.type === 'percentage'
          ? 0.5
          : metric.type === 'months'
            ? 1
            : Math.max(1, Math.round(Math.abs(value) * 0.05) || 1);

      levers.push({
        key: metric.key,
        label: metric.label || formatLabel(metric.key),
        value,
        min: metric.type === 'percentage' ? Math.max(0, value - spread) : value - spread,
        max: value + spread,
        step,
        type: metric.type || inferType(metric.key, value),
      });
    });
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
    lowerKey.includes('value')
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
    lowerKey.includes('margin')
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
      return `${n.toFixed(1)}%`;
    default:
      return n.toLocaleString();
  }
}

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

function buildScenarioMetricRows(result = {}, baselineMetrics = []) {
  if (!result) return [];
  const keys = Array.isArray(baselineMetrics) ? baselineMetrics.map((m) => m.key) : [];
  const fromBaseline = keys
    .map((key) => {
      const value = getMetricValue(result, key);
      if (value == null) return null;
      return {
        key,
        label: formatLabel(key),
        type: inferType(key),
        value,
      };
    })
    .filter(Boolean);
  if (fromBaseline.length > 0) return fromBaseline;
  return buildMetricRows(result);
}

// ============================================================================
// BASELINE COLUMN (Read-only)
// ============================================================================
function BaselineColumn({ result, metrics }) {
  const rows = Array.isArray(metrics) ? metrics : [];
  return (
    <div className="jas-scenario-col">
      <div className="jas-scenario-header">
        Baseline
        <span className="jas-scenario-badge">Current</span>
      </div>
      <div className="jas-scenario-body">
        {rows.length > 0 ? (
          rows.map((metric) => (
            <div key={metric.key} className="jas-scenario-field">
              <span style={{ color: 'var(--jas-navy)' }}>{metric.label}</span>
              <span style={{ color: 'var(--jas-gray-500)', fontWeight: 500 }}>
                {formatValue(metric.value, metric.type)}
              </span>
            </div>
          ))
        ) : (
          <div className="jas-scenario-field">
            <span style={{ color: 'var(--jas-gray-500)' }}>No baseline financial metrics available</span>
            <span style={{ color: 'var(--jas-gray-500)', fontWeight: 500 }}>—</span>
          </div>
        )}
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
  baselineValues,
  baselineMetrics,
  onChange,
  onRun,
  onAdopt,
  result,
  disabled,
  running,
}) {
  const scenarioMetricRows = useMemo(
    () => buildScenarioMetricRows(result, baselineMetrics),
    [result, baselineMetrics]
  );

  const calculateDelta = (currentValue, baselineValue, type) => {
    if (baselineValue == null || currentValue == null) return '—';
    const diff = Number(currentValue) - Number(baselineValue);
    if (!isFinite(diff) || diff === 0) return type === 'months' ? '0 mo' : '$0';
    const formatted = formatValue(Math.abs(diff), type);
    return diff > 0 ? `+${formatted}` : `-${formatted}`;
  };

  const getDeltaClass = (delta) => {
    if (delta.startsWith('+')) return 'positive';
    if (delta.startsWith('-') && delta !== '—') return 'negative';
    return '';
  };

  return (
    <div className="jas-scenario-col">
      <div className="jas-scenario-header">{title}</div>

      <div className="jas-scenario-body" style={{ minHeight: '180px' }}>
        {levers.length === 0 && (
          <div className="jas-scenario-field">
            <span style={{ color: 'var(--jas-gray-500)' }}>
              No editable baseline levers are available for this scorecard yet.
            </span>
            <span style={{ color: 'var(--jas-gray-500)', fontWeight: 500 }}>—</span>
          </div>
        )}

        {levers.map(lever => {
          const currentValue = values[lever.key] ?? lever.value;
          const delta = calculateDelta(currentValue, lever.value, lever.type);

          return (
            <div key={lever.key} className="input-group">
              <label className="input-label">{lever.label}</label>
              <div className="input-wrapper">
                <input
                  type="number"
                  className="input-field"
                  value={currentValue}
                  min={lever.min}
                  max={lever.max}
                  step={lever.step ?? (lever.type === 'currency' ? 1000 : lever.type === 'percentage' ? 0.1 : 1)}
                  onChange={(e) => onChange({ ...values, [lever.key]: Number(e.target.value) })}
                  disabled={disabled}
                />
                <span className={`input-delta ${getDeltaClass(delta)}`}>{delta}</span>
              </div>
            </div>
          );
        })}

        {result && (
          <div className="results-box">
            {scenarioMetricRows.map((metric) => (
              <div key={metric.key} className="result-row">
                <span className="result-label">{metric.label}</span>
                <span className="result-value">{formatValue(metric.value, metric.type)}</span>
              </div>
            ))}

            <div className="result-score">
              <div className="result-score-label">Jaspen Score</div>
              <div className="result-score-value">
                {result?.overall_score ?? result?.jaspen_score ?? '—'}
              </div>
              <div className="result-score-change">
                {typeof result?.overall_score === 'number' &&
                 typeof baselineValues?.overall_score === 'number'
                  ? (() => {
                      const delta = result.overall_score - baselineValues.overall_score;
                      return `${delta > 0 ? '+' : ''}${delta} points`;
                    })()
                  : typeof result?.jaspen_score === 'number' &&
                    typeof baselineValues?.jaspen_score === 'number'
                  ? (() => {
                      const delta = result.jaspen_score - baselineValues.jaspen_score;
                      return `${delta > 0 ? '+' : ''}${delta} points`;
                    })()
                  : 'New Score'}
              </div>
            </div>
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
          <FontAwesomeIcon icon={faCheck} /> Adopt
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
  scenarioLevers = [],
  refreshVersion = 0,
  onAdopt,
  onAdoptScenario = () => {},
  onAdoptScorecard = () => {},
  onResultA = () => {},
  onResultB = () => {},
  onCompare,
  loading = false,
}, ref) {
  // Determine threadId robustly (keep backward compatibility)
  const threadId =
    baseAnalysis?.thread_id ||
    baseAnalysis?.session_id ||
    baseAnalysis?.meta?.thread_id ||
    analysisId;

  // DEBUG: Log what baseAnalysis prop ScenarioModeler receives
  console.log('[ScenarioModeler] baseAnalysis prop:', baseAnalysis);
  console.log('[ScenarioModeler] baseAnalysis.meta?', baseAnalysis?.meta);
  console.log('[ScenarioModeler] baseAnalysis.meta.extracted_levers?', baseAnalysis?.meta?.extracted_levers);
  console.log('[ScenarioModeler] baseAnalysis.inputs?', baseAnalysis?.inputs);
  console.log('[ScenarioModeler] baseAnalysis.compat?', baseAnalysis?.compat);
  console.log('[ScenarioModeler] derived threadId:', threadId);

  const [baselineLevers, setBaselineLevers] = useState([]);
  const baselineMetrics = useMemo(() => buildMetricRows(baseAnalysis), [baseAnalysis]);

  const levers = useMemo(() => {
    if (baselineLevers.length > 0) {
      console.log('[ScenarioModeler.levers] using baselineLevers from API:', baselineLevers.length, 'levers');
      return baselineLevers;
    }
    const normalized = normalizeScenarioLevers(scenarioLevers);
    if (normalized.length > 0) {
      console.log('[ScenarioModeler.levers] using scenarioLevers prop:', normalized.length, 'levers');
      return normalized;
    }
    const extracted = extractLevers(baseAnalysis);
    console.log('[ScenarioModeler.levers] using extractLevers() fallback:', extracted.length, 'levers');
    console.log('[ScenarioModeler.levers] extractLevers found:', extracted.map(l => l.key));
    return extracted;
  }, [baselineLevers, scenarioLevers, baseAnalysis]);

  const initialValues = useMemo(() => {
    const vals = {};
    levers.forEach(lever => { vals[lever.key] = lever.value; });
    return vals;
  }, [levers]);

  const [scenarioA, setScenarioA] = useState(initialValues);
  const [scenarioB, setScenarioB] = useState(initialValues);

  useEffect(() => {
    setScenarioA(initialValues);
    setScenarioB(initialValues);
  }, [initialValues]);

  // Fetch lever schema from backend
  useEffect(() => {
    if (!threadId) return;

    async function fetchLevers() {
      try {
        console.log('[ScenarioModeler.fetchLevers] calling Jaspen.getLevers for threadId:', threadId);
        const response = await Jaspen.getLevers(threadId);
        console.log('[ScenarioModeler.fetchLevers] response:', response);
        console.log('[ScenarioModeler.fetchLevers] response.levers?', response?.levers);
        if (response?.levers && Array.isArray(response.levers)) {
          const normalized = normalizeScenarioLevers(response.levers);
          console.log('[ScenarioModeler.fetchLevers] normalized levers:', normalized);
          setBaselineLevers(normalized);
        } else {
          console.warn('[ScenarioModeler.fetchLevers] No levers array in response, will fall back to extractLevers');
        }
      } catch (err) {
        console.warn('[ScenarioModeler.fetchLevers] API call failed, using extracted levers:', err);
      }
    }

    fetchLevers();
  }, [threadId, refreshVersion]);

  const [resultA, setResultA] = useState(null);
  const [resultB, setResultB] = useState(null);

  const [busy, setBusy] = useState(false);
  const [activeScenario, setActiveScenario] = useState(null);
  const [aiSuggestOpen, setAiSuggestOpen] = useState(false);
  const [aiSuggestPrompt, setAiSuggestPrompt] = useState('');
  const [aiSuggestBusy, setAiSuggestBusy] = useState(false);
  const [aiSuggestDraft, setAiSuggestDraft] = useState(null);
  const [aiSuggestError, setAiSuggestError] = useState('');

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

      // Prefer parent handlers
      try { onAdopt?.(res, label); } catch {}
      try { onAdoptScorecard?.(res); } catch {}

      return res;
    },
  }), [scenarioA, scenarioB, resultA, resultB, onAdopt, onAdoptScorecard]);


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
    console.log('[ScenarioModeler] runScenario called', { values, label, threadId });
    if (!threadId) throw new Error('ScenarioModeler: threadId is required');

    const deltas = buildDeltas(values);
    console.log('[ScenarioModeler] Built deltas:', deltas);
    console.log('[ScenarioModeler] baseAnalysis:', baseAnalysis);

    // If nothing changed, just return baseline (avoid wasting calls)
    if (!deltas || Object.keys(deltas).length === 0) {
      console.log('[ScenarioModeler] No changes, returning baseline');
      const baseline = baseAnalysis || null;
      setter(baseline);
      return baseline;
    }

    // 1) Create scenario (baseline sent so backend can store it for apply)
    console.log('[ScenarioModeler] Creating scenario with:', { 
      threadId, 
      deltas, 
      label,
      baseline: baseAnalysis 
    });
    let created;
    try {
      created = await Jaspen.createScenario(threadId, {
        deltas,
        label,
        session_id: threadId,
        baseline: baseAnalysis,
      });
      console.log('[ScenarioModeler] Created scenario:', created);
    } catch (err) {
      console.error('[ScenarioModeler] Failed:', err);
      throw err;
    }

    const scenarioId =
      created?.scenario_id ||
      created?.id ||
      created?.scenario?.scenario_id ||
      created?.scenario?.id;

    if (!scenarioId) {
      throw new Error('ScenarioModeler: createScenario returned no scenario_id');
    }

    // 2) Apply scenario -> derived scorecard snapshot
    const applied = await Jaspen.applyScenario(scenarioId, threadId);
    const normalized = normalizeApplied(applied);
    const snapshot = normalized && typeof normalized === 'object'
      ? {
          ...normalized,
          id: normalized.id || normalized.analysis_id || scenarioId,
          label: label || normalized.label || 'Scenario',
        }
      : normalized;

setter(snapshot);

if (label === 'Scenario A') onResultA?.(snapshot);
if (label === 'Scenario B') onResultB?.(snapshot);
// DON'T auto-adopt - only adopt when user clicks "Adopt" button
    return snapshot;
  }

  async function runSingleScenario(values, setter, label) {
    setBusy(true);
    setActiveScenario(label);
    try {
      await runScenario(values, setter, label);
    } finally {
      setBusy(false);
      setActiveScenario(null);
    }
  }

  async function runAllScenarios() {
    setBusy(true);
    setActiveScenario('all');
    try {
      await Promise.all([
        runScenario(scenarioA, setResultA, 'Scenario A'),
        runScenario(scenarioB, setResultB, 'Scenario B'),
      ]);
    } finally {
      setBusy(false);
      setActiveScenario(null);
    }
  }

  function adoptScenario(result, label) {
    if (!result) return;

    // Call parent adoption handler (new)
    if (typeof onAdoptScenario === 'function') {
      onAdoptScenario(result, label);
    }

    // Legacy handlers (keep for backward compat)
    onAdopt?.(result);
    onAdoptScorecard?.({
      ...result,
      id: result.id || result.analysis_id,
      label: label || result.label || 'Scenario',
      isBaseline: false,
    });
  }

  function resetAllToBaseline() {
    setScenarioA(initialValues);
    setScenarioB(initialValues);
    setResultA(null);
    setResultB(null);
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
      const scorecard = normalizeApplied(createdScenario?.result || resp?.preview_scorecard || {});
      if (scorecard && typeof scorecard === 'object') {
        setResultA(scorecard);
        onResultA?.(scorecard);
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
        <BaselineColumn result={baseAnalysis} metrics={baselineMetrics} />

        <ScenarioColumn
          title="Scenario A"
          levers={levers}
          values={scenarioA}
          baselineValues={baseAnalysis}
          baselineMetrics={baselineMetrics}
          onChange={setScenarioA}
          onRun={() => runSingleScenario(scenarioA, setResultA, 'Scenario A')}
          onAdopt={() => adoptScenario(resultA, 'Scenario A')}
          result={resultA}
          disabled={busy}
          running={activeScenario === 'Scenario A'}
        />

        <ScenarioColumn
          title="Scenario B"
          levers={levers}
          values={scenarioB}
          baselineValues={baseAnalysis}
          baselineMetrics={baselineMetrics}
          onChange={setScenarioB}
          onRun={() => runSingleScenario(scenarioB, setResultB, 'Scenario B')}
          onAdopt={() => adoptScenario(resultB, 'Scenario B')}
          result={resultB}
          disabled={busy}
          running={activeScenario === 'Scenario B'}
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

      <div
        style={{
          background: 'var(--jas-navy)',
          color: 'rgba(255,255,255,0.7)',
          padding: '14px 20px',
          fontSize: 'var(--jas-text-sm)',
          lineHeight: 1.5,
        }}
      >
        Adjust values in Scenario A and B, then click "Run" to see projected impact.
        <br />
        After running, click "Adopt" to apply that scenario as your current analysis.
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
                disabled={aiSuggestBusy}
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
