import React, { useState, useEffect } from 'react';
import { useAdminSettings } from '../context/AdminContext';
import ResourcePageWrapper from '../../All/components/ResourcePageWrapper';
import styles from './ImplementationPlan.module.css';

const ImplementationPlan = () => {
  const { adminSettings } = useAdminSettings();

  // Small Kii integration hook (optional)
  const handleKiiDataUpdate = (extractedData) => {
    const updates = {};
    if (extractedData.projectName) updates.projectName = extractedData.projectName;
    if (extractedData.implementationLead) updates.implementationLead = extractedData.implementationLead;
    if (extractedData.implementationTeam) updates.implementationTeam = extractedData.implementationTeam;

    if (Object.keys(updates).length > 0) {
      setImplementationData(prev => ({
        ...prev,
        ...updates,
        lastUpdated: new Date().toISOString().split('T')[0]
      }));
    }
  };

  // Implementation Plan data structure
  const [implementationData, setImplementationData] = useState({
    projectName: '',
    implementationLead: '',
    implementationTeam: '',
    dateCreated: new Date().toISOString().split('T')[0],
    lastUpdated: new Date().toISOString().split('T')[0],
    
    // Implementation overview
    implementationOverview: {
      solutionName: '',
      solutionDescription: '',
      businessCase: '',
      expectedBenefits: '',
      scope: '',
      constraints: '',
      assumptions: '',
      successCriteria: ''
    },
    
    // Implementation strategy
    implementationStrategy: {
      approachType: 'phased', // 'phased', 'big-bang', 'pilot-rollout', 'parallel'
      rolloutSequence: '',
      timeline: '',
      resources: '',
      budget: '',
      dependencies: '',
      criticalPath: ''
    },
    
    // Implementation phases
    phases: [
      {
        id: 1,
        name: 'Phase 1: Preparation',
        description: '',
        startDate: '',
        endDate: '',
        duration: '',
        status: 'not-started', // 'not-started', 'in-progress', 'completed', 'delayed', 'cancelled'
        owner: '',
        deliverables: [],
        milestones: [],
        risks: [],
        dependencies: []
      }
    ],
    
    // Tasks and activities
    tasks: [
      {
        id: 1,
        phaseId: 1,
        name: 'Task 1',
        description: '',
        type: 'preparation', // 'preparation', 'implementation', 'testing', 'training', 'communication', 'monitoring'
        priority: 'medium', // 'low', 'medium', 'high', 'critical'
        startDate: '',
        endDate: '',
        duration: '',
        effort: '',
        assignee: '',
        status: 'not-started',
        dependencies: [],
        deliverables: [],
        notes: ''
      }
    ],
    
    // Resource planning
    resourcePlanning: {
      humanResources: [],
      technicalResources: [],
      financialResources: [],
      externalResources: [],
      trainingNeeds: [],
      facilityRequirements: []
    },
    
    // Change management
    changeManagement: {
      stakeholderAnalysis: [],
      communicationPlan: [],
      trainingPlan: [],
      resistanceManagement: '',
      changeReadiness: '',
      supportStructure: ''
    },
    
    // Risk management
    riskManagement: {
      riskAssessment: [],
      mitigationStrategies: [],
      contingencyPlans: [],
      riskMonitoring: '',
      escalationProcedures: ''
    },
    
    // Quality assurance
    qualityAssurance: {
      qualityStandards: '',
      testingPlan: '',
      acceptanceCriteria: '',
      qualityMetrics: [],
      reviewProcess: '',
      approvalGates: []
    },
    
    // Monitoring and control
    monitoringControl: {
      kpis: [],
      reportingSchedule: '',
      reviewMeetings: '',
      issueTracking: '',
      changeControl: '',
      statusReporting: ''
    },
    
    // Implementation results
    results: {
      implementationStatus: 'planning', // 'planning', 'in-progress', 'completed', 'cancelled'
      actualStartDate: '',
      actualEndDate: '',
      budgetVariance: 0,
      scheduleVariance: 0,
      benefitsRealized: '',
      lessonsLearned: '',
      recommendations: '',
      nextSteps: ''
    }
  });

  const [completionPercentage, setCompletionPercentage] = useState(0);

  // Calculate completion percentage
  useEffect(() => {
    const calculateCompletion = () => {
      let totalFields = 0;
      let completedFields = 0;

      // Basic info
      totalFields += 3;
      if (implementationData.projectName) completedFields++;
      if (implementationData.implementationLead) completedFields++;
      if (implementationData.implementationTeam) completedFields++;

      // Implementation overview
      totalFields += 4;
      if (implementationData.implementationOverview.solutionName) completedFields++;
      if (implementationData.implementationOverview.businessCase) completedFields++;
      if (implementationData.implementationOverview.expectedBenefits) completedFields++;
      if (implementationData.implementationOverview.successCriteria) completedFields++;

      // Implementation strategy
      totalFields += 3;
      if (implementationData.implementationStrategy.approachType) completedFields++;
      if (implementationData.implementationStrategy.timeline) completedFields++;
      if (implementationData.implementationStrategy.budget) completedFields++;

      // Phases
      totalFields += 1;
      const hasCompletePhase = implementationData.phases.some(phase => 
        phase.name && phase.description && phase.startDate && phase.endDate
      );
      if (hasCompletePhase) completedFields++;

      // Tasks
      totalFields += 1;
      const hasCompleteTask = implementationData.tasks.some(task => 
        task.name && task.description && task.assignee
      );
      if (hasCompleteTask) completedFields++;

      // Change management
      totalFields += 2;
      if (implementationData.changeManagement.stakeholderAnalysis.length > 0) completedFields++;
      if (implementationData.changeManagement.communicationPlan.length > 0) completedFields++;

      // Risk management
      totalFields += 1;
      if (implementationData.riskManagement.riskAssessment.length > 0) completedFields++;

      const percentage = totalFields > 0 ? Math.round((completedFields / totalFields) * 100) : 0;
      setCompletionPercentage(percentage);
    };

    calculateCompletion();
  }, [implementationData]);

  // Handle field changes
  const handleBasicInfoChange = (field, value) => {
    setImplementationData(prev => ({
      ...prev,
      [field]: value,
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleOverviewChange = (field, value) => {
    setImplementationData(prev => ({
      ...prev,
      implementationOverview: {
        ...prev.implementationOverview,
        [field]: value
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleStrategyChange = (field, value) => {
    setImplementationData(prev => ({
      ...prev,
      implementationStrategy: {
        ...prev.implementationStrategy,
        [field]: value
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handlePhaseChange = (phaseId, field, value) => {
    setImplementationData(prev => ({
      ...prev,
      phases: prev.phases.map(phase =>
        phase.id === phaseId ? { ...phase, [field]: value } : phase
      ),
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleTaskChange = (taskId, field, value) => {
    setImplementationData(prev => ({
      ...prev,
      tasks: prev.tasks.map(task =>
        task.id === taskId ? { ...task, [field]: value } : task
      ),
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleChangeManagementChange = (field, value) => {
    setImplementationData(prev => ({
      ...prev,
      changeManagement: {
        ...prev.changeManagement,
        [field]: value
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleResultsChange = (field, value) => {
    setImplementationData(prev => ({
      ...prev,
      results: {
        ...prev.results,
        [field]: value
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Add new phase
  const addPhase = () => {
    const newPhase = {
      id: Date.now(),
      name: `Phase ${implementationData.phases.length + 1}`,
      description: '',
      startDate: '',
      endDate: '',
      duration: '',
      status: 'not-started',
      owner: '',
      deliverables: [],
      milestones: [],
      risks: [],
      dependencies: []
    };
    
    setImplementationData(prev => ({
      ...prev,
      phases: [...prev.phases, newPhase],
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Remove phase
  const removePhase = (phaseId) => {
    if (implementationData.phases.length > 1) {
      setImplementationData(prev => ({
        ...prev,
        phases: prev.phases.filter(phase => phase.id !== phaseId),
        tasks: prev.tasks.filter(task => task.phaseId !== phaseId),
        lastUpdated: new Date().toISOString().split('T')[0]
      }));
    }
  };

  // Add new task
  const addTask = (phaseId) => {
    const newTask = {
      id: Date.now(),
      phaseId: phaseId,
      name: `Task ${implementationData.tasks.filter(t => t.phaseId === phaseId).length + 1}`,
      description: '',
      type: 'implementation',
      priority: 'medium',
      startDate: '',
      endDate: '',
      duration: '',
      effort: '',
      assignee: '',
      status: 'not-started',
      dependencies: [],
      deliverables: [],
      notes: ''
    };
    
    setImplementationData(prev => ({
      ...prev,
      tasks: [...prev.tasks, newTask],
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Remove task
  const removeTask = (taskId) => {
    setImplementationData(prev => ({
      ...prev,
      tasks: prev.tasks.filter(task => task.id !== taskId),
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Add stakeholder
  const addStakeholder = () => {
    const newStakeholder = {
      id: Date.now(),
      name: '',
      role: '',
      interest: 'medium', // 'low', 'medium', 'high'
      influence: 'medium', // 'low', 'medium', 'high'
      attitude: 'neutral', // 'supporter', 'neutral', 'resistor'
      communicationNeeds: '',
      engagementStrategy: ''
    };
    
    setImplementationData(prev => ({
      ...prev,
      changeManagement: {
        ...prev.changeManagement,
        stakeholderAnalysis: [...prev.changeManagement.stakeholderAnalysis, newStakeholder]
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Remove stakeholder
  const removeStakeholder = (stakeholderId) => {
    setImplementationData(prev => ({
      ...prev,
      changeManagement: {
        ...prev.changeManagement,
        stakeholderAnalysis: prev.changeManagement.stakeholderAnalysis.filter(s => s.id !== stakeholderId)
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Handle stakeholder change
  const handleStakeholderChange = (stakeholderId, field, value) => {
    setImplementationData(prev => ({
      ...prev,
      changeManagement: {
        ...prev.changeManagement,
        stakeholderAnalysis: prev.changeManagement.stakeholderAnalysis.map(stakeholder =>
          stakeholder.id === stakeholderId ? { ...stakeholder, [field]: value } : stakeholder
        )
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Add risk
  const addRisk = () => {
    const newRisk = {
      id: Date.now(),
      description: '',
      category: 'technical', // 'technical', 'resource', 'schedule', 'budget', 'organizational', 'external'
      probability: 'medium', // 'low', 'medium', 'high'
      impact: 'medium', // 'low', 'medium', 'high'
      priority: 'medium', // 'low', 'medium', 'high'
      mitigation: '',
      contingency: '',
      owner: '',
      status: 'open' // 'open', 'mitigated', 'closed'
    };
    
    setImplementationData(prev => ({
      ...prev,
      riskManagement: {
        ...prev.riskManagement,
        riskAssessment: [...prev.riskManagement.riskAssessment, newRisk]
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Remove risk
  const removeRisk = (riskId) => {
    setImplementationData(prev => ({
      ...prev,
      riskManagement: {
        ...prev.riskManagement,
        riskAssessment: prev.riskManagement.riskAssessment.filter(r => r.id !== riskId)
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Handle risk change
  const handleRiskChange = (riskId, field, value) => {
    setImplementationData(prev => ({
      ...prev,
      riskManagement: {
        ...prev.riskManagement,
        riskAssessment: prev.riskManagement.riskAssessment.map(risk =>
          risk.id === riskId ? { ...risk, [field]: value } : risk
        )
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Generate sample data
  const generateSampleData = () => {
    const sampleData = {
      implementationOverview: {
        solutionName: 'Automated Quality Control System',
        solutionDescription: 'Implementation of automated inspection system to reduce defects and improve quality consistency',
        businessCase: 'Current manual inspection results in 5% defect rate and high labor costs. Automated system will reduce defects to <1% and save $200K annually',
        expectedBenefits: 'Reduced defect rate from 5% to <1%, 40% reduction in inspection time, improved consistency, cost savings of $200K/year',
        scope: 'Production lines 1-3, quality control department, integration with existing MES system',
        constraints: 'Budget limit $500K, must maintain production during implementation, union agreement requirements',
        assumptions: 'Equipment vendor support available, staff training can be completed in 2 weeks, no major technical issues',
        successCriteria: 'System operational on all 3 lines, defect rate <1%, ROI achieved within 18 months'
      },
      implementationStrategy: {
        approachType: 'phased',
        rolloutSequence: 'Line 1 (pilot), Line 2, Line 3, then full integration and optimization',
        timeline: '6 months total: 2 months preparation, 3 months phased rollout, 1 month optimization',
        resources: '2 engineers, 1 project manager, vendor support team, 4 operators for training',
        budget: '$450K total: $300K equipment, $100K installation, $50K training and support',
        dependencies: 'Equipment delivery, network infrastructure upgrade, staff availability for training',
        criticalPath: 'Equipment procurement → Installation → Testing → Training → Go-live'
      },
      phases: [
        {
          id: 1,
          name: 'Phase 1: Preparation & Setup',
          description: 'Procurement, infrastructure preparation, and initial setup',
          startDate: '2024-02-01',
          endDate: '2024-03-31',
          duration: '8 weeks',
          status: 'not-started',
          owner: 'Project Manager',
          deliverables: ['Equipment procured', 'Infrastructure ready', 'Team trained'],
          milestones: ['Equipment delivery', 'Network upgrade complete'],
          risks: ['Delivery delays', 'Network issues'],
          dependencies: ['Budget approval', 'Vendor selection']
        },
        {
          id: 2,
          name: 'Phase 2: Pilot Implementation (Line 1)',
          description: 'Install and test system on production line 1',
          startDate: '2024-04-01',
          endDate: '2024-05-15',
          duration: '6 weeks',
          status: 'not-started',
          owner: 'Technical Lead',
          deliverables: ['System installed', 'Testing complete', 'Operators trained'],
          milestones: ['Installation complete', 'System acceptance'],
          risks: ['Integration issues', 'Performance problems'],
          dependencies: ['Phase 1 completion', 'Production schedule']
        },
        {
          id: 3,
          name: 'Phase 3: Full Rollout (Lines 2-3)',
          description: 'Deploy system to remaining production lines',
          startDate: '2024-05-16',
          endDate: '2024-07-15',
          duration: '8 weeks',
          status: 'not-started',
          owner: 'Technical Lead',
          deliverables: ['All lines operational', 'Full system integration'],
          milestones: ['Line 2 go-live', 'Line 3 go-live'],
          risks: ['Resource conflicts', 'Production disruption'],
          dependencies: ['Pilot success', 'Additional equipment']
        }
      ],
      changeManagement: {
        stakeholderAnalysis: [
          {
            id: 1,
            name: 'Production Manager',
            role: 'Key Decision Maker',
            interest: 'high',
            influence: 'high',
            attitude: 'supporter',
            communicationNeeds: 'Weekly status updates, budget tracking',
            engagementStrategy: 'Regular meetings, involve in key decisions'
          },
          {
            id: 2,
            name: 'Quality Control Team',
            role: 'End Users',
            interest: 'high',
            influence: 'medium',
            attitude: 'neutral',
            communicationNeeds: 'Training schedule, job impact clarification',
            engagementStrategy: 'Early involvement, comprehensive training, address concerns'
          },
          {
            id: 3,
            name: 'Production Operators',
            role: 'Affected Users',
            interest: 'medium',
            influence: 'low',
            attitude: 'resistor',
            communicationNeeds: 'Job security assurance, benefit explanation',
            engagementStrategy: 'Clear communication, hands-on training, show benefits'
          }
        ]
      },
      riskManagement: {
        riskAssessment: [
          {
            id: 1,
            description: 'Equipment delivery delays could impact timeline',
            category: 'schedule',
            probability: 'medium',
            impact: 'high',
            priority: 'high',
            mitigation: 'Order equipment early, maintain vendor communication, have backup suppliers',
            contingency: 'Adjust timeline, consider rental equipment, parallel activities',
            owner: 'Project Manager',
            status: 'open'
          },
          {
            id: 2,
            description: 'Staff resistance to new technology',
            category: 'organizational',
            probability: 'high',
            impact: 'medium',
            priority: 'high',
            mitigation: 'Early communication, involve staff in planning, comprehensive training',
            contingency: 'Additional training time, change champions, management support',
            owner: 'Change Manager',
            status: 'open'
          },
          {
            id: 3,
            description: 'Integration issues with existing MES system',
            category: 'technical',
            probability: 'medium',
            impact: 'high',
            priority: 'high',
            mitigation: 'Thorough testing, vendor support, technical review',
            contingency: 'Manual interfaces, system modifications, extended testing',
            owner: 'Technical Lead',
            status: 'open'
          }
        ]
      }
    };

    setImplementationData(prev => ({
      ...prev,
      implementationOverview: sampleData.implementationOverview,
      implementationStrategy: sampleData.implementationStrategy,
      phases: sampleData.phases,
      changeManagement: sampleData.changeManagement,
      riskManagement: sampleData.riskManagement,
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  return (
    <ResourcePageWrapper
      pageName="Implementation Plan"
      toolName="implementation-plan"
      adminSettings={adminSettings}
      onDataUpdate={handleKiiDataUpdate}
      currentData={implementationData}
    >
      <div className={styles.implementationContainer}>
        {/* Header */}
        <div className={styles.header}>
          <div className={styles.headerContent}>
            <h1>Implementation Plan</h1>
            <div className={styles.progressSection}>
<div className={styles.progressBar}>
  <div
    className={styles.progressFill}
    style={{
      width: `${completionPercentage}%`,
      background: '#0B1A33',
      backgroundImage: 'none'
    }}
  />
</div>
              <span className={styles.progressText}>{completionPercentage}% Complete</span>
            </div>
          </div>
          <div className={styles.headerActions}>
            <button className={styles.saveBtn}>
              <i className="fas fa-save"></i>
              Save Plan
            </button>
            <button className={styles.exportBtn}>
              <i className="fas fa-download"></i>
              Export
            </button>
          </div>
        </div>

        {/* Main Content */}
        <div className={styles.mainContent}>
          {/* Implementation Information (full width; chat removed) */}
          <div className={styles.processInfoCard}>
            <h2>Implementation Information</h2>
            
            <div className={styles.fieldRow}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Project Name <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={implementationData.projectName}
                  onChange={(e) => handleBasicInfoChange('projectName', e.target.value)}
                  placeholder="Enter project name"
                />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Implementation Lead <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={implementationData.implementationLead}
                  onChange={(e) => handleBasicInfoChange('implementationLead', e.target.value)}
                  placeholder="Enter implementation lead name"
                />
              </div>
            </div>

            <div className={styles.fieldRow}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Implementation Team</label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={implementationData.implementationTeam}
                  onChange={(e) => handleBasicInfoChange('implementationTeam', e.target.value)}
                  placeholder="Enter team members"
                />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Date Created</label>
                <input
                  type="date"
                  className={styles.textInput}
                  value={implementationData.dateCreated}
                  onChange={(e) => handleBasicInfoChange('dateCreated', e.target.value)}
                />
              </div>
            </div>

            <div className={styles.fieldRow}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Last Updated</label>
                <input
                  type="date"
                  className={styles.textInput}
                  value={implementationData.lastUpdated}
                  readOnly
                />
              </div>
            </div>
          </div>

          {/* Implementation Overview Card */}
          <div className={styles.overviewCard}>
            <div className={styles.sectionHeader}>
              <h2>Implementation Overview</h2>
              <button className={styles.generateBtn} onClick={generateSampleData}>
                <i className="fas fa-magic"></i>
                Generate Sample Data
              </button>
            </div>
            
            <div className={styles.overviewGrid}>
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>
                    Solution Name <span className={styles.required}>*</span>
                  </label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={implementationData.implementationOverview.solutionName}
                    onChange={(e) => handleOverviewChange('solutionName', e.target.value)}
                    placeholder="Name of the solution being implemented"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>
                    Business Case <span className={styles.required}>*</span>
                  </label>
                  <textarea
                    className={styles.textareaInput}
                    value={implementationData.implementationOverview.businessCase}
                    onChange={(e) => handleOverviewChange('businessCase', e.target.value)}
                    placeholder="Why is this implementation needed?"
                    rows="3"
                  />
                </div>
              </div>
              
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Solution Description</label>
                <textarea
                  className={styles.textareaInput}
                  value={implementationData.implementationOverview.solutionDescription}
                  onChange={(e) => handleOverviewChange('solutionDescription', e.target.value)}
                  placeholder="Describe the solution being implemented"
                  rows="3"
                />
              </div>
              
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Expected Benefits</label>
                <textarea
                  className={styles.textareaInput}
                  value={implementationData.implementationOverview.expectedBenefits}
                  onChange={(e) => handleOverviewChange('expectedBenefits', e.target.value)}
                  placeholder="What benefits are expected from this implementation?"
                  rows="3"
                />
              </div>
              
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Scope</label>
                  <textarea
                    className={styles.textareaInput}
                    value={implementationData.implementationOverview.scope}
                    onChange={(e) => handleOverviewChange('scope', e.target.value)}
                    placeholder="Define the implementation scope"
                    rows="2"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Constraints</label>
                  <textarea
                    className={styles.textareaInput}
                    value={implementationData.implementationOverview.constraints}
                    onChange={(e) => handleOverviewChange('constraints', e.target.value)}
                    placeholder="What are the implementation constraints?"
                    rows="2"
                  />
                </div>
              </div>
              
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Assumptions</label>
                  <textarea
                    className={styles.textareaInput}
                    value={implementationData.implementationOverview.assumptions}
                    onChange={(e) => handleOverviewChange('assumptions', e.target.value)}
                    placeholder="Key assumptions for the implementation"
                    rows="2"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Success Criteria</label>
                  <textarea
                    className={styles.textareaInput}
                    value={implementationData.implementationOverview.successCriteria}
                    onChange={(e) => handleOverviewChange('successCriteria', e.target.value)}
                    placeholder="How will success be measured?"
                    rows="2"
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Implementation Strategy Card */}
          <div className={styles.strategyCard}>
            <div className={styles.sectionHeader}>
              <h2>Implementation Strategy</h2>
            </div>
            
            <div className={styles.strategyGrid}>
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Approach Type</label>
                  <select
                    className={styles.selectInput}
                    value={implementationData.implementationStrategy.approachType}
                    onChange={(e) => handleStrategyChange('approachType', e.target.value)}
                  >
                    <option value="phased">Phased Implementation</option>
                    <option value="big-bang">Big Bang</option>
                    <option value="pilot-rollout">Pilot Rollout</option>
                    <option value="parallel">Parallel Implementation</option>
                  </select>
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Timeline</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={implementationData.implementationStrategy.timeline}
                    onChange={(e) => handleStrategyChange('timeline', e.target.value)}
                    placeholder="Overall implementation timeline"
                  />
                </div>
              </div>
              
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Rollout Sequence</label>
                <textarea
                  className={styles.textareaInput}
                  value={implementationData.implementationStrategy.rolloutSequence}
                  onChange={(e) => handleStrategyChange('rolloutSequence', e.target.value)}
                  placeholder="Describe the sequence of implementation activities"
                  rows="3"
                />
              </div>
              
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Resources</label>
                  <textarea
                    className={styles.textareaInput}
                    value={implementationData.implementationStrategy.resources}
                    onChange={(e) => handleStrategyChange('resources', e.target.value)}
                    placeholder="Required resources"
                    rows="2"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Budget</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={implementationData.implementationStrategy.budget}
                    onChange={(e) => handleStrategyChange('budget', e.target.value)}
                    placeholder="Implementation budget"
                  />
                </div>
              </div>
              
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Dependencies</label>
                  <textarea
                    className={styles.textareaInput}
                    value={implementationData.implementationStrategy.dependencies}
                    onChange={(e) => handleStrategyChange('dependencies', e.target.value)}
                    placeholder="Key dependencies"
                    rows="2"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Critical Path</label>
                  <textarea
                    className={styles.textareaInput}
                    value={implementationData.implementationStrategy.criticalPath}
                    onChange={(e) => handleStrategyChange('criticalPath', e.target.value)}
                    placeholder="Critical path activities"
                    rows="2"
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Implementation Phases Card */}
          <div className={styles.phasesCard}>
            <div className={styles.sectionHeader}>
              <h2>Implementation Phases</h2>
              <button className={styles.addBtn} onClick={addPhase}>
                <i className="fas fa-plus"></i>
                Add Phase
              </button>
            </div>
            
            <div className={styles.phasesGrid}>
              {implementationData.phases.map((phase) => (
                <div key={phase.id} className={styles.phaseCard}>
                  <div className={styles.phaseHeader}>
                    <h3>{phase.name}</h3>
                    <div className={styles.phaseActions}>
                      <span className={`${styles.statusBadge} ${styles[phase.status]}`}>
                        {phase.status.replace('-', ' ')}
                      </span>
                      {implementationData.phases.length > 1 && (
                        <button 
                          className={styles.removeBtn}
                          onClick={() => removePhase(phase.id)}
                        >
                          <i className="fas fa-times"></i>
                        </button>
                      )}
                    </div>
                  </div>
                  
                  <div className={styles.phaseFields}>
                    <div className={styles.fieldRow}>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Phase Name</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={phase.name}
                          onChange={(e) => handlePhaseChange(phase.id, 'name', e.target.value)}
                          placeholder="e.g., Phase 1: Preparation"
                        />
                      </div>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Status</label>
                        <select
                          className={styles.selectInput}
                          value={phase.status}
                          onChange={(e) => handlePhaseChange(phase.id, 'status', e.target.value)}
                        >
                          <option value="not-started">Not Started</option>
                          <option value="in-progress">In Progress</option>
                          <option value="completed">Completed</option>
                          <option value="delayed">Delayed</option>
                          <option value="cancelled">Cancelled</option>
                        </select>
                      </div>
                    </div>
                    
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Description</label>
                      <textarea
                        className={styles.textareaInput}
                        value={phase.description}
                        onChange={(e) => handlePhaseChange(phase.id, 'description', e.target.value)}
                        placeholder="Describe this phase"
                        rows="2"
                      />
                    </div>
                    
                    <div className={styles.fieldRow}>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Start Date</label>
                        <input
                          type="date"
                          className={styles.textInput}
                          value={phase.startDate}
                          onChange={(e) => handlePhaseChange(phase.id, 'startDate', e.target.value)}
                        />
                      </div>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>End Date</label>
                        <input
                          type="date"
                          className={styles.textInput}
                          value={phase.endDate}
                          onChange={(e) => handlePhaseChange(phase.id, 'endDate', e.target.value)}
                        />
                      </div>
                    </div>
                    
                    <div className={styles.fieldRow}>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Duration</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={phase.duration}
                          onChange={(e) => handlePhaseChange(phase.id, 'duration', e.target.value)}
                          placeholder="e.g., 4 weeks"
                        />
                      </div>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Phase Owner</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={phase.owner}
                          onChange={(e) => handlePhaseChange(phase.id, 'owner', e.target.value)}
                          placeholder="Phase owner name"
                        />
                      </div>
                    </div>
                    
                    <div className={styles.taskSection}>
                      <div className={styles.taskHeader}>
                        <h4>Tasks for this Phase</h4>
                        <button 
                          className={styles.addTaskBtn}
                          onClick={() => addTask(phase.id)}
                        >
                          <i className="fas fa-plus"></i>
                          Add Task
                        </button>
                      </div>
                      
                      {implementationData.tasks
                        .filter(task => task.phaseId === phase.id)
                        .map((task) => (
                          <div key={task.id} className={styles.taskCard}>
                            <div className={styles.taskHeader}>
                              <input
                                type="text"
                                className={styles.taskNameInput}
                                value={task.name}
                                onChange={(e) => handleTaskChange(task.id, 'name', e.target.value)}
                                placeholder="Task name"
                              />
                              <div className={styles.taskActions}>
                                <span className={`${styles.priorityBadge} ${styles[task.priority]}`}>
                                  {task.priority}
                                </span>
                                <button 
                                  className={styles.removeTaskBtn}
                                  onClick={() => removeTask(task.id)}
                                >
                                  <i className="fas fa-times"></i>
                                </button>
                              </div>
                            </div>
                            
                            <div className={styles.taskFields}>
                              <div className={styles.fieldRow}>
                                <div className={styles.fieldGroup}>
                                  <label className={styles.fieldLabel}>Type</label>
                                  <select
                                    className={styles.selectInput}
                                    value={task.type}
                                    onChange={(e) => handleTaskChange(task.id, 'type', e.target.value)}
                                  >
                                    <option value="preparation">Preparation</option>
                                    <option value="implementation">Implementation</option>
                                    <option value="testing">Testing</option>
                                    <option value="training">Training</option>
                                    <option value="communication">Communication</option>
                                    <option value="monitoring">Monitoring</option>
                                  </select>
                                </div>
                                <div className={styles.fieldGroup}>
                                  <label className={styles.fieldLabel}>Priority</label>
                                  <select
                                    className={styles.selectInput}
                                    value={task.priority}
                                    onChange={(e) => handleTaskChange(task.id, 'priority', e.target.value)}
                                  >
                                    <option value="low">Low</option>
                                    <option value="medium">Medium</option>
                                    <option value="high">High</option>
                                    <option value="critical">Critical</option>
                                  </select>
                                </div>
                              </div>
                              
                              <div className={styles.fieldRow}>
                                <div className={styles.fieldGroup}>
                                  <label className={styles.fieldLabel}>Assignee</label>
                                  <input
                                    type="text"
                                    className={styles.textInput}
                                    value={task.assignee}
                                    onChange={(e) => handleTaskChange(task.id, 'assignee', e.target.value)}
                                    placeholder="Task assignee"
                                  />
                                </div>
                                <div className={styles.fieldGroup}>
                                  <label className={styles.fieldLabel}>Status</label>
                                  <select
                                    className={styles.selectInput}
                                    value={task.status}
                                    onChange={(e) => handleTaskChange(task.id, 'status', e.target.value)}
                                  >
                                    <option value="not-started">Not Started</option>
                                    <option value="in-progress">In Progress</option>
                                    <option value="completed">Completed</option>
                                    <option value="delayed">Delayed</option>
                                  </select>
                                </div>
                              </div>
                            </div>
                          </div>
                        ))}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Change Management Card */}
          <div className={styles.changeManagementCard}>
            <div className={styles.sectionHeader}>
              <h2>Change Management</h2>
              <button className={styles.addBtn} onClick={addStakeholder}>
                <i className="fas fa-plus"></i>
                Add Stakeholder
              </button>
            </div>
            
            <div className={styles.stakeholdersGrid}>
              {implementationData.changeManagement.stakeholderAnalysis.map((stakeholder) => (
                <div key={stakeholder.id} className={styles.stakeholderCard}>
                  <div className={styles.stakeholderHeader}>
                    <h3>{stakeholder.name || 'New Stakeholder'}</h3>
                    <button 
                      className={styles.removeBtn}
                      onClick={() => removeStakeholder(stakeholder.id)}
                    >
                      <i className="fas fa-times"></i>
                    </button>
                  </div>
                  
                  <div className={styles.stakeholderFields}>
                    <div className={styles.fieldRow}>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Name</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={stakeholder.name}
                          onChange={(e) => handleStakeholderChange(stakeholder.id, 'name', e.target.value)}
                          placeholder="Stakeholder name"
                        />
                      </div>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Role</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={stakeholder.role}
                          onChange={(e) => handleStakeholderChange(stakeholder.id, 'role', e.target.value)}
                          placeholder="Role or title"
                        />
                      </div>
                    </div>
                    
                    <div className={styles.fieldRow}>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Interest Level</label>
                        <select
                          className={styles.selectInput}
                          value={stakeholder.interest}
                          onChange={(e) => handleStakeholderChange(stakeholder.id, 'interest', e.target.value)}
                        >
                          <option value="low">Low</option>
                          <option value="medium">Medium</option>
                          <option value="high">High</option>
                        </select>
                      </div>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Influence Level</label>
                        <select
                          className={styles.selectInput}
                          value={stakeholder.influence}
                          onChange={(e) => handleStakeholderChange(stakeholder.id, 'influence', e.target.value)}
                        >
                          <option value="low">Low</option>
                          <option value="medium">Medium</option>
                          <option value="high">High</option>
                        </select>
                      </div>
                    </div>
                    
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Attitude</label>
                      <select
                        className={styles.selectInput}
                        value={stakeholder.attitude}
                        onChange={(e) => handleStakeholderChange(stakeholder.id, 'attitude', e.target.value)}
                      >
                        <option value="supporter">Supporter</option>
                        <option value="neutral">Neutral</option>
                        <option value="resistor">Resistor</option>
                      </select>
                    </div>
                    
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Communication Needs</label>
                      <textarea
                        className={styles.textareaInput}
                        value={stakeholder.communicationNeeds}
                        onChange={(e) => handleStakeholderChange(stakeholder.id, 'communicationNeeds', e.target.value)}
                        placeholder="What information do they need?"
                        rows="2"
                      />
                    </div>
                    
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Engagement Strategy</label>
                      <textarea
                        className={styles.textareaInput}
                        value={stakeholder.engagementStrategy}
                        onChange={(e) => handleStakeholderChange(stakeholder.id, 'engagementStrategy', e.target.value)}
                        placeholder="How will you engage this stakeholder?"
                        rows="2"
                      />
                    </div>
                  </div>
                </div>
              ))}
            </div>
            
            <div className={styles.changeDetailsSection}>
              <h3>Change Management Details</h3>
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Resistance Management</label>
                  <textarea
                    className={styles.textareaInput}
                    value={implementationData.changeManagement.resistanceManagement}
                    onChange={(e) => handleChangeManagementChange('resistanceManagement', e.target.value)}
                    placeholder="How will resistance be managed?"
                    rows="3"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Change Readiness</label>
                  <textarea
                    className={styles.textareaInput}
                    value={implementationData.changeManagement.changeReadiness}
                    onChange={(e) => handleChangeManagementChange('changeReadiness', e.target.value)}
                    placeholder="Assessment of organizational readiness"
                    rows="3"
                  />
                </div>
              </div>
              
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Support Structure</label>
                <textarea
                  className={styles.textareaInput}
                  value={implementationData.changeManagement.supportStructure}
                  onChange={(e) => handleChangeManagementChange('supportStructure', e.target.value)}
                  placeholder="Support structure for change management"
                  rows="2"
                />
              </div>
            </div>
          </div>

          {/* Risk Management Card */}
          <div className={styles.riskCard}>
            <div className={styles.sectionHeader}>
              <h2>Risk Management</h2>
              <button className={styles.addBtn} onClick={addRisk}>
                <i className="fas fa-plus"></i>
                Add Risk
              </button>
            </div>
            
            <div className={styles.riskGrid}>
              {implementationData.riskManagement.riskAssessment.map((risk) => (
                <div key={risk.id} className={styles.riskItemCard}>
                  <div className={styles.riskHeader}>
                    <h3>Risk #{risk.id}</h3>
                    <div className={styles.riskActions}>
                      <span className={`${styles.priorityBadge} ${styles[risk.priority]}`}>
                        {risk.priority}
                      </span>
                      <button 
                        className={styles.removeBtn}
                        onClick={() => removeRisk(risk.id)}
                      >
                        <i className="fas fa-times"></i>
                      </button>
                    </div>
                  </div>
                  
                  <div className={styles.riskFields}>
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Risk Description</label>
                      <textarea
                        className={styles.textareaInput}
                        value={risk.description}
                        onChange={(e) => handleRiskChange(risk.id, 'description', e.target.value)}
                        placeholder="Describe the risk"
                        rows="2"
                      />
                    </div>
                    
                    <div className={styles.fieldRow}>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Category</label>
                        <select
                          className={styles.selectInput}
                          value={risk.category}
                          onChange={(e) => handleRiskChange(risk.id, 'category', e.target.value)}
                        >
                          <option value="technical">Technical</option>
                          <option value="resource">Resource</option>
                          <option value="schedule">Schedule</option>
                          <option value="budget">Budget</option>
                          <option value="organizational">Organizational</option>
                          <option value="external">External</option>
                        </select>
                      </div>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Status</label>
                        <select
                          className={styles.selectInput}
                          value={risk.status}
                          onChange={(e) => handleRiskChange(risk.id, 'status', e.target.value)}
                        >
                          <option value="open">Open</option>
                          <option value="mitigated">Mitigated</option>
                          <option value="closed">Closed</option>
                        </select>
                      </div>
                    </div>
                    
                    <div className={styles.fieldRow}>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Probability</label>
                        <select
                          className={styles.selectInput}
                          value={risk.probability}
                          onChange={(e) => handleRiskChange(risk.id, 'probability', e.target.value)}
                        >
                          <option value="low">Low</option>
                          <option value="medium">Medium</option>
                          <option value="high">High</option>
                        </select>
                      </div>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Impact</label>
                        <select
                          className={styles.selectInput}
                          value={risk.impact}
                          onChange={(e) => handleRiskChange(risk.id, 'impact', e.target.value)}
                        >
                          <option value="low">Low</option>
                          <option value="medium">Medium</option>
                          <option value="high">High</option>
                        </select>
                      </div>
                    </div>
                    
                    <div className={styles.fieldRow}>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Risk Owner</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={risk.owner}
                          onChange={(e) => handleRiskChange(risk.id, 'owner', e.target.value)}
                          placeholder="Risk owner"
                        />
                      </div>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Priority</label>
                        <select
                          className={styles.selectInput}
                          value={risk.priority}
                          onChange={(e) => handleRiskChange(risk.id, 'priority', e.target.value)}
                        >
                          <option value="low">Low</option>
                          <option value="medium">Medium</option>
                          <option value="high">High</option>
                        </select>
                      </div>
                    </div>
                    
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Mitigation Strategy</label>
                      <textarea
                        className={styles.textareaInput}
                        value={risk.mitigation}
                        onChange={(e) => handleRiskChange(risk.id, 'mitigation', e.target.value)}
                        placeholder="How will this risk be mitigated?"
                        rows="2"
                      />
                    </div>
                    
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Contingency Plan</label>
                      <textarea
                        className={styles.textareaInput}
                        value={risk.contingency}
                        onChange={(e) => handleRiskChange(risk.id, 'contingency', e.target.value)}
                        placeholder="What if the risk occurs?"
                        rows="2"
                      />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Results Card */}
          <div className={styles.resultsCard}>
            <div className={styles.sectionHeader}>
              <h2>Implementation Results</h2>
            </div>
            
            <div className={styles.resultsGrid}>
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Implementation Status</label>
                  <select
                    className={styles.selectInput}
                    value={implementationData.results.implementationStatus}
                    onChange={(e) => handleResultsChange('implementationStatus', e.target.value)}
                  >
                    <option value="planning">Planning</option>
                    <option value="in-progress">In Progress</option>
                    <option value="completed">Completed</option>
                    <option value="cancelled">Cancelled</option>
                  </select>
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Benefits Realized</label>
                  <textarea
                    className={styles.textareaInput}
                    value={implementationData.results.benefitsRealized}
                    onChange={(e) => handleResultsChange('benefitsRealized', e.target.value)}
                    placeholder="What benefits have been realized?"
                    rows="2"
                  />
                </div>
              </div>
              
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Lessons Learned</label>
                <textarea
                  className={styles.textareaInput}
                  value={implementationData.results.lessonsLearned}
                  onChange={(e) => handleResultsChange('lessonsLearned', e.target.value)}
                  placeholder="What lessons were learned during implementation?"
                  rows="4"
                />
              </div>
              
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Recommendations</label>
                <textarea
                  className={styles.textareaInput}
                  value={implementationData.results.recommendations}
                  onChange={(e) => handleResultsChange('recommendations', e.target.value)}
                  placeholder="What recommendations do you have for future implementations?"
                  rows="3"
                />
              </div>
              
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Next Steps</label>
                <textarea
                  className={styles.textareaInput}
                  value={implementationData.results.nextSteps}
                  onChange={(e) => handleResultsChange('nextSteps', e.target.value)}
                  placeholder="What are the next steps after implementation?"
                  rows="3"
                />
              </div>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className={styles.footer}>
          <div className={styles.footerContent}>
            <div className={styles.completionStatus}>
              <i className="fas fa-check-circle"></i>
              <span>Implementation Plan {completionPercentage}% Complete</span>
            </div>
            <div className={styles.footerActions}>
              <button className={styles.secondaryBtn}>
                <i className="fas fa-eye"></i>
                Preview Plan
              </button>
              <button 
                className={styles.primaryBtn}
                disabled={completionPercentage < 75}
              >
                <i className="fas fa-rocket"></i>
                Launch Implementation
              </button>
            </div>
          </div>
        </div>
      </div>
    </ResourcePageWrapper>
  );
};

export default ImplementationPlan;
