/**
 * ReadinessSidebarBlueprint.jsx — Analysis Readiness drawer content
 *
 * Shows:
 *  - Circular percentage indicator (88%)
 *  - "Almost ready!" status label
 *  - Information Categories checklist with weights and done/pending states
 *
 * This is the drawer content shown when the "Refine & Rescore" tab is active.
 *
 * INTEGRATION: replace mockCategories with your real readiness state.
 * INTEGRATION: keep existing hooks/state in your real component; only transplant JSX below.
 */
import React from 'react';

// ---- Mock Data (replace with real state) ----
const mockReadinessPercent = 88;
const mockStatusLabel = 'Almost ready!';

const mockCategories = [
  { name: 'Business Description', weight: '10%', done: false },
  { name: 'Target Market',        weight: '15%', done: true },
  { name: 'Revenue Model',        weight: '15%', done: true },
  { name: 'Financial Metrics',    weight: '25%', done: false },
  { name: 'Timeline',             weight: '10%', done: true },
  { name: 'Budget',               weight: '20%', done: true },
  { name: 'Risk Factors',         weight: '5%',  done: false },
];

export default function ReadinessSidebarBlueprint({
  // INTEGRATION: accept these as props from your real state
  percent = mockReadinessPercent,
  statusLabel = mockStatusLabel,
  categories = mockCategories,
}) {
  const isHigh = percent >= 70;

  return (
    <div style={{ padding: '20px 16px' }}>

      {/* Circular indicator */}
      <div style={{ textAlign: 'center', marginBottom: '20px' }}>
        <div
          className={`miq-readiness-circle ${isHigh ? 'high' : ''}`}
          style={{
            width: 120,
            height: 120,
            borderRadius: '50%',
            border: `8px solid ${isHigh ? 'var(--miq-magenta)' : 'var(--miq-gray-200)'}`,
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <span
            style={{
              fontSize: 'var(--miq-text-3xl)',
              fontWeight: 700,
              color: 'var(--miq-navy)',
            }}
          >
            {percent}%
          </span>
        </div>
        <div
          style={{
            fontSize: 'var(--miq-text-base)',
            color: 'var(--miq-gray-600)',
            marginTop: '8px',
          }}
        >
          {statusLabel}
        </div>
      </div>

      {/* Section label */}
      <div
        style={{
          fontSize: 'var(--miq-text-sm)',
          fontWeight: 600,
          textTransform: 'uppercase',
          letterSpacing: '0.1em',
          color: 'var(--miq-gray-600)',
          marginBottom: '12px',
        }}
      >
        Information Categories
      </div>

      {/* Category list */}
      {categories.map((cat, i) => (
        <div key={i} className="miq-readiness-cat">
          <div className={`miq-readiness-check ${cat.done ? 'done' : ''}`}>
            <i className={cat.done ? 'fa-solid fa-check' : 'fa-solid fa-minus'} />
          </div>
          <div style={{ flex: 1 }}>
            <div
              style={{
                color: 'var(--miq-navy)',
                fontWeight: 500,
                fontSize: 'var(--miq-text-base)',
              }}
            >
              {cat.name}
            </div>
            <div
              style={{
                fontSize: 'var(--miq-text-sm)',
                color: 'var(--miq-gray-500)',
              }}
            >
              {cat.weight} weight
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
