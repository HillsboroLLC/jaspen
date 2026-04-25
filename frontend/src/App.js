// =====================================================
// File: src/App.js
// =====================================================
import React, { Suspense, lazy, useEffect } from 'react';
import '@fortawesome/fontawesome-free/css/all.min.css';
import './App.css';

import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import ProtectedRoute from './homeSections/ProtectedRoute';
import RequireTeamAccess from './shared/auth/RequireTeamAccess';
import RequireDashboardAccess from './shared/auth/RequireDashboardAccess';
import { useAuth } from './shared/auth/AuthContext';
import { AppShell } from './jaspenInterface/layout';

// Shared
import HomePage      from './homeSections/HomePage/HomePage';
import GetInTouch    from './pages/GetInTouch/GetInTouch';
import Privacy       from './pages/Privacy/privacy';
import Terms         from './pages/Terms/terms';
import Support       from './pages/Support/Support';
import AuthCallback  from './shared/components/AuthCallback';
import ResetPasswordPage from './pages/Auth/ResetPasswordPage';
import JaspenScorePage from './pages/Marketing/JaspenScorePage';
import SolutionsPage from './pages/Marketing/SolutionsPage';
import PricingPage from './pages/Marketing/PricingPage';
import ApiPage from './pages/Marketing/ApiPage';
import DemosPage from './pages/Resources/DemosPage';
import TutorialsPage from './pages/Resources/TutorialsPage';
import IntegrationsPage from './pages/Resources/IntegrationsPage';
import ConnectorsPage from './pages/Resources/ConnectorsPage';
import PluginsPage from './pages/Resources/PluginsPage';
import NotFoundPage from './pages/NotFound/NotFound';
import ServerErrorPage from './pages/ServerError/ServerError';
import OfflineBanner from './shared/components/OfflineBanner';

// Lazily loaded internal routes for bundle splitting.
const PricingResult = lazy(() => import('./jaspenInterface/PricingResult/PricingResult'));
const Dashboard = lazy(() => import('./jaspenInterface/Jaspen Cleanup/Dashboard/Dashboard'));
const Projects = lazy(() => import('./jaspenInterface/Projects/Projects'));
const Scores = lazy(() => import('./jaspenInterface/Scores/Scores'));
const Insights = lazy(() => import('./jaspenInterface/Insights/Insights'));
const Reports = lazy(() => import('./jaspenInterface/Reports/Reports'));
const Activity = lazy(() => import('./jaspenInterface/Activity/Activity'));
const ConnectorsManage = lazy(() => import('./jaspenInterface/Connectors/ConnectorsManage'));
const Account = lazy(() => import('./jaspenInterface/Account/Account'));
const PaymentPage = lazy(() => import('./jaspenInterface/PaymentPage/PaymentPage'));
const JaspenAdmin = lazy(() => import('./jaspenInterface/Admin/JaspenAdmin'));
const Knowledge = lazy(() => import('./jaspenInterface/Knowledge/Knowledge'));
const Team = lazy(() => import('./jaspenInterface/Team/Team'));
const EnterpriseAdmin = lazy(() => import('./jaspenInterface/EnterpriseAdmin/EnterpriseAdmin'));
const JaspenWorkspace = lazy(() => import('./jaspenInterface/Workspace/JaspenWorkspace'));

