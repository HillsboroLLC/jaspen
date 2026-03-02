// ============================================================================
// File: ReadinessSidebar.jsx - ENHANCED A+ VERSION
// Purpose: Readiness indicator sidebar with expandable categories and micro elements
// Features:
// - Expandable/collapsible macro categories
// - Hyphen (-) for incomplete, checkmark (✓) for complete
// - Color-coded progress indicators
// - Detailed micro element tracking
// - Foundation for Phase 2/3 enhancements
// ============================================================================
import React from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faCheck, faMinus } from '@fortawesome/free-solid-svg-icons';

// Category display names
const CATEGORY_LABELS = {
  business_description: 'Business Description',
  target_market: 'Target Market',
  revenue_model: 'Revenue Model',
  financial_metrics: 'Financial Metrics',
  timeline: 'Timeline',
  budget: 'Budget',
  competition: 'Competition',
  team: 'Team & Resources'
};

export default function ReadinessSidebar({ readiness, collectedData, uiReadiness }) {
  // Helper functions
  const clamp = (v, lo = 0, hi = 100) => Math.min(hi, Math.max(lo, v));
  const isNum = (v) => typeof v === 'number' && Number.isFinite(v);

  // Extract categories from readiness object
  const categories = readiness?.categories || [];
  
  // Calculate overall readiness percent
  const computeReadinessPercent = (raw) => {
    if (raw && typeof raw === 'object') {
      const c = Number.isFinite(raw.collected) ? raw.collected : 0;
      const t = Number.isFinite(raw.total) ? raw.total : 0;
      if (t > 0) return clamp(Math.round((c / t) * 100));
    }
    if (isNum(raw)) return clamp(Math.round(raw));
    
    // Fallback: calculate from categories
    if (categories.length > 0) {
      const totalWeight = categories.reduce((sum, cat) => sum + (cat.weight || 0), 0);
      const weightedSum = categories.reduce((sum, cat) => {
        const percent = cat.percent || 0;
        const weight = cat.weight || 0;
        return sum + ((percent / 100) * weight);
      }, 0);
      return clamp(Math.round((weightedSum / totalWeight) * 100));
    }
    
    return 0;
  };

const readinessPercent = Number.isFinite(uiReadiness)
  ? clamp(Math.round(uiReadiness))
  : computeReadinessPercent(readiness?.percent ?? readiness);

  // Get status text
  const getStatusText = (percent) => {
    if (percent >= 90) return 'Ready to analyze';
    if (percent >= 60) return 'Almost ready';
    if (percent >= 25) return 'Making progress';
    return 'Gathering information';
  };

  const statusLabel = getStatusText(readinessPercent);
  const displayCategories = categories.map((category) => {
    const key = category.key || category.name || '';
    const label = category.label || CATEGORY_LABELS[key] || key || 'Category';
    const rawWeight = Number(category.weight);
    const weightPct = Number.isFinite(rawWeight)
      ? `${Math.round(rawWeight <= 1 ? rawWeight * 100 : rawWeight)}%`
      : '';
    const done = category.completed === true || (Number(category.percent) >= 100);
    return { key, label, weightPct, done };
  });

  return (
    <div style={{ padding: '20px 16px' }}>
      {/* Circular indicator */}
      <div style={{ textAlign: 'center', marginBottom: '20px' }}>
        <div
          className={`miq-readiness-circle ${readinessPercent >= 70 ? 'high' : ''}`}
          style={{
            width: 120,
            height: 120,
            borderRadius: '50%',
            border: `8px solid ${readinessPercent >= 70 ? 'var(--miq-magenta)' : 'var(--miq-gray-200)'}`,
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
            {readinessPercent}%
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
      {displayCategories.length === 0 && (
        <div
          style={{
            padding: '40px 16px',
            textAlign: 'center',
            color: 'var(--miq-gray-500)',
            fontSize: 'var(--miq-text-base)',
          }}
        >
          Start the conversation to begin tracking progress.
        </div>
      )}

      {displayCategories.map((cat) => (
        <div key={cat.key} className="miq-readiness-cat">
          <div className={`miq-readiness-check ${cat.done ? 'done' : ''}`}>
            <FontAwesomeIcon icon={cat.done ? faCheck : faMinus} />
          </div>
          <div style={{ flex: 1 }}>
            <div
              style={{
                color: 'var(--miq-navy)',
                fontWeight: 500,
                fontSize: 'var(--miq-text-base)',
              }}
            >
              {cat.label}
            </div>
            <div
              style={{
                fontSize: 'var(--miq-text-sm)',
                color: 'var(--miq-gray-500)',
              }}
            >
              {cat.weightPct ? `${cat.weightPct} weight` : 'Weight pending'}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
