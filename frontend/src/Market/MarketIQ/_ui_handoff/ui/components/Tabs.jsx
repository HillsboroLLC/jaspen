/**
 * Tabs.jsx — Presentational tabs component
 *
 * Controlled externally via `activeId` and `onTabChange`.
 * Renders only the tab bar; the parent is responsible for showing the
 * correct pane content based on the active tab.
 *
 * Usage:
 *   const tabs = [
 *     { id: 'score',     label: 'Score' },
 *     { id: 'scenarios', label: 'Scenarios' },
 *     { id: 'refine',    label: 'Refine & Rescore' },
 *   ];
 *   <Tabs tabs={tabs} activeId={activeTab} onTabChange={setActiveTab} />
 */
import React from 'react';

const barStyle = {
  display: 'flex',
  gap: 0,
  borderBottom: '1px solid var(--miq-border)',
  padding: '0 var(--miq-space-8) 0 var(--miq-space-12)',
  flexShrink: 0,
};

const tabBase = {
  padding: '10px 20px',
  fontSize: 'var(--miq-text-base)',
  fontWeight: 500,
  color: 'var(--miq-gray-600)',
  border: 'none',
  background: 'none',
  cursor: 'pointer',
  fontFamily: 'var(--miq-font)',
  borderBottom: '2px solid transparent',
  transition: 'all var(--miq-transition)',
};

const tabActive = {
  color: 'var(--miq-navy)',
  borderBottomColor: 'var(--miq-magenta)',
  fontWeight: 600,
};

export default function Tabs({
  tabs = [],
  activeId,
  onTabChange,
  className = '',
  style: customStyle = {},
  ...props
}) {
  return (
    <div className={`miq-tab-bar ${className}`} style={{ ...barStyle, ...customStyle }} {...props}>
      {tabs.map((tab) => {
        const isActive = tab.id === activeId;
        return (
          <button
            key={tab.id}
            className={`miq-tab ${isActive ? 'active' : ''}`}
            style={{ ...tabBase, ...(isActive ? tabActive : {}) }}
            onClick={() => onTabChange?.(tab.id)}
          >
            {tab.icon && <i className={tab.icon} style={{ marginRight: '6px', fontSize: '0.75rem' }} />}
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}