function AnimatedAppRoutes({ withShell }) {
  const location = useLocation();
  const prefersReducedMotion = useReducedMotion();
  const transitionProps = prefersReducedMotion
    ? { initial: false, animate: { opacity: 1 }, exit: { opacity: 1 }, transition: { duration: 0 } }
    : { initial: { opacity: 0, y: 6 }, animate: { opacity: 1, y: 0 }, exit: { opacity: 0, y: -6 }, transition: { duration: 0.2, ease: 'easeOut' } };

  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.div
        key={`${location.pathname}${location.search}`}
        className="app-route-transition"
        {...transitionProps}
      >
        <Suspense fallback={<div className="app-route-loading" aria-live="polite">Loading page…</div>}>
          <Routes location={location}>
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
            <Route path="/reset-password" element={withShell(<ResetPasswordPage />, { showHeader: false, fullBleed: true, noPadding: true })} />
            <Route path="/server-error" element={withShell(<ServerErrorPage />, { title: 'Server error', showHeader: false, fullBleed: true, noPadding: true })} />

            {/* Protected (Market) */}
            <Route
              path="/dashboard"
              element={
                <ProtectedRoute>
                  <RequireDashboardAccess>
                    {withShell(<Dashboard />, { showHeader: false, fullBleed: true, noPadding: true })}
                  </RequireDashboardAccess>
                </ProtectedRoute>
              }
            />
            <Route
              path="/new"
              element={withShell(<JaspenWorkspace />, { title: 'Jaspen', showHeader: false, fullBleed: true, noPadding: true })}
            />
            <Route path="/strategy" element={<Navigate to="/new" replace />} />
            <Route path="/projects"  element={<ProtectedRoute>{withShell(<Projects />, { showHeader: false, fullBleed: true, noPadding: true })}</ProtectedRoute>} />
            <Route
              path="/scores"
              element={
                <ProtectedRoute>
                  {withShell(<Scores />, { showHeader: false, fullBleed: true, noPadding: true })}
                </ProtectedRoute>
              }
            />
            <Route
              path="/insights"
              element={
                <ProtectedRoute>
                  {withShell(<Insights />, { showHeader: false, fullBleed: true, noPadding: true })}
                </ProtectedRoute>
              }
            />
            <Route
              path="/reports"
              element={
                <ProtectedRoute>
                  {withShell(<Reports />, { showHeader: false, fullBleed: true, noPadding: true })}
                </ProtectedRoute>
              }
            />
            <Route
              path="/activity"
              element={
                <ProtectedRoute>
                  {withShell(<Activity />, { showHeader: false, fullBleed: true, noPadding: true })}
                </ProtectedRoute>
              }
            />
            <Route
              path="/connectors-manage"
              element={
                <ProtectedRoute>
                  {withShell(<ConnectorsManage />, { showHeader: false, fullBleed: true, noPadding: true })}
                </ProtectedRoute>
              }
            />
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
              path="/team"
              element={
                <ProtectedRoute>
                  <RequireTeamAccess>
                    {withShell(<Team />, {
                      title: 'Team',
                      showHeader: false,
                      fullBleed: true,
                      noPadding: true,
                    })}
                  </RequireTeamAccess>
                </ProtectedRoute>
              }
            />
            <Route
              path="/enterprise-admin"
              element={
                <ProtectedRoute>
                  {withShell(<EnterpriseAdmin />, {
                    title: 'Enterprise Admin',
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

            <Route path="*" element={withShell(<NotFoundPage />, { title: 'Page not found', showHeader: false, fullBleed: true, noPadding: true })} />
          </Routes>
        </Suspense>
      </motion.div>
    </AnimatePresence>
  );
}
export default function App() {
  const { user } = useAuth();

  useEffect(() => {
    const root = document.documentElement;
    const preference = String(user?.ui_preferences?.theme || 'system').trim().toLowerCase();
    const themePreference = ['light', 'dark', 'system'].includes(preference) ? preference : 'system';

    const applyResolvedTheme = () => {
      if (themePreference === 'dark') {
        root.setAttribute('data-theme', 'dark');
        return;
      }
      if (themePreference === 'light') {
        root.setAttribute('data-theme', 'light');
        return;
      }
      root.removeAttribute('data-theme');
    };

    applyResolvedTheme();

    if (themePreference !== 'system') return undefined;
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const onChange = () => applyResolvedTheme();
    if (typeof media.addEventListener === 'function') {
      media.addEventListener('change', onChange);
      return () => media.removeEventListener('change', onChange);
    }
    media.addListener(onChange);
    return () => media.removeListener(onChange);
  }, [user?.ui_preferences?.theme]);

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
      <OfflineBanner />
      <AnimatedAppRoutes withShell={withShell} />
    </BrowserRouter>
  );
}
