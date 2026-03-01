// src/Ops/PMDashboard/PMDashboard.jsx
import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import PMCustomDropdown from './PMCustomDropdown';
import styles from './PMDashboard.module.css';

const PMDashboard = () => {
  const navigate = useNavigate();
  const location = useLocation();

  const [dashboardData, setDashboardData] = useState({
    activeProjects: 0,
    completedProjects: 0,
    overdueProjects: 0,
    totalTasks: 0,
    completedTasks: 0,
    overdueTasks: 0,
    teamUtilization: 0,
    budgetStatus: 0,
    upcomingDeadlines: [],
    recentActivity: [],
    projectHealth: []
  });

  const [selectedTool, setSelectedTool] = useState(null);
  const [expandedCategory, setExpandedCategory] = useState('core');

  // Tabs (plain JS)
  const tabs = [
    { id: 'overview', label: 'Overview', icon: 'fas fa-chart-line' },
    { id: 'project-health', label: 'Project Health', icon: 'fas fa-heartbeat' },
    { id: 'team-performance', label: 'Team Performance', icon: 'fas fa-users' },
    { id: 'financials', label: 'Financials', icon: 'fas fa-dollar-sign' }
  ];
  const [activeTab, setActiveTab] = useState('overview');

  // PM Tools drawer state (matching LSS Dashboard pattern)
  const [pmDrawerOpen, setPmDrawerOpen] = useState(false);

  const openPmDrawer = useCallback(() => setPmDrawerOpen(true), []);
  const closePmDrawer = useCallback(() => setPmDrawerOpen(false), []);

  useEffect(() => {
    fetchDashboardData();
  }, []);

  const fetchDashboardData = async () => {
    try {
      // TODO: Replace with actual API call
      setDashboardData({
        activeProjects: 8,
        completedProjects: 24,
        overdueProjects: 2,
        totalTasks: 156,
        completedTasks: 98,
        overdueTasks: 12,
        teamUtilization: 78,
        budgetStatus: 92,
        upcomingDeadlines: [
          { id: 1, project: 'Website Redesign', task: 'Design Review', date: '2025-11-05' },
          { id: 2, project: 'Mobile App Launch', task: 'Beta Testing', date: '2025-11-08' },
          { id: 3, project: 'CRM Integration', task: 'Phase 1 Completion', date: '2025-11-12' }
        ],
        recentActivity: [
          { id: 1, user: 'Sarah Chen', action: 'completed task', project: 'Website Redesign', time: '2 hours ago' },
          { id: 2, user: 'Marcus Rodriguez', action: 'updated status', project: 'Mobile App Launch', time: '4 hours ago' },
          { id: 3, user: 'Emily Watson', action: 'added comment', project: 'CRM Integration', time: '1 day ago' }
        ],
        projectHealth: [
          { name: 'Website Redesign', status: 'on-track', progress: 75 },
          { name: 'Mobile App Launch', status: 'at-risk', progress: 45 },
          { name: 'CRM Integration', status: 'on-track', progress: 60 }
        ]
      });
    } catch (error) {
      console.error('Error fetching dashboard data:', error);
    }
  };

  const pmTools = {
    core: [
      { id: 'project-planning', name: 'Project Planning', icon: 'fa-tasks', route: '/ops/project-planning' },
      { id: 'timeline', name: 'Timeline View', icon: 'fa-calendar-alt', route: '/ops/pm/timeline' },
      { id: 'kanban', name: 'Kanban Board', icon: 'fa-columns', route: '/ops/pm/kanban' },
      { id: 'gantt', name: 'Gantt Chart', icon: 'fa-chart-bar', route: '/ops/pm/gantt' }
    ],
    resources: [
      { id: 'team', name: 'Team Management', icon: 'fa-users', route: '/ops/pm/team' },
      { id: 'workload', name: 'Workload Balancing', icon: 'fa-balance-scale', route: '/ops/pm/workload' },
      { id: 'capacity', name: 'Capacity Planning', icon: 'fa-chart-pie', route: '/ops/pm/capacity' }
    ],
    tracking: [
      { id: 'milestones', name: 'Milestones', icon: 'fa-flag-checkered', route: '/ops/pm/milestones' },
      { id: 'budget', name: 'Budget Tracker', icon: 'fa-dollar-sign', route: '/ops/pm/budget' },
      { id: 'risks', name: 'Risk Register', icon: 'fa-exclamation-triangle', route: '/ops/pm/risks' },
      { id: 'issues', name: 'Issue Tracker', icon: 'fa-bug', route: '/ops/pm/issues' }
    ],
    reporting: [
      { id: 'reports', name: 'Project Reports', icon: 'fa-file-alt', route: '/ops/pm/reports' },
      { id: 'analytics', name: 'Analytics', icon: 'fa-chart-line', route: '/ops/pm/analytics' },
      { id: 'dashboard', name: 'Custom Dashboards', icon: 'fa-tachometer-alt', route: '/ops/pm/custom-dashboard' }
    ]
  };

  const toggleCategory = (category) => {
    setExpandedCategory(expandedCategory === category ? null : category);
  };

  const handleToolClick = (tool) => {
    setSelectedTool(tool.id);
    if (tool.route) navigate(tool.route);
  };

  const handleStartNew = (projectType) => {
    navigate('/ops/project-planning', { state: { projectType } });
  };

  const taskCompletionRate =
    dashboardData.totalTasks > 0
      ? Math.round((dashboardData.completedTasks / dashboardData.totalTasks) * 100)
      : 0;

  const onTimeRate =
    dashboardData.activeProjects > 0
      ? Math.round(((dashboardData.activeProjects - dashboardData.overdueProjects) / dashboardData.activeProjects) * 100)
      : 0;

  // Route-based active state (persists across navigation)
  const isRouteActive = (route) =>
    typeof route === 'string' && location.pathname.startsWith(route);

  return (
    <div className={styles.pmDashboardContainer}>
      {/* LEFT RAIL TAB (always visible on desktop) */}
      <button
        className={styles.railTab}
        aria-label="Open PM Tools"
        aria-expanded={pmDrawerOpen}
        onClick={openPmDrawer}
      >
        <i className="fas fa-tools" />
        <span className={styles.railTabLabel}>Tools</span>
      </button>

      {/* SCRIM (click to close on mobile/overlay) */}
      {pmDrawerOpen && (
        <div
          className={styles.scrim}
          aria-hidden="true"
          onClick={closePmDrawer}
        />
      )}

      {/* DRAWER */}
      <aside
        id="pm-tools-drawer"
        className={`${styles.drawer} ${pmDrawerOpen ? styles.drawerOpen : ""}`}
        role="complementary"
        aria-label="PM Tools navigation"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Drawer header */}
        <div className={styles.drawerHeader}>
          <div className={styles.userBadge}>
            <i className="fas fa-user-circle" />
            <span className={styles.userRole}>PROJECT MANAGER</span>
          </div>

          <button
            type="button"
            className={styles.drawerCloseBtn}
            onClick={closePmDrawer}
            aria-label="Close tools drawer"
            title="Close"
          >
            <i className="fas fa-times" />
          </button>
        </div>

        <div className={styles.toolsSection}>
          <h3 className={styles.sectionTitle}>PM Tools</h3>

          {/* Core Tools */}
          <div className={styles.toolCategory}>
            <button
              className={`${styles.categoryHeader} ${expandedCategory === 'core' ? styles.expanded : ''}`}
              onClick={() => toggleCategory('core')}
              aria-expanded={expandedCategory === 'core'}
            >
              <i className="fas fa-project-diagram" />
              <span>CORE TOOLS</span>
              <i className={`fas fa-chevron-down ${styles.chevron}`} />
            </button>
            {expandedCategory === 'core' && (
              <div className={styles.toolList}>
                {pmTools.core.map((tool) => (
                  <button
                    key={tool.id}
                    className={`${styles.toolItem} ${isRouteActive(tool.route) ? styles.isSelected : ''}`}
                    onClick={() => handleToolClick(tool)}
                  >
                    <i className={`fas ${tool.icon}`} />
                    <span>{tool.name}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Resources */}
          <div className={styles.toolCategory}>
            <button
              className={`${styles.categoryHeader} ${expandedCategory === 'resources' ? styles.expanded : ''}`}
              onClick={() => toggleCategory('resources')}
              aria-expanded={expandedCategory === 'resources'}
            >
              <i className="fas fa-users-cog" />
              <span>RESOURCES</span>
              <i className={`fas fa-chevron-down ${styles.chevron}`} />
            </button>
            {expandedCategory === 'resources' && (
              <div className={styles.toolList}>
                {pmTools.resources.map((tool) => (
                  <button
                    key={tool.id}
                    className={`${styles.toolItem} ${isRouteActive(tool.route) ? styles.isSelected : ''}`}
                    onClick={() => handleToolClick(tool)}
                  >
                    <i className={`fas ${tool.icon}`} />
                    <span>{tool.name}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Tracking */}
          <div className={styles.toolCategory}>
            <button
              className={`${styles.categoryHeader} ${expandedCategory === 'tracking' ? styles.expanded : ''}`}
              onClick={() => toggleCategory('tracking')}
              aria-expanded={expandedCategory === 'tracking'}
            >
              <i className="fas fa-clipboard-check" />
              <span>TRACKING</span>
              <i className={`fas fa-chevron-down ${styles.chevron}`} />
            </button>
            {expandedCategory === 'tracking' && (
              <div className={styles.toolList}>
                {pmTools.tracking.map((tool) => (
                  <button
                    key={tool.id}
                    className={`${styles.toolItem} ${isRouteActive(tool.route) ? styles.isSelected : ''}`}
                    onClick={() => handleToolClick(tool)}
                  >
                    <i className={`fas ${tool.icon}`} />
                    <span>{tool.name}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Reporting */}
          <div className={styles.toolCategory}>
            <button
              className={`${styles.categoryHeader} ${expandedCategory === 'reporting' ? styles.expanded : ''}`}
              onClick={() => toggleCategory('reporting')}
              aria-expanded={expandedCategory === 'reporting'}
            >
              <i className="fas fa-chart-area" />
              <span>REPORTING</span>
              <i className={`fas fa-chevron-down ${styles.chevron}`} />
            </button>
            {expandedCategory === 'reporting' && (
              <div className={styles.toolList}>
                {pmTools.reporting.map((tool) => (
                  <button
                    key={tool.id}
                    className={`${styles.toolItem} ${isRouteActive(tool.route) ? styles.isSelected : ''}`}
                    onClick={() => handleToolClick(tool)}
                  >
                    <i className={`fas ${tool.icon}`} />
                    <span>{tool.name}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className={styles.recentProjects}>
          <h4>RECENT PROJECTS</h4>
          <div className={styles.projectsList}>
            {dashboardData.projectHealth.slice(0, 3).map((project, index) => (
              <div key={index} className={styles.recentProjectItem}>
                <div className={styles.projectInfo}>
                  <span className={styles.projectName}>{project.name}</span>
                  <span className={`${styles.projectStatus} ${styles[project.status]}`}>
                    {project.status === 'on-track' ? 'On Track' : 'At Risk'}
                  </span>
                </div>
                <div className={styles.progressBar}>
                  <div className={styles.progressFill} style={{ width: `${project.progress}%` }} />
                </div>
              </div>
            ))}
          </div>
        </div>
      </aside>

      {/* Main Content */}
      <main className={styles.mainContent}>
        {/* Header */}
        <header className={styles.dashboardHeader}>
          {/* Mobile: open drawer */}
          <button
            type="button"
            className={styles.mobileMenuBtn}
            onClick={openPmDrawer}
            aria-label="Open tools drawer"
            title="Open tools"
          >
            <i className="fas fa-bars" />
          </button>

          <div className={styles.headerContent}>
            <button onClick={() => navigate(-1)} className={styles.backButton}>
              <i className="fas fa-arrow-left"></i> Back
            </button>
            <h1>Project Management Operations</h1>
            <p>Manage projects, track progress, and optimize team performance</p>
          </div>

          <div className={styles.startNew}>
            <PMCustomDropdown
              label="Start New:"
              options={[
                { value: 'standard', label: 'Standard Project' },
                { value: 'agile', label: 'Agile Sprint' },
                { value: 'campaign', label: 'Marketing Campaign' },
                { value: 'product', label: 'Product Launch' }
              ]}
              onSelect={handleStartNew}
              placeholder="Select…"
            />
            <button className={styles.addBtn}>Add</button>
          </div>
        </header>

        {/* Tabs */}
        <div className={styles.tabNavigation}>
          {tabs.map((tab) => (
            <button
              key={tab.id}
              className={`${styles.tabBtn} ${activeTab === tab.id ? styles.isActive : ''}`}
              onClick={() => setActiveTab(tab.id)}
              aria-pressed={activeTab === tab.id}
            >
              <i className={tab.icon} style={{ marginRight: 8 }} />
              {tab.label}
            </button>
          ))}
        </div>

        {/* OVERVIEW */}
        {activeTab === 'overview' && (
          <>
            {/* Metrics Grid */}
            <div className={styles.metricsGrid}>
              <div className={styles.metricCard}>
                <div className={styles.metricIcon}>
                  <i className="fas fa-project-diagram" />
                </div>
                <div className={styles.metricContent}>
                  <h3>Active Projects</h3>
                  <div className={styles.metricValue}>{dashboardData.activeProjects}</div>
                  <p className={styles.metricSubtext}>Your projects</p>
                </div>
              </div>

              <div className={styles.metricCard}>
                <div className={styles.metricIcon}>
                  <i className="fas fa-check-circle" />
                </div>
                <div className={styles.metricContent}>
                  <h3>Completed Projects</h3>
                  <div className={styles.metricValue}>{dashboardData.completedProjects}</div>
                  <p className={styles.metricSubtext}>All time</p>
                </div>
              </div>

              <div className={styles.metricCard}>
                <div className={styles.metricIcon}>
                  <i className="fas fa-exclamation-circle" />
                </div>
                <div className={styles.metricContent}>
                  <h3>Overdue Projects</h3>
                  <div className={styles.metricValue}>{dashboardData.overdueProjects}</div>
                  <p className={styles.metricSubtext}>Need attention</p>
                </div>
              </div>

              <div className={styles.metricCard}>
                <div className={styles.metricIcon}>
                  <i className="fas fa-tasks" />
                </div>
                <div className={styles.metricContent}>
                  <h3>Task Completion</h3>
                  <div className={styles.metricValue}>{taskCompletionRate}%</div>
                  <p className={styles.metricSubtext}>
                    {dashboardData.completedTasks} of {dashboardData.totalTasks} tasks
                  </p>
                </div>
              </div>

              <div className={styles.metricCard}>
                <div className={styles.metricIcon}>
                  <i className="fas fa-users" />
                </div>
                <div className={styles.metricContent}>
                  <h3>Team Utilization</h3>
                  <div className={styles.metricValue}>{dashboardData.teamUtilization}%</div>
                  <p className={styles.metricSubtext}>Average capacity</p>
                </div>
              </div>

              <div className={styles.metricCard}>
                <div className={styles.metricIcon}>
                  <i className="fas fa-dollar-sign" />
                </div>
                <div className={styles.metricContent}>
                  <h3>Budget Status</h3>
                  <div className={styles.metricValue}>{dashboardData.budgetStatus}%</div>
                  <p className={styles.metricSubtext}>On budget</p>
                </div>
              </div>
            </div>

            {/* Charts Section */}
            <div className={styles.chartsSection}>
              <div className={styles.chartCard}>
                <h3>
                  <i className="fas fa-heartbeat" />
                  Project Health Overview
                </h3>
                <div className={styles.projectHealthList}>
                  {dashboardData.projectHealth.map((project, index) => (
                    <div key={index} className={styles.healthItem}>
                      <div className={styles.healthHeader}>
                        <span className={styles.healthProjectName}>{project.name}</span>
                        <span className={`${styles.healthStatus} ${styles[project.status]}`}>
                          {project.status === 'on-track' ? '✓ On Track' : '⚠ At Risk'}
                        </span>
                      </div>
                      <div className={styles.healthProgress}>
                        <div className={styles.healthProgressBar}>
                          <div
                            className={`${styles.healthProgressFill} ${styles[project.status]}`}
                            style={{ width: `${project.progress}%` }}
                          />
                        </div>
                        <span className={styles.healthPercentage}>{project.progress}%</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className={styles.chartCard}>
                <h3>
                  <i className="fas fa-calendar-check" />
                  Upcoming Deadlines
                </h3>
                <div className={styles.deadlinesList}>
                  {dashboardData.upcomingDeadlines.length > 0 ? (
                    dashboardData.upcomingDeadlines.map((deadline) => (
                      <div key={deadline.id} className={styles.deadlineItem}>
                        <div className={styles.deadlineDate}>
                          <i className="fas fa-calendar" />
                          <span>
                            {new Date(deadline.date).toLocaleDateString('en-US', {
                              month: 'short',
                              day: 'numeric'
                            })}
                          </span>
                        </div>
                        <div className={styles.deadlineInfo}>
                          <div className={styles.deadlineTask}>{deadline.task}</div>
                          <div className={styles.deadlineProject}>{deadline.project}</div>
                        </div>
                      </div>
                    ))
                  ) : (
                    <p className={styles.emptyState}>No upcoming deadlines.</p>
                  )}
                </div>
              </div>
            </div>

            {/* Recent Activity */}
            <div className={styles.activitySection}>
              <div className={styles.activityCard}>
                <h3>
                  <i className="fas fa-history" />
                  Recent Activity
                </h3>
                <div className={styles.activityList}>
                  {dashboardData.recentActivity.length > 0 ? (
                    dashboardData.recentActivity.map((activity) => (
                      <div key={activity.id} className={styles.activityItem}>
                        <div className={styles.activityAvatar}>
                          {activity.user.split(' ').map((n) => n[0]).join('')}
                        </div>
                        <div className={styles.activityContent}>
                          <div className={styles.activityText}>
                            <strong>{activity.user}</strong> {activity.action} in <em>{activity.project}</em>
                          </div>
                          <div className={styles.activityTime}>{activity.time}</div>
                        </div>
                      </div>
                    ))
                  ) : (
                    <p className={styles.emptyState}>No recent activity.</p>
                  )}
                </div>
              </div>
            </div>
          </>
        )}

        {/* PROJECT HEALTH */}
        {activeTab === 'project-health' && (
          <div className={styles.placeholderContent}>
            <div className={styles.placeholderIcon}>
              <i className="fas fa-heartbeat" />
            </div>
            <h2>Project Health Dashboard</h2>
            <p>Detailed project health metrics and analysis will be displayed here.</p>
          </div>
        )}

        {/* TEAM PERFORMANCE */}
        {activeTab === 'team-performance' && (
          <div className={styles.placeholderContent}>
            <div className={styles.placeholderIcon}>
              <i className="fas fa-users" />
            </div>
            <h2>Team Performance Analytics</h2>
            <p>Team productivity metrics, workload distribution, and performance insights will be shown here.</p>
          </div>
        )}

        {/* FINANCIALS */}
        {activeTab === 'financials' && (
          <div className={styles.placeholderContent}>
            <div className={styles.placeholderIcon}>
              <i className="fas fa-dollar-sign" />
            </div>
            <h2>Financial Overview</h2>
            <p>Budget tracking, cost analysis, and financial forecasting will be available here.</p>
          </div>
        )}
      </main>
    </div>
  );
};

export default PMDashboard;
