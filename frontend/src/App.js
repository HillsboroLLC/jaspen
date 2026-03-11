// =====================================================
// File: src/App.js
// =====================================================
import React from 'react';
import '@fortawesome/fontawesome-free/css/all.min.css';
import './App.css';

import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import ProtectedRoute from './homeSections/ProtectedRoute';
import { AppShell } from './jaspenInterface/layout';

// Shared
import HomePage      from './homeSections/HomePage/HomePage';
import GetInTouch    from './pages/GetInTouch/GetInTouch';
import Privacy       from './pages/Privacy/privacy';
import Terms         from './pages/Terms/terms';
import Support       from './pages/Support/Support';
import AuthCallback  from './shared/components/AuthCallback';
import JaspenScorePage from './pages/Marketing/JaspenScorePage';
import SolutionsPage from './pages/Marketing/SolutionsPage';
import PricingPage from './pages/Marketing/PricingPage';
import ApiPage from './pages/Marketing/ApiPage';
import DemosPage from './pages/Resources/DemosPage';
import TutorialsPage from './pages/Resources/TutorialsPage';
import IntegrationsPage from './pages/Resources/IntegrationsPage';
import ConnectorsPage from './pages/Resources/ConnectorsPage';
import PluginsPage from './pages/Resources/PluginsPage';

// Jaspen
import PricingResult from './jaspenInterface/PricingResult/PricingResult';
import Dashboard     from './jaspenInterface/Jaspen Cleanup/Dashboard/Dashboard';
import Sessions      from './jaspenInterface/Sessions/Sessions';
import Account       from './jaspenInterface/Account/Account';
import PaymentPage   from './jaspenInterface/PaymentPage/PaymentPage';
import JaspenAdmin   from './jaspenInterface/Admin/JaspenAdmin';
import Knowledge     from './jaspenInterface/Knowledge/Knowledge';

// Jaspen.ai Workspace
import JaspenWorkspace from './jaspenInterface/Workspace/JaspenWorkspace';
console.log("[BOOT] App.js loaded", window.location.href);
export default function App() {
  const getDisplayName = (node) =>
    node?.type?.displayName || node?.type?.name || 'Page';

  const toTitle = (name) =>
    String(name || 'Page')
      .replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2')
      .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
      .replace(/_/g, ' ')
      .trim();

  const withShell = (node, options = {}) => {
    const title = options.title ?? toTitle(getDisplayName(node));
    return (
      <AppShell
        title={title}
        subtitle={options.subtitle}
        actions={options.actions}
        header={options.header}
        showHeader={options.showHeader !== false}
        fullBleed={options.fullBleed}
        noPadding={options.noPadding}
      >
        {node}
      </AppShell>
    );
  };

  return (
    <BrowserRouter>
      <Routes>
        {/* Public */}
        <Route path="/"               element={withShell(<HomePage />, { showHeader: false, fullBleed: true, noPadding: true })} />
        <Route path="/login"          element={withShell(<GetInTouch />, { showHeader: false, fullBleed: true, noPadding: true })} />
        <Route path="/pricing"        element={withShell(<PricingResult />)} />
        <Route path="/pages/privacy"  element={withShell(<Privacy />)} />
        <Route path="/pages/terms"    element={withShell(<Terms />)} />
        <Route path="/pages/support"  element={withShell(<Support />)} />
        <Route path="/pages/jaspen-score" element={withShell(<JaspenScorePage />, { showHeader: false, fullBleed: true, noPadding: true })} />
        <Route path="/pages/solutions" element={withShell(<SolutionsPage />, { showHeader: false, fullBleed: true, noPadding: true })} />
        <Route path="/pages/pricing" element={withShell(<PricingPage />, { showHeader: false, fullBleed: true, noPadding: true })} />
        <Route path="/pages/api" element={withShell(<ApiPage />, { showHeader: false, fullBleed: true, noPadding: true })} />
        <Route path="/pages/resources/demos" element={withShell(<DemosPage />, { showHeader: false, fullBleed: true, noPadding: true })} />
        <Route path="/pages/resources/tutorials" element={withShell(<TutorialsPage />, { showHeader: false, fullBleed: true, noPadding: true })} />
        <Route path="/pages/resources/integrations" element={withShell(<IntegrationsPage />, { showHeader: false, fullBleed: true, noPadding: true })} />
        <Route path="/pages/resources/connectors" element={withShell(<ConnectorsPage />, { showHeader: false, fullBleed: true, noPadding: true })} />
        <Route path="/pages/resources/plugins" element={withShell(<PluginsPage />, { showHeader: false, fullBleed: true, noPadding: true })} />
        <Route path="/auth/callback"  element={withShell(<AuthCallback />, { showHeader: false, fullBleed: true, noPadding: true })} />

        {/* Protected (Market) */}
        <Route
          path="/dashboard"
          element={
            <ProtectedRoute>
              {withShell(<Dashboard />, { showHeader: false, fullBleed: true, noPadding: true })}
            </ProtectedRoute>
          }
        />
        <Route
          path="/new"
          element={withShell(<JaspenWorkspace />, { title: 'Jaspen', showHeader: false, fullBleed: true, noPadding: true })}
        />
        <Route path="/market-iq" element={<Navigate to="/new" replace />} />
        <Route path="/sessions"  element={<ProtectedRoute>{withShell(<Sessions />)}</ProtectedRoute>} />
        <Route
          path="/account"
          element={
            <ProtectedRoute>
              {withShell(<Account />, {
                title: 'Account and billing',
                showHeader: false,
                fullBleed: true,
                noPadding: true,
              })}
            </ProtectedRoute>
          }
        />
        <Route
          path="/knowledge"
          element={
            <ProtectedRoute>
              {withShell(<Knowledge />, {
                title: 'Knowledge',
                showHeader: false,
                fullBleed: true,
                noPadding: true,
              })}
            </ProtectedRoute>
          }
        />
        <Route
          path="/jaspen-admin"
          element={
            <ProtectedRoute>
              {withShell(<JaspenAdmin />, {
                title: 'Jaspen Admin',
                showHeader: false,
                fullBleed: true,
                noPadding: true,
              })}
            </ProtectedRoute>
          }
        />
        <Route path="/payment"   element={<ProtectedRoute>{withShell(<PaymentPage />)}</ProtectedRoute>} />

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
