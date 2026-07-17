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
import { JaspenAIProvider } from './jaspenInterface/shared/JaspenAIContext';

// Shared
import HomePage      from './homeSections/HomePage/HomePage';
import GetInTouch    from './pages/GetInTouch/GetInTouch';
import Privacy       from './pages/Privacy/privacy';
import Terms         from './pages/Terms/terms';
import Support       from './pages/Support/Support';
import AuthCallback  from './shared/components/AuthCallback';
import ResetPasswordPage from './pages/Auth/ResetPasswordPage';
import SalesforceOAuthBridge from './pages/Auth/SalesforceOAuthBridge';
import JaspenScorePage from './pages/Marketing/JaspenScorePage';
import JaspenPage from './pages/Marketing/JaspenPage';
import ProjectManagementPage from './pages/Marketing/ProjectManagementPage';
import JaspenInJiraPage from './pages/Marketing/JaspenInJiraPage';
import JaspenInSmartsheetsPage from './pages/Marketing/JaspenInSmartsheetsPage';
import PricingPage from './pages/Marketing/PricingPage';
import ApiPage from './pages/Marketing/ApiPage';
import DemosPage from './pages/Resources/DemosPage';
import TutorialsPage from './pages/Resources/TutorialsPage';
import ConnectorsPage from './pages/Resources/ConnectorsPage';
import PluginsPage from './pages/Resources/PluginsPage';
import CalculatorsHubPage from './pages/Calculators/CalculatorsHubPage';
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
const JaspenAdmin = lazy(() => import('./jaspenInterface/Admin/JaspenAdmin'));
const MasterAnalytics = lazy(() => import('./jaspenInterface/Admin/MasterAnalytics'));
const MasterLeads = lazy(() => import('./jaspenInterface/Admin/MasterLeads'));
const MasterErrors = lazy(() => import('./jaspenInterface/Admin/MasterErrors'));
const DecisionProfile = lazy(() => import('./jaspenInterface/DecisionProfile/DecisionProfile'));
const Knowledge = lazy(() => import('./jaspenInterface/Knowledge/Knowledge'));
const Team = lazy(() => import('./jaspenInterface/Team/Team'));
const EnterpriseAdmin = lazy(() => import('./jaspenInterface/EnterpriseAdmin/EnterpriseAdmin'));
const JaspenChat = lazy(() => import('./jaspenInterface/Workspace/JaspenChat'));
const JaspenWorkspace = lazy(() => import('./jaspenInterface/Workspace/JaspenWorkspace'));
const StudioApp = lazy(() => import('./studio/StudioApp'));
const ExecutionPlan = lazy(() => import('./jaspenInterface/ExecutionPlan/ExecutionPlan'));
// Public business utilities (tools). Lazily loaded for bundle splitting.
const CostOfTurnoverPage = lazy(() => import('./tools/costOfTurnover/components/CostOfTurnoverPage'));
const MortgageCalculatorPage = lazy(() => import('./tools/mortgage/components/MortgageCalculatorPage'));
const RentCalculatorPage = lazy(() => import('./tools/rent/components/RentCalculatorPage'));

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
            <Route path="/"               element={withShell(<HomePage />, { title: 'Jaspen', showHeader: false, fullBleed: true, noPadding: true })} />
            <Route path="/login"          element={withShell(<GetInTouch />, { title: 'Login', showHeader: false, fullBleed: true, noPadding: true })} />
            <Route path="/pricing"        element={withShell(<PricingResult />, { title: 'Pricing', showHeader: false, fullBleed: true, noPadding: true })} />
            <Route path="/pages/privacy"  element={withShell(<Privacy />, { title: 'Privacy policy', showHeader: false, fullBleed: true, noPadding: true })} />
            <Route path="/pages/terms"    element={withShell(<Terms />, { title: 'Terms of service', showHeader: false, fullBleed: true, noPadding: true })} />
            <Route path="/pages/support"  element={withShell(<Support />, { title: 'Support', showHeader: false, fullBleed: true, noPadding: true })} />
            <Route path="/pages/jaspen-score" element={withShell(<JaspenScorePage />, { title: 'Jaspen Score', showHeader: false, fullBleed: true, noPadding: true })} />
            <Route path="/pages/jaspen" element={withShell(<JaspenPage />, { title: 'Jaspen — Execution Intelligence', showHeader: false, fullBleed: true, noPadding: true })} />
            <Route path="/pages/project-management" element={withShell(<ProjectManagementPage />, { title: 'Project Management | Jaspen', showHeader: false, fullBleed: true, noPadding: true })} />
            <Route path="/pages/jaspen-in-jira" element={withShell(<JaspenInJiraPage />, { title: 'Jaspen in Jira', showHeader: false, fullBleed: true, noPadding: true })} />
            <Route path="/pages/jaspen-in-smartsheets" element={withShell(<JaspenInSmartsheetsPage />, { title: 'Jaspen in Smartsheet', showHeader: false, fullBleed: true, noPadding: true })} />
            <Route path="/pages/pricing" element={withShell(<PricingPage />, { title: 'Pricing', showHeader: false, fullBleed: true, noPadding: true })} />
            <Route path="/pages/api" element={withShell(<ApiPage />, { title: 'API', showHeader: false, fullBleed: true, noPadding: true })} />
            <Route path="/pages/resources/demos" element={withShell(<DemosPage />, { title: 'Demos', showHeader: false, fullBleed: true, noPadding: true })} />
            <Route path="/pages/resources/tutorials" element={withShell(<TutorialsPage />, { title: 'Tutorials', showHeader: false, fullBleed: true, noPadding: true })} />
            <Route path="/pages/resources/connectors" element={withShell(<ConnectorsPage />, { title: 'Connectors', showHeader: false, fullBleed: true, noPadding: true })} />
            <Route path="/pages/resources/plugins" element={withShell(<PluginsPage />, { title: 'Plugins', showHeader: false, fullBleed: true, noPadding: true })} />
            <Route path="/calculators" element={withShell(<CalculatorsHubPage />, { title: 'Free Calculators', showHeader: false, fullBleed: true, noPadding: true })} />
            <Route path="/auth/callback"  element={withShell(<AuthCallback />, { title: 'Authentication', showHeader: false, fullBleed: true, noPadding: true })} />
            <Route path="/api/v1/connectors/salesforce/oauth/callback" element={<SalesforceOAuthBridge />} />
            <Route path="/reset-password" element={withShell(<ResetPasswordPage />, { title: 'Reset password', showHeader: false, fullBleed: true, noPadding: true })} />

            {/* Public business utilities (tools) */}
            <Route path="/tools/cost-of-turnover" element={withShell(<CostOfTurnoverPage />, { title: 'Cost of Employee Turnover Calculator', showHeader: false, fullBleed: true, noPadding: true })} />
            {/* Canonical redirects: never duplicate the page for these aliases */}
            <Route path="/tools/cost-of-turnover-calculator" element={<Navigate to="/tools/cost-of-turnover" replace />} />
            <Route path="/tools/employee-turnover-cost" element={<Navigate to="/tools/cost-of-turnover" replace />} />
            <Route path="/tools/cost-of-employee-turnover" element={<Navigate to="/tools/cost-of-turnover" replace />} />
            <Route path="/tools/attrition-cost-calculator" element={<Navigate to="/tools/cost-of-turnover" replace />} />

            <Route path="/tools/mortgage-calculator" element={withShell(<MortgageCalculatorPage />, { title: 'True Cost of Home Ownership Calculator', showHeader: false, fullBleed: true, noPadding: true })} />
            <Route path="/tools/true-cost-of-mortgage" element={<Navigate to="/tools/mortgage-calculator" replace />} />
            <Route path="/tools/home-ownership-cost-calculator" element={<Navigate to="/tools/mortgage-calculator" replace />} />

            <Route path="/tools/rent-calculator" element={withShell(<RentCalculatorPage />, { title: 'True Cost of Renting Calculator', showHeader: false, fullBleed: true, noPadding: true })} />
            <Route path="/tools/true-cost-of-rent" element={<Navigate to="/tools/rent-calculator" replace />} />
            <Route path="/server-error" element={withShell(<ServerErrorPage />, { title: 'Server error', showHeader: false, fullBleed: true, noPadding: true })} />

            {/* Protected (Market) */}
            <Route
              path="/dashboard"
              element={
                <ProtectedRoute>
                  <RequireDashboardAccess>
                    {withShell(<Dashboard />, { title: 'Dashboard', showHeader: false, fullBleed: true, noPadding: true, backToJaspen: true })}
                  </RequireDashboardAccess>
                </ProtectedRoute>
              }
            />
            <Route
              path="/new"
              element={withShell(<JaspenChat />, { title: 'Jaspen', showHeader: false, fullBleed: true, noPadding: true })}
            />
            <Route
              path="/studio"
              element={<ProtectedRoute>{withShell(<StudioApp />, { title: 'Studio | Jaspen', showHeader: false, fullBleed: true, noPadding: true })}</ProtectedRoute>}
            />
            <Route
              path="/workspace/:threadId/:scorecardId"
              element={withShell(<JaspenWorkspace />, { title: 'Workspace | Jaspen', showHeader: false, fullBleed: true, noPadding: true })}
            />
            <Route
              path="/execution-plan"
              element={withShell(<ExecutionPlan />, { title: 'Execution | Jaspen', showHeader: false, fullBleed: true, noPadding: true })}
            />
            <Route path="/strategy" element={<Navigate to="/new" replace />} />
            <Route path="/projects"  element={<ProtectedRoute>{withShell(<Projects />, { title: 'Projects', showHeader: false, fullBleed: true, noPadding: true, backToJaspen: true })}</ProtectedRoute>} />
            <Route
              path="/scores"
              element={
                <ProtectedRoute>
                  {withShell(<Scores />, { title: 'Scores', showHeader: false, fullBleed: true, noPadding: true, backToJaspen: true })}
                </ProtectedRoute>
              }
            />
            <Route
              path="/insights"
              element={
                <ProtectedRoute>
                  {withShell(<Insights />, { title: 'Insights', showHeader: false, fullBleed: true, noPadding: true, backToJaspen: true })}
                </ProtectedRoute>
              }
            />
            <Route
              path="/reports"
              element={
                <ProtectedRoute>
                  {withShell(<Reports />, { title: 'Reports', showHeader: false, fullBleed: true, noPadding: true, backToJaspen: true })}
                </ProtectedRoute>
              }
            />
            <Route
              path="/activity"
              element={
                <ProtectedRoute>
                  {withShell(<Activity />, { title: 'Activity', showHeader: false, fullBleed: true, noPadding: true, backToJaspen: true })}
                </ProtectedRoute>
              }
            />
            <Route
              path="/connectors-manage"
              element={
                <ProtectedRoute>
                  {withShell(<ConnectorsManage />, { title: 'Data Sources', showHeader: false, fullBleed: true, noPadding: true, backToJaspen: true })}
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
                    noPadding: true, backToJaspen: true,
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
                    noPadding: true, backToJaspen: true,
                  })}
                </ProtectedRoute>
              }
            />
            <Route
              path="/decision-profile"
              element={
                <ProtectedRoute>
                  {withShell(<DecisionProfile />, {
                    title: 'Decision Profile',
                    showHeader: false,
                    fullBleed: true,
                    noPadding: true, backToJaspen: true,
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
                    noPadding: true, backToJaspen: true,
                  })}
                </ProtectedRoute>
              }
            />
            <Route
              path="/admin/analytics"
              element={
                <ProtectedRoute>
                  {withShell(<MasterAnalytics />, {
                    title: 'Analytics',
                    showHeader: false,
                    fullBleed: true,
                    noPadding: true, backToJaspen: true,
                  })}
                </ProtectedRoute>
              }
            />
            <Route
              path="/admin/leads"
              element={
                <ProtectedRoute>
                  {withShell(<MasterLeads />, {
                    title: 'Leads',
                    showHeader: false,
                    fullBleed: true,
                    noPadding: true, backToJaspen: true,
                  })}
                </ProtectedRoute>
              }
            />
            <Route
              path="/admin/errors"
              element={
                <ProtectedRoute>
                  {withShell(<MasterErrors />, {
                    title: 'Error Dashboard',
                    showHeader: false,
                    fullBleed: true,
                    noPadding: true, backToJaspen: true,
                  })}
                </ProtectedRoute>
              }
            />

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

  const withShell = (node, options = {}) => {
    const title = options.title ?? 'Jaspen';
    return (
      <AppShell
        title={title}
        subtitle={options.subtitle}
        actions={options.actions}
        header={options.header}
        showHeader={options.showHeader !== false}
        fullBleed={options.fullBleed}
        noPadding={options.noPadding}
        backToJaspen={options.backToJaspen}
      >
        {node}
      </AppShell>
    );
  };

  return (
    <BrowserRouter>
      <JaspenAIProvider>
        <OfflineBanner />
        <AnimatedAppRoutes withShell={withShell} />
      </JaspenAIProvider>
    </BrowserRouter>
  );
}
