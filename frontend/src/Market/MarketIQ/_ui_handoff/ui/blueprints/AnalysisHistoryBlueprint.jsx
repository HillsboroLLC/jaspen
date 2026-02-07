/**
 * AnalysisHistoryBlueprint.jsx — Analysis History list
 *
 * Used in two contexts:
 *  1. As drawer content (inside the HISTORY drawer on the chat page)
 *  2. As the full-page Analyses list (page 08-activities)
 *
 * Shows a list of past analysis sessions with:
 *  - Score circle (small)
 *  - Project name
 *  - Date and metadata
 *  - Delete / action buttons
 *
 * INTEGRATION: replace mockHistory with your real analysis history data.
 * INTEGRATION: wire onSelect, onDelete to your real handlers.
 */
import React from 'react';

// ---- Mock Data ----
const mockHistory = [
  {
    id: 'abc-001',
    name: 'Retail Expansion — Texas',
    score: 72,
    label: 'Good',
    date: 'Jan 28, 2026',
    version: 'v3',
  },
  {
    id: 'abc-002',
    name: 'SaaS Product Launch',
    score: 46,
    label: 'Fair',
    date: 'Jan 15, 2026',
    version: 'v1',
  },
  {
    id: 'abc-003',
    name: 'Franchise Model Analysis',
    score: 58,
    label: 'Fair',
    date: 'Dec 20, 2025',
    version: 'v2',
  },
];

function ScoreCircleSmall({ score }) {
  return (
    <div
      style={{
        width: 44,
        height: 44,
        borderRadius: '50%',
        border: '3px solid var(--miq-navy)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexShrink: 0,
      }}
    >
      <span style={{ fontSize: 'var(--miq-text-base)', fontWeight: 700, color: 'var(--miq-navy)' }}>
        {score}
      </span>
    </div>
  );
}

export default function AnalysisHistoryBlueprint({
  // INTEGRATION: accept these as props
  items = mockHistory,
  onSelect,
  onDelete,
  /** Set to true when used as full-page list (adds padding, title) */
  fullPage = false,
}) {
  const containerStyle = fullPage
    ? { padding: '0' }
    : { padding: '8px 0' };

  return (
    <div style={containerStyle}>
      {/* INTEGRATION: replace mockHistory with real analysis history */}
      {items.length === 0 && (
        <div
          style={{
            padding: '40px 16px',
            textAlign: 'center',
            color: 'var(--miq-gray-500)',
            fontSize: 'var(--miq-text-base)',
          }}
        >
          <i
            className="fa-solid fa-clock-rotate-left"
            style={{ fontSize: '1.5rem', marginBottom: '8px', display: 'block' }}
          />
          No analyses yet. Start a conversation to create your first scorecard.
        </div>
      )}

      {items.map((item) => (
        <div
          key={item.id}
          onClick={() => onSelect?.(item.id)}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '12px',
            padding: '12px 16px',
            cursor: 'pointer',
            borderBottom: '1px solid var(--miq-border)',
            transition: 'background var(--miq-transition)',
          }}
          onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--miq-gray-50)')}
          onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
        >
          <ScoreCircleSmall score={item.score} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div
              style={{
                fontSize: 'var(--miq-text-base)',
                fontWeight: 600,
                color: 'var(--miq-navy)',
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}
            >
              {item.name}
            </div>
            <div style={{ fontSize: 'var(--miq-text-sm)', color: 'var(--miq-gray-500)' }}>
              {item.date}
              {item.version && (
                <span style={{ marginLeft: '8px', color: 'var(--miq-gray-400)' }}>
                  {item.version}
                </span>
              )}
            </div>
          </div>
          <button
            onClick={(e) => {
              e.stopPropagation();
              onDelete?.(item.id);
            }}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--miq-gray-400)',
              cursor: 'pointer',
              fontSize: 'var(--miq-text-base)',
              padding: '4px',
              flexShrink: 0,
            }}
          >
            <i className="fa-solid fa-trash" />
          </button>
        </div>
      ))}
    </div>
  );
}
