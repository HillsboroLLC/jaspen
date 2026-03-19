// ============================================================================
// File: ScoreDashboard.jsx
// Purpose: Render dynamic scorecard with AI Agent Enterprise Design System
// Colors: Navy (#161f3b), Magenta (#a0036c), Ice (#eff9fc)
// ============================================================================
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faChevronDown, faDownload, faPlay, faSpinner } from '@fortawesome/free-solid-svg-icons';
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
  onBeginProject = null,
  onGenerateAiWbs = null,
  generatingAiWbs = false,
  canExportScorecardPdf = false,
  canExportScorecardPptx = false,
  canExportWbsCsv = false,
  exportBusyType = null,
  onExportScorecardPdf = null,
  onExportScorecardPptx = null,
  onExportWbsCsv = null,
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
  const componentScores = result.component_scores || {};
  const financialImpact = result.financial_impact || {};
  const risks = result.top_risks || result.risks || [];
  const recommendations = result.recommendations || [];
  const aiInsights = Array.isArray(result.ai_insights) ? result.ai_insights : [];

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

  const buildSmartExplanations = () => {
    const byCategory = {
      financial_health: 'Reflects available revenue, margin, and churn inputs.',
      market_position: 'Reflects stated market and competitive context.',
      operational_efficiency: 'Based on available execution and ops inputs.',
      execution_readiness: 'Reflects stated timeline, team, and funding inputs.',
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

  const formatCurrency = (v) => {
    if (v === null || v === undefined || v === '') return 'N/A';
    const n = Number(String(v).replace(/[^\d.-]/g, ''));
    if (isNaN(n)) return 'N/A';
    if (Math.abs(n) >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
    if (Math.abs(n) >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
    if (Math.abs(n) >= 1e3) return `$${(n / 1e3).toFixed(1)}K`;
    return `$${n.toLocaleString()}`;
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
    return options;
  }, [
    canExportScorecardPdf,
    canExportScorecardPptx,
    canExportWbsCsv,
    onExportScorecardPdf,
    onExportScorecardPptx,
    onExportWbsCsv,
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
    const priorityKeys = ['ebitda_at_risk', 'potential_loss', 'roi_opportunity', 'projected_ebitda'];
    const items = [];

    priorityKeys.forEach((key) => {
      if (financialImpact && financialImpact[key] !== undefined && financialImpact[key] !== null) {
        items.push({
          label: formatLabel(key),
          value: formatCurrency(financialImpact[key]),
        });
      }
    });

    // If we have fewer than 4 items, add other financial impact values
    if (items.length < 4) {
      Object.entries(financialImpact || {}).forEach(([key, value]) => {
        if (!priorityKeys.includes(key) && value !== null && value !== undefined && items.length < 4) {
          items.push({
            label: formatLabel(key),
            value: formatCurrency(value),
          });
        }
      });
    }

    return items;
  }, [financialImpact]);

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
        {/* Score + Financial Impact Row */}
        <div className="score-header-row">
          {/* Score Main Card */}
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

          {/* Financial Impact Card */}
          <div className="financial-card">
            <h4>Financial Impact</h4>
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
              <div className="empty-state">
                <p>No financial impact data available</p>
              </div>
            )}
          </div>
        </div>

        {/* Category Scores */}
        {hasScores && (
          <div className="scores-section">
            <div className="ss-header">Category Scores</div>
            {categoryScoreRows.map((row) => (
              <div key={row.key} className="score-row">
                <span className="sr-name">{row.name}</span>
                <div className="sr-bar">
                  <div className="progress-bar">
                    <div
                      className={`fill ${row.color}`}
                      style={{ width: `${row.value}%` }}
                    />
                  </div>
                </div>
                <span className="sr-value">{row.value}</span>
                <span className="sr-desc">{row.description}</span>
              </div>
            ))}
          </div>
        )}

        {/* Top Risks */}
        {risks.length > 0 && (
          <div className="risks-section">
            <div className="rs-header">Top Risks</div>
            {risks.map((risk, idx) => (
              <div key={idx} className="risk-item">
                <span className="ri-num">{idx + 1}</span>
                <span className="ri-text">
                  {typeof risk === 'string' ? risk : (risk.title || risk.risk || risk.description || `Risk ${idx + 1}`)}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* Recommendations */}
        {recommendations.length > 0 && (
          <div className="recommendations-section">
            <div className="rec-header">Recommendations</div>
            {recommendations.map((rec, idx) => (
              <div key={idx} className="rec-item">
                <span className="rec-num">{idx + 1}</span>
                <span className="rec-text">
                  {typeof rec === 'string' ? rec : (rec.title || rec.recommendation || rec.description || `Recommendation ${idx + 1}`)}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* AI Insights Widget */}
        {hasAiInsights && (
          <div className="insights-section">
            <div className="ins-header">AI Insights</div>
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
        )}

        {/* Strategic Decision Framework */}
        {hasDecisionData && (
          <div className="decision-section">
            <div className="ds-header">Strategic Decision Framework</div>
            {[
              ['acceptable_payback', 'Acceptable Payback'],
              ['irr_above_hurdle', 'IRR Above Hurdle'],
              ['npv_positive', 'NPV Positive'],
              ['strategic_alignment', 'Strategic Alignment'],
              ['robust_sensitivity', 'Robust Sensitivity'],
            ].map(([key, label]) => {
              const yes = !!decisionFramework?.[key];
              return (
                <div key={key} className="decision-row">
                  <span className="dr-criteria">{label}</span>
                  <span className="dr-status">
                    <span className={`badge ${yes ? 'badge-success' : 'badge-danger'}`}>
                      {yes ? 'YES' : 'NO'}
                    </span>
                  </span>
                  <span className="dr-desc">{yes ? 'Criteria met' : 'Criteria not met'}</span>
                </div>
              );
            })}
            {decisionFramework?.overall_recommendation && (
              <div className="decision-row">
                <span className="dr-criteria">Overall Recommendation</span>
                <span className="dr-status">
                  <span className={`badge ${
                    decisionFramework.overall_recommendation === 'Go' ||
                    decisionFramework.overall_recommendation === 'YES'
                      ? 'badge-success'
                      : 'badge-danger'
                  }`}>
                    {decisionFramework.overall_recommendation === 'Go' ||
                     decisionFramework.overall_recommendation === 'YES' ? 'YES' : 'NO'}
                  </span>
                </span>
                <span className="dr-desc">{decisionFramework.overall_recommendation}</span>
              </div>
            )}
          </div>
        )}

        {/* Investment Analysis */}
        {hasInvestmentData && (
          <div className="data-section">
            <div className="section-header">Investment Analysis</div>
            {investmentAnalysis.initial_investment && (
              <div className="data-row">
                <span className="data-label">Initial Investment</span>
                <span className="data-value">{formatCurrency(investmentAnalysis.initial_investment)}</span>
              </div>
            )}
            {investmentAnalysis.payback_period && (
              <div className="data-row">
                <span className="data-label">Payback Period</span>
                <span className="data-value">{investmentAnalysis.payback_period.toFixed(1)} years</span>
              </div>
            )}
            {investmentAnalysis.roi && (
              <div className="data-row">
                <span className="data-label">Return on Investment (ROI)</span>
                <span className="data-value">{formatPercent(investmentAnalysis.roi)}</span>
              </div>
            )}
          </div>
        )}

        {/* NPV & IRR Analysis */}
        {hasNpvData && (
          <div className="data-section">
            <div className="section-header">NPV & IRR Analysis</div>
            {npvIrrAnalysis.npv && (
              <div className="data-row">
                <span className="data-label">Net Present Value (NPV)</span>
                <span className="data-value">{formatCurrency(npvIrrAnalysis.npv)}</span>
              </div>
            )}
            {npvIrrAnalysis.irr && (
              <div className="data-row">
                <span className="data-label">Internal Rate of Return (IRR)</span>
                <span className="data-value">{formatPercent(npvIrrAnalysis.irr * 100)}</span>
              </div>
            )}
            {npvIrrAnalysis.discount_rate && (
              <div className="data-row">
                <span className="data-label">Discount Rate</span>
                <span className="data-value">{formatPercent(npvIrrAnalysis.discount_rate * 100)}</span>
              </div>
            )}
          </div>
        )}

        {/* Valuation */}
        {hasValuationData && (
          <div className="data-section">
            <div className="section-header">Valuation</div>
            {valuation.enterprise_value && (
              <div className="data-row">
                <span className="data-label">Enterprise Value</span>
                <span className="data-value">{formatCurrency(valuation.enterprise_value)}</span>
              </div>
            )}
            {valuation.multiple && (
              <div className="data-row">
                <span className="data-label">EBITDA Multiple</span>
                <span className="data-value">{valuation.multiple}x</span>
              </div>
            )}
          </div>
        )}

        {/* Before vs After Financial Analysis */}
        {(before.revenue || after.revenue) && (
          <div className="data-section">
            <div className="section-header">Before vs After Financial Analysis</div>
            {(before.revenue || after.revenue) && (
              <>
                <div className="data-row">
                  <span className="data-label">Revenue (Before)</span>
                  <span className="data-value">{formatCurrency(before.revenue)}</span>
                </div>
                <div className="data-row">
                  <span className="data-label">Revenue (After)</span>
                  <span className="data-value">{formatCurrency(after.revenue)}</span>
                </div>
              </>
            )}
            {(before.ebitda || after.ebitda) && (
              <>
                <div className="data-row">
                  <span className="data-label">EBITDA (Before)</span>
                  <span className="data-value">{formatCurrency(before.ebitda)}</span>
                </div>
                <div className="data-row">
                  <span className="data-label">EBITDA (After)</span>
                  <span className="data-value">{formatCurrency(after.ebitda)}</span>
                </div>
              </>
            )}
          </div>
        )}

        {/* Begin Project Card (alternate placement) */}
        {(onBeginProject || onGenerateAiWbs) && threadBundleId && selectedScorecardId && (
          <div className="begin-project-card">
            <h3>Ready to Begin?</h3>
            <p>
              Generate a detailed Work Breakdown Structure and project plan based on this scorecard.
            </p>
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
              {onGenerateAiWbs && (
                <button
                  className="sc-btn sc-btn-primary"
                  onClick={() => onGenerateAiWbs({
                    threadBundleId,
                    scorecardId: selectedScorecardId,
                    projectName: result.project_name || 'Untitled Idea',
                  })}
                  disabled={generatingAiWbs}
                >
                  <FontAwesomeIcon icon={generatingAiWbs ? faSpinner : faPlay} spin={generatingAiWbs} /> {generatingAiWbs ? 'Generating project plan…' : 'Generate with AI'}
                </button>
              )}
              {onBeginProject && (
                <button
                  className="sc-btn sc-btn-primary"
                  onClick={async () => {
                    try {
                      const projectData = await onBeginProject({
                        threadBundleId,
                        scorecardId: selectedScorecardId,
                        projectName: result.project_name || 'Untitled Idea'
                      });
                      console.log('[ScoreDashboard] Project created:', projectData);
                    } catch (err) {
                      console.error('[ScoreDashboard] Begin Project failed:', err);
                      alert('Failed to create project. Please try again.');
                    }
                  }}
                >
                  <FontAwesomeIcon icon={faPlay} /> Project
                </button>
              )}
            </div>
          </div>
        )}
    </div>
  );
}
