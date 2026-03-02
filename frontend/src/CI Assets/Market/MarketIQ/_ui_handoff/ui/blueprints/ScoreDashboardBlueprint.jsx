/**
 * ScoreDashboardBlueprint.jsx — Score tab main content
 *
 * Shows:
 *  - Edit link (top-right)
 *  - Score circle (big number + badge)
 *  - Financial Impact table
 *  - Key Metrics section (navy bar header)
 *  - Scores breakdown table (navy bar header)
 *
 * INTEGRATION: replace mockScores / mockFinancials with real scorecard data.
 * INTEGRATION: keep existing hooks/state in your real component; only transplant JSX below.
 */
import React from 'react';

// ---- Mock Data ----
const mockScore = {
  value: 46,
  label: 'Fair',
  description:
    'The overall score reflects your current inputs and highlights both strengths and areas to improve.',
};

const mockFinancials = [
  { label: 'EBITDA At Risk',   value: '$0' },
  { label: 'Potential Loss',   value: '$0' },
  { label: 'ROI Opportunity',  value: '$0' },
  { label: 'Projected EBITDA', value: '$0' },
];

const mockMetrics = [
  { label: 'Industry Vertical', value: 'Real Estate', sub: 'Market Position' },
];

const mockScores = [
  { name: 'Execution Readiness',    value: 40, explanation: 'Reflects your stated timeline, team, and funding inputs.' },
  { name: 'Financial Health',       value: 50, explanation: 'Reflects the available revenue, margin, and churn inputs.' },
  { name: 'Market Position',        value: 45, explanation: 'Reflects your stated market and competitive context.' },
  { name: 'Operational Efficiency', value: 50, explanation: 'Based on the available execution and ops inputs.' },
];

export default function ScoreDashboardBlueprint({
  // INTEGRATION: accept these as props
  score = mockScore,
  financials = mockFinancials,
  metrics = mockMetrics,
  scores = mockScores,
  onEdit,
}) {
  const overallValue = scores.reduce((sum, s) => sum + s.value, 0) / scores.length;

  return (
    <div>
      {/* Edit link */}
      <div style={{ textAlign: 'right', marginBottom: '16px' }}>
        <span
          onClick={onEdit}
          style={{
            fontSize: 'var(--miq-text-base)',
            color: 'var(--miq-magenta)',
            cursor: 'pointer',
            fontWeight: 500,
          }}
        >
          Edit
        </span>
      </div>

      {/* Score + Financial Impact row */}
      <div style={{ display: 'flex', gap: '40px', alignItems: 'flex-start', marginBottom: '32px' }}>

        {/* Score circle area */}
        <div style={{ textAlign: 'center', minWidth: '200px' }}>
          <div
            style={{
              fontSize: 'var(--miq-text-xs)',
              fontWeight: 600,
              textTransform: 'uppercase',
              letterSpacing: '0.1em',
              color: 'var(--miq-gray-500)',
              marginBottom: '8px',
            }}
          >
            AI Agent Score
          </div>
          <div
            style={{
              fontSize: '3.5rem',
              fontWeight: 700,
              color: 'var(--miq-navy)',
              lineHeight: 1,
            }}
          >
            {score.value}
          </div>
          <div
            style={{
              display: 'inline-block',
              marginTop: '8px',
              padding: '4px 16px',
              borderRadius: 'var(--miq-radius-full)',
              fontSize: 'var(--miq-text-sm)',
              fontWeight: 600,
              color: 'var(--miq-white)',
              background: 'var(--miq-navy)',
            }}
          >
            {score.label}
          </div>
          <div
            style={{
              fontSize: 'var(--miq-text-base)',
              color: 'var(--miq-gray-600)',
              marginTop: '12px',
              lineHeight: 1.5,
              maxWidth: '220px',
            }}
          >
            {score.description}
          </div>
        </div>

        {/* Financial Impact */}
        <div style={{ flex: 1 }}>
          <div
            style={{
              fontSize: 'var(--miq-text-xs)',
              fontWeight: 600,
              textTransform: 'uppercase',
              letterSpacing: '0.1em',
              color: 'var(--miq-gray-500)',
              marginBottom: '10px',
            }}
          >
            Financial Impact
          </div>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <tbody>
              {/* INTEGRATION: replace mockFinancials with real financial data */}
              {financials.map((row, i) => (
                <tr key={i}>
                  <td
                    style={{
                      padding: '10px 14px',
                      fontSize: 'var(--miq-text-base)',
                      borderBottom: '1px solid var(--miq-border)',
                      color: 'var(--miq-navy)',
                      fontWeight: 500,
                    }}
                  >
                    {row.label}
                  </td>
                  <td
                    style={{
                      padding: '10px 14px',
                      fontSize: 'var(--miq-text-base)',
                      borderBottom: '1px solid var(--miq-border)',
                      color: 'var(--miq-navy)',
                      fontWeight: 600,
                      textAlign: 'right',
                    }}
                  >
                    {row.value}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Key Metrics */}
      <div className="miq-section-bar">Key Metrics</div>
      <div style={{ padding: '16px 0' }}>
        {/* INTEGRATION: replace mockMetrics with real key metrics */}
        {metrics.map((m, i) => (
          <div key={i} style={{ marginBottom: '8px' }}>
            <div
              style={{
                fontSize: 'var(--miq-text-xs)',
                textTransform: 'uppercase',
                letterSpacing: '0.08em',
                color: 'var(--miq-gray-500)',
              }}
            >
              {m.label}
            </div>
            <div
              style={{
                fontSize: 'var(--miq-text-lg)',
                fontWeight: 600,
                color: 'var(--miq-navy)',
              }}
            >
              {m.value}
            </div>
            {m.sub && (
              <div style={{ fontSize: 'var(--miq-text-sm)', color: 'var(--miq-gray-500)' }}>
                {m.sub}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Scores Table */}
      <div className="miq-section-bar">Scores</div>
      <table className="miq-table" style={{ marginTop: '4px' }}>
        <thead>
          <tr>
            <th>Score</th>
            <th>Value</th>
            <th>Explanation</th>
          </tr>
        </thead>
        <tbody>
          {/* INTEGRATION: replace mockScores with real score breakdown */}
          {scores.map((s, i) => (
            <tr key={i}>
              <td>{s.name}</td>
              <td style={{ fontWeight: 600 }}>{s.value}</td>
              <td style={{ color: 'var(--miq-gray-600)', fontSize: 'var(--miq-text-sm)' }}>
                {s.explanation}
              </td>
            </tr>
          ))}
          <tr>
            <td style={{ fontWeight: 600 }}>Overall</td>
            <td style={{ fontWeight: 700 }}>{score.value}</td>
            <td>&mdash;</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}
