import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../shared/auth/AuthContext';
import { API_BASE } from '../../config/apiBase';
import './Dashboard.css';

export default function Dashboard() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [sessionRange, setSessionRange] = useState('month');
  const [darkMode, setDarkMode] = useState(false);
  const [timezone, setTimezone] = useState('America/New_York');
  const [showSettings, setShowSettings] = useState(false);
  const [showBillingModal, setShowBillingModal] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  const [showKanban, setShowKanban] = useState(false);
  const [currentSlide, setCurrentSlide] = useState(0);
  const [newTaskText, setNewTaskText] = useState('');
  const [showAddTask, setShowAddTask] = useState({ toDo: false, doing: false, done: false });
  const [billingStatus, setBillingStatus] = useState(null);
  const [billingCatalog, setBillingCatalog] = useState({ plans: {}, overage_packs: {} });
  const [billingLoading, setBillingLoading] = useState(true);
  const [billingError, setBillingError] = useState('');
  const [billingActionLoading, setBillingActionLoading] = useState('');
  
  const [kanbanData, setKanbanData] = useState({
    toDo: [
      { id: 1, text: 'Plan new features' },
      { id: 2, text: 'Review user feedback' },
      { id: 3, text: 'Update documentation' }
    ],
    doing: [
      { id: 4, text: 'Implement dashboard' },
      { id: 5, text: 'Fix login issues' }
    ],
    done: [
      { id: 6, text: 'Setup authentication' },
      { id: 7, text: 'Create wireframes' },
      { id: 8, text: 'Design database schema' }
    ]
  });

  // Mock data - replace with real data from your backend
  const [dashboardData, setDashboardData] = useState({
    activeProjects: 3,
    documentsCreated: 8,
    completionRate: 75,
    creditsUsed: 5,
    creditsTotal: 10,
    documentTypes: {
      'market_analysis': 3,
      'gap_analysis': 2,
      'swot_analysis': 3
    },
    recentSessions: [
      { id: 1, name: 'Market Analysis - Product Launch', date: '2025-01-05' },
      { id: 2, name: 'SWOT Analysis - Q1 Strategy', date: '2025-01-04' },
      { id: 3, name: 'Gap Analysis - User Experience', date: '2025-01-03' }
    ]
  });

  const hasMeteredCredits =
    Number.isFinite(billingStatus?.monthly_credit_limit) &&
    Number.isFinite(billingStatus?.credits_remaining);
  const creditsTotal = hasMeteredCredits
    ? Number(billingStatus?.monthly_credit_limit)
    : dashboardData.creditsTotal;
  const creditsRemaining = hasMeteredCredits
    ? Number(billingStatus?.credits_remaining)
    : (dashboardData.creditsTotal - dashboardData.creditsUsed);
  const creditsUsed = hasMeteredCredits
    ? Math.max(0, creditsTotal - creditsRemaining)
    : dashboardData.creditsUsed;
  const creditsPercentage = creditsTotal > 0 ? (creditsRemaining / creditsTotal) * 100 : 0;
  const currentPlanKey = billingStatus?.plan_key || 'free';
  const currentPlan = billingCatalog?.plans?.[currentPlanKey];

  const helpImages = [
    '/help_images/1.gif',
    '/help_images/2.gif', 
    '/help_images/3.gif',
    '/help_images/4.gif',
    '/help_images/5.gif',
    '/help_images/6-1.gif',
    '/help_images/7.gif'
  ];
  const planOrder = ['free', 'essential', 'team', 'enterprise'];
  const packOrder = ['pack_1000', 'pack_5000', 'pack_20000'];

  useEffect(() => {
    const savedDarkMode = localStorage.getItem('darkModeEnabled') === 'true';
    setDarkMode(savedDarkMode);
    if (savedDarkMode) {
      document.body.classList.add('dark-mode');
    }

    const savedTimezone = localStorage.getItem('userTimezone') || Intl.DateTimeFormat().resolvedOptions().timeZone;
    setTimezone(savedTimezone);
  }, []);

  useEffect(() => {
    const token = localStorage.getItem('access_token') || localStorage.getItem('token');
    if (!token) {
      setBillingLoading(false);
      return;
    }

    const loadBilling = async () => {
      setBillingLoading(true);
      setBillingError('');
      try {
        const [statusRes, catalogRes] = await Promise.all([
          fetch(`${API_BASE}/api/billing/status`, {
            headers: { Authorization: `Bearer ${token}` },
          }),
          fetch(`${API_BASE}/api/billing/catalog`),
        ]);
        const statusData = await statusRes.json();
        const catalogData = await catalogRes.json();

        if (!statusRes.ok) {
          throw new Error(statusData?.msg || 'Unable to load billing status.');
        }

        setBillingStatus(statusData);
        setBillingCatalog(catalogData || { plans: {}, overage_packs: {} });
      } catch (error) {
        setBillingError(error.message || 'Unable to load billing data.');
      } finally {
        setBillingLoading(false);
      }
    };

    loadBilling();
  }, []);

  const refreshBilling = async () => {
    const token = localStorage.getItem('access_token') || localStorage.getItem('token');
    if (!token) return;
    const res = await fetch(`${API_BASE}/api/billing/status`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const data = await res.json();
    if (res.ok) {
      setBillingStatus(data);
    }
  };

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const handleAnalysisClick = (type) => {
    navigate(`/iq?source=${type}`);
  };

  const toggleDarkMode = () => {
    const newDarkMode = !darkMode;
    setDarkMode(newDarkMode);
    localStorage.setItem('darkModeEnabled', newDarkMode.toString());
    document.body.classList.toggle('dark-mode', newDarkMode);
  };

  const handleTimezoneChange = (e) => {
    const newTimezone = e.target.value;
    setTimezone(newTimezone);
    localStorage.setItem('userTimezone', newTimezone);
  };

  const startPlanChange = async (planKey) => {
    const token = localStorage.getItem('access_token') || localStorage.getItem('token');
    if (!token) {
      navigate('/?auth=1');
      return;
    }

    setBillingActionLoading(planKey);
    setBillingError('');
    try {
      const response = await fetch(`${API_BASE}/api/billing/create-checkout-session`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ plan_key: planKey }),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data?.msg || 'Unable to start plan change.');
      }

      if (data?.url) {
        window.location.href = data.url;
        return;
      }

      await refreshBilling();
    } catch (error) {
      setBillingError(error.message || 'Unable to start plan change.');
    } finally {
      setBillingActionLoading('');
    }
  };

  const buyCreditPack = async (packKey) => {
    const token = localStorage.getItem('access_token') || localStorage.getItem('token');
    if (!token) {
      navigate('/?auth=1');
      return;
    }

    setBillingActionLoading(packKey);
    setBillingError('');
    try {
      const response = await fetch(`${API_BASE}/api/billing/create-overage-checkout-session`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ pack_key: packKey }),
      });
      const data = await response.json();
      if (!response.ok || !data?.url) {
        throw new Error(data?.msg || 'Unable to start overage checkout.');
      }
      window.location.href = data.url;
    } catch (error) {
      setBillingError(error.message || 'Unable to start overage checkout.');
      setBillingActionLoading('');
    }
  };

  const openBillingPortal = async () => {
    const token = localStorage.getItem('access_token') || localStorage.getItem('token');
    if (!token) {
      navigate('/?auth=1');
      return;
    }

    setBillingActionLoading('portal');
    setBillingError('');
    try {
      const response = await fetch(`${API_BASE}/api/billing/create-portal-session`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ return_url: `${window.location.origin}/dashboard` }),
      });
      const data = await response.json();
      if (!response.ok || !data?.url) {
        throw new Error(data?.msg || 'Unable to open billing portal.');
      }
      window.location.href = data.url;
    } catch (error) {
      setBillingError(error.message || 'Unable to open billing portal.');
      setBillingActionLoading('');
    }
  };

  const saveKanban = () => {
    // Here you would save to your backend
    console.log('Saving kanban data:', kanbanData);
    setShowKanban(false);
  };

  const updateKanbanColumn = (column, value) => {
    const tasks = value.split('\n').filter(task => task.trim()).map((task, index) => ({
      id: Date.now() + index,
      text: task.trim()
    }));
    setKanbanData(prev => ({
      ...prev,
      [column]: tasks
    }));
  };

  const addTask = (column) => {
    if (newTaskText.trim()) {
      const newTask = {
        id: Date.now(),
        text: newTaskText.trim()
      };
      setKanbanData(prev => ({
        ...prev,
        [column]: [...prev[column], newTask]
      }));
      setNewTaskText('');
      setShowAddTask(prev => ({ ...prev, [column]: false }));
    }
  };

  const deleteTask = (column, taskId) => {
    setKanbanData(prev => ({
      ...prev,
      [column]: prev[column].filter(task => task.id !== taskId)
    }));
  };

  const moveTask = (taskId, fromColumn, toColumn) => {
    const task = kanbanData[fromColumn].find(t => t.id === taskId);
    if (task) {
      setKanbanData(prev => ({
        ...prev,
        [fromColumn]: prev[fromColumn].filter(t => t.id !== taskId),
        [toColumn]: [...prev[toColumn], task]
      }));
    }
  };

  const nextSlide = () => {
    setCurrentSlide(prev => (prev + 1) % helpImages.length);
  };

  const prevSlide = () => {
    setCurrentSlide(prev => (prev - 1 + helpImages.length) % helpImages.length);
  };

  return (
    <div className="workspace-container">
      {/* Workspace Header */}
      <header className="workspace-header">
        <h1>Welcome, {user?.name || 'User'}</h1>
        <a href="#" onClick={handleLogout} className="logout-link">Logout</a>
      </header>

      <div className="workspace-layout">
        {/* Left Sidebar */}
        <aside className="left-panel">
          {/* Sessions Button */}
          <div className="workflows-section">
            <a href="/session-management" className="workflows-button">
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 512" className="sessions-icon">
                <path d="M64 360a56 56 0 1 0 0 112 56 56 0 1 0 0-112zm0-160a56 56 0 1 0 0 112 56 56 0 1 0 0-112zM120 96A56 56 0 1 0 8 96a56 56 0 1 0 112 0z"/>
              </svg>
              <span className="sessions-label">Sessions</span>
            </a>
            <hr className="divider" />
          </div>

          {/* Analysis Buttons */}
          <div className="action-buttons">
            <button 
              className="action-button"
              onClick={() => handleAnalysisClick('market_analysis')}
            >
              Market Analysis
            </button>
            <button 
              className="action-button"
              onClick={() => handleAnalysisClick('gap_analysis')}
            >
              Gap Analysis
            </button>
            <button 
              className="action-button"
              onClick={() => handleAnalysisClick('swot_analysis')}
            >
              SWOT Analysis
            </button>
          </div>

          {/* Credits Remaining */}
          <div className="storage-info">
            <h4>Credits Remaining</h4>
            <div className="storage-progress">
              <div className="progress-container">
                <div className="progress-bar-container">
                  <div 
                    className="progress-bar"
                    style={{ width: `${Math.max(0, Math.min(100, creditsPercentage))}%` }}
                  ></div>
                </div>
              </div>
            </div>
            <div className="storage-text">
              {billingLoading ? (
                'Loading credits...'
              ) : hasMeteredCredits ? (
                `${creditsRemaining.toLocaleString()} of ${creditsTotal.toLocaleString()} credits remaining`
              ) : billingStatus?.monthly_credit_limit == null ? (
                'Contracted usage plan (sales-managed)'
              ) : (
                `${creditsRemaining} of ${dashboardData.creditsTotal} credits remaining`
              )}
            </div>
            {hasMeteredCredits && (
              <div className="storage-text">
                {creditsUsed.toLocaleString()} used this cycle
              </div>
            )}
          </div>

          {/* Recent Sessions */}
          <div className="recent-sessions-box">
            <h4>Recent Sessions</h4>
            {dashboardData.recentSessions.length === 0 ? (
              <p>No sessions yet.</p>
            ) : (
              <ul>
                {dashboardData.recentSessions.map(session => (
                  <li key={session.id}>
                    <a href={`/session-management?session_id=${session.id}`}>
                      • {session.name}
                    </a>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* Settings and Help */}
          <div className="sidebar-controls">
            <button 
              id="openSettingsBtn" 
              className="action-button settings-btn"
              onClick={() => setShowSettings(true)}
            >
              Settings
            </button>
            <button 
              id="openHelpBtn" 
              className="help-icon" 
              title="Help"
              onClick={() => setShowHelp(true)}
            >
              ?
            </button>
          </div>
        </aside>

        {/* Main Panel */}
        <main className="main-panel">
          {/* Session Range Selector */}
          <div className="session-range-selector">
            <label htmlFor="sessionRange">View by:</label>
            <select 
              id="sessionRange" 
              value={sessionRange}
              onChange={(e) => setSessionRange(e.target.value)}
            >
              <option value="week">Last 7 days</option>
              <option value="month">This month</option>
              <option value="year">This year</option>
              <option value="all">All time</option>
            </select>
          </div>

          {/* Dashboard Cards */}
          <section className="dashboard-cards">
            <div className="dashboard-card">
              <h3>Active Projects</h3>
              <div className="card-value">{dashboardData.activeProjects}</div>
              <div className="card-subtitle">Projects in progress</div>
            </div>
            <div className="dashboard-card">
              <h3>Documents Created</h3>
              <div className="card-value">{dashboardData.documentsCreated}</div>
              <div className="card-subtitle">Completed documents</div>
            </div>
            <div className="dashboard-card completion-rate-card">
              <h3>Completion Rate</h3>
              <div className="card-subtitle">Overall progress</div>
              <div className="circular-progress">
                <div className="percentage">{dashboardData.completionRate}%</div>
              </div>
            </div>
          </section>

          {/* Bottom Section */}
          <section className="bottom-section">
            {/* Kanban Board */}
            <div className="kanban-container">
              <h2>
                Kanban
                <a 
                  href="#" 
                  className="modify-link"
                  onClick={(e) => {
                    e.preventDefault();
                    setShowKanban(true);
                  }}
                >
                  Modify
                </a>
              </h2>
              <div className="kanban-board">
                {/* To Do Column */}
                <div className="kanban-column">
                  <h3>To Do</h3>
                  <div className="kanban-items">
                    {kanbanData.toDo.map(task => (
                      <div key={task.id} className="kanban-item">
                        <span>{task.text}</span>
                        <div className="item-actions">
                          <button 
                            onClick={() => moveTask(task.id, 'toDo', 'doing')}
                            title="Move to Doing"
                          >
                            →
                          </button>
                          <button 
                            onClick={() => deleteTask('toDo', task.id)}
                            title="Delete"
                          >
                            ×
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                  {showAddTask.toDo ? (
                    <div className="add-task-form">
                      <input
                        type="text"
                        value={newTaskText}
                        onChange={(e) => setNewTaskText(e.target.value)}
                        placeholder="Enter task..."
                        onKeyPress={(e) => e.key === 'Enter' && addTask('toDo')}
                        autoFocus
                      />
                      <div className="add-task-buttons">
                        <button onClick={() => addTask('toDo')}>Add</button>
                        <button onClick={() => setShowAddTask(prev => ({ ...prev, toDo: false }))}>Cancel</button>
                      </div>
                    </div>
                  ) : (
                    <button 
                      className="add-item-button"
                      onClick={() => setShowAddTask(prev => ({ ...prev, toDo: true }))}
                    >
                      + Add Task
                    </button>
                  )}
                </div>

                {/* Doing Column */}
                <div className="kanban-column">
                  <h3>Doing</h3>
                  <div className="kanban-items">
                    {kanbanData.doing.map(task => (
                      <div key={task.id} className="kanban-item">
                        <span>{task.text}</span>
                        <div className="item-actions">
                          <button 
                            onClick={() => moveTask(task.id, 'doing', 'toDo')}
                            title="Move to To Do"
                          >
                            ←
                          </button>
                          <button 
                            onClick={() => moveTask(task.id, 'doing', 'done')}
                            title="Move to Done"
                          >
                            →
                          </button>
                          <button 
                            onClick={() => deleteTask('doing', task.id)}
                            title="Delete"
                          >
                            ×
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                  {showAddTask.doing ? (
                    <div className="add-task-form">
                      <input
                        type="text"
                        value={newTaskText}
                        onChange={(e) => setNewTaskText(e.target.value)}
                        placeholder="Enter task..."
                        onKeyPress={(e) => e.key === 'Enter' && addTask('doing')}
                        autoFocus
                      />
                      <div className="add-task-buttons">
                        <button onClick={() => addTask('doing')}>Add</button>
                        <button onClick={() => setShowAddTask(prev => ({ ...prev, doing: false }))}>Cancel</button>
                      </div>
                    </div>
                  ) : (
                    <button 
                      className="add-item-button"
                      onClick={() => setShowAddTask(prev => ({ ...prev, doing: true }))}
                    >
                      + Add Task
                    </button>
                  )}
                </div>

                {/* Done Column */}
                <div className="kanban-column">
                  <h3>Done</h3>
                  <div className="kanban-items">
                    {kanbanData.done.map(task => (
                      <div key={task.id} className="kanban-item">
                        <span>{task.text}</span>
                        <div className="item-actions">
                          <button 
                            onClick={() => moveTask(task.id, 'done', 'doing')}
                            title="Move to Doing"
                          >
                            ←
                          </button>
                          <button 
                            onClick={() => deleteTask('done', task.id)}
                            title="Delete"
                          >
                            ×
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                  {showAddTask.done ? (
                    <div className="add-task-form">
                      <input
                        type="text"
                        value={newTaskText}
                        onChange={(e) => setNewTaskText(e.target.value)}
                        placeholder="Enter task..."
                        onKeyPress={(e) => e.key === 'Enter' && addTask('done')}
                        autoFocus
                      />
                      <div className="add-task-buttons">
                        <button onClick={() => addTask('done')}>Add</button>
                        <button onClick={() => setShowAddTask(prev => ({ ...prev, done: false }))}>Cancel</button>
                      </div>
                    </div>
                  ) : (
                    <button 
                      className="add-item-button"
                      onClick={() => setShowAddTask(prev => ({ ...prev, done: true }))}
                    >
                      + Add Task
                    </button>
                  )}
                </div>
              </div>
            </div>

            {/* Document Types Section */}
            <div className="document-types-section">
              <h3>Document Types</h3>
              <div className="document-types-list">
                {Object.entries(dashboardData.documentTypes).map(([type, count]) => (
                  <div key={type} className="document-type-item">
                    <span className="type-name">{type.replace('_', ' ')}</span>
                    <span className="type-count">{count}</span>
                  </div>
                ))}
              </div>
            </div>
          </section>
        </main>
      </div>

      {/* Settings Modal */}
      {showSettings && (
        <div id="settingsModal" className="modal show">
          <div className="modal-content">
            <button 
              className="close-settings" 
              onClick={() => setShowSettings(false)}
            >
              &times;
            </button>
            <h2>Settings</h2>
            <div className="settings-body">
              <label>
                <input 
                  type="checkbox" 
                  checked={darkMode}
                  onChange={toggleDarkMode}
                />
                Enable Dark Mode
              </label>

              <div className="settings-section">
                <h3>Preferences</h3>
                <div className="form-group">
                  <label htmlFor="timezone-select">Time Zone</label>
                  <select 
                    id="timezone-select"
                    value={timezone}
                    onChange={handleTimezoneChange}
                    className="timezone-select"
                  >
                    <optgroup label="US & Canada">
                      <option value="America/New_York">Eastern Time (ET)</option>
                      <option value="America/Chicago">Central Time (CT)</option>
                      <option value="America/Denver">Mountain Time (MT)</option>
                      <option value="America/Los_Angeles">Pacific Time (PT)</option>
                      <option value="America/Anchorage">Alaska Time (AKT)</option>
                      <option value="Pacific/Honolulu">Hawaii Time (HST)</option>
                    </optgroup>
                    <optgroup label="Europe">
                      <option value="Europe/London">London (GMT/BST)</option>
                      <option value="Europe/Paris">Paris (CET/CEST)</option>
                      <option value="Europe/Berlin">Berlin (CET/CEST)</option>
                      <option value="Europe/Rome">Rome (CET/CEST)</option>
                      <option value="Europe/Madrid">Madrid (CET/CEST)</option>
                      <option value="Europe/Amsterdam">Amsterdam (CET/CEST)</option>
                      <option value="Europe/Stockholm">Stockholm (CET/CEST)</option>
                      <option value="Europe/Moscow">Moscow (MSK)</option>
                    </optgroup>
                    <optgroup label="Asia Pacific">
                      <option value="Asia/Tokyo">Tokyo (JST)</option>
                      <option value="Asia/Shanghai">Shanghai (CST)</option>
                      <option value="Asia/Hong_Kong">Hong Kong (HKT)</option>
                      <option value="Asia/Singapore">Singapore (SGT)</option>
                      <option value="Asia/Seoul">Seoul (KST)</option>
                      <option value="Asia/Kolkata">Mumbai (IST)</option>
                      <option value="Australia/Sydney">Sydney (AEDT/AEST)</option>
                      <option value="Australia/Melbourne">Melbourne (AEDT/AEST)</option>
                    </optgroup>
                    <optgroup label="Other">
                      <option value="UTC">UTC (Coordinated Universal Time)</option>
                      <option value="America/Sao_Paulo">São Paulo (BRT)</option>
                      <option value="Africa/Cairo">Cairo (EET)</option>
                      <option value="Africa/Johannesburg">Johannesburg (SAST)</option>
                    </optgroup>
                  </select>
                </div>
              </div>
              
              <div className="settings-section">
                <h3>Account</h3>
                <button 
                  className="account-button"
                  onClick={() => {
                    setShowSettings(false);
                    setShowBillingModal(true);
                  }}
                >
                  <i className="fas fa-credit-card"></i>
                  Plan & Billing
                </button>
                <button
                  className="account-button account-button-secondary"
                  onClick={() => {
                    setShowSettings(false);
                    navigate('/account');
                  }}
                >
                  <i className="fas fa-user"></i>
                  Open Account Page
                </button>
              </div>
            </div>
            <div className="modal-buttons">
              <button 
                className="save-settings"
                onClick={() => setShowSettings(false)}
              >
                Save
              </button>
            </div>
          </div>
        </div>
      )}

      {showBillingModal && (
        <div id="billingModal" className="modal show">
          <div className="modal-content billing-modal-content">
            <button
              className="close-settings"
              onClick={() => setShowBillingModal(false)}
            >
              &times;
            </button>
            <h2>Plan & Billing</h2>
            <div className="settings-body">
              {billingLoading ? (
                <p>Loading billing details...</p>
              ) : (
                <>
                  <div className="billing-summary-card">
                    <p className="billing-summary-label">Current plan</p>
                    <h3>{currentPlan?.label || currentPlanKey}</h3>
                    <p>
                      {hasMeteredCredits
                        ? `${creditsRemaining.toLocaleString()} credits remaining of ${creditsTotal.toLocaleString()} this month`
                        : 'Contracted usage managed under your sales agreement'}
                    </p>
                  </div>

                  <div className="billing-grid">
                    {planOrder.map((key) => {
                      const plan = billingCatalog?.plans?.[key];
                      if (!plan) return null;
                      const isCurrent = key === currentPlanKey;
                      const isSalesOnly = !!plan.sales_only;
                      return (
                        <article key={key} className={`billing-option-card ${isCurrent ? 'is-current' : ''}`}>
                          <h4>{plan.label}</h4>
                          <p className="billing-option-price">
                            {Number.isFinite(plan.monthly_price_usd)
                              ? (plan.monthly_price_usd === 0 ? '$0' : `$${plan.monthly_price_usd}/mo`)
                              : 'Contact sales'}
                          </p>
                          <p>
                            {plan.monthly_credits == null
                              ? 'Pooled contracted usage'
                              : `${Number(plan.monthly_credits).toLocaleString()} credits/month`}
                          </p>
                          {isCurrent ? (
                            <span className="billing-chip">Current</span>
                          ) : isSalesOnly ? (
                            <a href="/login" className="billing-action-link">Talk to sales</a>
                          ) : (
                            <button
                              type="button"
                              className="save-settings"
                              onClick={() => startPlanChange(key)}
                              disabled={billingActionLoading === key}
                            >
                              {billingActionLoading === key ? 'Redirecting...' : 'Select'}
                            </button>
                          )}
                        </article>
                      );
                    })}
                  </div>

                  <h3 className="billing-subhead">Overage credit packs</h3>
                  <div className="billing-grid">
                    {packOrder.map((key) => {
                      const pack = billingCatalog?.overage_packs?.[key];
                      if (!pack) return null;
                      return (
                        <article key={key} className="billing-option-card billing-pack-card">
                          <h4>{pack.label}</h4>
                          <p className="billing-option-price">${pack.price_usd}</p>
                          <p>{Number(pack.credits || 0).toLocaleString()} one-time credits</p>
                          <button
                            type="button"
                            className="save-settings"
                            onClick={() => buyCreditPack(key)}
                            disabled={billingActionLoading === key}
                          >
                            {billingActionLoading === key ? 'Redirecting...' : 'Buy'}
                          </button>
                        </article>
                      );
                    })}
                  </div>
                </>
              )}

              {billingError && <p className="billing-error">{billingError}</p>}

              <div className="modal-buttons">
                <button
                  className="close-kanban"
                  onClick={() => setShowBillingModal(false)}
                >
                  Close
                </button>
                <button
                  className="save-settings"
                  onClick={openBillingPortal}
                  disabled={billingActionLoading === 'portal'}
                >
                  {billingActionLoading === 'portal' ? 'Opening...' : 'Open Stripe Billing Portal'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Help Modal */}
      {showHelp && (
        <div id="helpModal" className="help-modal">
          <div className="help-modal-content">
            <div className="help-modal-header">
              <h2>User Instructions</h2>
              <button 
                className="close-settings"
                onClick={() => setShowHelp(false)}
              >
                &times;
              </button>
            </div>

            <div className="slider-container">
              <div 
                className="slider-wrapper"
                style={{ transform: `translateX(-${currentSlide * 100}%)` }}
              >
                {helpImages.map((img, index) => (
                  <div key={index} className="slide">
                    <img src={img} alt={`Instruction ${index + 1}`} />
                  </div>
                ))}
              </div>
            </div>

            <div className="slider-nav">
              <button 
                className="nav-button"
                onClick={prevSlide}
                disabled={currentSlide === 0}
              >
                ← Previous
              </button>
              <span className="slide-counter">
                {currentSlide + 1} of {helpImages.length}
              </span>
              <button 
                className="nav-button"
                onClick={nextSlide}
                disabled={currentSlide === helpImages.length - 1}
              >
                Next →
              </button>
            </div>

            <div className="slide-indicators">
              {helpImages.map((_, index) => (
                <span 
                  key={index}
                  className={`indicator ${index === currentSlide ? 'active' : ''}`}
                  onClick={() => setCurrentSlide(index)}
                ></span>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Kanban Modal */}
      {showKanban && (
        <div id="kanbanModal" className="modal show">
          <div className="modal-content">
            <h2>Edit Kanban Board</h2>

            <div className="kanban-columns">
              <div className="kanban-column">
                <label htmlFor="kanbanToDo">To Do (one task per line):</label>
                <textarea 
                  id="kanbanToDo"
                  value={kanbanData.toDo.map(task => task.text).join('\n')}
                  onChange={(e) => updateKanbanColumn('toDo', e.target.value)}
                  placeholder="Enter tasks here…"
                />
              </div>
              <div className="kanban-column">
                <label htmlFor="kanbanDoing">Doing (one task per line):</label>
                <textarea 
                  id="kanbanDoing"
                  value={kanbanData.doing.map(task => task.text).join('\n')}
                  onChange={(e) => updateKanbanColumn('doing', e.target.value)}
                  placeholder="Enter tasks here…"
                />
              </div>
              <div className="kanban-column">
                <label htmlFor="kanbanDone">Done (one task per line):</label>
                <textarea 
                  id="kanbanDone"
                  value={kanbanData.done.map(task => task.text).join('\n')}
                  onChange={(e) => updateKanbanColumn('done', e.target.value)}
                  placeholder="Enter tasks here…"
                />
              </div>
            </div>

            <div className="modal-buttons">
              <button 
                className="close-kanban"
                onClick={() => setShowKanban(false)}
              >
                Close
              </button>
              <button 
                className="save-kanban"
                onClick={saveKanban}
              >
                Save
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
