import React, { useState } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faArrowLeft,
  faComments,
  faChartLine,
  faBalanceScale,
  faProjectDiagram,
  faDollarSign,
  faBullseye,
  faArrowTrendUp,
  faUsers
} from '@fortawesome/free-solid-svg-icons';

// --- normalize backend payload (handles compat + snake_case) ---
const normalizeAnalysis = (analysis) => {
  const hasCompat = !!(analysis && analysis.compat);

  const score = hasCompat
    ? (analysis.compat.score ?? 0)
    : (analysis && analysis.market_iq_score) ?? 0;

  const title = hasCompat
    ? (analysis.compat.title ?? 'Market IQ Project')
    : (analysis && analysis.project_name) ?? 'Market IQ Project';

  const components = hasCompat
    ? analysis.compat.components
    : {
        financialHealth: analysis?.component_scores?.financial_health ?? 0,
        operationalEfficiency: analysis?.component_scores?.operational_efficiency ?? 0,
        marketPosition: analysis?.component_scores?.market_position ?? 0,
        executionReadiness: analysis?.component_scores?.execution_readiness ?? 0
      };

  // financial strings are already formatted (e.g. "$1.2M")
  const financials = hasCompat
    ? analysis.compat.financials
    : {
        ebitdaAtRisk: analysis?.financial_impact?.ebitda_at_risk ?? '—',
        potentialLoss: analysis?.financial_impact?.potential_loss ?? '—',
        roiOpportunity: analysis?.financial_impact?.roi_opportunity ?? '—',
        projectedEbitda: analysis?.financial_impact?.projected_ebitda ?? '—'
      };

  return { score, title, components, financials, raw: analysis };
};

