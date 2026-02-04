// =====================================================
// File: src/App.js
// =====================================================
import React from 'react';
import '@fortawesome/fontawesome-free/css/all.min.css';
import './App.css';

import { LSSProjectProvider } from './Ops/context/LSSProjectContext';
import { LSSWorkflowProvider } from './Ops/context/LSSWorkflowContext';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import ProtectedRoute from './All/components/ProtectedRoute';

// Shared
import HomePage      from './All/components/HomePage/HomePage';
import Home          from './All/pages/Home/Home';
import Profile       from './All/Profile/Profile';
import Blog          from './All/Blog/Blog';
import Login         from './All/Login/Login';
import SignUp        from './All/SignUp/SignUp';
import Privacy       from './All/pages/Privacy/privacy';
import Terms         from './All/pages/Terms/terms';
import Support       from './All/pages/Support/Support';

// Market
import Solopreneurs  from './Market/Solopreneurs/Solopreneurs';
import SmallBusiness from './Market/SmallBusiness/SmallBusiness';
import Enterprise    from './Market/Enterprise/Enterprise';
import PricingResult from './Market/PricingResult/PricingResult';
import Dashboard     from './Market/Dashboard/Dashboard';
import Sessions      from './Market/Sessions/Sessions';
import Account       from './Market/Account/Account';
import PaymentPage   from './Market/PaymentPage/PaymentPage';

// Market IQ (NEW)
import MarketIQWorkspace from './Market/MarketIQ/workspace/MarketIQWorkspace';

// Ops
import { AdminProvider } from './Ops/context/AdminContext';
import OpsDashboard        from './Ops/OpsDashboard/OpsDashboard';
import PMDashboard        from './Ops/PMDashboard/PMDashboard';
import LSSDashboard        from './Ops/LSSDashboard/LSSDashboard';
import SIPOC               from './Ops/SIPOC';
import ProcessMap          from './Ops/ProcessMap';
import ValueStreamMap      from './Ops/ValueStreamMap';
import RootCauseAnalysis   from './Ops/RootCauseAnalysis';
import FMEA                from './Ops/FMEA';
import ProjectCharter      from './Ops/ProjectCharter';
import VoiceOfCustomer     from './Ops/VoiceOfCustomer';
import DataCollectionPlan  from './Ops/DataCollectionPlan';
import MSA                 from './Ops/MSA';
import ControlPlan         from './Ops/ControlPlan';
import StandardWork        from './Ops/StandardWork';
import Checksheet          from './Ops/Checksheet';
import RunChart            from './Ops/RunChart';
import ParetoAnalysis      from './Ops/ParetoAnalysis';
import HypothesisTesting   from './Ops/HypothesisTesting';
import FiveWhys            from './Ops/FiveWhys';
import Histogram           from './Ops/Histogram';
import ScatterPlot         from './Ops/ScatterPlot';
import ControlChart        from './Ops/ControlChart';
import BoxPlot             from './Ops/BoxPlot';
import ANOVA               from './Ops/ANOVA';
import CapabilityAnalysis  from './Ops/CapabilityAnalysis';
import SolutionSelection   from './Ops/SolutionSelection';
import PilotPlan           from './Ops/PilotPlan';
import DOE                 from './Ops/DOE';
import ImplementationPlan  from './Ops/ImplementationPlan';
import A3                  from './Ops/A3';
import Checklists          from './Ops/Checklists';
import DataCollection      from './Ops/DataCollection';
import EffortImpactMatrix  from './Ops/EffortImpactMatrix';
import GapAnalysis         from './Ops/GapAnalysis';
import ProblemStatement    from './Ops/ProblemStatement';
import ProjectPlanning     from './Ops/ProjectPlanning';
import StakeholderAnalysis from './Ops/StakeholderAnalysis';
import SustainmentPlan     from './Ops/SustainmentPlan';
import DMAIC               from './Ops/DMAIC';
import FinY                from './Ops/FinY';
import Kaizen              from './Ops/Kaizen'; // uses src/Ops/Kaizen/index.js
import Statistics          from './Ops/Statistics/Statistics';
import Activities          from './Ops/Activities/Activities';

