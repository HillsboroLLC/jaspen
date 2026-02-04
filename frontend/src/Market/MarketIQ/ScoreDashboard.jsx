// ============================================================================
// File: ScoreDashboard.jsx (Dynamic Metrics - Updated)
// Purpose: Render dynamic metrics from backend instead of hardcoded NPV/IRR/Payback
// Colors: Navy (#161f3b) and Light Blue (#eff9fc)
// ============================================================================
import React, { useMemo, useState } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faChevronDown, faChartPie, faLightbulb, faDollarSign,
  faCalculator, faChartArea, faBuilding, faClipboardCheck,
  faExclamationTriangle, faCheckCircle, faInfoCircle,
  faChartLine, faBalanceScale
} from '@fortawesome/free-solid-svg-icons';

import './ScoreDashboard.css';

export default function ScoreDashboard({
  analysisResult,
  onBackToMain,
  onOpenExplore,
  onOpenChat,
  onOpenScenario,
  onConvertToProject,
  onOpenThreadEdit = null,
  scoreCommentary = null,

  // PROMPT ALIGNMENT: Scorecard snapshot props
  scorecardSnapshots = [],
  selectedScorecardId = null,
  onSelectScorecard = null,
  baselineScorecardId = null,
  threadBundleId = null,
  onBeginProject = null,

  // Legacy variant props (keep for backward compat)
  scoreVariants = [],
  selectedVariantId = null,
  onSelectVariant = null,
}) {
  // If snapshots are provided, render the selected snapshot as the source of truth.
  const selectedSnapshot = useMemo(() => {
    if (!Array.isArray(scorecardSnapshots) || !selectedScorecardId) return null;
    return scorecardSnapshots.find(s => s?.id === selectedScorecardId) || null;
  }, [scorecardSnapshots, selectedScorecardId]);

  const result = selectedSnapshot || analysisResult || {};
  const score = result.market_iq_score || 0;
  const category = result.score_category || 'Unknown';
  const componentScores = result.component_scores || {};
  const financialImpact = result.financial_impact || {};
  const insights = result.key_insights || [];
  const risks = result.top_risks || result.risks || [];
  const recommendations = result.recommendations || [];
  
  // NEW: Dynamic metrics from backend
  const metrics = result.metrics || {};
  const hasMetrics = Object.keys(metrics).length > 0;
  
  // Before/After financial data
  const beforeAfter = result.before_after_financials || {};
  const before = beforeAfter.before || {};
  const after = beforeAfter.after || {};

  // Investment Analysis
  const investmentAnalysis = result.investment_analysis || {};
  const hasInvestmentData = Object.keys(investmentAnalysis).length > 0;
  
  // NPV/IRR Analysis
  const npvIrrAnalysis = result.npv_irr_analysis || {};
  const hasNpvData = Object.keys(npvIrrAnalysis).length > 0;
  
  // Valuation
  const valuation = result.valuation || {};
  const hasValuationData = Object.keys(valuation).length > 0;
  
// Decision Framework (supports object or JSON string)
const dfRaw =
  result.decision_framework ?? result.strategic_decision_framework ?? null;

const decisionFramework =
  typeof dfRaw === 'string'
    ? (() => { try { return JSON.parse(dfRaw); } catch { return null; } })()
    : (dfRaw && typeof dfRaw === 'object' ? dfRaw : null);

const hasDecisionData = !!(decisionFramework && Object.keys(decisionFramework).length);

  const projectName =
    result.project_name ||
    (result.compat && result.compat.title) ||
    'Untitled Project';

  const extractNumber = (v) => {
    if (v === null || v === undefined || v === '') return null;
    if (typeof v === 'number' && Number.isFinite(v)) return v;
    const n = Number(String(v).replace(/[^\d.-]/g, ''));
    return Number.isFinite(n) ? n : null;
  };

  const normalizeInputs = () => {
    const rawInputs = result.inputs && typeof result.inputs === 'object' ? result.inputs : {};
    const compatInputs = result.compat && typeof result.compat === 'object' ? result.compat : {};
    return { ...rawInputs, ...compatInputs };
  };

  const buildSmartExplanations = () => {
    const inputs = normalizeInputs();
    const fin = inputs.financial_metrics && typeof inputs.financial_metrics === 'object'
      ? inputs.financial_metrics
      : {};

    const budget = extractNumber(inputs.budget?.amount ?? inputs.budget);
    const timeline = extractNumber(inputs.timeline_months ?? inputs.timeline);
    const revenueTarget = extractNumber(inputs.revenue_target ?? fin.revenue_target);
    const margin = extractNumber(inputs.margin_percent ?? fin.margin ?? fin.margin_percent);
    const churn = extractNumber(inputs.churn_rate ?? fin.churn_rate);
    const pricePoint = extractNumber(inputs.price_point);
    const teamSize = extractNumber(inputs.team);
    const targetMarket = inputs.target_market || '';
    const competition = inputs.competition || '';
    const businessDescription = inputs.business_description || '';

    const toPercent = (v) => {
      if (v === null || v === undefined) return null;
      const n = Number(v);
      if (!Number.isFinite(n)) return null;
      return n <= 1 ? n * 100 : n;
    };

    const marginPct = toPercent(margin);
    const churnPct = toPercent(churn);

    const parts = [];
    if (revenueTarget != null) parts.push(`Revenue target ~${formatCurrency(revenueTarget)}`);
    if (marginPct != null) parts.push(`Margins ~${formatPercent(marginPct)}`);
    if (churnPct != null) parts.push(`Churn ~${formatPercent(churnPct)}`);
    if (budget != null) parts.push(`Budget ~${formatCurrency(budget)}`);
    if (timeline != null) parts.push(`Timeline ~${timeline} months`);

    const overall = parts.length > 0
      ? `Based on your inputs (${parts.join(', ')}), the overall score reflects a balanced profile with clear strengths and a few gaps to address.`
      : `The overall score reflects your current inputs and highlights both strengths and areas to improve.`;

    const byCategory = {
      financial_health: (() => {
        const bits = [];
        if (revenueTarget != null) bits.push(`Revenue target ${formatCurrency(revenueTarget)}`);
        if (marginPct != null) bits.push(`Margins ${formatPercent(marginPct)}`);
        if (churnPct != null) bits.push(`Churn ${formatPercent(churnPct)}`);
        if (pricePoint != null) bits.push(`Price point ${formatCurrency(pricePoint)}`);
        return bits.length
          ? `Financial health reflects ${bits.join(', ')}.`
          : `Financial health reflects the available revenue, margin, and churn inputs.`;
      })(),
      market_position: (() => {
        const bits = [];
        if (targetMarket) bits.push(`Target market: ${targetMarket}`);
        if (competition) bits.push(`Competition: ${competition}`);
        if (businessDescription) bits.push(`Positioning: ${businessDescription}`);
        return bits.length
          ? `Market position is based on ${bits.join('. ')}.`
          : `Market position reflects your stated market and competitive context.`;
      })(),
      operational_efficiency: (() => {
        const bits = [];
        if (timeline != null) bits.push(`Timeline ${timeline} months`);
        if (teamSize != null) bits.push(`Team size ${teamSize}`);
        return bits.length
          ? `Operational efficiency considers ${bits.join(', ')}.`
          : `Operational efficiency is based on the available execution and ops inputs.`;
      })(),
      execution_readiness: (() => {
        const bits = [];
        if (timeline != null) bits.push(`Timeline ${timeline} months`);
        if (teamSize != null) bits.push(`Team size ${teamSize}`);
        if (budget != null) bits.push(`Budget ${formatCurrency(budget)}`);
        return bits.length
          ? `Execution readiness reflects ${bits.join(', ')}.`
          : `Execution readiness reflects your stated timeline, team, and funding inputs.`;
      })(),
    };

    return { overall, byCategory };
  };

  const getScoreColor = (s) => {
    if (s >= 80) return '#161f3b';
    if (s >= 60) return '#161f3b';
    if (s >= 40) return '#161f3b';
    return '#161f3b';
  };

  const getScoreLabel = (s) => {
    if (s >= 80) return 'Excellent';
    if (s >= 60) return 'Good';
    if (s >= 40) return 'Fair';
    return 'At Risk';
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

  const formatNumber = (v) => {
    if (v === null || v === undefined || v === '') return 'N/A';
    const n = Number(String(v).replace(/[^\d.-]/g, ''));
    if (isNaN(n)) return 'N/A';
    return n.toLocaleString();
  };

  const formatPercent = (v) => {
    if (v === null || v === undefined || v === '') return 'N/A';
    const n = Number(String(v).replace(/[^\d.-]/g, ''));
    if (isNaN(n)) return 'N/A';
    return `${n.toFixed(1)}%`;
  };

  const formatLabel = (k) =>
    String(k || '')
      .replace(/_/g, ' ')
      .replace(/\b\w/g, (l) => l.toUpperCase());

  const formatGenericValue = (v) => {
    if (v === null || v === undefined || v === '') return 'N/A';
    if (typeof v === 'number') return formatNumber(v);
    if (typeof v === 'boolean') return v ? 'Yes' : 'No';
    if (typeof v === 'string') return v;
    try { return JSON.stringify(v); } catch { return String(v); }
  };

  const calculateChange = (beforeVal, afterVal) => {
    if (!beforeVal || !afterVal) return { value: 'N/A', percent: 'N/A', isPositive: null };
    const b = Number(String(beforeVal).replace(/[^\d.-]/g, ''));
    const a = Number(String(afterVal).replace(/[^\d.-]/g, ''));
    if (isNaN(b) || isNaN(a)) return { value: 'N/A', percent: 'N/A', isPositive: null };
    
    const change = a - b;
    const percentChange = b !== 0 ? ((change / b) * 100) : 0;
    const isPositive = change > 0;
    
    return {
      value: change,
      percent: percentChange,
      isPositive,
      formatted: (isPositive ? '+' : '') + formatCurrency(change),
      percentFormatted: (isPositive ? '+' : '') + percentChange.toFixed(1) + '%'
    };
  };

  // Component weights
  const componentWeights = {
    financial_health: 0.30,
    operational_efficiency: 0.20,
    market_position: 0.30,
    execution_readiness: 0.20
  };

  const componentEntries = useMemo(() => {
    return Object.entries(componentScores).map(([key, value]) => {
      const weight = componentWeights[key] || 0.25;
      const contribution = (value * weight).toFixed(1);
      return { key, value, weight, contribution };
    });
  }, [componentScores]);

  const scoreColor = getScoreColor(score);
  const scoreLabel = getScoreLabel(score);
  const backendExplanations =
    result.score_explanations ||
    result.score_explanation ||
    result.scorecard_explanations ||
    null;

  const backendOverall =
    backendExplanations?.overall ||
    result.overall_assessment ||
    result.score_summary ||
    '';

  const backendByCategory =
    backendExplanations?.by_category ||
    backendExplanations?.categories ||
    result.component_explanations ||
    {};

  const smartExplanations = buildSmartExplanations();

  const overallCommentary =
    backendOverall ||
    smartExplanations.overall ||
    (scoreCommentary && scoreCommentary.overall) ||
    '';

  const commentaryByCategory = {
    ...(scoreCommentary?.byCategory || {}),
    ...(smartExplanations.byCategory || {}),
    ...(backendByCategory && typeof backendByCategory === 'object' ? backendByCategory : {}),
  };

  // NEW: Flatten all metrics into a single array for rendering
  const allMetrics = useMemo(() => {
    const flattened = [];
    Object.entries(metrics).forEach(([category, metricArray]) => {
      if (Array.isArray(metricArray)) {
        metricArray.forEach(metric => {
          flattened.push({
            ...metric,
            category: category.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())
          });
        });
      }
    });
    return flattened;
  }, [metrics]);

  const scoresObject = result.scores || result.component_scores || {};
  const hasScores = Object.keys(scoresObject).length > 0;
  const hasFinancialImpact = Object.keys(financialImpact).length > 0;

  const extraSections = useMemo(() => {
    const ignoreKeys = new Set([
      'market_iq_score',
      'score_category',
      'component_scores',
      'scores',
      'financial_impact',
      'key_insights',
      'top_risks',
      'risks',
      'recommendations',
      'metrics',
      'before_after_financials',
      'investment_analysis',
      'npv_irr_analysis',
      'valuation',
      'decision_framework',
      'strategic_decision_framework',
      'project_name',
      'compat',
      'analysis_id',
      'id',
      'label',
      'isBaseline',
      'createdAt',
      'selected_scorecard_id',
      'baseline_scorecard_id',
      'scorecard_snapshots',
      '_baseline_scorecard',
      'status',
      'chat_history',
      'collected_data',
      'readiness',
      'conversation_history',
    ]);

    return Object.entries(result).filter(([key, value]) => {
      if (ignoreKeys.has(key)) return false;
      if (value === null || value === undefined) return false;
      return typeof value === 'object';
    });
  }, [result]);

  if (!selectedSnapshot && !analysisResult) return <div>No analysis result available</div>;

  return (
    <div className="score-dashboard-container">
  {/* Variant switcher (Baseline / Scenario A–C) */}
  {/* PROMPT ALIGNMENT: Scorecard Snapshot Selector */}
  <div style={{
    display: 'flex',
    justifyContent: 'flex-end',
    marginBottom: '12px',
    alignItems: 'center'
  }}>
    {Array.isArray(scorecardSnapshots) && scorecardSnapshots.length > 1 && (
      <>
        <label htmlFor="miq-variant-select" style={{ fontSize: 12, marginRight: 8, color: '#4b5563' }}>
          View:
        </label>
        <select
          id="miq-variant-select"
          value={selectedScorecardId ?? ''}
          onChange={(e) => onSelectScorecard && onSelectScorecard(e.target.value)}
          style={{
            padding: '8px 10px',
            borderRadius: 8,
            border: '1px solid #e5e7eb',
            background: '#fff',
            fontSize: 14
          }}
        >
          {scorecardSnapshots.map(v => (
            <option key={v.id} value={v.id}>{v.label}</option>
          ))}
        </select>
      </>
    )}
    {onOpenThreadEdit && (
      <button
        type="button"
        onClick={onOpenThreadEdit}
        style={{
          marginLeft: Array.isArray(scorecardSnapshots) && scorecardSnapshots.length > 1 ? 12 : 0,
          border: 'none',
          background: 'transparent',
          color: '#161f3b',
          fontWeight: 700,
          fontSize: 13,
          textDecoration: 'underline',
          cursor: 'pointer',
          padding: 0
        }}
      >
        Edit
      </button>
    )}
  </div>

      {/* Top Summary Section */}
      <div className="summary-section">
        <div className="summary-grid">
          <div className="score-display">
            <div className="score-label">Market IQ Score</div>
            <div className="score-value">{score}</div>
            <div className="score-badge">{scoreLabel}</div>
            {overallCommentary && (
              <div className="score-commentary">{overallCommentary}</div>
            )}
          </div>

          <div className="summary-impact">
            <div className="summary-impact-title">Financial Impact</div>
            {hasFinancialImpact ? (
              <table className="data-table summary-impact-table">
                <tbody>
                  {Object.entries(financialImpact).map(([key, value]) => (
                    value === null || value === undefined ? null : (
                      <tr key={key}>
                        <td className="label">{formatLabel(key)}</td>
                        <td className="value">{formatCurrency(value)}</td>
                      </tr>
                    )
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="summary-impact-empty">No financial impact available</div>
            )}
          </div>
        </div>
      </div>

      {/* Main Content - Table Sections */}
      <div className="scorecard-body">
        {hasMetrics && allMetrics.length > 0 && (
          <div className="table-section">
            <div className="section-header">Key Metrics</div>
            <div className="key-metrics">
              {allMetrics.map((metric, idx) => (
                <div key={idx} className="metric-card">
                  <div className="metric-label">{metric.label}</div>
                  <div className="metric-value">{metric.value}</div>
                  <div className="metric-description">{metric.category}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {hasScores && (
          <div className="table-section">
            <div className="section-header">Scores</div>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Score</th>
                  <th>Value</th>
                  <th>Explanation</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(scoresObject).map(([key, value]) => (
                  <tr key={key}>
                    <td className="label">{formatLabel(key)}</td>
                    <td className="value">{formatNumber(value)}</td>
                    <td className="explanation">
                      {commentaryByCategory[key] || '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Strategic Decision Framework */}
        {hasDecisionData && (
          <div className="table-section">
            <div className="section-header">Strategic Decision Framework</div>
            <table className="checklist-table">
              <tbody>
                {[
                  ['acceptable_payback',   'Acceptable Payback'],
                  ['irr_above_hurdle',     'IRR Above Hurdle'],
                  ['npv_positive',         'NPV Positive'],
                  ['strategic_alignment',  'Strategic Alignment'],
                  ['robust_sensitivity',   'Robust Sensitivity'],
                ].map(([key, label]) => {
                  const yes = !!decisionFramework?.[key];
                  return (
                    <tr key={key}>
                      <td className="criteria">{label}</td>
                      <td className="status">
                        <span className="status-badge">{yes ? 'YES' : 'NO'}</span>
                      </td>
                      <td>{yes ? 'Criteria met' : 'Criteria not met'}</td>
                    </tr>
                  );
                })}
                {decisionFramework?.overall_recommendation && (
                  <tr>
                    <td className="criteria">Overall Recommendation</td>
                    <td className="status">
                      <span className="status-badge">
                        {decisionFramework.overall_recommendation === 'Go' || 
                         decisionFramework.overall_recommendation === 'YES' ? 'YES' : 'NO'}
                      </span>
                    </td>
                    <td>{decisionFramework.overall_recommendation}</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}

        {/* Investment Analysis */}
        {hasInvestmentData && (
          <div className="table-section">
            <div className="section-header">Investment Analysis</div>
            <table className="data-table">
              <tbody>
                {investmentAnalysis.initial_investment && (
                  <tr>
                    <td className="label">Initial Investment</td>
                    <td className="value">{formatCurrency(investmentAnalysis.initial_investment)}</td>
                  </tr>
                )}
                {investmentAnalysis.payback_period && (
                  <tr>
                    <td className="label">Payback Period</td>
                    <td className="value">{investmentAnalysis.payback_period.toFixed(1)} years</td>
                  </tr>
                )}
                {investmentAnalysis.roi && (
                  <tr>
                    <td className="label">Return on Investment (ROI)</td>
                    <td className="value">{formatPercent(investmentAnalysis.roi)}</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}

        {/* NPV & IRR Analysis */}
        {hasNpvData && (
          <div className="table-section">
            <div className="section-header">NPV & IRR Analysis</div>
            <table className="data-table">
              <tbody>
                {npvIrrAnalysis.npv && (
                  <tr>
                    <td className="label">Net Present Value (NPV)</td>
                    <td className="value">{formatCurrency(npvIrrAnalysis.npv)}</td>
                  </tr>
                )}
                {npvIrrAnalysis.irr && (
                  <tr>
                    <td className="label">Internal Rate of Return (IRR)</td>
                    <td className="value">{formatPercent(npvIrrAnalysis.irr * 100)}</td>
                  </tr>
                )}
                {npvIrrAnalysis.discount_rate && (
                  <tr>
                    <td className="label">Discount Rate</td>
                    <td className="value">{formatPercent(npvIrrAnalysis.discount_rate * 100)}</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}

        {/* Valuation */}
        {hasValuationData && (
          <div className="table-section">
            <div className="section-header">Valuation</div>
            <table className="data-table">
              <tbody>
                {valuation.enterprise_value && (
                  <tr>
                    <td className="label">Enterprise Value</td>
                    <td className="value">{formatCurrency(valuation.enterprise_value)}</td>
                  </tr>
                )}
                {valuation.multiple && (
                  <tr>
                    <td className="label">EBITDA Multiple</td>
                    <td className="value">{valuation.multiple}x</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}

        {/* Before vs After Financial Analysis */}
        {(before.revenue || after.revenue) && (
          <div className="table-section">
            <div className="section-header">Before vs After Financial Analysis</div>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Metric</th>
                  <th style={{textAlign: 'center'}}>Before</th>
                  <th style={{textAlign: 'center'}}>After</th>
                  <th style={{textAlign: 'center'}}>Change</th>
                </tr>
              </thead>
              <tbody>
                {(before.revenue || after.revenue) && (
                  <tr>
                    <td className="label">Revenue</td>
                    <td style={{textAlign: 'center'}}>{formatCurrency(before.revenue)}</td>
                    <td style={{textAlign: 'center'}}>{formatCurrency(after.revenue)}</td>
                    <td style={{textAlign: 'center', fontWeight: 700}}>
                      {calculateChange(before.revenue, after.revenue).percentFormatted}
                    </td>
                  </tr>
                )}
                {(before.ebitda || after.ebitda) && (
                  <tr>
                    <td className="label">EBITDA</td>
                    <td style={{textAlign: 'center'}}>{formatCurrency(before.ebitda)}</td>
                    <td style={{textAlign: 'center'}}>{formatCurrency(after.ebitda)}</td>
                    <td style={{textAlign: 'center', fontWeight: 700}}>
                      {calculateChange(before.ebitda, after.ebitda).percentFormatted}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}

        {/* Risks and Recommendations */}
        {(risks.length > 0 || recommendations.length > 0) && (
          <div className="two-column">
            {/* Risks */}
            {risks.length > 0 && (
              <div className="list-section">
                <div className="section-header">Top Risks</div>
                <div className="list-items">
                  {risks.map((risk, idx) => (
                    <div key={idx} className="list-item">
                      <div className="list-item-title">
                        {risk.title || risk.risk || `Risk ${idx + 1}`}
                      </div>
                      <div className="list-item-text">
                        {risk.description || risk.mitigation || risk}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Recommendations */}
            {recommendations.length > 0 && (
              <div className="list-section">
                <div className="section-header">Recommendations</div>
                <div className="list-items">
                  {recommendations.map((rec, idx) => (
                    <div key={idx} className="list-item">
                      <div className="list-item-title">
                        {rec.title || rec.recommendation || `Recommendation ${idx + 1}`}
                      </div>
                      <div className="list-item-text">
                        {rec.description || rec.rationale || rec}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {extraSections.map(([key, value]) => {
          const rows = Array.isArray(value)
            ? value
                .filter((v) => v !== null && v !== undefined)
                .map((v, idx) => ({
                  label: `${formatLabel(key)} ${idx + 1}`,
                  value: formatGenericValue(v),
                }))
            : Object.entries(value || {})
                .filter(([, v]) => v !== null && v !== undefined)
                .map(([k, v]) => ({
                  label: formatLabel(k),
                  value: formatGenericValue(v),
                }));

          if (!rows || rows.length === 0) return null;

          return (
            <div key={key} className="table-section">
              <div className="section-header">{formatLabel(key)}</div>
              <table className="data-table">
                <tbody>
                  {rows.map((row, idx) => (
                    <tr key={`${key}-${idx}`}>
                      <td className="label">{row.label}</td>
                      <td className="value">{row.value}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        })}

      </div>

      {/* PROMPT ALIGNMENT: Begin Project Button */}
      {onBeginProject && threadBundleId && selectedScorecardId && (
        <div style={{
          marginTop: '24px',
          padding: '20px',
          background: '#f9fafb',
          borderRadius: '12px',
          border: '1px solid #e5e7eb'
        }}>
          <h3 style={{ margin: '0 0 12px 0', fontSize: '16px', color: '#161f3b' }}>
            Ready to Begin?
          </h3>
          <p style={{ margin: '0 0 16px 0', fontSize: '14px', color: '#6b7280' }}>
            Generate a detailed Work Breakdown Structure and project plan based on this scorecard.
          </p>
          <button
            onClick={async () => {
              try {
                const projectData = await onBeginProject({
                  threadBundleId,
                  scorecardId: selectedScorecardId,
                  projectName: result.project_name || 'Market IQ Project'
                });
                console.log('[ScoreDashboard] Project created:', projectData);
              } catch (err) {
                console.error('[ScoreDashboard] Begin Project failed:', err);
                alert('Failed to create project. Please try again.');
              }
            }}
            style={{
              padding: '12px 24px',
              background: '#161f3b',
              color: '#fff',
              border: 'none',
              borderRadius: '8px',
              fontSize: '14px',
              fontWeight: '600',
              cursor: 'pointer',
              transition: 'all 0.2s'
            }}
            onMouseOver={(e) => e.target.style.background = '#0f172a'}
            onMouseOut={(e) => e.target.style.background = '#161f3b'}
          >
            Begin Project →
          </button>
        </div>
      )}

    </div>
  );
}
