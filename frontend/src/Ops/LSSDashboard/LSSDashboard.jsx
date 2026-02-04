// ==========================================
// File: src/Ops/LSSDashboard/LSSDashboard.jsx
// ==========================================
import React, { useState, useMemo, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../All/shared/auth/AuthContext';
import { useLSSProject } from '../hooks/useLSSProject';
import { useLSSWorkflow } from '../hooks/useLSSWorkflow';
import BackButton from '../../Market/components/Buttons/BackButton';
import RoleSwitcher from '../RoleSwitcher/RoleSwitcher';
import LSSCustomDropdown from './LSSCustomDropdown';
import styles from './LSSDashboard.module.css';

/* ---------- Feature flags / config ----------
   Safe defaults while backend isn’t wired.
------------------------------------------------*/
const ENV = (typeof import.meta !== 'undefined' ? import.meta.env : process.env) || {};

const ALLOW_CREATE_ADMINS =
  String(ENV.VITE_ALLOW_CREATE_ADMINS ?? ENV.REACT_APP_ALLOW_CREATE_ADMINS ?? 'false') === 'true';

const SEATS = {
  TM:    Number(ENV.VITE_SEATS_TM    ?? ENV.REACT_APP_SEATS_TM    ?? 50),
  PL:    Number(ENV.VITE_SEATS_PL    ?? ENV.REACT_APP_SEATS_PL    ?? 10),
  ADMIN: Number(ENV.VITE_SEATS_ADMIN ?? ENV.REACT_APP_SEATS_ADMIN ?? 2),
};
const TOTAL_PLAN = SEATS.TM + SEATS.PL + SEATS.ADMIN;

// Only include routes that actually exist in App.js
const OPS_ROUTES = {
  'Ops Home': '/ops',
  'LSS Dashboard': '/ops/lss',

  // DMAIC
  'Project Charter': '/ops/project-charter',
  'SIPOC': '/ops/sipoc',
  'Voice of Customer': '/ops/voice-of-customer',
  'Process Map': '/ops/process-map',
  'Root Cause Analysis': '/ops/root-cause',
  'FMEA': '/ops/fmea',

  // Statistical & Analysis
  'Control Charts': '/ops/control-chart',
  'Pareto Analysis': '/ops/pareto-analysis',
  'Histogram': '/ops/histogram',
  'Capability Analysis': '/ops/capability',
  'DOE (Design of Experiments)': '/ops/doe',
  'MSA (Measurement System Analysis)': '/ops/msa',
  '5 Whys': '/ops/five-whys',
  'Value Stream Map': '/ops/value-stream',
  'Scatter Plot': '/ops/scatter-plot',
  'Run Chart': '/ops/run-chart',
  'Box Plot': '/ops/box-plot',
  'ANOVA': '/ops/anova',
  'Hypothesis Testing': '/ops/hypothesis-testing',

  // Change Mgmt & Others
  'Control Plan': '/ops/control-plan',
  'Standard Work': '/ops/standard-work',
  'Checksheet': '/ops/checksheet',
  'Solution Selection': '/ops/solution-selection',
  'Pilot Plan': '/ops/pilot-plan',
  'Implementation Plan': '/ops/implementation-plan',
  'A3': '/ops/a3',
  'Checklists': '/ops/checklists',
  'Data Collection': '/ops/data-collection',
  'Effort-Impact Matrix': '/ops/effort-impact',
  'Gap Analysis': '/ops/gap-analysis',
  'Problem Statement': '/ops/problem-statement',
  'Project Planning': '/ops/project-planning',
  'Stakeholder Analysis': '/ops/stakeholder-analysis',
  'Sustainment Plan': '/ops/sustainment-plan',
  'DMAIC': '/ops/dmaic',
  'FinY': '/ops/finy',
};

// Live nav button to valid routes only
const ToolLinkButton = ({ icon, name }) => {
  const navigate = useNavigate();
  const path = OPS_ROUTES[name];
  const disabled = !path;

  return (
    <button
      className={styles.toolBtn}
      onClick={() => !disabled && navigate(path)}
      title={disabled ? 'Coming soon' : path}
      aria-label={name}
      disabled={disabled}
      style={disabled ? { opacity: 0.6, cursor: 'not-allowed' } : undefined}
    >
      <i className={icon}></i>
      <span>{name}</span>
    </button>
  );
};

const LSSDashboard = () => {
  const [activeTab, setActiveTab] = useState('overview');
  const [showKanban, setShowKanban] = useState(false);
  const [viewMode, setViewMode] = useState('all');
  const [selectedTimeRange, setSelectedTimeRange] = useState('30days');

  // Collapsible (desktop) + Drawer (mobile)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);

  // Tools drawer state
  const [lssDrawerOpen, setLssDrawerOpen] = useState(false);
  const [lssActiveTab, setLssActiveTab] = useState("tools");

  const openLssDrawer  = useCallback(() => setLssDrawerOpen(true), []);
  const closeLssDrawer = useCallback(() => setLssDrawerOpen(false), []);

  // Admin System Settings slide-over
  const [showAdminSettings, setShowAdminSettings] = useState(false);

  const [accordionState, setAccordionState] = useState({
    dmaic: true,
    kaizen: false,
    statistical: false,
    analysis: false,
    changeManagement: false,
    financial: false,
    adminSettings: false,
    recentProjects: true,
    myProjects: true,     // Team member
    myDocuments: false    // Team member
  });

  // Right sidebar selections
  const [selectedUserId, setSelectedUserId] = useState(null); // admin

  // PL: collaborator accordion + modals
  const [collabAccordionOpen, setCollabAccordionOpen] = useState(true);
  const [collabModalOpen, setCollabModalOpen] = useState(false);
  const [collabModalUserId, setCollabModalUserId] = useState(null);

  // PL: Add Collaborator modal
  const [addCollabOpen, setAddCollabOpen] = useState(false);
  const [addQuery, setAddQuery] = useState('');
  const [addSelectionId, setAddSelectionId] = useState(null);

  const {
    user,
    isAdmin,
    hasPermission,
    isProjectLead: ctxIsProjectLead,
    currentUserRole,
    USER_ROLES,
    canAccessKanban,
    lssUsers
  } = useAuth();

  const navigate = useNavigate();

  const { projects } = useLSSProject();
  const { DMAIC_PHASES } = useLSSWorkflow();

  const dmaicPhaseNames = Array.isArray(DMAIC_PHASES)
    ? DMAIC_PHASES.map(p => (typeof p === 'string' ? p : p.name || p.id || 'Unknown'))
    : ['DEFINE', 'MEASURE', 'ANALYZE', 'IMPROVE', 'CONTROL'];

  const toggleAccordion = (section) =>
    setAccordionState(prev => ({ ...prev, [section]: !prev[section] }));

  // ---- ROLE
  const getUserRole = () => {
    if (isAdmin && isAdmin()) return 'admin';
    const leadByHelper = typeof ctxIsProjectLead === 'function' ? ctxIsProjectLead() : false;
    const leadByPerm = typeof hasPermission === 'function' ? hasPermission('project_lead') : false;
    const leadByValue = currentUserRole === USER_ROLES?.PROJECT_LEAD;
    if (leadByHelper || leadByPerm || leadByValue) return 'projectLead';
    return 'teamMember';
  };

  // ---- FILTERS
  const getFilteredProjects = () => {
    if (!Array.isArray(projects)) return [];
    const role = getUserRole();
    const uid = user?.id;

    if (role === 'teamMember') {
      return projects.filter(
        p => Array.isArray(p?.teamMembers) && p.teamMembers.includes(uid)
      );
    }

    if (isAdmin && isAdmin()) {
      if (viewMode === 'all') return projects;
      return projects.filter(p => p.leadId === uid || (Array.isArray(p?.teamMembers) && p.teamMembers.includes(uid)));
    }

    // project lead: only their projects
    if (role === 'projectLead') {
      return projects.filter(
        p => p.leadId === uid || (Array.isArray(p?.teamMembers) && p.teamMembers.includes(uid))
      );
    }

    return projects.filter(
      p => p.leadId === uid || (p.teamMembers && p.teamMembers.includes(uid))
    );
  };

  const filteredProjects = getFilteredProjects();

  // Users list + role normalization
  const users = Array.isArray(lssUsers) ? lssUsers : [];
  const normRole = (r = '') => {
    const s = String(r).toLowerCase();
    if (s.includes('lead')) return 'Project Lead';
    if (s.includes('admin')) return 'Admin';
    return 'Team Member';
  };

  const seatUsage = useMemo(() => {
    const counts = { TM: 0, PL: 0, ADMIN: 0 };
    users.forEach(u => {
      const role = normRole(u.role);
      if (role === 'Project Lead') counts.PL += 1;
      else if (role === 'Admin') counts.ADMIN += 1;
      else counts.TM += 1;
    });
    return counts;
  }, [users]);

  const seatAvail = {
    TM: Math.max(SEATS.TM - seatUsage.TM, 0),
    PL: Math.max(SEATS.PL - seatUsage.PL, 0),
    ADMIN: Math.max(SEATS.ADMIN - seatUsage.ADMIN, 0),
  };

  // ---- DOCUMENTS (scoped)
  const projectsForDocs = (isAdmin && isAdmin()) ? (projects || []) : (filteredProjects || []);
  const allDocuments = Array.isArray(projectsForDocs)
    ? projectsForDocs.flatMap(p =>
        Array.isArray(p?.documents)
          ? p.documents.map(d => ({
              ...d,
              __projectId: p.id,
              __projectName: p.name
            }))
          : []
      )
    : [];

  const myDocuments = allDocuments.filter(d => {
    const uid = user?.id;
    const inCollab = Array.isArray(d?.collaborators) && d.collaborators.includes(uid);
    const inInvited = Array.isArray(d?.invited) && d.invited.includes(uid);
    const isOwner = d?.ownerId === uid;
    return inCollab || inInvited || isOwner;
  });

  // Helpers to normalize document "type" and completion
  const getDocType = (doc) => {
    if (doc?.type) return doc.type;
    const t = (doc?.title || doc?.name || '').toLowerCase();
    if (t.includes('charter')) return 'Project Charter';
    if (t.includes('sipoc')) return 'SIPOC';
    if (t.includes('voice of customer') || t.includes('voc')) return 'Voice of Customer';
    if (t.includes('process map')) return 'Process Map';
    if (t.includes('root cause')) return 'Root Cause Analysis';
    if (t.includes('fmea')) return 'FMEA';
    if (t.includes('control chart')) return 'Control Charts';
    if (t.includes('pareto')) return 'Pareto Analysis';
    if (t.includes('histogram')) return 'Histogram';
    if (t.includes('capability')) return 'Capability Analysis';
    if (t.includes('doe')) return 'DOE (Design of Experiments)';
    if (t.includes('msa')) return 'MSA (Measurement System Analysis)';
    if (t.includes('5 whys') || t === '5 whys') return '5 Whys';
    if (t.includes('value stream')) return 'Value Stream Map';
    if (t.includes('scatter')) return 'Scatter Plot';
    if (t.includes('run chart')) return 'Run Chart';
    if (t.includes('box plot')) return 'Box Plot';
    if (t.includes('anova')) return 'ANOVA';
    if (t.includes('hypothesis')) return 'Hypothesis Testing';
    if (t.includes('control plan')) return 'Control Plan';
    if (t.includes('checklist')) return 'Checklists';
    return 'Other';
  };

  const isCompletedByUser = (doc, uid) => {
    const statusDone = doc?.status === 'completed' || doc?.completed === true || !!doc?.completedAt;
    const byUser =
      doc?.completedBy === uid ||
      (Array.isArray(doc?.completedBy) && doc.completedBy.includes(uid)) ||
      doc?.ownerId === uid;
    return statusDone && byUser;
  };

  const myCompletedDocs = myDocuments.filter(d => isCompletedByUser(d, user?.id));

  const completedCountsByType = myCompletedDocs.reduce((acc, d) => {
    const key = getDocType(d);
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});
  const itemsCompletedRows = Object.entries(completedCountsByType)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10);
  const maxCompleted = itemsCompletedRows.reduce((m, [, v]) => Math.max(m, v), 0) || 1;

  // Time helpers
  const nowTs = Date.now();
  const msPerDay = 1000 * 60 * 60 * 24;
  const rangeDays = (range) => {
    switch (range) {
      case '7days': return 7;
      case '30days': return 30;
      case '90days': return 90;
      case '1year': return 365;
      default: return 30;
    }
  };
  const isInRange = (dateIso, range) => {
    if (!dateIso) return false;
    const days = rangeDays(range);
    const dt = new Date(dateIso).getTime();
    return (nowTs - dt) <= days * msPerDay;
  };
  const dayDiff = (startIso, endIso) => {
    if (!startIso || !endIso) return null;
    const diff = (new Date(endIso).getTime() - new Date(startIso).getTime()) / msPerDay;
    return diff >= 0 ? Math.round(diff) : null;
  };
  const getDocStart = (doc) => doc?.startedAt || doc?.createdAt || doc?.updatedAt || null;
  const isDocCompleted = (doc) =>
    doc?.status === 'completed' || doc?.completed === true || !!doc?.completedAt;

  // ---- METRICS (adds Cancelled)
  const dashboardMetrics = (() => {
    const activeProjects = filteredProjects.filter(p => p.status && p.status !== 'completed' && p.status !== 'cancelled').length;
    const completedProjects = filteredProjects.filter(p => p.status === 'completed').length;
    const cancelledProjects = filteredProjects.filter(p => p.status === 'cancelled').length;
    const totalSavings = filteredProjects.reduce((s, p) => s + (p.savings || 0), 0);
    const totalUsers = Array.isArray(lssUsers) ? lssUsers.length : 0;
    const onSchedule = filteredProjects.filter(p => p.scheduleStatus === 'on-track').length;
    const withinScope = filteredProjects.filter(p => p.scopeStatus === 'within-scope').length;
    const withinBudget = filteredProjects.filter(p => p.budgetStatus === 'within-budget').length;
    const utilization = totalUsers > 0 ? Math.round((activeProjects / totalUsers) * 100) : 0;
    const denom = Math.max(activeProjects, 1) * 3;
    const projectHealth = Math.round(((onSchedule + withinScope + withinBudget) / denom) * 100) || 0;

    // Avg cycle time
    const role = getUserRole();
    const sourceDocs = role === 'admin'
      ? allDocuments.filter(d => isDocCompleted(d) && isInRange(d?.completedAt, selectedTimeRange))
      : myCompletedDocs.filter(d => isInRange(d?.completedAt, selectedTimeRange));

    const docCycleTimes = sourceDocs
      .map(d => dayDiff(getDocStart(d), d?.completedAt))
      .filter(v => Number.isFinite(v));

    let avgCycleTime = 0;
    if (docCycleTimes.length > 0) {
      const sum = docCycleTimes.reduce((a, b) => a + b, 0);
      avgCycleTime = Math.round(sum / docCycleTimes.length);
    } else {
      const projectsForFallback = role === 'admin' ? (Array.isArray(projects) ? projects : []) : filteredProjects;
      const completedProjectsInRange = projectsForFallback.filter(
        p => p.status === 'completed' && isInRange(p?.completedAt || p?.endDate, selectedTimeRange)
      );
      const projCycleTimes = completedProjectsInRange
        .map(p => dayDiff(p?.startDate || p?.createdAt, p?.completedAt || p?.endDate))
        .filter(v => Number.isFinite(v));
      avgCycleTime = projCycleTimes.length > 0
        ? Math.round(projCycleTimes.reduce((a, b) => a + b, 0) / projCycleTimes.length)
        : 0;
    }

    return {
      activeProjects,
      completedProjects,
      cancelledProjects,
      totalSavings,
      avgCycleTime,
      totalUsers,
      onSchedule,
      withinScope,
      withinBudget,
      utilization,
      projectHealth
    };
  })();

  // ---- Dynamic charts
  const dmaicPhaseRows = useMemo(() => {
    const order = dmaicPhaseNames.map(n => String(n).toUpperCase());
    const counts = {};
    order.forEach(k => (counts[k] = 0));
    (filteredProjects || []).forEach(p => {
      const key = String(p?.currentPhase || '').toUpperCase();
      if (!key) return;
      if (!(key in counts)) counts[key] = 0;
      counts[key] += 1;
    });
    const rows = [...order, ...Object.keys(counts).filter(k => !order.includes(k))].map(k => [k, counts[k] || 0]);
    const max = rows.reduce((m, [, v]) => Math.max(m, v), 0) || 1;
    return { rows, max };
  }, [filteredProjects, dmaicPhaseNames]);

  const monthlySavings = useMemo(() => {
    const months = [];
    const now = new Date();
    for (let i = 5; i >= 0; i--) {
      const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
      months.push({
        key: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`,
        label: d.toLocaleString('en-US', { month: 'short' }),
        total: 0
      });
    }
    const buckets = new Map(months.map(m => [m.key, m]));
    const pickDate = (p) =>
      p?.savingsAppliedAt || p?.completedAt || p?.updatedAt || p?.createdAt || null;

    (filteredProjects || []).forEach(p => {
      const amount = Number(p?.savings || 0);
      if (!Number.isFinite(amount) || amount <= 0) return;
      const when = pickDate(p);
      if (!when) return;
      const dt = new Date(when);
      const key = `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}`;
      if (buckets.has(key)) buckets.get(key).total += amount;
    });

    const max = months.reduce((m, b) => Math.max(m, b.total), 0) || 1;
    return { months, max };
  }, [filteredProjects]);

  const formatCurrency = (amount) =>
    new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 0, maximumFractionDigits: 0 }).format(amount);

  const handleCreateProject = () => {
    const newProject = {
      name: `New LSS Project ${filteredProjects.length + 1}`,
      type: 'DMAIC',
      leadId: user?.id,
      status: 'active',
      currentPhase: 'DEFINE',
      savings: 0,
      createdAt: new Date().toISOString()
    };
    // if (typeof createProject === 'function') createProject(newProject);
  };

  // Admin tabs (removed System Settings tab — slide-over replaces it)
  const tabs = (isAdmin && isAdmin())
    ? [
        { id: 'overview', label: 'Overview', icon: 'fas fa-chart-line' },
        { id: 'financials', label: 'Financials', icon: 'fas fa-dollar-sign' },
        { id: 'project-health', label: 'Project Health', icon: 'fas fa-heartbeat' },
        { id: 'team-performance', label: 'Team Performance', icon: 'fas fa-users' }
      ]
    : [{ id: 'overview', label: 'Overview', icon: 'fas fa-chart-line' }];

  // ======== LEFT NAV SECTIONS (Updated categorization only) ========
  const allSections = {
    dmaic: {
      title: 'DMAIC TOOLS',
      icon: 'fas fa-project-diagram',
      tools: [
        { name: 'DMAIC', icon: 'fas fa-stream' },
        { name: 'Project Charter', icon: 'fas fa-clipboard-list' },
        { name: 'Problem Statement', icon: 'fas fa-quote-left' },
        { name: 'SIPOC', icon: 'fas fa-sitemap' },
        { name: 'Voice of Customer', icon: 'fas fa-comments' },
        { name: 'Process Map', icon: 'fas fa-project-diagram' },
        { name: 'Stakeholder Analysis', icon: 'fas fa-users' },
        { name: 'Data Collection', icon: 'fas fa-database' },
      ]
    },
    kaizen: {
      title: 'KAIZEN TOOLS',
      icon: 'fas fa-sync-alt',
      tools: [
        { name: '5S Audit', icon: 'fas fa-list-check' },
        { name: 'Gemba Walk', icon: 'fas fa-walking' },
        { name: 'Kaizen Event Plan', icon: 'fas fa-calendar-alt' },
        { name: 'Standard Work', icon: 'fas fa-clipboard-check' },
        { name: 'Visual Management', icon: 'fas fa-eye' }
      ]
    },
    statistical: {
      title: 'STATISTICAL TOOLS',
      icon: 'fas fa-chart-bar',
      tools: [
        { name: 'Control Charts', icon: 'fas fa-chart-line' },
        { name: 'Pareto Analysis', icon: 'fas fa-chart-bar' },
        { name: 'Histogram', icon: 'fas fa-chart-area' },
        { name: 'Capability Analysis', icon: 'fas fa-calculator' },
        { name: 'DOE (Design of Experiments)', icon: 'fas fa-flask' },
        { name: 'MSA (Measurement System Analysis)', icon: 'fas fa-ruler' },
        { name: 'Run Chart', icon: 'fas fa-wave-square' },
        { name: 'Scatter Plot', icon: 'fas fa-braille' },
        { name: 'Box Plot', icon: 'fas fa-square' },
        { name: 'ANOVA', icon: 'fas fa-table' },
        { name: 'Hypothesis Testing', icon: 'fas fa-vial' },
        { name: 'Checksheet', icon: 'fas fa-clipboard-check' },
      ]
    },
    analysis: {
      title: 'ANALYSIS TOOLS',
      icon: 'fas fa-search-plus',
      tools: [
        { name: 'Root Cause Analysis', icon: 'fas fa-search' },
        { name: '5 Whys', icon: 'fas fa-question-circle' },
        { name: 'FMEA', icon: 'fas fa-exclamation-triangle' },
        { name: 'Gap Analysis', icon: 'fas fa-ruler-combined' },
        { name: 'Value Stream Map', icon: 'fas fa-stream' },
      ]
    },
    changeManagement: {
      title: 'CHANGE MANAGEMENT TOOLS',
      icon: 'fas fa-exchange-alt',
      tools: [
        { name: 'Project Planning', icon: 'fas fa-project-diagram' },
        { name: 'Solution Selection', icon: 'fas fa-tasks' },
        { name: 'Pilot Plan', icon: 'fas fa-rocket' },
        { name: 'Implementation Plan', icon: 'fas fa-route' },
        { name: 'Effort-Impact Matrix', icon: 'fas fa-th-large' },
        { name: 'Control Plan', icon: 'fas fa-shield-alt' },
        { name: 'Sustainment Plan', icon: 'fas fa-leaf' },
        { name: 'Standard Work', icon: 'fas fa-clipboard-check' },
        { name: 'Checklists', icon: 'fas fa-list' },
        { name: 'A3', icon: 'fas fa-file-alt' },
      ]
    },
    financial: {
      title: 'FINANCIAL TOOLS',
      icon: 'fas fa-dollar-sign',
      tools: [
        { name: 'FinY', icon: 'fas fa-dollar-sign' },
      ]
    }
  };
  // ======== END Updated categorization ========

  const getToolSections = () => {
    const role = getUserRole();
    if (role === 'admin' || role === 'projectLead') return allSections;
    return {};
  };

  const getAdminSettings = () => {
    if (!(isAdmin && isAdmin())) return null;
    return {
      title: 'ADMIN SETTINGS',
      icon: 'fas fa-cog',
      tools: [
        { name: 'Ops Home', icon: 'fas fa-home' },
        { name: 'LSS Dashboard', icon: 'fas fa-th' }
      ]
    };
  };

  const renderAccordionSection = (sectionKey, section) => {
    const expanded = !!accordionState[sectionKey];
    return (
      <div key={sectionKey} className={styles.accordionSection}>
        <button
          className={`${styles.accordionHeader} ${expanded ? styles.expanded : ''}`}
          onClick={() => toggleAccordion(sectionKey)}
        >
          <div className={styles.accordionTitle}>
            <i className={section.icon}></i>
            <span>{section.title}</span>
          </div>
          <i className={`fas fa-chevron-${expanded ? 'up' : 'down'} ${styles.accordionChevron}`}></i>
        </button>

        {expanded && (
          <div className={styles.accordionContent}>
            <div className={styles.toolsList}>
              {section.tools.map((tool, idx) => (
                <ToolLinkButton key={`${tool.name}-${idx}`} icon={tool.icon} name={tool.name} />
              ))}
            </div>
          </div>
        )}
      </div>
    );
  };

  // List-based accordion renderer for TM "My Projects" & "My Documents"
  const renderListAccordion = (sectionKey, { title, icon, items, emptyText }) => {
    const expanded = !!accordionState[sectionKey];
    return (
      <div className={styles.accordionSection}>
        <button
          className={`${styles.accordionHeader} ${expanded ? styles.expanded : ''}`}
          onClick={() => toggleAccordion(sectionKey)}
        >
          <div className={styles.accordionTitle}>
            <i className={icon}></i>
            <span>{title}</span>
          </div>
          <i className={`fas fa-chevron-${expanded ? 'up' : 'down'} ${styles.accordionChevron}`}></i>
        </button>

        {expanded && (
          <div className={styles.accordionContent}>
            {items.length === 0 ? (
              <div className={styles.emptyState}>{emptyText}</div>
            ) : (
              <div className={styles.simpleList}>
                {items.map((it, idx) => (
                  <div key={`${sectionKey}-${idx}`} className={styles.simpleListItem} title={it.subtitle || ''}>
                    <div className={styles.simpleListLeading}>
                      <i className={it.icon || 'fas fa-file-alt'}></i>
                    </div>
                    <div className={styles.simpleListBody}>
                      <div className={styles.simpleListTitle}>{it.title}</div>
                      {it.subtitle && <div className={styles.simpleListSub}>{it.subtitle}</div>}
                    </div>
                    {it.onClick && (
                      <button className={styles.actionBtn} onClick={it.onClick}>
                        <i className="fas fa-arrow-right"></i>
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    );
  };

  // ------- Kanban Modal -------
  const KanbanModal = () => {
    const [kanbanTasks, setKanbanTasks] = useState({
      todo: ['Plan new features', 'Review user feedback', 'Update documentation'],
      doing: ['Implement dashboard', 'Fix login issues'],
      done: ['Setup authentication', 'Create wireframes', 'Design database schema']
    });
    const [newTask, setNewTask] = useState({ todo: '', doing: '', done: '' });

    const moveTask = (task, from, to) =>
      setKanbanTasks(prev => ({ ...prev, [from]: prev[from].filter(t => t !== task), [to]: [...prev[to], task] }));

    const addTask = (column) => {
      if (newTask[column].trim()) {
        setKanbanTasks(prev => ({ ...prev, [column]: [...prev[column], newTask[column]] }));
        setNewTask(prev => ({ ...prev, [column]: '' }));
      }
    };

    const deleteTask = (task, column) =>
      setKanbanTasks(prev => ({ ...prev, [column]: prev[column].filter(t => t !== task) }));

    if (!showKanban) return null;

    return (
      <div className={styles.modalOverlay} onClick={() => setShowKanban(false)}>
        <div className={styles.kanbanModal} onClick={e => e.stopPropagation()}>
          <div className={styles.kanbanHeader}>
            <h2>Project Board</h2>
            <div className={styles.kanbanActions}>
              <button className={styles.modifyBtn}>Modify</button>
              <button className={styles.closeBtn} onClick={() => setShowKanban(false)}>×</button>
            </div>
          </div>

          <div className={styles.kanbanBoard}>
            {['todo', 'doing', 'done'].map(column => (
              <div key={column} className={styles.kanbanColumn}>
                <div className={styles.columnHeader}>
                  <h3>{column === 'todo' ? 'To Do' : column === 'doing' ? 'Doing' : 'Done'}</h3>
                </div>

                <div className={styles.taskList}>
                  {kanbanTasks[column].map((task, index) => (
                    <div key={index} className={styles.taskCard}>
                      <span>{task}</span>
                      <div className={styles.taskActions}>
                        {column !== 'todo' && (
                          <button className={styles.moveBtn} onClick={() => moveTask(task, column, column === 'doing' ? 'todo' : 'doing')}>←</button>
                        )}
                        {column !== 'done' && (
                          <button className={styles.moveBtn} onClick={() => moveTask(task, column, column === 'todo' ? 'doing' : 'done')}>→</button>
                        )}
                        <button className={styles.deleteBtn} onClick={() => deleteTask(task, column)}>×</button>
                      </div>
                    </div>
                  ))}
                </div>

                <div className={styles.addTask}>
                  <input
                    type="text"
                    placeholder="Add a task..."
                    value={newTask[column]}
                    onChange={(e) => setNewTask(prev => ({ ...prev, [column]: e.target.value }))}
                    onKeyDown={(e) => e.key === 'Enter' && addTask(column)}
                  />
                  <button onClick={() => addTask(column)}>Add Task</button>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  };

  // -------- Project Lead: collaborators (dynamic) --------
  const usersById = useMemo(() => {
    const map = new Map();
    users.forEach(u => map.set(u.id, u));
    return map;
  }, [users]);

  const collaboratorUsers = useMemo(() => {
    if (getUserRole() !== 'projectLead') return [];
    const set = new Set();

    (projectsForDocs || []).forEach(p => {
      (Array.isArray(p?.teamMembers) ? p.teamMembers : []).forEach(uid => set.add(uid));
      if (Array.isArray(p?.documents)) {
        p.documents.forEach(d => {
          (Array.isArray(d?.collaborators) ? d.collaborators : []).forEach(uid => set.add(uid));
          (Array.isArray(d?.invited) ? d.invited : []).forEach(uid => set.add(uid));
          if (d?.ownerId) set.add(d.ownerId);
        });
      }
      if (p?.leadId) set.add(p.leadId);
    });

    set.delete(user?.id);
    return Array.from(set)
      .map(uid => usersById.get(uid))
      .filter(Boolean)
      .sort((a, b) => (a.name || '').localeCompare(b.name || ''));
  }, [projectsForDocs, user?.id, usersById]);

  const selectedCollab = collabModalUserId ? usersById.get(collabModalUserId) : null;

  const collabProjects = useMemo(() => {
    if (!collabModalUserId) return [];
    return (projectsForDocs || []).filter(p => {
      const inTeam = Array.isArray(p?.teamMembers) && p.teamMembers.includes(collabModalUserId);
      const isLead = p?.leadId === collabModalUserId;
      return inTeam || isLead;
    });
  }, [projectsForDocs, collabModalUserId]);

  const collabDocs = useMemo(() => {
    if (!collabModalUserId) return [];
    return (projectsForDocs || [])
      .flatMap(p => Array.isArray(p?.documents)
        ? p.documents.map(d => ({ ...d, __projectId: p.id, __projectName: p.name }))
        : [])
      .filter(d => {
        const inCollab = Array.isArray(d?.collaborators) && d.collaborators.includes(collabModalUserId);
        const inInvited = Array.isArray(d?.invited) && d.invited.includes(collabModalUserId);
        const isOwner = d?.ownerId === collabModalUserId;
        return inCollab || inInvited || isOwner;
      });
  }, [projectsForDocs, collabModalUserId]);

  // ------- Collaborator Detail Modal -------
  const CollaboratorDetailModal = () => {
    if (!collabModalOpen || !selectedCollab) return null;
    return (
      <div className={styles.modalOverlay} onClick={() => setCollabModalOpen(false)}>
        <div className={styles.collaboratorModal} onClick={e => e.stopPropagation()}>
          <div className={styles.modalHeader}>
            <div className={styles.modalTitle}>
              <i className="fas fa-user-friends"></i>
              <span>{selectedCollab.name || 'Teammate'}</span>
            </div>
            <button className={styles.closeBtn} onClick={() => setCollabModalOpen(false)}>×</button>
          </div>

          <div className={styles.modalBody}>
            <div className={styles.modalSection}>
              <h3><i className="fas fa-folder-open"></i> Projects</h3>
              {collabProjects.length === 0 ? (
                <div className={styles.emptyState}>No shared projects yet.</div>
              ) : (
                <ul className={styles.modalList}>
                  {collabProjects.map(p => (
                    <li key={p.id} className={styles.modalListItem}>
                      <div className={styles.itemMain}>{p.name || 'Untitled Project'}</div>
                      <div className={styles.itemMeta}>
                        {p.currentPhase ? `Phase: ${p.currentPhase}` : 'No phase'}
                        {p.status ? ` • ${p.status}` : ''}
                      </div>
                      <button className={styles.linkBtn} onClick={() => {}} title="Open project">
                        Open
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className={styles.modalSection}>
              <h3><i className="fas fa-file-alt"></i> Documents</h3>
              {collabDocs.length === 0 ? (
                <div className={styles.emptyState}>No shared documents yet.</div>
              ) : (
                <ul className={styles.modalList}>
                  {collabDocs.map((d, idx) => (
                    <li key={d.id || idx} className={styles.modalListItem}>
                      <div className={styles.itemMain}>{d.title || d.name || 'Untitled Document'}</div>
                      <div className={styles.itemMeta}>
                        {d.__projectName ? `Project: ${d.__projectName}` : 'Unassigned'}
                        {d.status ? ` • ${d.status}` : ''}
                      </div>
                      <button className={styles.linkBtn} onClick={() => {}} title="Open document">
                        Open
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </div>
      </div>
    );
  };

  // ------- Add Collaborator Search Modal (PL) -------
  const AddCollaboratorModal = () => {
    if (!addCollabOpen) return null;

    const candidates = (Array.isArray(lssUsers) ? lssUsers : [])
      .filter(u => u.id !== user?.id)
      .filter(u => {
        if (!addQuery) return true;
        const hay = `${u.name || ''} ${u.email || ''}`.toLowerCase();
        return hay.includes(addQuery.toLowerCase());
      })
      .sort((a, b) => (a.name || '').localeCompare(b.name || ''));

    const onConfirm = () => {
      if (!addSelectionId) return;
      // TODO: wire to mutation when backend is ready.
      setAddCollabOpen(false);
      setAddSelectionId(null);
      setAddQuery('');
    };

    return (
      <div className={styles.modalOverlay} onClick={() => setAddCollabOpen(false)}>
        <div className={styles.collabModal} onClick={(e) => e.stopPropagation()}>
          <div className={styles.modalHeader}>
            <div className={styles.modalTitle}>
              <i className="fas fa-user-plus" />
              <span>Add Collaborator</span>
            </div>
            <button className={styles.closeBtn} onClick={() => setAddCollabOpen(false)}>×</button>
          </div>

          <div className={styles.modalBody}>
            <div className={styles.modalSection}>
              <label htmlFor="add-collab-search" className={styles.settingLabel}>Search people</label>
              <input
                id="add-collab-search"
                type="text"
                placeholder="Type a name or email…"
                value={addQuery}
                onChange={(e) => setAddQuery(e.target.value)}
                className={styles.input}
              />
              <div className={styles.modalList} style={{ maxHeight: 260, overflow: 'auto', marginTop: 8 }}>
                {candidates.length === 0 ? (
                  <div className={styles.emptyState}>No matches.</div>
                ) : (
                  candidates.map(u => {
                    const selected = addSelectionId === u.id;
                    return (
                      <button
                        key={u.id}
                        className={`${styles.modalListItem} ${selected ? 'selected' : ''}`}
                        onClick={() => setAddSelectionId(u.id)}
                        title={u.email || ''}
                        aria-selected={selected}
                      >
                        <div className={styles.itemMain}>{u.name || 'Teammate'}</div>
                        <div className={styles.itemMeta}>{u.email || u.role || 'Member'}</div>
                      </button>
                    );
                  })
                )}
              </div>
            </div>

            <div className={styles.modalSection} style={{ marginTop: 12 }}>
              <div className={styles.settingDescription}>
                Not finding who you need? Please contact your Admin via Teams or email to have them added to the Sekki System.
              </div>
            </div>
          </div>

          <div className={styles.modalFooter}>
            <button className={styles.actionBtn} onClick={() => setAddCollabOpen(false)}>Cancel</button>
            <button className={styles.actionBtn} disabled={!addSelectionId} onClick={onConfirm}>
              <i className="fas fa-check" /> Add
            </button>
          </div>
        </div>
      </div>
    );
  };

  // -------- System Settings Slide-over (ADMIN ONLY) --------
  const SystemSettingsSidebar = () => {
    const [newUserName, setNewUserName] = useState('');
    const [newUserEmail, setNewUserEmail] = useState('');
    const [newUserRole, setNewUserRole] = useState('Team Member');

    const isAdminRole = isAdmin && isAdmin();

    const addUser = () => {
      const gate =
        (newUserRole === 'Team Member' && seatAvail.TM > 0) ||
        (newUserRole === 'Project Lead' && seatAvail.PL > 0) ||
        (newUserRole === 'Admin' && seatAvail.ADMIN > 0);

      if (!gate) {
        alert(`No ${newUserRole} seats available. (Stub) Please buy more seats.`);
        return;
      }
      // TODO: wire to backend create user + role assignment
      alert(`(Stub) Added user: ${newUserEmail} as ${newUserRole}`);
      setNewUserName('');
      setNewUserEmail('');
      setNewUserRole('Team Member');
    };

    if (!isAdminRole) return null;

    return (
      <aside
        className={`${styles.settingsSidebar} ${showAdminSettings ? styles.open : ''}`}
        aria-hidden={!showAdminSettings}
      >
        <div className={styles.settingsHeaderBar}>
          <h3><i className="fas fa-cog" /> System Settings</h3>
          <div className={styles.headerBtns}>
            <button
              className={styles.iconBtn}
              title="Collapse"
              aria-label="Collapse"
              onClick={() => setShowAdminSettings(false)}
              style={{ background: 'none', border: 'none', cursor: 'pointer' }}
            >
              <i className="fas fa-chevron-right" />
            </button>
          </div>
        </div>

        <div className={styles.settingsBody}>
          {/* Users & Licenses */}
          <div className={styles.settingsCard}>
            <div className={styles.settingsCardHeader}>
              <h4><i className="fas fa-id-card" /> Users & Licenses</h4>
            </div>

            <div className={styles.settingsRow}>
              <div className={styles.kv}>
                <span className={styles.kvLabel}>Team Member</span>
                <span className={styles.kvValue}>{seatUsage.TM}/{SEATS.TM}</span>
              </div>
              <div className={styles.kv}>
                <span className={styles.kvLabel}>Project Lead</span>
                <span className={styles.kvValue}>{seatUsage.PL}/{SEATS.PL}</span>
              </div>
              <div className={styles.kv}>
                <span className={styles.kvLabel}>Admin</span>
                <span className={styles.kvValue}>{seatUsage.ADMIN}/{SEATS.ADMIN}</span>
              </div>
            </div>

            <div className={styles.divider} />

            <div className={styles.formRow}>
              <div className={styles.field}>
                <label>Name</label>
                <input
                  className={styles.input}
                  value={newUserName}
                  onChange={(e) => setNewUserName(e.target.value)}
                  placeholder="Full name"
                />
              </div>
              <div className={styles.field}>
                <label>Email</label>
                <input
                  className={styles.input}
                  value={newUserEmail}
                  onChange={(e) => setNewUserEmail(e.target.value)}
                  placeholder="name@company.com"
                  type="email"
                />
              </div>
              <div className={styles.field}>
                <label>Role</label>
                <select
                  className={styles.input}
                  value={newUserRole}
                  onChange={(e) => setNewUserRole(e.target.value)}
                >
                  <option>Team Member</option>
                  <option>Project Lead</option>
                  {ALLOW_CREATE_ADMINS && <option>Admin</option>}
                </select>
                <div className={styles.settingDescription} style={{ marginTop: 4 }}>
                  {newUserRole === 'Team Member' && `Available: ${seatAvail.TM}`}
                  {newUserRole === 'Project Lead' && `Available: ${seatAvail.PL}`}
                  {newUserRole === 'Admin' && `Available: ${seatAvail.ADMIN}`}
                </div>
              </div>
            </div>

            <div className={styles.cardActions}>
              <button
                className={styles.actionBtn}
                onClick={addUser}
                disabled={
                  !newUserEmail ||
                  !newUserName ||
                  (newUserRole === 'Team Member' && seatAvail.TM <= 0) ||
                  (newUserRole === 'Project Lead' && seatAvail.PL <= 0) ||
                  (newUserRole === 'Admin' && seatAvail.ADMIN <= 0)
                }
                title={
                  (newUserRole === 'Team Member' && seatAvail.TM <= 0) ? 'No Team Member seats available' :
                  (newUserRole === 'Project Lead' && seatAvail.PL <= 0) ? 'No Project Lead seats available' :
                  (newUserRole === 'Admin' && seatAvail.ADMIN <= 0) ? 'No Admin seats available' :
                  ''
                }
              >
                <i className="fas fa-user-plus" /> Add User
              </button>
              <button
                className={styles.actionBtn}
                onClick={() => alert('(Stub) Open billing portal')}
              >
                <i className="fas fa-credit-card" /> Buy more seats
              </button>
            </div>
          </div>

          {/* Feature Flags (placeholders) */}
          <div className={styles.settingsCard}>
            <div className={styles.settingsCardHeader}>
              <h4><i className="fas fa-flask" /> Feature Flags</h4>
            </div>
            <div className={styles.settingsList}>
              <div className={styles.settingItemRow}>
                <div>
                  <div className={styles.itemName}>Advanced Analytics</div>
                  <div className={styles.itemHint}>Enable deeper reporting modules</div>
                </div>
                <label className={styles.switch}>
                  <input type="checkbox" disabled />
                  <span className={styles.slider}></span>
                </label>
              </div>

              <div className={styles.settingItemRow}>
                <div>
                  <div className={styles.itemName}>Require Charter Approval</div>
                  <div className={styles.itemHint}>New projects must have an approved charter</div>
                </div>
                <label className={styles.switch}>
                  <input type="checkbox" defaultChecked disabled />
                  <span className={styles.slider}></span>
                </label>
              </div>

              <div className={styles.settingItemRow}>
                <div>
                  <div className={styles.itemName}>Tollgate Notifications</div>
                  <div className={styles.itemHint}>Email reminders for upcoming reviews</div>
                </div>
                <label className={styles.switch}>
                  <input type="checkbox" defaultChecked disabled />
                  <span className={styles.slider}></span>
                </label>
              </div>
            </div>
          </div>

          {/* Security (placeholder) */}
          <div className={styles.settingsCard}>
            <div className={styles.settingsCardHeader}>
              <h4><i className="fas fa-shield-alt" /> Security</h4>
            </div>
            <div className={styles.settingItemRow}>
              <div>
                <div className={styles.itemName}>SSO Required</div>
                <div className={styles.itemHint}>Only allow sign in via company SSO</div>
              </div>
              <label className={styles.switch}>
                <input type="checkbox" disabled />
                <span className={styles.slider}></span>
              </label>
            </div>
          </div>
        </div>
      </aside>
    );
  };

  // --------- LEFT SIDEBAR CONTENT (role-aware) ----------
  const role = getUserRole();
  const teamMemberLeftMenu = (
    <>
      {renderListAccordion('myProjects', {
        title: 'MY PROJECTS',
        icon: 'fas fa-folder-open',
        items: filteredProjects.map(p => ({
          title: p.name || 'Untitled Project',
          subtitle: p.currentPhase ? `Phase: ${p.currentPhase}` : undefined,
          icon: 'fas fa-folder',
          onClick: () => {}
        })),
        emptyText: 'No invited projects yet.'
      })}
      {renderListAccordion('myDocuments', {
        title: 'MY DOCUMENTS',
        icon: 'fas fa-file-alt',
        items: myDocuments.map(d => ({
          title: d.title || d.name || 'Untitled Document',
          subtitle: d.__projectName ? `Project: ${d.__projectName}` : undefined,
          icon: 'fas fa-file',
          onClick: () => {}
        })),
        emptyText: 'No shared documents yet.'
      })}
    </>
  );

  // Dynamic "Recent Artifacts" for Admin/PL (from docs in scope)
  const recentArtifacts = (allDocuments || [])
    .slice()
    .sort((a, b) => {
      const da = new Date(a?.updatedAt || a?.completedAt || a?.createdAt || 0).getTime();
      const db = new Date(b?.updatedAt || b?.completedAt || b?.createdAt || 0).getTime();
      return db - da;
    })
    .slice(0, 6);

  // Optional Tollgates if your project objects include p.tollgates[]
  const upcomingTollgates = (() => {
    const list = [];
    (filteredProjects || []).forEach((p) => {
      (Array.isArray(p?.tollgates) ? p.tollgates : []).forEach((tg) => {
        const due = tg?.dueDate ? new Date(tg.dueDate) : null;
        if (due && due.getTime() >= Date.now()) {
          list.push({
            project: p.name || 'Untitled',
            name: tg.name || 'Tollgate',
            dueInDays: Math.round((due.getTime() - Date.now()) / msPerDay),
            status: tg.status || 'Pending',
          });
        }
      });
    });
    return list.sort((a, b) => a.dueInDays - b.dueInDays).slice(0, 6);
  })();

  return (
    <div
      className={`${styles.lssDashboard} ${sidebarCollapsed ? styles.sidebarCollapsed : ''} ${mobileSidebarOpen ? styles.sidebarOpen : ''}`}
    >
      {/* LEFT RAIL TAB (always visible) */}
      <button
        className={styles.railTab}
        aria-label="Open LSS Tools"
        aria-expanded={lssDrawerOpen}
        onClick={openLssDrawer}
      >
        <i className="fas fa-tools" />
        <span className={styles.railTabLabel}>Tools</span>
      </button>

      {/* SCRIM (click to close on mobile/overlay) */}
      {lssDrawerOpen && (
        <div
          className={styles.scrim}
          aria-hidden="true"
          onClick={closeLssDrawer}
        />
      )}

      {/* DRAWER */}
      <aside
        id="lss-tools-drawer"
        className={`${styles.drawer} ${lssDrawerOpen ? styles.drawerOpen : ""}`}
        role="complementary"
        aria-label="LSS navigation"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Drawer header */}
        <div className={styles.drawerHeader}>
          <h2>{role === 'teamMember' ? 'Your Work' : 'LSS Tools'}</h2>
          <button
            className={styles.drawerCloseBtn}
            aria-label="Close menu"
            onClick={closeLssDrawer}
          >
            <i className="fas fa-times" />
          </button>
        </div>

        {/* ---- your original sidebar content starts here ---- */}
        <div className={styles.roleIndicator}>
          <i className={`fas ${(isAdmin && isAdmin()) ? 'fa-crown' : getUserRole() === 'projectLead' ? 'fa-user-tie' : 'fa-user'}`}></i>
          <span className={`${styles.roleBadge} ${styles[getUserRole()]}`}>
            {getUserRole() === 'admin' ? 'ADMIN' : getUserRole() === 'projectLead' ? 'PROJECT LEAD' : 'TEAM MEMBER'}
          </span>
        </div>

        <div className={styles.roleSwitcherContainer}>
          <RoleSwitcher />
        </div>

        <div className={styles.toolSections}>
          {role === 'teamMember'
            ? teamMemberLeftMenu
            : (
              <>
                {Object.entries(getToolSections()).map(([key, section]) => renderAccordionSection(key, section))}
                {(isAdmin && isAdmin()) && getAdminSettings() && renderAccordionSection('adminSettings', getAdminSettings())}
              </>
            )
          }
        </div>

        {(canAccessKanban && canAccessKanban()) && (
          <div className={styles.toolSection}>
            <button className={styles.kanbanBtn} onClick={() => setShowKanban(true)}>
              <i className="fas fa-columns"></i>
              <span>Kanban Board</span>
            </button>
          </div>
        )}

        {role !== 'teamMember' && (
          <div className={styles.accordionSection}>
            <button
              className={`${styles.accordionHeader} ${accordionState.recentProjects ? styles.expanded : ''}`}
              onClick={() => toggleAccordion('recentProjects')}
            >
              <div className={styles.accordionTitle}>
                <i className="fas fa-history"></i>
                <span>RECENT PROJECTS</span>
              </div>
              <i className={`fas fa-chevron-${accordionState.recentProjects ? 'up' : 'down'} ${styles.accordionChevron}`}></i>
            </button>

            {accordionState.recentProjects && (
              <div className={styles.accordionContent}>
                <div className={styles.recentProjects}>
                  {filteredProjects.length === 0 ? (
                    <div className={styles.emptyState}>No projects yet.</div>
                  ) : (
                    filteredProjects.slice(0, 5).map((p) => (
                      <div key={p.id} className={styles.projectItem}>
                        {p.name || 'Untitled Project'}
                      </div>
                    ))
                  )}
                </div>
              </div>
            )}
          </div>
        )}
        {/* ---- your original sidebar content ends here ---- */}
      </aside>

      {/* Main Content */}
      <div className={styles.mainContent}>
        <div className={styles.header}>
          <div className={styles.headerContent}>
            {/* LEFT: menu buttons + title */}
            <div className={styles.headerLeft}>

              {/* Mobile open button (changed to open the Tools drawer) */}
              <button
                className={styles.sidebarToggleMobile}
                aria-label="Open menu"
                aria-controls="lss-tools-drawer"
                aria-expanded={lssDrawerOpen}
                onClick={openLssDrawer}
              >
                <i className="fas fa-bars" style={{ color: '#fff' }} />
              </button>

              {/* Desktop collapse/expand */}
              <button
                className={styles.sidebarToggleDesktop}
                aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
                onClick={() => setSidebarCollapsed(v => !v)}
                title={sidebarCollapsed ? 'Expand' : 'Collapse'}
              >
                <i className={`fas ${sidebarCollapsed ? 'fa-chevron-right' : 'fa-chevron-left'}`} />
              </button>

              <BackButton onClick={() => navigate(-1)} />
              <h1>Lean Six Sigma Operations</h1>
              <div className={styles.subtitle}>
                <span>Drive continuous improvement with data-driven methodologies</span>
              </div>
            </div>
            <div className={styles.headerActions}>
              {(canAccessKanban && canAccessKanban()) && (
                <button className={styles.kanbanHeaderBtn} onClick={() => setShowKanban(true)}>
                  <i className="fas fa-columns"></i> Kanban Board
                </button>
              )}

              {(() => {
                const role = getUserRole();
                if (role === 'teamMember') return null;

                const lssOptions = [
                  { value: 'dmaic', label: 'DMAIC' },
                  { value: 'kaizen', label: 'Kaizen Blitz' },
                  { value: 'statistics', label: 'Statistical Analysis' }
                ];

                const handleLSSSelect = (val) => {
                  if (val === 'dmaic') navigate('/ops/dmaic');
                  if (val === 'kaizen') navigate('/ops/kaizen');
                  if (val === 'statistics') navigate('/ops/statistics');
                };

                return (
                  <LSSCustomDropdown
                    label="Start New:"
                    options={lssOptions}
                    onSelect={handleLSSSelect}
                    placeholder="Select…"
                  />
                );
              })()}
            </div>
          </div>
        </div>

        {(isAdmin && isAdmin()) && (
          <div className={styles.tabNavigation}>
            {tabs.map((tab) => (
              <button
                key={tab.id}
                className={`${styles.tabBtn} ${activeTab === tab.id ? styles.active : ''}`}
                onClick={() => setActiveTab(tab.id)}
              >
                <i className={tab.icon}></i>
                <span>{tab.label}</span>
              </button>
            ))}
          </div>
        )}

        <div className={styles.content}>
          <div className={styles.tabContent}>
            {/* Metrics */}
            <div className={styles.metricsGrid}>
              <div className={styles.metricCard}>
                <div className={styles.metricHeader}><h3>Active Projects</h3><i className="fas fa-chart-bar"></i></div>
                <div className={styles.metricValue}>{dashboardMetrics.activeProjects}</div>
                <div className={styles.metricSubtext}>{(isAdmin && isAdmin() && viewMode === 'all') ? 'System-wide' : 'Your projects'}</div>
              </div>

              <div className={styles.metricCard}>
                <div className={styles.metricHeader}><h3>Completed Projects</h3><i className="fas fa-check-circle"></i></div>
                <div className={styles.metricValue}>{dashboardMetrics.completedProjects}</div>
              </div>

              {/* NEW: Cancelled Projects */}
              <div className={styles.metricCard}>
                <div className={styles.metricHeader}><h3>Cancelled Projects</h3><i className="fas fa-ban"></i></div>
                <div className={styles.metricValue}>{dashboardMetrics.cancelledProjects}</div>
              </div>

              {getUserRole() !== 'teamMember' && (
                <div className={styles.metricCard}>
                  <div className={styles.metricHeader}><h3>Total Savings YTD</h3><i className="fas fa-dollar-sign"></i></div>
                  <div className={styles.metricValue}>{formatCurrency(dashboardMetrics.totalSavings)}</div>
                </div>
              )}

              <div className={styles.metricCard}>
                <div className={styles.metricHeader}>
                  <h3>{(isAdmin && isAdmin()) ? 'Team Utilization' : 'Avg. Cycle Time'}</h3>
                  <i className={`fas ${(isAdmin && isAdmin()) ? 'fa-users' : 'fa-clock'}`}></i>
                </div>
                <div className={styles.metricValue}>
                  {(isAdmin && isAdmin()) ? `${dashboardMetrics.utilization}%` : `${dashboardMetrics.avgCycleTime} days`}
                </div>
              </div>
            </div>

            {/* Charts Row */}
            <div className={styles.chartsRow}>
              {getUserRole() === 'teamMember' ? (
                <>
                  <div className={styles.chartCard}>
                    <div className={styles.chartHeader}>
                      <h3><i className="fas fa-check-double"></i> Items Completed</h3>
                    </div>
                    <div className={styles.phaseChart}>
                      {itemsCompletedRows.length === 0 ? (
                        <div className={styles.emptyState}>No completed items yet.</div>
                      ) : (
                        itemsCompletedRows.map(([type, count]) => (
                          <div key={type} className={styles.phaseRow}>
                            <span className={styles.phaseLabel}>{type}</span>
                            <div className={styles.phaseBar}>
                              <div className={styles.phaseBarFill} style={{ width: `${(count / maxCompleted) * 100}%` }} />
                            </div>
                            <span className={styles.phaseCount}>{count}</span>
                          </div>
                        ))
                      )}
                    </div>
                  </div>

                  <div className={styles.chartCard}>
                    <div className={styles.chartHeader}>
                      <h3><i className="fas fa-clock"></i> Recent Artifacts</h3>
                    </div>
                    <div className={styles.artifactsList}>
                      {myDocuments.length === 0 ? (
                        <div className={styles.emptyState}>No recent artifacts.</div>
                      ) : (
                        recentArtifacts.map((d, idx) => (
                          <div key={d.id || idx} className={styles.artifactItem}>
                            <div className={styles.artifactInfo}>
                              <h4>{d.title || d.name || 'Untitled Document'}</h4>
                              {d.__projectName && (
                                <span className={styles.artifactMeta}>Project • {d.__projectName}</span>
                              )}
                            </div>
                          </div>
                        ))
                      )}
                    </div>
                  </div>
                </>
              ) : (
                <>
                  <div className={styles.chartCard}>
                    <div className={styles.chartHeader}><h3><i className="fas fa-chart-bar"></i> Projects by DMAIC Phase</h3></div>
                    <div className={styles.phaseChart}>
                      {dmaicPhaseRows.rows.every(([, c]) => c === 0) ? (
                        <div className={styles.emptyState}>No projects found.</div>
                      ) : (
                        dmaicPhaseRows.rows.map(([phaseKey, count]) => (
                          <div key={phaseKey} className={styles.phaseRow}>
                            <span className={styles.phaseLabel}>{phaseKey.charAt(0) + phaseKey.slice(1).toLowerCase()}</span>
                            <div className={styles.phaseBar}>
                              <div className={styles.phaseBarFill} style={{ width: `${(count / dmaicPhaseRows.max) * 100}%` }} />
                            </div>
                            <span className={styles.phaseCount}>{count}</span>
                          </div>
                        ))
                      )}
                    </div>
                  </div>

                  <div className={styles.chartCard}>
                    <div className={styles.chartHeader}><h3><i className="fas fa-chart-line"></i> Monthly Savings Trend</h3></div>
                    <div className={styles.savingsChart}>
                      <div className={styles.chartContainer}>
                        {monthlySavings.months.map((m) => (
                          <div key={m.key} className={styles.barContainer}>
                            <div
                              className={styles.savingsBar}
                              style={{ height: `${(m.total / monthlySavings.max) * 100}%` }}
                              title={`${m.label}: ${formatCurrency(m.total)}`}
                            />
                            <div className={styles.barLabel}>{m.label}</div>
                          </div>
                        ))}
                      </div>
                      {monthlySavings.months.every((m) => m.total === 0) && (
                        <div className={styles.emptyState} style={{ marginTop: 12 }}>
                          No savings recorded in the last 6 months.
                        </div>
                      )}
                    </div>
                  </div>
                </>
              )}
            </div>

            {/* Recent Section (Admin/PL) */}
            {getUserRole() !== 'teamMember' && (
              <div className={styles.recentSection}>
                <div className={styles.sectionGrid}>
                  <div className={styles.recentCard}>
                    <div className={styles.sectionHeader}>
                      <h3><i className="fas fa-clock"></i> Recent Artifacts</h3>
                      <button className={styles.viewAllBtn}>View All</button>
                    </div>
                    <div className={styles.artifactsList}>
                      {recentArtifacts.length === 0 ? (
                        <div className={styles.emptyState}>No recent artifacts.</div>
                      ) : (
                        recentArtifacts.map((d, idx) => (
                          <div key={d.id || idx} className={styles.artifactItem}>
                            <div className={styles.artifactInfo}>
                              <h4>{d.title || d.name || 'Untitled Document'}</h4>
                              <span className={styles.artifactMeta}>
                                {(d.type || getDocType(d))} • {d.__projectName || '—'}
                              </span>
                            </div>
                            <span className={styles.artifactStatus}>
                              {d.status === 'completed' ? 'Completed' : (d.status || 'In Progress')}
                            </span>
                          </div>
                        ))
                      )}
                    </div>
                  </div>

                  <div className={styles.recentCard}>
                    <div className={styles.sectionHeader}>
                      <h3><i className="fas fa-flag-checkered"></i> Upcoming Tollgates</h3>
                      <button className={styles.viewAllBtn}>View All</button>
                    </div>
                    <div className={styles.tollgatesList}>
                      {upcomingTollgates.length === 0 ? (
                        <div className={styles.emptyState}>No upcoming tollgates.</div>
                      ) : (
                        upcomingTollgates.map((tg, idx) => (
                          <div key={idx} className={styles.tollgateItem}>
                            <div className={styles.tollgateInfo}>
                              <h4>{tg.name}</h4>
                              <span className={styles.tollgateMeta}>
                                {tg.project} • Due in {tg.dueInDays} day{tg.dueInDays === 1 ? '' : 's'}
                              </span>
                            </div>
                            <span className={styles.tollgateStatus}>{tg.status}</span>
                          </div>
                        ))
                      )}
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Right Sidebar (admin & projectLead only) */}
      {(() => {
        const RightSidebar = () => {
          const role = getUserRole();
          if (role === 'teamMember') return null;

          const selectedUser = users.find(u => u.id === selectedUserId);

          return (
            <aside className={styles.rightSidebar}>
              <div className={styles.rightSidebarHeader}>
                <h3>
                  <i className="fas fa-sliders-h"></i>
                  {role === 'admin' ? ' Admin Panel' : ' Project Lead Panel'}
                </h3>

                {/* Single gear for System Settings */}
                {role === 'admin' && (
                  <button
                    title="System Settings"
                    aria-label="System Settings"
                    onClick={() => setShowAdminSettings(true)}
                    style={{ background: 'none', border: 'none', cursor: 'pointer' }}
                  >
                    <i className="fas fa-cog" />
                  </button>
                )}
              </div>

              {role === 'admin' && (
                <div className={styles.adminRightContent}>
                  <div className={styles.viewToggle}>
                    <button
                      className={`${styles.toggleBtn} ${viewMode === 'all' ? styles.active : ''}`}
                      onClick={() => setViewMode('all')}
                    >
                      <i className="fas fa-globe"></i> All
                    </button>
                    <button
                      className={`${styles.toggleBtn} ${viewMode === 'mine' ? styles.active : ''}`}
                      onClick={() => setViewMode('mine')}
                    >
                      <i className="fas fa-user"></i> Mine
                    </button>
                  </div>

                  <div className={styles.userList}>
                    <div className={styles.listHeader}>
                      <span>Users</span>
                      <span className={styles.userCount}>
                        {users.length}/{TOTAL_PLAN}
                      </span>
                    </div>

                    {users.map(u => (
                      <div
                        key={u.id}
                        className={`${styles.userItem} ${selectedUserId === u.id ? styles.selected : ''}`}
                        onClick={() => setSelectedUserId(u.id)}
                      >
                        <div className={styles.userInfo}>
                          <div className={styles.userAvatar}><i className="fas fa-user"></i></div>
                          <div className={styles.userDetails}>
                            <div className={styles.userName}>{u.name || 'User'}</div>
                            <div className={styles.userRole}>{u.role || 'Member'}</div>
                          </div>
                        </div>
                        <div className={styles.userStats}>
                          <i className="fas fa-folder-open"></i>
                          <span className={styles.projectCount}>{u.projectCount ?? 0}</span>
                        </div>
                      </div>
                    ))}

                    {selectedUser && (
                      <div className={styles.itemCard} style={{ marginTop: '0.5rem' }}>
                        <div className={styles.itemInfo}>
                          <div className={styles.itemName}>{selectedUser.name}</div>
                          <div className={styles.itemStatus}>Role: {selectedUser.role || 'Member'}</div>
                        </div>
                        <div className={styles.itemActions}>
                          <button className={styles.actionBtn}><i className="fas fa-user-shield"></i> Manage</button>
                        </div>
                      </div>
                    )}

                    {/* Seats breakdown (no extra settings buttons here) */}
                    <div className={styles.itemCard} style={{ marginTop: '0.5rem' }}>
                      <div className={styles.itemInfo}>
                        <div className={styles.itemName}>Seats</div>
                        <div className={styles.itemStatus}>
                          TM {seatUsage.TM}/{SEATS.TM} • PL {seatUsage.PL}/{SEATS.PL} • Admin {seatUsage.ADMIN}/{SEATS.ADMIN}
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {role === 'projectLead' && (
                <div className={styles.projectLeadRightContent}>
                  {/* Add Collaborator: modal launcher */}
                  <div className={styles.itemsSection} style={{ marginBottom: '0.75rem' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                      <h3 style={{ margin: 0 }}><i className="fas fa-user-plus"></i> Add Collaborator</h3>
                      <button className={styles.actionBtn} onClick={() => setAddCollabOpen(true)}>
                        <i className="fas fa-plus" /> Add
                      </button>
                    </div>
                    <p className={styles.settingDescription} style={{ marginTop: 6 }}>
                      Search the Sekki user directory managed by Admin.
                    </p>
                  </div>

                  {/* Collaborators Accordion */}
                  <div className={styles.accordionSection}>
                    <button
                      className={`${styles.accordionHeader} ${collabAccordionOpen ? styles.expanded : ''}`}
                      onClick={() => setCollabAccordionOpen(v => !v)}
                    >
                      <div className={styles.accordionTitle}>
                        <i className="fas fa-users"></i>
                        <span>COLLABORATORS</span>
                      </div>
                      <i className={`fas fa-chevron-${collabAccordionOpen ? 'up' : 'down'} ${styles.accordionChevron}`}></i>
                    </button>

                    {collabAccordionOpen && (
                      <div className={styles.accordionContent}>
                        {collaboratorUsers.length === 0 ? (
                          <div className={styles.emptyState}>No collaborators yet.</div>
                        ) : (
                          <div className={styles.simpleList}>
                            {collaboratorUsers.map(u => (
                              <div key={u.id} className={styles.simpleListItem}>
                                <div className={styles.simpleListLeading}>
                                  <i className="fas fa-user-circle"></i>
                                </div>
                                <div className={styles.simpleListBody}>
                                  <div className={styles.simpleListTitle}>{u.name || 'Teammate'}</div>
                                  <div className={styles.simpleListSub}>{u.role || 'Member'}</div>
                                </div>
                                <button
                                  className={styles.actionBtn}
                                  onClick={() => {
                                    setCollabModalUserId(u.id);
                                    setCollabModalOpen(true);
                                  }}
                                  title="View shared work"
                                >
                                  <i className="fas fa-eye"></i>
                                </button>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </aside>
          );
        };
        return <RightSidebar />;
      })()}

      {/* System Settings slide-over (admin only) */}
      <SystemSettingsSidebar />

      {/* Modals */}
      <KanbanModal />
      <CollaboratorDetailModal />
      <AddCollaboratorModal />
    </div>
  );
};

export default LSSDashboard;