export default function ExploreAnalysis({ analysisResult, onBackToSummary, onOpenChat, onOpenScenario, onConvertToProject }) {
  const a = normalizeAnalysis(analysisResult);

  const getScoreColor = (score) => {
    if (score >= 70) return '#10b981';
    if (score >= 50) return '#f59e0b';
    return '#ef4444';
  };

  const scoreColor = getScoreColor(a.score || 0);

  const componentIcons = {
    'Execution Readiness': faUsers,
    'Financial Health': faDollarSign,
    'Market Position': faBullseye,
    'Operational Efficiency': faArrowTrendUp
  };

  const methodologyData = [
    {
      component: 'Financial Health',
      weight: '30%',
      score: a.components?.financialHealth || 0,
      contribution: ((a.components?.financialHealth || 0) * 0.3).toFixed(1)
    },
    {
      component: 'Operational Efficiency',
      weight: '20%',
      score: a.components?.operationalEfficiency || 0,
      contribution: ((a.components?.operationalEfficiency || 0) * 0.2).toFixed(1)
    },
    {
      component: 'Market Position',
      weight: '30%',
      score: a.components?.marketPosition || 0,
      contribution: ((a.components?.marketPosition || 0) * 0.3).toFixed(1)
    },
    {
      component: 'Execution Readiness',
      weight: '20%',
      score: a.components?.executionReadiness || 0,
      contribution: ((a.components?.executionReadiness || 0) * 0.2).toFixed(1)
    }
  ];

  const weightedSum = methodologyData
    .reduce((sum, item) => sum + parseFloat(item.contribution), 0)
    .toFixed(2);

  const [whatsNextOpen, setWhatsNextOpen] = useState(false);

  return (
    <div className="explore-analysis">
      {/* Header */}
      <div className="dashboard-header">
        <button className="back-button" onClick={onBackToSummary}>
          <FontAwesomeIcon icon={faArrowLeft} />
          Back
        </button>
        <h1 className="dashboard-title">Explore Analysis</h1>
        <div className="explore-whats-next-dropdown">
          <button 
            className="explore-btn-whats-next"
            onClick={() => setWhatsNextOpen(!whatsNextOpen)}
          >
            <span>What's Next</span>
            <span className={`explore-dropdown-arrow ${whatsNextOpen ? 'open' : ''}`}>▼</span>
          </button>
          {whatsNextOpen && (
            <div className="explore-dropdown-menu">
              <button className="explore-dropdown-item" onClick={() => { onOpenChat(); setWhatsNextOpen(false); }}>
                <FontAwesomeIcon icon={faComments} />
                <span>Discuss with Analyst</span>
              </button>
              <button className="explore-dropdown-item" onClick={() => { onOpenScenario(); setWhatsNextOpen(false); }}>
                <FontAwesomeIcon icon={faBalanceScale} />
                <span>Scenario Modeling</span>
              </button>
              <button className="explore-dropdown-item" onClick={() => { onConvertToProject(); setWhatsNextOpen(false); }}>
                <FontAwesomeIcon icon={faProjectDiagram} />
                <span>Begin Project</span>
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Score Summary */}
      <div className="explore-score-summary">
        <div className="explore-score-header">
          <div
            className="explore-score-circle"
            style={{ borderColor: scoreColor, color: scoreColor }}
          >
            {a.score || '--'}
          </div>
          <div className="explore-score-details">
            <div className="explore-score-label">Market IQ Score</div>
            <div className="explore-score-category">{a.title}</div>
          </div>
        </div>

        <div className="explore-financial-grid">
          <div className="explore-financial-item">
            <div className="explore-financial-label">EBITDA at Risk</div>
            <div className="explore-financial-value risk">
              {a.financials?.ebitdaAtRisk ?? '—'}
            </div>
          </div>
          <div className="explore-financial-item">
            <div className="explore-financial-label">Potential Loss</div>
            <div className="explore-financial-value negative">
              {a.financials?.potentialLoss ?? '—'}
            </div>
          </div>
          <div className="explore-financial-item">
            <div className="explore-financial-label">ROI Opportunity</div>
            <div className="explore-financial-value opportunity">
              {a.financials?.roiOpportunity ?? '—'}
            </div>
          </div>
          <div className="explore-financial-item">
            <div className="explore-financial-label">Projected EBITDA</div>
            <div className="explore-financial-value positive">
              {a.financials?.projectedEbitda ?? '—'}
            </div>
          </div>
        </div>
      </div>

      {/* Methodology */}
      <div className="methodology-section">
        <h3>How Your Score Was Calculated</h3>
        <p>
          Your Market IQ score is a weighted average of four key components. Each component is
          scored 0-100, then multiplied by its weight to determine its contribution to the final
          score.
        </p>

        <div className="methodology-table">
          <div className="methodology-header">
            <div>Component</div>
            <div>Weight</div>
            <div>Score</div>
            <div>Contribution</div>
          </div>

          {methodologyData.map((item, index) => (
            <div key={index} className="methodology-row">
              <div>{item.component}</div>
              <div>{item.weight}</div>
              <div style={{ color: getScoreColor(item.score), fontWeight: 600 }}>
                {item.score}
              </div>
              <div>{item.contribution}</div>
            </div>
          ))}

          <div className="methodology-footer">
            <div>Weighted Sum</div>
            <div></div>
            <div></div>
            <div style={{ color: scoreColor }}>{weightedSum}</div>
          </div>
        </div>
      </div>

      {/* Component Breakdown */}
      <div className="component-breakdown-section">
        <h3>Component Breakdown</h3>
        <div className="breakdown-grid">
          {methodologyData.map((item, index) => (
            <div key={index} className="breakdown-item">
              <div className="breakdown-icon" style={{ color: getScoreColor(item.score) }}>
                <FontAwesomeIcon icon={componentIcons[item.component] || faChartLine} />
              </div>
              <div className="breakdown-content">
                <div className="breakdown-label">{item.component}</div>
                <div className="breakdown-score" style={{ color: getScoreColor(item.score) }}>
                  {item.score}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Raw Analysis Data */}
      <div className="raw-data-section">
        <h3>Raw Analysis Data</h3>
        <div className="raw-data-container">
          <pre>{JSON.stringify(a.raw, null, 2)}</pre>
        </div>
        <div className="raw-data-actions">
          <button
            className="action-btn secondary"
            onClick={() => {
              navigator.clipboard.writeText(JSON.stringify(a.raw, null, 2));
              alert('JSON copied to clipboard!');
            }}
          >
            Copy JSON
          </button>
          <button
            className="action-btn secondary"
            onClick={() => {
              const blob = new Blob([JSON.stringify(a.raw, null, 2)], {
                type: 'application/json'
              });
              const url = URL.createObjectURL(blob);
              const aEl = document.createElement('a');
              aEl.href = url;
              aEl.download = `market-iq-analysis-${Date.now()}.json`;
              aEl.click();
              URL.revokeObjectURL(url);
            }}
          >
            Download JSON
          </button>
        </div>
      </div>
    </div>
  );
}
