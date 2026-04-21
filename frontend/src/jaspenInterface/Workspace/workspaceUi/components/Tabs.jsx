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
 *   ];
 *   <Tabs tabs={tabs} activeId={activeTab} onTabChange={setActiveTab} />
 */
import React from 'react';

const barStyle = {
  display: 'flex',
  gap: 0,
  borderBottom: '1px solid var(--jas-border)',
  padding: '0 var(--jas-space-8) 0 var(--jas-space-12)',
  flexShrink: 0,
};

const tabBase = {
  padding: '10px 20px',
  fontSize: 'var(--jas-text-base)',
  fontWeight: 500,
  color: 'var(--jas-gray-600)',
  border: 'none',
  background: 'none',
  cursor: 'pointer',
  fontFamily: 'var(--jas-font)',
  borderBottom: '2px solid transparent',
  transition: 'all var(--jas-transition)',
};

const tabActive = {
  color: 'var(--jas-navy)',
  borderBottomColor: 'var(--jas-magenta)',
  fontWeight: 600,
};

export default function Tabs({
  tabs = [],
  activeId,
  onTabChange,
  tablistLabel = 'Tabs',
  className = '',
  style: customStyle = {},
  ...props
}) {
  return (
    <div
      className={`jas-tab-bar ${className}`}
      style={{ ...barStyle, ...customStyle }}
      role="tablist"
      aria-label={tablistLabel}
      {...props}
    >
      {tabs.map((tab) => {
        const isActive = tab.id === activeId;
        return (
          <button
            key={tab.id}
            type="button"
            className={`jas-tab ${isActive ? 'active' : ''}`}
            style={{ ...tabBase, ...(isActive ? tabActive : {}) }}
            onClick={() => onTabChange?.(tab.id)}
            role="tab"
            aria-selected={isActive}
            tabIndex={isActive ? 0 : -1}
          >
            {tab.icon && <i className={tab.icon} style={{ marginRight: '6px', fontSize: '0.75rem' }} />}
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}
