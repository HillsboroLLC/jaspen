// ============================================================================
// File: ScoreDashboard.jsx
// Purpose: Render dynamic scorecard with AI Agent Enterprise Design System
// Colors: Navy (#161f3b), Magenta (#a0036c), Ice (#eff9fc)
// ============================================================================
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faChevronDown, faDownload, faSpinner } from '@fortawesome/free-solid-svg-icons';
import { ScoreDashboardSkeleton } from '../../shared/components/SkeletonLoader';
import './ScoreDashboard.css';

export default function ScoreDashboard({
  analysisResult,
  // Props passed from parent workspace (kept for API compatibility)
  onOpenChat: _onOpenChat,
  onOpenScenario: _onOpenScenario,
  onSelectScorecard: _onSelectScorecard,

  // Scorecard snapshot props
  scorecardSnapshots = [],
  selectedScorecardId = null,
  threadBundleId = null,
  scoreCommentary = null,
  canExportScorecardPdf = false,
  canExportScorecardPptx = false,
  canExportWbsCsv = false,
  canExportConversationPdf = false,
  canExportConversationMarkdown = false,
  exportBusyType = null,
  onExportScorecardPdf = null,
  onExportScorecardPptx = null,
  onExportWbsCsv = null,
  onExportConversationPdf = null,
  onExportConversationMarkdown = null,
  loading = false,
}) {
  const [exportMenuOpen, setExportMenuOpen] = useState(false);
  const exportMenuRef = useRef(null);
  // If snapshots are provided, render the selected snapshot as the source of truth.
  const selectedSnapshot = useMemo(() => {
    if (!Array.isArray(scorecardSnapshots) || !selectedScorecardId) return null;
    return scorecardSnapshots.find(s => s?.id === selectedScorecardId) || null;
  }, [scorecardSnapshots, selectedScorecardId]);

  const result = selectedSnapshot || analysisResult || {};
  const score = result.jaspen_score || 0;
  const componentScores = useMemo(() => result.component_scores || {}, [result.component_scores]);
  const componentRationale = useMemo(() => result.component_rationale || {}, [result.component_rationale]);
  const financialImpact = useMemo(() => result.financial_impact || {}, [result.financial_impact]);
  const sectionProvenance = useMemo(() => result.section_provenance || {}, [result.section_provenance]);
  const risks = result.top_risks || result.risks || [];
  const recommendations = result.recommendations || [];
  const aiInsights = Array.isArray(result.ai_insights) ? result.ai_insights : [];
  const keyInsights = useMemo(() => (
    Array.isArray(result.key_insights)
      ? result.key_insights
      : typeof result.key_insights === 'string' && result.key_insights.trim()
      ? [result.key_insights.trim()]
      : []
  ), [result.key_insights]);
  const assumptions = useMemo(() => (
    Array.isArray(result.assumptions)
      ? result.assumptions.filter((item) => typeof item === 'string' && item.trim())
      : []
  ), [result.assumptions]);

  // Before/After financial data
  const beforeAfter = result.before_after_financials || {};
  const before = beforeAfter.before || {};
  const after = beforeAfter.after || {};

  const hasMeaningfulValue = (value) => {
    if (value === null || value === undefined || value === '') return false;
    if (Array.isArray(value)) return value.some(hasMeaningfulValue);
    if (typeof value === 'object') {
      return Object.entries(value).some(([key, inner]) => key !== '_numeric' && hasMeaningfulValue(inner));
    }
    return true;
  };

  // Investment Analysis
  const investmentAnalysis = result.investment_analysis || {};
  const hasInvestmentData = hasMeaningfulValue(investmentAnalysis);

  // NPV/IRR Analysis
  const npvIrrAnalysis = result.npv_irr_analysis || {};
  const hasNpvData = hasMeaningfulValue(npvIrrAnalysis);

  // Valuation
  const valuation = result.valuation || {};
  const hasValuationData = hasMeaningfulValue(valuation);

  // Decision Framework (supports object or JSON string)
  const dfRaw =
    result.decision_framework ?? result.strategic_decision_framework ?? null;

  const decisionFramework =
    typeof dfRaw === 'string'
      ? (() => { try { return JSON.parse(dfRaw); } catch { return null; } })()
      : (dfRaw && typeof dfRaw === 'object' ? dfRaw : null);

  const hasDecisionData = hasMeaningfulValue(decisionFramework);
  const hasBeforeAfterData = hasMeaningfulValue(before) || hasMeaningfulValue(after);

  const cleanNarrativeText = (value) => {
    const text = String(value || '')
      .replace(/\*\*/g, '')
      .replace(/^- /gm, '')
      .replace(/\s+/g, ' ')
      .trim();
    if (!text) return '';
    if (text.includes('?')) return '';
    if (/^before i generate/i.test(text)) return '';
    if (/^what is your specific goal/i.test(text)) return '';
    return text;
  };

  const buildSmartExplanations = () => {
    const fallbackByCategory = (key) => {
      if (!Object.prototype.hasOwnProperty.call(componentScores, key)) return 'Not enough information.';
      const provenance = sectionProvenance?.component_rationale || sectionProvenance?.component_scores;
      const byCategory = {
        financial_health: 'Scored from the current financial and value signals in the conversation. Add clearer budget, ROI, or savings detail if you want a sharper rationale here.',
        operational_efficiency: 'Scored from the operating model and workflow detail currently in the conversation. Add more process, capacity, or handoff context if you want a stronger explanation here.',
        market_position: 'Scored from the current market and strategic context. Add customer outcome, positioning, or competitive detail if you want a clearer rationale here.',
        execution_readiness: 'Scored from the team, sequencing, and delivery detail currently in the conversation. Add more ownership, timeline, and dependency context if you want a fuller rationale here.',
      };
      if (provenance === 'estimated') {
        return byCategory[key] || 'Estimated from the current conversation. Add more detail if you want a stronger rationale for this dimension.';
      }
      return byCategory[key] || 'Scored from the current context. Add more detail if you want a fuller explanation for this dimension.';
    };

    const byCategory = {
      financial_health: componentRationale.financial_health || fallbackByCategory('financial_health'),
      market_position: componentRationale.market_position || fallbackByCategory('market_position'),
      operational_efficiency: componentRationale.operational_efficiency || fallbackByCategory('operational_efficiency'),
      execution_readiness: componentRationale.execution_readiness || fallbackByCategory('execution_readiness'),
    };

    return { byCategory };
  };

  const getScoreLabel = (s) => {
    if (s >= 80) return 'Excellent';
    if (s >= 60) return 'Good';
    if (s >= 40) return 'Fair';
    return 'At Risk';
  };

  const getScoreRatingClass = (s) => {
    if (s >= 80) return 'excellent';
    if (s >= 60) return 'good';
    if (s >= 40) return 'fair';
    return 'at-risk';
  };

  const formatLabel = (k) =>
    String(k || '')
      .replace(/_/g, ' ')
      .replace(/\b\w/g, (l) => l.toUpperCase());

  const scoreLabel = getScoreLabel(score);
  const scoreRatingClass = getScoreRatingClass(score);
  const smartExplanations = buildSmartExplanations();
  const exportOptions = useMemo(() => {
    const options = [];
    if (canExportScorecardPdf && onExportScorecardPdf) {
      options.push({
        key: 'pdf',
        label: 'Export PDF',
        onClick: () => onExportScorecardPdf({
          threadBundleId,
          scorecardId: selectedScorecardId,
          projectName: result.project_name || 'Untitled Idea',
        }),
      });
    }
    if (canExportScorecardPptx && onExportScorecardPptx) {
      options.push({
        key: 'pptx',
        label: 'Export PowerPoint',
        onClick: () => onExportScorecardPptx({
          threadBundleId,
          scorecardId: selectedScorecardId,
          projectName: result.project_name || 'Untitled Idea',
        }),
      });
    }
    if (canExportWbsCsv && onExportWbsCsv) {
      options.push({
        key: 'csv',
        label: 'Export WBS CSV',
        onClick: () => onExportWbsCsv({
          threadBundleId,
          projectName: result.project_name || 'Untitled Idea',
        }),
      });
    }
    if (canExportConversationMarkdown && onExportConversationMarkdown) {
      options.push({
        key: 'conversation-md',
        label: 'Export Transcript (.md)',
        onClick: () => onExportConversationMarkdown({
          threadBundleId,
          projectName: result.project_name || 'Untitled Idea',
        }),
      });
    }
    if (canExportConversationPdf && onExportConversationPdf) {
      options.push({
        key: 'conversation-pdf',
        label: 'Export Transcript PDF',
        onClick: () => onExportConversationPdf({
          threadBundleId,
          projectName: result.project_name || 'Untitled Idea',
        }),
      });
    }
    return options;
  }, [
    canExportScorecardPdf,
    canExportScorecardPptx,
    canExportWbsCsv,
    canExportConversationPdf,
    canExportConversationMarkdown,
    onExportScorecardPdf,
    onExportScorecardPptx,
    onExportWbsCsv,
    onExportConversationPdf,
    onExportConversationMarkdown,
    threadBundleId,
    selectedScorecardId,
    result.project_name,
  ]);
  const hasExportMenu = Boolean(threadBundleId && exportOptions.length);

  useEffect(() => {
    if (!exportMenuOpen) return undefined;
    const handlePointerDown = (event) => {
      if (exportMenuRef.current && !exportMenuRef.current.contains(event.target)) {
        setExportMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handlePointerDown);
    return () => document.removeEventListener('mousedown', handlePointerDown);
  }, [exportMenuOpen]);

  // Financial impact rows for the grid
  const financialGridItems = useMemo(() => {
    const priorityKeys = ['ebitda_at_risk', 'potential_loss', 'roi_opportunity', 'projected_ebitda', 'time_to_market_impact'];
    const items = [];

    priorityKeys.forEach((key) => {
      const rawValue = financialImpact?.[key];
      if (rawValue !== undefined && rawValue !== null && rawValue !== '') {
        items.push({
          label: formatLabel(key),
          value: String(rawValue),
        });
      }
    });

    if (items.length < 5) {
      Object.entries(financialImpact || {}).forEach(([key, value]) => {
        if (key === '_numeric') return;
        if (!priorityKeys.includes(key) && value !== null && value !== undefined && value !== '' && items.length < 5) {
          items.push({
            label: formatLabel(key),
            value: String(value),
          });
        }
      });
    }

    return items;
  }, [financialImpact]);

  const narrativeHighlights = useMemo(() => {
    const items = [];
    keyInsights.forEach((entry) => {
      const text = typeof entry === 'string'
        ? cleanNarrativeText(entry)
        : cleanNarrativeText(entry?.summary || entry?.title || entry?.description || '');
      if (text) items.push(text);
    });
    Object.values(componentRationale || {}).forEach((entry) => {
      const text = cleanNarrativeText(entry);
      if (text) items.push(text);
    });
    const commentaryOverall = cleanNarrativeText(scoreCommentary?.overall || '');
    if (commentaryOverall) items.push(commentaryOverall);
    return Array.from(new Set(items)).slice(0, 3);
  }, [scoreCommentary, componentRationale, keyInsights]);

  // Category scores with progress bar data
  const categoryScoreRows = useMemo(() => {
    const scoreMapping = {
      financial_health: { order: 1, color: 'navy' },
      execution_readiness: { order: 2, color: 'navy' },
      operational_efficiency: { order: 3, color: 'navy' },
      market_position: { order: 4, color: 'magenta' },
    };

    return Object.entries(componentScores)
      .map(([key, value]) => ({
        key,
        name: formatLabel(key),
        value: Number(value) || 0,
        description: smartExplanations.byCategory[key] || '',
        color: scoreMapping[key]?.color || 'navy',
        order: scoreMapping[key]?.order || 99,
      }))
      .sort((a, b) => a.order - b.order);
  }, [componentScores, smartExplanations]);

  const hasScores = categoryScoreRows.length > 0;
  const hasFinancialImpact = financialGridItems.length > 0;
  const hasAiInsights = aiInsights.length > 0;
  const hasNarrativeHighlights = narrativeHighlights.length > 0;
  const missingSectionLabels = [
    !hasScores ? 'Category Scores' : null,
    risks.length === 0 ? 'Top Risks' : null,
    recommendations.length === 0 ? 'Recommendations' : null,
    !hasAiInsights ? 'AI Insights' : null,
    !hasDecisionData ? 'Strategic Decision Framework' : null,
    !hasInvestmentData ? 'Investment Analysis' : null,
    !hasNpvData ? 'NPV & IRR Analysis' : null,
    !hasValuationData ? 'Valuation' : null,
    !hasBeforeAfterData ? 'Before vs After Financial Analysis' : null,
  ].filter(Boolean);

  const getSectionState = (key, populated, { missingLabel = 'Needs more detail' } = {}) => {
    if (!populated) {
      return { label: missingLabel, tone: 'missing' };
    }
    const provenance = sectionProvenance?.[key] || (key === 'component_rationale' ? sectionProvenance?.component_scores : null);
    switch (provenance) {
      case 'uploaded_data':
        return { label: 'Uploaded data', tone: 'uploaded' };
      case 'estimated':
        return { label: 'Estimated', tone: 'estimated' };
      case 'derived_from_conversation':
        return { label: 'Current context', tone: 'grounded' };
      default:
        return { label: 'Available', tone: 'grounded' };
    }
  };

  const renderSectionBadge = (state) => (
    <span className={`section-status-pill ${state.tone}`}>{state.label}</span>
  );

  const renderMetricRows = (fields = []) => (
    <div className="metric-stack">
      {fields.filter((field) => field?.value !== null && field?.value !== undefined && field?.value !== '').map((field) => (
        <div className="metric-row" key={field.key || field.label}>
          <span className="metric-label">{field.label}</span>
          <span className="metric-value">{field.value}</span>
        </div>
      ))}
    </div>
  );

  const sectionCards = [
    {
      key: 'scores',
      title: 'Category Scores',
      populated: hasScores,
      priority: 1,
      span: 'wide',
      state: getSectionState('component_rationale', hasScores, { missingLabel: 'Needs stronger rationale' }),
      render: () => (
        <div className="scores-section">
          {categoryScoreRows.map((row) => (
            <div key={row.key} className="score-row">
              <span className="sr-name">{row.name}</span>
              <div className="sr-bar">
                <div className="progress-bar">
                  <div className={`fill ${row.color}`} style={{ width: `${row.value}%` }} />
                </div>
              </div>
              <span className="sr-value">{row.value}</span>
              <span className="sr-desc">{row.description}</span>
            </div>
          ))}
        </div>
      ),
    },
    {
      key: 'recommendations',
      title: 'Recommendations',
      populated: recommendations.length > 0,
      priority: 2,
      span: 'wide',
      state: getSectionState('recommendations', recommendations.length > 0),
      render: () => (
        <div className="recommendations-section">
          {recommendations.map((rec, idx) => {
            const recommendationText = typeof rec === 'string'
              ? rec
              : (rec.action || rec.title || rec.recommendation || rec.description || 'Not enough information.');
            const chips = [rec.expected_impact, rec.effort, rec.timeline].filter(Boolean);
            return (
              <div key={idx} className="rec-item">
                <span className="rec-num">{idx + 1}</span>
                <div className="rec-text">
                  <div className="section-item-title">{recommendationText}</div>
                  {chips.length > 0 && (
                    <div className="section-chip-row">
                      {chips.map((chip) => (
                        <span className="section-chip" key={`${idx}_${chip}`}>{chip}</span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      ),
    },
    {
      key: 'risks',
      title: 'Top Risks',
      populated: risks.length > 0,
      priority: 3,
      span: 'wide',
      state: getSectionState('top_risks', risks.length > 0),
      render: () => (
        <div className="risks-section">
          {risks.map((risk, idx) => {
            const riskText = typeof risk === 'string'
              ? risk
              : (risk.risk || risk.title || risk.description || 'Not enough information.');
            const chips = [
              risk.probability,
              risk.impact_category ? formatLabel(risk.impact_category) : null,
              risk.impact_dollars || risk.impact,
              risk.residual_risk ? `Residual: ${risk.residual_risk}` : null,
            ].filter(Boolean);
            return (
              <div key={idx} className="risk-item">
                <span className="ri-num">{idx + 1}</span>
                <div className="ri-text">
                  <div className="section-item-title">{riskText}</div>
                  {chips.length > 0 && (
                    <div className="section-chip-row">
                      {chips.map((chip) => (
                        <span className="section-chip" key={`${idx}_${chip}`}>{chip}</span>
                      ))}
                    </div>
                  )}
                  {typeof risk === 'object' && risk.mitigation && (
                    <div className="section-inline-note">Mitigation: {risk.mitigation}</div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      ),
    },
    {
      key: 'decision',
      title: 'Decision Framework',
      populated: hasDecisionData,
      priority: 4,
      state: getSectionState('decision_framework', hasDecisionData),
      render: () => (
        <div className="decision-section">
          {decisionFramework?.go_no_go && (
            <div className="decision-row">
              <span className="dr-criteria">Decision</span>
              <span className="dr-status">
                <span className={`badge ${
                  decisionFramework.go_no_go === 'GO'
                    ? 'badge-success'
                    : decisionFramework.go_no_go === 'CONDITIONAL'
                    ? 'badge-warning'
                    : 'badge-danger'
                }`}>
                  {decisionFramework.go_no_go}
                </span>
              </span>
              <span className="dr-desc">{decisionFramework.key_condition || 'Decision outcome derived from the current scorecard context.'}</span>
            </div>
          )}
          {decisionFramework?.confidence_level && (
            <div className="decision-row">
              <span className="dr-criteria">Confidence</span>
              <span className="dr-status">{decisionFramework.confidence_level}</span>
              <span className="dr-desc">Confidence in the current recommendation.</span>
            </div>
          )}
          {decisionFramework?.downside_scenario && (
            <div className="decision-row">
              <span className="dr-criteria">Downside</span>
              <span className="dr-desc">{decisionFramework.downside_scenario}</span>
            </div>
          )}
          {decisionFramework?.upside_scenario && (
            <div className="decision-row">
              <span className="dr-criteria">Upside</span>
              <span className="dr-desc">{decisionFramework.upside_scenario}</span>
            </div>
          )}
        </div>
      ),
    },
    {
      key: 'investment',
      title: 'Investment Analysis',
      populated: hasInvestmentData,
      priority: 5,
      state: getSectionState('investment_analysis', hasInvestmentData),
      render: () => renderMetricRows([
        { key: 'investment', label: 'Total Investment Required', value: investmentAnalysis.total_investment_required },
        { key: 'annual-return', label: 'Expected Annual Return', value: investmentAnalysis.expected_annual_return },
        { key: 'payback', label: 'Payback Period', value: investmentAnalysis.payback_period },
        { key: 'inaction', label: 'Cost of Inaction', value: investmentAnalysis.cost_of_inaction },
      ]),
    },
    {
      key: 'before-after',
      title: 'Before vs After',
      populated: hasBeforeAfterData,
      priority: 6,
      state: getSectionState('before_after_financials', hasBeforeAfterData),
      render: () => renderMetricRows([
        { key: 'before-revenue', label: 'Revenue (Before)', value: before.revenue },
        { key: 'after-revenue', label: 'Revenue (After)', value: after.revenue },
        { key: 'before-ebitda', label: 'EBITDA (Before)', value: before.ebitda },
        { key: 'after-ebitda', label: 'EBITDA (After)', value: after.ebitda },
        { key: 'before-margin', label: 'Margin (Before)', value: before.margin },
        { key: 'after-margin', label: 'Margin (After)', value: after.margin },
      ]),
    },
    {
      key: 'npv',
      title: 'NPV & IRR Analysis',
      populated: hasNpvData,
      priority: 7,
      state: getSectionState('npv_irr_analysis', hasNpvData),
      render: () => renderMetricRows([
        { key: 'npv', label: '3-Year NPV', value: npvIrrAnalysis.npv_3_year },
        { key: 'irr', label: 'Internal Rate of Return (IRR)', value: npvIrrAnalysis.irr },
        { key: 'discount-rate', label: 'Discount Rate', value: npvIrrAnalysis.discount_rate_used },
        { key: 'break-even', label: 'Break-even Month', value: npvIrrAnalysis.break_even_month },
      ]),
    },
    {
      key: 'valuation',
      title: 'Valuation',
      populated: hasValuationData,
      priority: 8,
      state: getSectionState('valuation', hasValuationData),
      render: () => renderMetricRows([
        { key: 'enterprise-value', label: 'Enterprise Value', value: valuation.enterprise_value },
        { key: 'multiple', label: 'Multiple', value: valuation.multiple !== null && valuation.multiple !== undefined && valuation.multiple !== '' ? `${valuation.multiple}x` : null },
        { key: 'basis', label: 'Basis', value: valuation.basis },
        { key: 'comparables', label: 'Comparable Range', value: valuation.comparable_range },
      ]),
    },
    {
      key: 'insights',
      title: 'AI Insights',
      populated: hasAiInsights,
      priority: 9,
      state: getSectionState('ai_insights', hasAiInsights),
      render: () => (
        <div className="insights-section">
          {aiInsights.slice(0, 5).map((entry, idx) => {
            const summary =
              String(entry?.summary || entry?.insight?.insight_text || '').trim() ||
              'Insight generated from uploaded data.';
            const fileName = String(entry?.file_name || entry?.insight?.file_name || '').trim();
            return (
              <div key={`${fileName || 'ins'}_${idx}`} className="ins-item">
                <div className="ins-meta">{fileName || `Insight ${idx + 1}`}</div>
                <div className="ins-text">{summary}</div>
              </div>
            );
          })}
        </div>
      ),
    },
    {
      key: 'assumptions',
      title: 'What Would Sharpen This Score',
      populated: assumptions.length > 0,
      priority: 10,
      state: getSectionState('assumptions', assumptions.length > 0, { missingLabel: 'No major gaps flagged' }),
      render: () => (
        <div className="section-bullet-list">
          {assumptions.map((item, idx) => (
            <div className="section-bullet-item" key={`assumption_${idx}`}>{item}</div>
          ))}
        </div>
      ),
    },
  ]
    .sort((a, b) => {
      if (a.populated !== b.populated) return a.populated ? -1 : 1;
      return a.priority - b.priority;
    });

  if (loading) {
    return <div className="score-dashboard-container"><ScoreDashboardSkeleton /></div>;
  }

  if (!selectedSnapshot && !analysisResult) return <div className="score-dashboard-container"><div className="empty-state"><p>No analysis result available</p></div></div>;

  return (
    <div className="score-dashboard-container">
        <div className="score-toolbar">
          <div className="score-toolbar-copy">
            <span className="score-toolbar-kicker">{selectedSnapshot ? 'Selected scorecard' : 'Current scorecard'}</span>
            <span className="score-toolbar-title">{result.project_name || 'Strategic snapshot'}</span>
          </div>
          {hasExportMenu && (
            <div className="sc-export-wrap" ref={exportMenuRef}>
              <button
                type="button"
                className="sc-btn sc-btn-secondary sc-btn-sm"
                onClick={() => setExportMenuOpen((open) => !open)}
                disabled={Boolean(exportBusyType)}
              >
                <FontAwesomeIcon icon={Boolean(exportBusyType) ? faSpinner : faDownload} spin={Boolean(exportBusyType)} />
                {Boolean(exportBusyType) ? 'Exporting…' : 'Export'}
                {!exportBusyType && <FontAwesomeIcon icon={faChevronDown} />}
              </button>
              {exportMenuOpen && (
                <div className="sc-export-menu">
                  {exportOptions.map((option) => (
                    <button
                      key={option.key}
                      type="button"
                      className="sc-export-option"
                      disabled={Boolean(exportBusyType)}
                      onClick={() => {
                        setExportMenuOpen(false);
                        option.onClick();
                      }}
                    >
                      {exportBusyType === option.key ? 'Exporting…' : option.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
        <div className="score-header-row">
          <div className="score-primary-column">
            <div className="score-main-card">
              <div className="score-circle">
                <span className="score-value">{score}</span>
                <span className="score-label">Score</span>
              </div>
              <div className="score-text">
                <h3>Strategy Score</h3>
                <span className={`score-rating ${scoreRatingClass}`}>{scoreLabel}</span>
              </div>
            </div>

            <div className="summary-card">
              <div className="card-title-row">
                <h4>What drove this score</h4>
                {renderSectionBadge(getSectionState('component_rationale', hasNarrativeHighlights, { missingLabel: 'Needs more detail' }))}
              </div>
              {hasNarrativeHighlights ? (
                <div className="summary-list">
                  {narrativeHighlights.map((item, idx) => (
                    <p key={`summary_${idx}`}>{item}</p>
                  ))}
                </div>
              ) : (
                <p className="section-fallback-message">Jaspen needs a little more context to explain what most affected this score.</p>
              )}
            </div>
          </div>

          <div className="score-secondary-column">
            <div className="financial-card">
              <div className="card-title-row">
                <h4>Financial Impact</h4>
                {renderSectionBadge(getSectionState('financial_impact', hasFinancialImpact, { missingLabel: 'Needs more detail' }))}
              </div>
              {hasFinancialImpact ? (
                <div className="fi-grid">
                  {financialGridItems.map((item, idx) => (
                    <div key={idx} className="fi-item">
                      <div className="fi-label">{item.label}</div>
                      <div className="fi-value">{item.value}</div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="section-fallback-message">
                  Not enough information to estimate financial impact yet.
                </p>
              )}
            </div>
          </div>
        </div>

        <div className="score-body-grid">
          {sectionCards.filter((section) => section.populated).map((section) => (
            <section
              key={section.key}
              className={`score-section-card ${section.span === 'wide' ? 'span-2' : ''}`}
            >
              <div className="section-card-head">
                <span className="section-card-title">{section.title}</span>
                {renderSectionBadge(section.state)}
              </div>
              <div className="section-card-body">{section.render()}</div>
            </section>
          ))}
        </div>

        {missingSectionLabels.length > 0 && (
          <section className="score-section-card muted-section">
            <div className="section-card-head">
              <span className="section-card-title">Additional analysis areas</span>
              {renderSectionBadge({ label: 'Needs more detail', tone: 'missing' })}
            </div>
            <div className="section-card-body">
              <div className="section-bullet-list">
                {missingSectionLabels.map((label) => (
                  <div className="section-bullet-item" key={label}>
                    {label}: Not enough information.
                  </div>
                ))}
              </div>
            </div>
          </section>
        )}
    </div>
  );
}
