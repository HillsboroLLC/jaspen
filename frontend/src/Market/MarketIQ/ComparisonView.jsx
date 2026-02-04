// ============================================================================
// File: src/pages/MarketIQ/ComparisonView.jsx
// Purpose: Side-by-side comparison of multiple scenarios with visual diffs
// ============================================================================
import React, { useMemo } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faArrowLeft, faArrowUp, faArrowDown, faMinus, faCheck
} from '@fortawesome/free-solid-svg-icons';
import '../styles/MarketIQ.css';

export default function ComparisonView({
  baseAnalysis,
  scenarios,
  onBackToScenario,
  onBackToSummary,
  onAdopt,
}) {
  const getScoreColor = (s) => (s >= 80 ? '#28a745' : s >= 60 ? '#ffc107' : s >= 40 ? '#fd7e14' : '#dc3545');
  
  const formatCurrency = (v) => {
    if (v === null || v === undefined || v === '') return 'N/A';
    const n = Number(String(v).replace(/[^\d.-]/g, ''));
    if (isNaN(n)) return 'N/A';
    if (Math.abs(n) >= 1e9) return `$${(n/1e9).toFixed(1)}B`;
    if (Math.abs(n) >= 1e6) return `$${(n/1e6).toFixed(1)}M`;
    if (Math.abs(n) >= 1e3) return `$${(n/1e3).toFixed(1)}K`;
    return `$${n.toFixed(0)}`;
  };

  const getDelta = (base, current) => {
    const b = Number(base) || 0;
    const c = Number(current) || 0;
    const delta = c - b;
    if (Math.abs(delta) < 0.1) return { icon: faMinus, color: 'var(--text-muted)', text: '—' };
    if (delta > 0) return { icon: faArrowUp, color: 'var(--success-color)', text: `+${delta.toFixed(1)}` };
    return { icon: faArrowDown, color: 'var(--error-color)', text: delta.toFixed(1) };
  };

  const baseScore = baseAnalysis?.market_iq_score || 0;
  const baseFinancial = baseAnalysis?.financial_impact || {};

  // Limit to 3 scenarios for clean comparison
  const compareScenarios = useMemo(() => scenarios.slice(0, 3), [scenarios]);

  // Collect all unique delta keys across scenarios for dynamic parameter rows
  const allDeltaKeys = useMemo(() => {
    const keys = new Set();
    compareScenarios.forEach(s => {
      if (s.values && typeof s.values === 'object') {
        Object.keys(s.values).forEach(k => keys.add(k));
      }
    });
    return Array.from(keys).sort();
  }, [compareScenarios]);

  // Baseline input values for diff display
  const baseInputs = useMemo(() => {
    return baseAnalysis?.inputs || baseAnalysis?.compat || {};
  }, [baseAnalysis]);

  const formatDeltaLabel = (key) =>
    key.replace(/_/g, ' ').replace(/([A-Z])/g, ' $1').split(' ')
      .map(w => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()).join(' ').trim();

  const formatDeltaValue = (key, val) => {
    if (val == null) return '—';
    const n = Number(val);
    if (isNaN(n)) return String(val);
    const k = key.toLowerCase();
    if (k.includes('budget') || k.includes('invest') || k.includes('cost') || k.includes('price') || k.includes('revenue') || k.includes('value'))
      return formatCurrency(n);
    if (k.includes('month') || k.includes('timeline') || k.includes('duration') || k.includes('period'))
      return `${n} mo`;
    if (k.includes('percent') || k.includes('rate') || k.includes('margin') || k.includes('growth'))
      return `${n.toFixed(1)}%`;
    return n.toLocaleString();
  };

  return (
    <div className="score-dashboard" style={{ minHeight: '100vh' }}>
      {/* Header */}
      <div className="dashboard-header">
        <button className="back-button" onClick={onBackToScenario}>
          <FontAwesomeIcon icon={faArrowLeft} />
        </button>
        <h1>Scenario Comparison</h1>
      </div>

      <div className="dashboard-content">
        {/* Instructions */}
        <div className="scenario-instructions">
          <h3>Compare Scenarios</h3>
          <p>
            Review how each scenario compares to your baseline analysis. Green arrows indicate improvements, 
            red arrows indicate declines. Adopt a scenario to make it your current analysis.
          </p>
        </div>

        {/* Comparison Grid */}
        <div className="comparison-container">
          <div className="comparison-table">
            {/* Header Row */}
            <div className="comparison-header-row">
              <div className="comparison-metric-label">Metric</div>
              <div className="comparison-scenario-col">
                <div className="comparison-scenario-title">Baseline</div>
              </div>
              {compareScenarios.map((scenario, idx) => (
                <div key={idx} className="comparison-scenario-col">
                  <div className="comparison-scenario-title">{scenario.label}</div>
                </div>
              ))}
            </div>

            {/* Market IQ Score */}
            <div className="comparison-row">
              <div className="comparison-metric-label">Market IQ Score</div>
              <div className="comparison-scenario-col">
                <div className="comparison-value" style={{ color: getScoreColor(baseScore) }}>
                  {baseScore}
                </div>
              </div>
              {compareScenarios.map((scenario, idx) => {
                const score = scenario.result?.market_iq_score || 0;
                const delta = getDelta(baseScore, score);
                return (
                  <div key={idx} className="comparison-scenario-col">
                    <div className="comparison-value" style={{ color: getScoreColor(score) }}>
                      {score}
                    </div>
                    <div className="comparison-delta" style={{ color: delta.color }}>
                      <FontAwesomeIcon icon={delta.icon} /> {delta.text}
                    </div>
                  </div>
                );
              })}
            </div>

            {/* ROI Opportunity */}
            <div className="comparison-row">
              <div className="comparison-metric-label">ROI Opportunity</div>
              <div className="comparison-scenario-col">
                <div className="comparison-value">
                  {formatCurrency(baseFinancial.roi_opportunity)}
                </div>
              </div>
              {compareScenarios.map((scenario, idx) => {
                const value = scenario.result?.financial_impact?.roi_opportunity;
                return (
                  <div key={idx} className="comparison-scenario-col">
                    <div className="comparison-value">{formatCurrency(value)}</div>
                  </div>
                );
              })}
            </div>

            {/* Projected EBITDA */}
            <div className="comparison-row">
              <div className="comparison-metric-label">Projected EBITDA</div>
              <div className="comparison-scenario-col">
                <div className="comparison-value">
                  {formatCurrency(baseFinancial.projected_ebitda)}
                </div>
              </div>
              {compareScenarios.map((scenario, idx) => {
                const value = scenario.result?.financial_impact?.projected_ebitda;
                return (
                  <div key={idx} className="comparison-scenario-col">
                    <div className="comparison-value">{formatCurrency(value)}</div>
                  </div>
                );
              })}
            </div>

            {/* EBITDA at Risk */}
            <div className="comparison-row">
              <div className="comparison-metric-label">EBITDA at Risk</div>
              <div className="comparison-scenario-col">
                <div className="comparison-value">
                  {formatCurrency(baseFinancial.ebitda_at_risk)}
                </div>
              </div>
              {compareScenarios.map((scenario, idx) => {
                const value = scenario.result?.financial_impact?.ebitda_at_risk;
                return (
                  <div key={idx} className="comparison-scenario-col">
                    <div className="comparison-value">{formatCurrency(value)}</div>
                  </div>
                );
              })}
            </div>

            {/* Potential Loss */}
            <div className="comparison-row">
              <div className="comparison-metric-label">Potential Loss</div>
              <div className="comparison-scenario-col">
                <div className="comparison-value">
                  {formatCurrency(baseFinancial.potential_loss)}
                </div>
              </div>
              {compareScenarios.map((scenario, idx) => {
                const value = scenario.result?.financial_impact?.potential_loss;
                return (
                  <div key={idx} className="comparison-scenario-col">
                    <div className="comparison-value">{formatCurrency(value)}</div>
                  </div>
                );
              })}
            </div>

            {/* Scenario Parameters – dynamic from actual deltas */}
            {allDeltaKeys.length > 0 && (
              <>
                <div className="comparison-section-header">
                  <div className="comparison-metric-label">Scenario Parameters</div>
                </div>

                {allDeltaKeys.map(key => (
                  <div key={key} className="comparison-row">
                    <div className="comparison-metric-label">{formatDeltaLabel(key)}</div>
                    <div className="comparison-scenario-col">
                      <div className="comparison-value">
                        {baseInputs[key] != null ? formatDeltaValue(key, baseInputs[key]) : '—'}
                      </div>
                    </div>
                    {compareScenarios.map((scenario, idx) => {
                      const val = scenario.values?.[key];
                      const baseVal = baseInputs[key];
                      const hasDelta = val != null && baseVal != null && Number(val) !== Number(baseVal);
                      return (
                        <div key={idx} className="comparison-scenario-col">
                          <div className="comparison-value">
                            {val != null ? formatDeltaValue(key, val) : '—'}
                          </div>
                          {hasDelta && (
                            <div className="comparison-delta" style={{ color: Number(val) > Number(baseVal) ? 'var(--success-color)' : 'var(--error-color)' }}>
                              <FontAwesomeIcon icon={Number(val) > Number(baseVal) ? faArrowUp : faArrowDown} />{' '}
                              {Number(val) > Number(baseVal) ? '+' : ''}{formatDeltaValue(key, Number(val) - Number(baseVal))}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                ))}
              </>
            )}
          </div>
        </div>

        {/* Action Buttons */}
        <div className="action-buttons">
          <button className="action-btn secondary" onClick={onBackToScenario}>
            Back to Scenario Modeling
          </button>
          <button className="action-btn secondary" onClick={onBackToSummary}>
            Back to Dashboard
          </button>
          {compareScenarios.map((scenario, idx) => (
            <button 
              key={idx}
              className="action-btn success" 
              onClick={() => {
                onAdopt?.(scenario.result);
                alert(`${scenario.label} adopted as current analysis`);
              }}
            >
              <FontAwesomeIcon icon={faCheck} /> Adopt {scenario.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
