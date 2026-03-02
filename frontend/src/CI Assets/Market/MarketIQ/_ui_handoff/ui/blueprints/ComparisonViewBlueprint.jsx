/**
 * ComparisonViewBlueprint.jsx — Score Summary drawer panel
 *
 * This is the "Score Summary" sub-tab content shown inside the drawer
 * when the Scenarios tab is active. It displays:
 *  - Project name
 *  - Overall score (big number) with /100 and label
 *  - Category breakdown bars (Financial Health, Operational Efficiency, etc.)
 *
 * INTEGRATION: replace mockCategories with your real score breakdown data.
 * INTEGRATION: keep existing hooks/state in your real component; only transplant JSX below.
 */
import React from 'react';

// ---- Mock Data ----
const mockProjectName = 'AI Agent Project';
const mockOverallScore = 46;
const mockOverallLabel = 'Fair';

const mockCategories = [
  { name: 'Financial Health',       value: 50 },
  { name: 'Operational Efficiency', value: 50 },
  { name: 'Market Position',        value: 45 },
  { name: 'Execution Readiness',    value: 40 },
];

export default function ComparisonViewBlueprint({
  // INTEGRATION: accept these as props
  projectName = mockProjectName,
  overallScore = mockOverallScore,
  overallLabel = mockOverallLabel,
  categories = mockCategories,
}) {
  return (
    <div style={{ padding: '20px 16px' }}>
      {/* Project name */}
      <div
        style={{
          fontSize: 'var(--miq-text-md)',
          fontWeight: 600,
          color: 'var(--miq-navy)',
          marginBottom: '4px',
        }}
      >
        {projectName}
      </div>

      {/* Overall score */}
      <div style={{ marginBottom: '20px' }}>
        <span
          style={{
            fontSize: '2rem',
            fontWeight: 700,
            color: 'var(--miq-navy)',
          }}
        >
          {overallScore}
        </span>
        <span
          style={{
            fontSize: 'var(--miq-text-md)',
            fontWeight: 500,
            color: 'var(--miq-gray-500)',
            marginLeft: '4px',
          }}
        >
          /100
        </span>
        <span
          style={{
            fontSize: 'var(--miq-text-md)',
            fontWeight: 500,
            color: 'var(--miq-gray-500)',
            marginLeft: '8px',
          }}
        >
          &bull; {overallLabel}
        </span>
      </div>

      {/* Category bars */}
      {/* INTEGRATION: replace mockCategories with real score categories */}
      {categories.map((cat, i) => (
        <div key={i} style={{ marginBottom: '14px' }}>
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              fontSize: 'var(--miq-text-base)',
              marginBottom: '4px',
            }}
          >
            <span style={{ color: 'var(--miq-navy)' }}>{cat.name}</span>
            <span style={{ fontWeight: 600, color: 'var(--miq-navy)' }}>{cat.value}</span>
          </div>
          <div className="miq-progress" style={{ height: '8px' }}>
            <div
              className="miq-progress-fill magenta"
              style={{ width: `${cat.value}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}