export default function App() {
  return (
    <AdminProvider>
        <LSSProjectProvider>
          <LSSWorkflowProvider>
            <BrowserRouter>
              <Routes>
                {/* Public */}
                <Route path="/"               element={<HomePage />} />
                <Route path="/profile"        element={<Profile />} />
                <Route path="/blog"           element={<Blog />} />
                <Route path="/solopreneurs"   element={<Solopreneurs />} />
                <Route path="/small-business" element={<SmallBusiness />} />
                <Route path="/enterprise"     element={<Enterprise />} />
                <Route path="/login"          element={<Login />} />
                <Route path="/sign-up"        element={<SignUp />} />
                <Route path="/pricing"        element={<PricingResult />} />
                <Route path="/pages/privacy"  element={<Privacy />} />
                <Route path="/pages/terms"    element={<Terms />} />
                <Route path="/pages/support"  element={<Support />} />
                <Route path="/pages/home"     element={<Home />} />

                {/* Protected (Market) */}
                <Route path="/dashboard" element={<ProtectedRoute><Dashboard /></ProtectedRoute>} />
                <Route path="/market-iq" element={<ProtectedRoute><MarketIQWorkspace /></ProtectedRoute>} />
                <Route path="/sessions"  element={<ProtectedRoute><Sessions /></ProtectedRoute>} />
                <Route path="/account"   element={<ProtectedRoute><Account /></ProtectedRoute>} />
                <Route path="/payment"   element={<ProtectedRoute><PaymentPage /></ProtectedRoute>} />

                {/* Protected (Ops) */}
                <Route path="/ops"                      element={<ProtectedRoute><OpsDashboard /></ProtectedRoute>} />
                <Route path="/ops/pm"                   element={<ProtectedRoute><PMDashboard /></ProtectedRoute>} />
                <Route path="/ops/lss"                  element={<ProtectedRoute><LSSDashboard /></ProtectedRoute>} />
                <Route path="/ops/dmaic"                element={<ProtectedRoute><DMAIC /></ProtectedRoute>} />
                <Route path="/ops/kaizen"               element={<ProtectedRoute><Kaizen /></ProtectedRoute>} />
                <Route path="/ops/sipoc"                element={<ProtectedRoute><SIPOC /></ProtectedRoute>} />
                <Route path="/ops/process-map"          element={<ProtectedRoute><ProcessMap /></ProtectedRoute>} />
                <Route path="/ops/value-stream"         element={<ProtectedRoute><ValueStreamMap /></ProtectedRoute>} />
                <Route path="/ops/root-cause"           element={<ProtectedRoute><RootCauseAnalysis /></ProtectedRoute>} />
                <Route path="/ops/fmea"                 element={<ProtectedRoute><FMEA /></ProtectedRoute>} />
                <Route path="/ops/project-charter"      element={<ProtectedRoute><ProjectCharter /></ProtectedRoute>} />
                <Route path="/ops/voice-of-customer"    element={<ProtectedRoute><VoiceOfCustomer /></ProtectedRoute>} />
                <Route path="/ops/data-collection-plan" element={<ProtectedRoute><DataCollectionPlan /></ProtectedRoute>} />
                <Route path="/ops/msa"                  element={<ProtectedRoute><MSA /></ProtectedRoute>} />
                <Route path="/ops/control-plan"         element={<ProtectedRoute><ControlPlan /></ProtectedRoute>} />
                <Route path="/ops/standard-work"        element={<ProtectedRoute><StandardWork /></ProtectedRoute>} />
                <Route path="/ops/checksheet"           element={<ProtectedRoute><Checksheet /></ProtectedRoute>} />
                <Route path="/ops/run-chart"            element={<ProtectedRoute><RunChart /></ProtectedRoute>} />
                <Route path="/ops/pareto-analysis"      element={<ProtectedRoute><ParetoAnalysis /></ProtectedRoute>} />
                <Route path="/ops/hypothesis-testing"   element={<ProtectedRoute><HypothesisTesting /></ProtectedRoute>} />
                <Route path="/ops/five-whys"            element={<ProtectedRoute><FiveWhys /></ProtectedRoute>} />
                <Route path="/ops/histogram"            element={<ProtectedRoute><Histogram /></ProtectedRoute>} />
                <Route path="/ops/scatter-plot"         element={<ProtectedRoute><ScatterPlot /></ProtectedRoute>} />
                <Route path="/ops/control-chart"        element={<ProtectedRoute><ControlChart /></ProtectedRoute>} />
                <Route path="/ops/box-plot"             element={<ProtectedRoute><BoxPlot /></ProtectedRoute>} />
                <Route path="/ops/anova"                element={<ProtectedRoute><ANOVA /></ProtectedRoute>} />
                <Route path="/ops/capability"           element={<ProtectedRoute><CapabilityAnalysis /></ProtectedRoute>} />
                <Route path="/ops/solution-selection"   element={<ProtectedRoute><SolutionSelection /></ProtectedRoute>} />
                <Route path="/ops/pilot-plan"           element={<ProtectedRoute><PilotPlan /></ProtectedRoute>} />
                <Route path="/ops/doe"                  element={<ProtectedRoute><DOE /></ProtectedRoute>} />
                <Route path="/ops/implementation-plan"  element={<ProtectedRoute><ImplementationPlan /></ProtectedRoute>} />
                <Route path="/ops/a3"                   element={<ProtectedRoute><A3 /></ProtectedRoute>} />
                <Route path="/ops/checklists"           element={<ProtectedRoute><Checklists /></ProtectedRoute>} />
                <Route path="/ops/data-collection"      element={<ProtectedRoute><DataCollection /></ProtectedRoute>} />
                <Route path="/ops/effort-impact"        element={<ProtectedRoute><EffortImpactMatrix /></ProtectedRoute>} />
                <Route path="/ops/gap-analysis"         element={<ProtectedRoute><GapAnalysis /></ProtectedRoute>} />
                <Route path="/ops/problem-statement"    element={<ProtectedRoute><ProblemStatement /></ProtectedRoute>} />
                <Route path="/ops/project-planning"     element={<ProtectedRoute><ProjectPlanning /></ProtectedRoute>} />
                <Route path="/ops/stakeholder-analysis" element={<ProtectedRoute><StakeholderAnalysis /></ProtectedRoute>} />
                <Route path="/ops/sustainment-plan"     element={<ProtectedRoute><SustainmentPlan /></ProtectedRoute>} />
                <Route path="/ops/finy"                 element={<ProtectedRoute><FinY /></ProtectedRoute>} />
                <Route path="/ops/statistics"           element={<ProtectedRoute><Statistics /></ProtectedRoute>} />
                <Route path="/ops/activities"           element={<ProtectedRoute><Activities /></ProtectedRoute>} />

                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </BrowserRouter>
          </LSSWorkflowProvider>
        </LSSProjectProvider>
    </AdminProvider>
  );
}
