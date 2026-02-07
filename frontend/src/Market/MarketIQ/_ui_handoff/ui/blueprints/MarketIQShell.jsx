/**
 * MarketIQShell.jsx — Master layout blueprint
 *
 * Provides the outer shell: drawer tab(s) on left edge, slide-out drawer panel,
 * and main content area. The drawer PUSHES main content (no overlap).
 *
 * INTEGRATION: This is a layout wrapper. In your real app, wrap your MarketIQ
 * page content with <MarketIQShell>. Keep your existing routing and state;
 * only transplant the JSX structure below.
 */
import React, { useState, useCallback } from 'react';

// INTEGRATION: replace these with your real drawer content components
const PlaceholderDrawerContent = ({ label }) => (
  <div style={{ padding: '20px', color: 'var(--miq-gray-600)', fontSize: 'var(--miq-text-base)' }}>
    {label} drawer content goes here
  </div>
);

export default function MarketIQShell({
  /** Which drawer tab(s) to show. Array of { id, label, icon } */
  drawerTabs = [],
  /** The currently active drawer tab id (controls which drawer variant renders) */
  activeDrawerTab = null,
  /** Render prop: (activeDrawerTab) => JSX for the drawer body */
  renderDrawer,
  /** Main page content */
  children,
}) {
  const [isDrawerOpen, setDrawerOpen] = useState(false);
  const [selectedDrawer, setSelectedDrawer] = useState(activeDrawerTab || drawerTabs[0]?.id);

  const openDrawer = useCallback((tabId) => {
    setSelectedDrawer(tabId);
    setDrawerOpen(true);
  }, []);

  const closeDrawer = useCallback(() => {
    setDrawerOpen(false);
  }, []);

  // Sync activeDrawerTab prop changes (e.g., when main tabs switch)
  React.useEffect(() => {
    if (activeDrawerTab) setSelectedDrawer(activeDrawerTab);
  }, [activeDrawerTab]);

  const activeTabMeta = drawerTabs.find((t) => t.id === selectedDrawer) || drawerTabs[0];

  return (
    <div className={`miq miq-shell ${isDrawerOpen ? 'drawer-open' : ''}`}>

      {/* ===== Drawer Tab(s) on left edge ===== */}
      {drawerTabs.map((tab, idx) => (
        <button
          key={tab.id}
          className="miq-drawer-tab"
          style={{ top: `${80 + idx * 120}px` }}
          onClick={() => openDrawer(tab.id)}
        >
          <i className={tab.icon} />
          {tab.label}
        </button>
      ))}

      {/* ===== Drawer Panel ===== */}
      <aside className={`miq-drawer ${isDrawerOpen ? 'open' : ''}`}>
        <div className="miq-drawer-header">
          <h3>
            {activeTabMeta?.icon && (
              <i className={activeTabMeta.icon} style={{ color: 'var(--miq-magenta)' }} />
            )}
            {activeTabMeta?.label}
          </h3>
          <button className="miq-drawer-close" onClick={closeDrawer}>
            <i className="fa-solid fa-xmark" />
          </button>
        </div>
        <div className="miq-drawer-body">
          {/* INTEGRATION: replace with your real drawer content */}
          {renderDrawer
            ? renderDrawer(selectedDrawer)
            : <PlaceholderDrawerContent label={activeTabMeta?.label} />
          }
        </div>
      </aside>

      {/* ===== Main Content ===== */}
      <main className="miq-main">
        {children}
      </main>
    </div>
  );
}
