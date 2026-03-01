// src/Ops/DMAIC/DMAIC.jsx
import React, { useState, useEffect, useMemo } from 'react';
import styles from './DMAIC.module.css';
import { useAdminSettings } from '../context/AdminContext';
import ResourcePageWrapper from '../../All/components/ResourcePageWrapper';

const DMAIC = () => {
  const { adminSettings } = useAdminSettings();

  // Local admin overlay (non-persistent)
  const defaultAdminPrefs = {
    enableSave: true,
    enableExport: true,
    enableApprovals: true,
    showFinancialTools: true,
  };
  const [adminModalOpen, setAdminModalOpen] = useState(false);
  const [localAdminPrefs, setLocalAdminPrefs] = useState(defaultAdminPrefs);

  const effectiveAdmin = useMemo(
    () => ({
      ...defaultAdminPrefs,
      ...(adminSettings || {}),
      ...(localAdminPrefs || {}),
    }),
    [adminSettings, localAdminPrefs]
  );

  const phases = [
    { id: 'charter', name: 'Charter', order: 1 },
    { id: 'define', name: 'Define', order: 2 },
    { id: 'measure', name: 'Measure', order: 3 },
    { id: 'analyze', name: 'Analyze', order: 4 },
    { id: 'improve', name: 'Improve', order: 5 },
    { id: 'control', name: 'Control', order: 6 }
  ];

  // Optional references left intact
  const statusOptions = [
    'Draft','Submitted','Under Review','Pending Approval','Approved','Rejected','Revision Required'
  ];
  const financialTypes = ['Cost Savings','Revenue Increase','Cost Avoidance','Cost Out'];
  const teamRoles = [
    'Sponsor','Process Owner','Black Belt','Green Belt','Team Member','Subject Matter Expert','Finance Representative'
  ];

  const [currentPhase, setCurrentPhase] = useState('charter');
  const [projectData, setProjectData] = useState({
    projectName: '',
    projectId: '',
    startDate: '',
    targetEndDate: '',
    problemStatement: '',
    businessCase: '',
    scope: '',
    outOfScope: '',
    financialType: 'Cost Savings',
    financialAmount: '',
    currency: 'USD',
    teamMembers: [{ id: 1, name: '', email: '', role: 'Sponsor', department: '' }],
    kpis: [{ id: 1, metric: '', baseline: '', target: '', unit: '', frequency: 'Monthly' }],
    phaseData: {
      charter: { status: 'Draft', startDate: '', endDate: '', daysInPhase: 0, approvals: [], comments: [] },
      define: { status: 'Not Started', startDate: '', endDate: '', daysInPhase: 0, approvals: [], comments: [] },
      measure: { status: 'Not Started', startDate: '', endDate: '', daysInPhase: 0, approvals: [], comments: [] },
      analyze: { status: 'Not Started', startDate: '', endDate: '', daysInPhase: 0, approvals: [], comments: [] },
      improve: { status: 'Not Started', startDate: '', endDate: '', daysInPhase: 0, approvals: [], comments: [] },
      control: { status: 'Not Started', startDate: '', endDate: '', daysInPhase: 0, approvals: [], comments: [] }
    },
    toolsData: {
      projectCharter: null,
      businessCase: null,
      finYBenefit: null,
      problemStatement: null,
      sipoc: null,
      stakeholderAnalysis: null,
      processMap: null,
      dataCollection: null,
      controlChart: null,
      histogram: null,
      checksheet: null,
      scatterPlot: null,
      boxPlot: null,
      anova: null,
      gapAnalysis: null,
      effortImpactMatrix: null,
      projectPlanning: null,
      controlPlan: null,
      sustainmentPlan: null
    }
  });

  const [showApprovalModal, setShowApprovalModal] = useState(false);
  const [showToolsModal, setShowToolsModal] = useState(false);
  const [selectedTool, setSelectedTool] = useState(null);

  // Days-in-phase updater (why: SLA visibility)
  useEffect(() => {
    const updateDaysInPhase = () => {
      const currentPhaseData = projectData.phaseData[currentPhase];
      if (currentPhaseData.startDate) {
        const startDate = new Date(currentPhaseData.startDate);
        const today = new Date();
        const diffTime = Math.abs(today - startDate);
        const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
        setProjectData(prev => ({
          ...prev,
          phaseData: {
            ...prev.phaseData,
            [currentPhase]: { ...prev.phaseData[currentPhase], daysInPhase: diffDays }
          }
        }));
      }
    };
    updateDaysInPhase();
    const interval = setInterval(updateDaysInPhase, 24 * 60 * 60 * 1000);
    return () => clearInterval(interval);
  }, [currentPhase, projectData.phaseData]);

  const handleInputChange = (field, value) => {
    setProjectData(prev => ({ ...prev, [field]: value }));
  };

  const handleTeamMemberChange = (id, field, value) => {
    setProjectData(prev => ({
      ...prev,
      teamMembers: prev.teamMembers.map(m => (m.id === id ? { ...m, [field]: value } : m))
    }));
  };

  const addTeamMember = () => {
    const newId = projectData.teamMembers.reduce((m, t) => Math.max(m, t.id), 0) + 1;
    setProjectData(prev => ({
      ...prev,
      teamMembers: [...prev.teamMembers, { id: newId, name: '', email: '', role: 'Team Member', department: '' }]
    }));
  };

  const removeTeamMember = id => {
    setProjectData(prev => ({ ...prev, teamMembers: prev.teamMembers.filter(m => m.id !== id) }));
  };

  const handleKpiChange = (id, field, value) => {
    setProjectData(prev => ({
      ...prev,
      kpis: prev.kpis.map(k => (k.id === id ? { ...k, [field]: value } : k))
    }));
  };

  const addKpi = () => {
    const newId = projectData.kpis.reduce((m, t) => Math.max(m, t.id), 0) + 1;
    setProjectData(prev => ({
      ...prev,
      kpis: [...prev.kpis, { id: newId, metric: '', baseline: '', target: '', unit: '', frequency: 'Monthly' }]
    }));
  };

  const removeKpi = id => {
    setProjectData(prev => ({ ...prev, kpis: prev.kpis.filter(k => k.id !== id) }));
  };

  const submitPhaseForApproval = phaseId => {
    if (!effectiveAdmin.enableApprovals) return;
    setProjectData(prev => ({
      ...prev,
      phaseData: {
        ...prev.phaseData,
        [phaseId]: {
          ...prev.phaseData[phaseId],
          status: 'Submitted',
          startDate: prev.phaseData[phaseId].startDate || new Date().toISOString().split('T')[0]
        }
      }
    }));
    setShowApprovalModal(true);
  };

  const launchTool = toolName => {
    setSelectedTool(toolName);
    setShowToolsModal(true);
  };

  const getToolStatus = toolKey => {
    const toolData = projectData.toolsData[toolKey];
    if (!toolData) return 'notStarted';
    if (toolData.status === 'completed') return 'completed';
    if (toolData.status === 'in-progress') return 'inProgress';
    return 'notStarted';
  };

  const getToolStatusText = toolKey => {
    const s = getToolStatus(toolKey);
    if (s === 'completed') return 'Completed';
    if (s === 'inProgress') return 'In Progress';
    return 'Not Started';
  };

  const getToolStatusIcon = toolKey => {
    const s = getToolStatus(toolKey);
    if (s === 'completed') return <i className="fas fa-check-circle" />;
    if (s === 'inProgress') return <i className="fas fa-clock" />;
    return <i className="fas fa-circle" />;
  };

  const getPhaseStatusColor = status => {
    switch (status) {
      case 'Approved': return 'var(--lss-success)';
      case 'Rejected': return 'var(--lss-danger)';
      case 'Under Review': return 'var(--lss-warning)';
      case 'Submitted': return 'var(--lss-info)';
      case 'Draft': return 'var(--lss-gray-500)';
      default: return 'var(--lss-gray-400)';
    }
  };

  const calculateCompletion = () => {
    const approvedPhases = Object.values(projectData.phaseData).filter(p => p.status === 'Approved').length;
    return Math.round((approvedPhases / phases.length) * 100);
  };

  const isAdmin = !!(adminSettings?.isAdmin || adminSettings?.role === 'admin');

  return (
    <ResourcePageWrapper
      pageName="DMAIC"
      toolName="DMAIC"
      adminSettings={adminSettings}
    >
      <div className={styles.dmaic} style={{ paddingBottom: 0, marginBottom: 0 }}>
        {/* Header */}
        <div className={styles.header}>
          <div className={styles.headerContent}>
            <div className={styles.projectInfo}>
              <h1>DMAIC Workflow</h1>
              <div className={styles.projectDetails}>
                <span className={styles.projectId}>
                  Project: {projectData.projectId || 'New Project'}
                </span>
                <span className={styles.projectName}>
                  {projectData.projectName || 'Untitled Project'}
                </span>
              </div>
            </div>
            <div className={styles.headerActions}>
              {effectiveAdmin.enableSave && (
                <button className={styles.saveBtn}>
                  <i className="fas fa-save" /> Save Project
                </button>
              )}
              {effectiveAdmin.enableExport && (
                <button className={styles.exportBtn}>
                  <i className="fas fa-download" /> Export Report
                </button>
              )}
              {isAdmin && (
                <button
                  className={styles.helperToggleBtn}
                  onClick={() => setAdminModalOpen(true)}
                  title="Admin Settings"
                >
                  <i className="fas fa-cog" />
                  Admin
                </button>
              )}
            </div>
          </div>
        </div>

        {/* Phase Stepper */}
        <div className={styles.phaseStepper}>
          <div className={styles.stepperContainer}>
            {phases.map((phase, index) => {
              const phaseData = projectData.phaseData[phase.id];
              const isActive = currentPhase === phase.id;
              const isCompleted = phaseData.status === 'Approved';
              const isInProgress = phaseData.status === 'Submitted' || phaseData.status === 'Under Review';

              return (
                <div key={phase.id} className={styles.stepperItem}>
                  <div
                    className={`${styles.stepperNode} ${isActive ? styles.active : ''} ${isCompleted ? styles.completed : ''} ${isInProgress ? styles.inProgress : ''}`}
                    onClick={() => setCurrentPhase(phase.id)}
                    style={{
                      backgroundColor: isCompleted ? 'var(--lss-success)' : '',
                      color: isCompleted ? 'var(--lss-white)' : ''
                    }}
                  >
                    <div className={styles.stepNumber}>
                      {isCompleted ? <i className="fas fa-check" /> : phase.order}
                    </div>
                    <div className={styles.stepLabel}>{phase.name}</div>
                    <div className={styles.stepStatus} style={{ color: getPhaseStatusColor(phaseData.status) }}>
                      {phaseData.status}
                    </div>
                    {phaseData.daysInPhase > 0 && (
                      <div className={styles.stepDays}>{phaseData.daysInPhase} days</div>
                    )}
                  </div>
                  {index < phases.length - 1 && (
                    <div className={`${styles.stepperLine} ${phaseData.status === 'Approved' ? styles.completed : ''}`} />
                  )}
                </div>
              );
            })}
          </div>

          {/* Progress Summary */}
          <div className={styles.progressSummary}>
            <div className={styles.progressBar}>
              <div className={styles.progressFill} style={{ width: `${calculateCompletion()}%` }} />
            </div>
            <span className={styles.progressText}>{calculateCompletion()}% Complete</span>
          </div>
        </div>

        {/* Main Content */}
        <div className={styles.mainContent}>
          {/* Charter Phase */}
          {currentPhase === 'charter' && (
            <div className={styles.phaseContent}>
              <div className={styles.phaseHeader}>
                <h2>Charter Phase</h2>
                <div className={styles.phaseActions}>
                  {effectiveAdmin.enableApprovals && (
                    <button className={styles.submitBtn} onClick={() => submitPhaseForApproval('charter')}>
                      Submit for Approval
                    </button>
                  )}
                </div>
              </div>

              <div className={styles.section}>
                <h3>Charter Phase Activities</h3>
                <div className={styles.toolsGrid}>
                  {/* Business Case */}
                  <div className={styles.toolCard} onClick={() => launchTool('businessCase')}>
                    <div className={styles.toolIcon}><i className="fas fa-chart-line" /></div>
                    <div className={styles.toolInfo}>
                      <h4>Business Case</h4>
                      <p>Document financial impact, ROI, and business justification</p>
                      <div className={styles.toolStatus}>
                        <span className={`${styles.statusBadge} ${styles[getToolStatus('businessCase')]}`}>
                          {getToolStatusIcon('businessCase')} {getToolStatusText('businessCase')}
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Project Charter */}
                  <div className={styles.toolCard} onClick={() => launchTool('projectCharter')}>
                    <div className={styles.toolIcon}><i className="fas fa-file-contract" /></div>
                    <div className={styles.toolInfo}>
                      <h4>Project Charter</h4>
                      <p>Define project scope, objectives, team, and success criteria</p>
                      <div className={styles.toolStatus}>
                        <span className={`${styles.statusBadge} ${styles[getToolStatus('projectCharter')]}`}>
                          {getToolStatusIcon('projectCharter')} {getToolStatusText('projectCharter')}
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* FinY Benefit (admin-toggle) */}
                  {effectiveAdmin.showFinancialTools && (
                    <div className={styles.toolCard} onClick={() => launchTool('finYBenefit')}>
                      <div className={styles.toolIcon}><i className="fas fa-dollar-sign" /></div>
                      <div className={styles.toolInfo}>
                        <h4>FinY Benefit</h4>
                        <p>Document financial gains and ROI estimates</p>
                        <div className={styles.toolStatus}>
                          <span className={`${styles.statusBadge} ${styles[getToolStatus('finYBenefit')]}`}>
                            {getToolStatusIcon('finYBenefit')} {getToolStatusText('finYBenefit')}
                          </span>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              </div>

              <div className={styles.section}>
                <h3>Phase 1 Deliverables</h3>
                <div className={styles.deliverablesList}>
                  <div className={styles.deliverable}>
                    <input type="checkbox" id="charter-1" />
                    <label htmlFor="charter-1">Business Case documented with financial impact</label>
                  </div>
                  <div className={styles.deliverable}>
                    <input type="checkbox" id="charter-2" />
                    <label htmlFor="charter-2">Project Charter completed and approved</label>
                  </div>
                  <div className={styles.deliverable}>
                    <input type="checkbox" id="charter-3" />
                    <label htmlFor="charter-3">Project team identified and committed</label>
                  </div>
                  <div className={styles.deliverable}>
                    <input type="checkbox" id="charter-4" />
                    <label htmlFor="charter-4">Success criteria and KPIs defined</label>
                  </div>
                  <div className={styles.deliverable}>
                    <input type="checkbox" id="charter-5" />
                    <label htmlFor="charter-5">Project timeline and milestones established</label>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Define Phase */}
          {currentPhase === 'define' && (
            <div className={styles.phaseContent}>
              <div className={styles.phaseHeader}>
                <h2>Define Phase</h2>
                <div className={styles.phaseActions}>
                  {effectiveAdmin.enableApprovals && (
                    <button className={styles.submitBtn} onClick={() => submitPhaseForApproval('define')}>
                      Submit for Tollgate Review
                    </button>
                  )}
                </div>
              </div>

              <div className={styles.section}>
                <h3>Define Phase Tools</h3>
                <div className={styles.toolsGrid}>
                  <div className={styles.toolCard} onClick={() => launchTool('problemStatement')}>
                    <div className={styles.toolIcon}><i className="fas fa-exclamation-triangle" /></div>
                    <div className={styles.toolInfo}>
                      <h4>Problem Statement</h4>
                      <p>Define the specific problem to be solved with measurable terms</p>
                      <div className={styles.toolStatus}>
                        <span className={`${styles.statusBadge} ${styles[getToolStatus('problemStatement')]}`}>
                          {getToolStatusIcon('problemStatement')} {getToolStatusText('problemStatement')}
                        </span>
                      </div>
                    </div>
                  </div>

                  <div className={styles.toolCard} onClick={() => launchTool('sipoc')}>
                    <div className={styles.toolIcon}><i className="fas fa-project-diagram" /></div>
                    <div className={styles.toolInfo}>
                      <h4>SIPOC</h4>
                      <p>Map suppliers, inputs, process, outputs, and customers</p>
                      <div className={styles.toolStatus}>
                        <span className={`${styles.statusBadge} ${styles[getToolStatus('sipoc')]}`}>
                          {getToolStatusIcon('sipoc')} {getToolStatusText('sipoc')}
                        </span>
                      </div>
                    </div>
                  </div>

                  <div className={styles.toolCard} onClick={() => launchTool('stakeholderAnalysis')}>
                    <div className={styles.toolIcon}><i className="fas fa-users" /></div>
                    <div className={styles.toolInfo}>
                      <h4>Stakeholder Analysis</h4>
                      <p>Identify and analyze project stakeholders and their influence</p>
                      <div className={styles.toolStatus}>
                        <span className={`${styles.statusBadge} ${styles[getToolStatus('stakeholderAnalysis')]}`}>
                          {getToolStatusIcon('stakeholderAnalysis')} {getToolStatusText('stakeholderAnalysis')}
                        </span>
                      </div>
                    </div>
                  </div>

                  <div className={styles.toolCard} onClick={() => launchTool('processMap')}>
                    <div className={styles.toolIcon}><i className="fas fa-route" /></div>
                    <div className={styles.toolInfo}>
                      <h4>Process Map</h4>
                      <p>Create detailed process flow and identify improvement opportunities</p>
                      <div className={styles.toolStatus}>
                        <span className={`${styles.statusBadge} ${styles[getToolStatus('processMap')]}`}>
                          {getToolStatusIcon('processMap')} {getToolStatusText('processMap')}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <div className={styles.section}>
                <h3>Define Phase Deliverables</h3>
                <div className={styles.deliverablesList}>
                  <div className={styles.deliverable}>
                    <input type="checkbox" id="define-1" />
                    <label htmlFor="define-1">Problem Statement refined and validated</label>
                  </div>
                  <div className={styles.deliverable}>
                    <input type="checkbox" id="define-2" />
                    <label htmlFor="define-2">SIPOC diagram completed</label>
                  </div>
                  <div className={styles.deliverable}>
                    <input type="checkbox" id="define-3" />
                    <label htmlFor="define-3">Stakeholder analysis completed</label>
                  </div>
                  <div className={styles.deliverable}>
                    <input type="checkbox" id="define-4" />
                    <label htmlFor="define-4">Process map created</label>
                  </div>
                  <div className={styles.deliverable}>
                    <input type="checkbox" id="define-5" />
                    <label htmlFor="define-5">Voice of Customer (VOC) captured</label>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Measure Phase */}
          {currentPhase === 'measure' && (
            <div className={styles.phaseContent}>
              <div className={styles.phaseHeader}>
                <h2>Measure Phase</h2>
                <div className={styles.phaseActions}>
                  {effectiveAdmin.enableApprovals && (
                    <button className={styles.submitBtn} onClick={() => submitPhaseForApproval('measure')}>
                      Submit for Tollgate Review
                    </button>
                  )}
                </div>
              </div>

              <div className={styles.section}>
                <h3>Measure Phase Tools</h3>
                <div className={styles.toolsGrid}>
                  <div className={styles.toolCard} onClick={() => launchTool('dataCollection')}>
                    <div className={styles.toolIcon}><i className="fas fa-database" /></div>
                    <div className={styles.toolInfo}>
                      <h4>Data Collection</h4>
                      <p>Collect and organize data to establish baseline performance</p>
                      <div className={styles.toolStatus}>
                        <span className={`${styles.statusBadge} ${styles[getToolStatus('dataCollection')]}`}>
                          {getToolStatusIcon('dataCollection')} {getToolStatusText('dataCollection')}
                        </span>
                      </div>
                    </div>
                  </div>

                  <div className={styles.toolCard} onClick={() => launchTool('controlChart')}>
                    <div className={styles.toolIcon}><i className="fas fa-chart-line" /></div>
                    <div className={styles.toolInfo}>
                      <h4>Control Chart</h4>
                      <p>Monitor process stability and identify special cause variation</p>
                      <div className={styles.toolStatus}>
                        <span className={`${styles.statusBadge} ${styles[getToolStatus('controlChart')]}`}>
                          {getToolStatusIcon('controlChart')} {getToolStatusText('controlChart')}
                        </span>
                      </div>
                    </div>
                  </div>

                  <div className={styles.toolCard} onClick={() => launchTool('histogram')}>
                    <div className={styles.toolIcon}><i className="fas fa-chart-bar" /></div>
                    <div className={styles.toolInfo}>
                      <h4>Histogram</h4>
                      <p>Visualize data distribution and identify patterns</p>
                      <div className={styles.toolStatus}>
                        <span className={`${styles.statusBadge} ${styles[getToolStatus('histogram')]}`}>
                          {getToolStatusIcon('histogram')} {getToolStatusText('histogram')}
                        </span>
                      </div>
                    </div>
                  </div>

                  <div className={styles.toolCard} onClick={() => launchTool('checksheet')}>
                    <div className={styles.toolIcon}><i className="fas fa-clipboard-check" /></div>
                    <div className={styles.toolInfo}>
                      <h4>Checksheet</h4>
                      <p>Systematically collect and tally data for analysis</p>
                      <div className={styles.toolStatus}>
                        <span className={`${styles.statusBadge} ${styles[getToolStatus('checksheet')]}`}>
                          {getToolStatusIcon('checksheet')} {getToolStatusText('checksheet')}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Analyze Phase */}
          {currentPhase === 'analyze' && (
            <div className={styles.phaseContent}>
              <div className={styles.phaseHeader}>
                <h2>Analyze Phase</h2>
                <div className={styles.phaseActions}>
                  {effectiveAdmin.enableApprovals && (
                    <button className={styles.submitBtn} onClick={() => submitPhaseForApproval('analyze')}>
                      Submit for Tollgate Review
                    </button>
                  )}
                </div>
              </div>

              <div className={styles.section}>
                <h3>Analyze Phase Tools</h3>
                <div className={styles.toolsGrid}>
                  <div className={styles.toolCard} onClick={() => launchTool('scatterPlot')}>
                    <div className={styles.toolIcon}><i className="fas fa-chart-scatter" /></div>
                    <div className={styles.toolInfo}>
                      <h4>Scatter Plot</h4>
                      <p>Analyze relationships and correlations between variables</p>
                      <div className={styles.toolStatus}>
                        <span className={`${styles.statusBadge} ${styles[getToolStatus('scatterPlot')]}`}>
                          {getToolStatusIcon('scatterPlot')} {getToolStatusText('scatterPlot')}
                        </span>
                      </div>
                    </div>
                  </div>

                  <div className={styles.toolCard} onClick={() => launchTool('boxPlot')}>
                    <div className={styles.toolIcon}><i className="fas fa-box" /></div>
                    <div className={styles.toolInfo}>
                      <h4>Box Plot</h4>
                      <p>Visualize data distribution and identify outliers</p>
                      <div className={styles.toolStatus}>
                        <span className={`${styles.statusBadge} ${styles[getToolStatus('boxPlot')]}`}>
                          {getToolStatusIcon('boxPlot')} {getToolStatusText('boxPlot')}
                        </span>
                      </div>
                    </div>
                  </div>

                  <div className={styles.toolCard} onClick={() => launchTool('anova')}>
                    <div className={styles.toolIcon}><i className="fas fa-microscope" /></div>
                    <div className={styles.toolInfo}>
                      <h4>ANOVA</h4>
                      <p>Analyze variance between groups and identify significant differences</p>
                      <div className={styles.toolStatus}>
                        <span className={`${styles.statusBadge} ${styles[getToolStatus('anova')]}`}>
                          {getToolStatusIcon('anova')} {getToolStatusText('anova')}
                        </span>
                      </div>
                    </div>
                  </div>

                  <div className={styles.toolCard} onClick={() => launchTool('gapAnalysis')}>
                    <div className={styles.toolIcon}><i className="fas fa-bullseye" /></div>
                    <div className={styles.toolInfo}>
                      <h4>Gap Analysis</h4>
                      <p>Identify gaps between current and desired performance</p>
                      <div className={styles.toolStatus}>
                        <span className={`${styles.statusBadge} ${styles[getToolStatus('gapAnalysis')]}`}>
                          {getToolStatusIcon('gapAnalysis')} {getToolStatusText('gapAnalysis')}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Improve Phase */}
          {currentPhase === 'improve' && (
            <div className={styles.phaseContent}>
              <div className={styles.phaseHeader}>
                <h2>Improve Phase</h2>
                <div className={styles.phaseActions}>
                  {effectiveAdmin.enableApprovals && (
                    <button className={styles.submitBtn} onClick={() => submitPhaseForApproval('improve')}>
                      Submit for Tollgate Review
                    </button>
                  )}
                </div>
              </div>

              <div className={styles.section}>
                <h3>Improve Phase Tools</h3>
                <div className={styles.toolsGrid}>
                  <div className={styles.toolCard} onClick={() => launchTool('effortImpactMatrix')}>
                    <div className={styles.toolIcon}><i className="fas fa-balance-scale" /></div>
                    <div className={styles.toolInfo}>
                      <h4>Effort Impact Matrix</h4>
                      <p>Prioritize improvement opportunities based on effort and impact</p>
                      <div className={styles.toolStatus}>
                        <span className={`${styles.statusBadge} ${styles[getToolStatus('effortImpactMatrix')]}`}>
                          {getToolStatusIcon('effortImpactMatrix')} {getToolStatusText('effortImpactMatrix')}
                        </span>
                      </div>
                    </div>
                  </div>

                  <div className={styles.toolCard} onClick={() => launchTool('projectPlanning')}>
                    <div className={styles.toolIcon}><i className="fas fa-calendar-alt" /></div>
                    <div className={styles.toolInfo}>
                      <h4>Project Planning</h4>
                      <p>Plan implementation timeline and resource allocation</p>
                      <div className={styles.toolStatus}>
                        <span className={`${styles.statusBadge} ${styles[getToolStatus('projectPlanning')]}`}>
                          {getToolStatusIcon('projectPlanning')} {getToolStatusText('projectPlanning')}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Control Phase */}
          {currentPhase === 'control' && (
            <div className={styles.phaseContent}>
              <div className={styles.phaseHeader}>
                <h2>Control Phase</h2>
                <div className={styles.phaseActions}>
                  {effectiveAdmin.enableApprovals && (
                    <button className={styles.submitBtn} onClick={() => submitPhaseForApproval('control')}>
                      Submit for Final Review
                    </button>
                  )}
                </div>
              </div>

              <div className={styles.section}>
                <h3>Control Phase Tools</h3>
                <div className={styles.toolsGrid}>
                  <div className={styles.toolCard} onClick={() => launchTool('controlPlan')}>
                    <div className={styles.toolIcon}><i className="fas fa-sliders-h" /></div>
                    <div className={styles.toolInfo}>
                      <h4>Control Plan</h4>
                      <p>Establish monitoring and control systems for sustained improvement</p>
                      <div className={styles.toolStatus}>
                        <span className={`${styles.statusBadge} ${styles[getToolStatus('controlPlan')]}`}>
                          {getToolStatusIcon('controlPlan')} {getToolStatusText('controlPlan')}
                        </span>
                      </div>
                    </div>
                  </div>

                  <div className={styles.toolCard} onClick={() => launchTool('sustainmentPlan')}>
                    <div className={styles.toolIcon}><i className="fas fa-sync-alt" /></div>
                    <div className={styles.toolInfo}>
                      <h4>Sustainment Plan</h4>
                      <p>Ensure long-term sustainability of improvements</p>
                      <div className={styles.toolStatus}>
                        <span className={`${styles.statusBadge} ${styles[getToolStatus('sustainmentPlan')]}`}>
                          {getToolStatusIcon('sustainmentPlan')} {getToolStatusText('sustainmentPlan')}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Approval Modal */}
        {showApprovalModal && (
          <div className={styles.modal}>
            <div className={styles.modalContent}>
              <div className={styles.modalHeader}>
                <h3>Submit for Approval</h3>
                <button className={styles.closeBtn} onClick={() => setShowApprovalModal(false)}>
                  <i className="fas fa-times" />
                </button>
              </div>
              <div className={styles.modalBody}>
                <p>Are you sure you want to submit this phase for approval?</p>
                <p>Once submitted, you will not be able to make changes until the review is complete.</p>
              </div>
              <div className={styles.modalFooter}>
                <button className={styles.cancelBtn} onClick={() => setShowApprovalModal(false)}>Cancel</button>
                <button className={styles.confirmBtn} onClick={() => { setShowApprovalModal(false); }}>Submit</button>
              </div>
            </div>
          </div>
        )}

        {/* Tools Modal */}
        {showToolsModal && (
          <div className={styles.modal}>
            <div className={styles.modalContent}>
              <div className={styles.modalHeader}>
                <h3>Launch Tool: {selectedTool}</h3>
                <button className={styles.closeBtn} onClick={() => setShowToolsModal(false)}>
                  <i className="fas fa-times" />
                </button>
              </div>
              <div className={styles.modalBody}>
                <p>This will open the {selectedTool} tool in a new window.</p>
                <p>Any data you create will be automatically linked to this DMAIC project.</p>
              </div>
              <div className={styles.modalFooter}>
                <button className={styles.cancelBtn} onClick={() => setShowToolsModal(false)}>Cancel</button>
                <button className={styles.confirmBtn} onClick={() => { setShowToolsModal(false); }}>Launch Tool</button>
              </div>
            </div>
          </div>
        )}

        {/* Admin Settings Modal */}
        {adminModalOpen && (
          <div className={styles.modal}>
            <div className={styles.modalContent}>
              <div className={styles.modalHeader}>
                <h3>Admin Settings</h3>
                <button className={styles.closeBtn} onClick={() => setAdminModalOpen(false)}>
                  <i className="fas fa-times" />
                </button>
              </div>
              <div className={styles.modalBody}>
                <div className={styles.adminRow}>
                  <label>
                    <input
                      type="checkbox"
                      checked={!!localAdminPrefs.enableSave}
                      onChange={e => setLocalAdminPrefs(s => ({ ...s, enableSave: e.target.checked }))}
                    />
                    Enable Save
                  </label>
                </div>
                <div className={styles.adminRow}>
                  <label>
                    <input
                      type="checkbox"
                      checked={!!localAdminPrefs.enableExport}
                      onChange={e => setLocalAdminPrefs(s => ({ ...s, enableExport: e.target.checked }))}
                    />
                    Enable Export
                  </label>
                </div>
                <div className={styles.adminRow}>
                  <label>
                    <input
                      type="checkbox"
                      checked={!!localAdminPrefs.enableApprovals}
                      onChange={e => setLocalAdminPrefs(s => ({ ...s, enableApprovals: e.target.checked }))}
                    />
                    Enable Approvals
                  </label>
                </div>
                <div className={styles.adminRow}>
                  <label>
                    <input
                      type="checkbox"
                      checked={!!localAdminPrefs.showFinancialTools}
                      onChange={e => setLocalAdminPrefs(s => ({ ...s, showFinancialTools: e.target.checked }))}
                    />
                    Show Financial Tools
                  </label>
                </div>
                <p className={styles.note}>
                  These settings affect this page locally. To persist org-wide, update the AdminContext provider.
                </p>
              </div>
              <div className={styles.modalFooter}>
                <button className={styles.confirmBtn} onClick={() => setAdminModalOpen(false)}>Done</button>
              </div>
            </div>
          </div>
        )}
      </div>
    </ResourcePageWrapper>
  );
};

export default DMAIC;
