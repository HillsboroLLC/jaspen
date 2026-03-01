import React, { useState, useEffect } from 'react';
import { useAdminSettings } from '../context/AdminContext';
import ResourcePageWrapper from '../../All/components/ResourcePageWrapper';
import styles from './PilotPlan.module.css';

const PilotPlan = () => {
  const { adminSettings } = useAdminSettings();

  // Pilot Plan data structure
  const [pilotData, setPilotData] = useState({
    projectName: '',
    pilotLeader: '',
    pilotTeam: '',
    dateCreated: new Date().toISOString().split('T')[0],
    lastUpdated: new Date().toISOString().split('T')[0],
    
    // Pilot overview
    pilotOverview: {
      purpose: '',
      scope: '',
      objectives: '',
      hypothesis: '',
      successCriteria: '',
      duration: '',
      location: '',
      participants: ''
    },
    
    // Solution details
    solutionDetails: {
      solutionName: '',
      description: '',
      category: 'process', // 'process', 'technology', 'people', 'policy'
      changeType: 'incremental', // 'incremental', 'radical', 'transformational'
      complexity: 'low', // 'low', 'medium', 'high'
      resources: '',
      dependencies: ''
    },
    
    // Pilot design
    pilotDesign: {
      pilotType: 'parallel', // 'parallel', 'sequential', 'before-after'
      sampleSize: '',
      selectionCriteria: '',
      controlGroup: false,
      controlGroupSize: '',
      randomization: false,
      blindingType: 'none', // 'none', 'single', 'double'
      dataCollection: ''
    },
    
    // Success metrics
    successMetrics: [
      {
        id: 1,
        name: 'Primary Outcome',
        description: '',
        type: 'quantitative', // 'quantitative', 'qualitative'
        unit: '',
        baseline: '',
        target: '',
        measurementMethod: '',
        frequency: 'daily' // 'daily', 'weekly', 'monthly', 'continuous'
      }
    ],
    
    // Timeline and milestones
    timeline: {
      startDate: '',
      endDate: '',
      phases: [
        {
          id: 1,
          name: 'Preparation',
          startDate: '',
          endDate: '',
          description: '',
          deliverables: '',
          responsible: '',
          status: 'not-started'
        },
        {
          id: 2,
          name: 'Implementation',
          startDate: '',
          endDate: '',
          description: '',
          deliverables: '',
          responsible: '',
          status: 'not-started'
        },
        {
          id: 3,
          name: 'Monitoring',
          startDate: '',
          endDate: '',
          description: '',
          deliverables: '',
          responsible: '',
          status: 'not-started'
        },
        {
          id: 4,
          name: 'Evaluation',
          startDate: '',
          endDate: '',
          description: '',
          deliverables: '',
          responsible: '',
          status: 'not-started'
        }
      ]
    },
    
    // Risk management
    riskManagement: {
      riskAssessment: [
        {
          id: 1,
          risk: '',
          probability: 'medium',
          impact: 'medium',
          mitigation: '',
          contingency: '',
          owner: ''
        }
      ],
      rollbackPlan: '',
      escalationProcedure: ''
    },
    
    // Communication plan
    communicationPlan: {
      stakeholders: [
        {
          id: 1,
          name: '',
          role: '',
          interest: 'high',
          influence: 'high',
          communicationMethod: 'email',
          frequency: 'weekly'
        }
      ],
      reportingSchedule: '',
      communicationChannels: ''
    },
    
    // Results and evaluation
    results: {
      pilotStatus: 'planning',
      actualStartDate: '',
      actualEndDate: '',
      metricsAchieved: false,
      lessonsLearned: '',
      recommendations: '',
      scaleUpPlan: '',
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
      if (pilotData.projectName) completedFields++;
      if (pilotData.pilotLeader) completedFields++;
      if (pilotData.pilotTeam) completedFields++;

      // Pilot overview
      totalFields += 4;
      if (pilotData.pilotOverview.purpose) completedFields++;
      if (pilotData.pilotOverview.objectives) completedFields++;
      if (pilotData.pilotOverview.successCriteria) completedFields++;
      if (pilotData.pilotOverview.duration) completedFields++;

      // Solution details
      totalFields += 3;
      if (pilotData.solutionDetails.solutionName) completedFields++;
      if (pilotData.solutionDetails.description) completedFields++;
      if (pilotData.solutionDetails.resources) completedFields++;

      // Pilot design
      totalFields += 3;
      if (pilotData.pilotDesign.sampleSize) completedFields++;
      if (pilotData.pilotDesign.selectionCriteria) completedFields++;
      if (pilotData.pilotDesign.dataCollection) completedFields++;

      // Success metrics
      totalFields += 1;
      const hasCompleteMetric = pilotData.successMetrics.some(metric => 
        metric.name && metric.description && metric.baseline && metric.target
      );
      if (hasCompleteMetric) completedFields++;

      // Timeline
      totalFields += 2;
      if (pilotData.timeline.startDate && pilotData.timeline.endDate) completedFields++;
      const hasCompletePhase = pilotData.timeline.phases.some(phase => 
        phase.description && phase.responsible
      );
      if (hasCompletePhase) completedFields++;

      const percentage = totalFields > 0 ? Math.round((completedFields / totalFields) * 100) : 0;
      setCompletionPercentage(percentage);
    };

    calculateCompletion();
  }, [pilotData]);

  // Handlers
  const handleBasicInfoChange = (field, value) => {
    setPilotData(prev => ({
      ...prev,
      [field]: value,
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleOverviewChange = (field, value) => {
    setPilotData(prev => ({
      ...prev,
      pilotOverview: {
        ...prev.pilotOverview,
        [field]: value
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleSolutionChange = (field, value) => {
    setPilotData(prev => ({
      ...prev,
      solutionDetails: {
        ...prev.solutionDetails,
        [field]: value
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleDesignChange = (field, value) => {
    setPilotData(prev => ({
      ...prev,
      pilotDesign: {
        ...prev.pilotDesign,
        [field]: value
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleMetricChange = (metricId, field, value) => {
    setPilotData(prev => ({
      ...prev,
      successMetrics: prev.successMetrics.map(metric =>
        metric.id === metricId ? { ...metric, [field]: value } : metric
      ),
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleTimelineChange = (field, value) => {
    setPilotData(prev => ({
      ...prev,
      timeline: {
        ...prev.timeline,
        [field]: value
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handlePhaseChange = (phaseId, field, value) => {
    setPilotData(prev => ({
      ...prev,
      timeline: {
        ...prev.timeline,
        phases: prev.timeline.phases.map(phase =>
          phase.id === phaseId ? { ...phase, [field]: value } : phase
        )
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleRiskChange = (riskId, field, value) => {
    setPilotData(prev => ({
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

  const handleStakeholderChange = (stakeholderId, field, value) => {
    setPilotData(prev => ({
      ...prev,
      communicationPlan: {
        ...prev.communicationPlan,
        stakeholders: prev.communicationPlan.stakeholders.map(stakeholder =>
          stakeholder.id === stakeholderId ? { ...stakeholder, [field]: value } : stakeholder
        )
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleResultsChange = (field, value) => {
    setPilotData(prev => ({
      ...prev,
      results: {
        ...prev.results,
        [field]: value
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Risk priority helper
  const getRiskPriority = (probability, impact) => {
    const scores = { low: 1, medium: 2, high: 3 };
    return scores[probability] * scores[impact];
  };

  return (
    <ResourcePageWrapper
      pageName="Pilot Plan"
      toolName="Pilot Plan"
      adminSettings={adminSettings}
    >
      <div className={styles.pilotContainer}>
        {/* Header */}
        <div className={styles.header}>
          <div className={styles.headerContent}>
            <h1>Pilot Plan</h1>
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
          {/* Full-width Pilot Information Card (chat removed, no topSection wrapper) */}
          <div className={styles.processInfoCard}>
            <h2>Pilot Information</h2>
            
            <div className={styles.fieldRow}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Project Name <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={pilotData.projectName}
                  onChange={(e) => handleBasicInfoChange('projectName', e.target.value)}
                  placeholder="Enter project name"
                />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Pilot Leader <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={pilotData.pilotLeader}
                  onChange={(e) => handleBasicInfoChange('pilotLeader', e.target.value)}
                  placeholder="Enter pilot leader name"
                />
              </div>
            </div>

            <div className={styles.fieldRow}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Pilot Team</label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={pilotData.pilotTeam}
                  onChange={(e) => handleBasicInfoChange('pilotTeam', e.target.value)}
                  placeholder="Enter team members"
                />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Date Created</label>
                <input
                  type="date"
                  className={styles.textInput}
                  value={pilotData.dateCreated}
                  onChange={(e) => handleBasicInfoChange('dateCreated', e.target.value)}
                />
              </div>
            </div>
          </div>

          {/* Pilot Overview Card */}
          <div className={styles.pilotOverviewCard}>
            <div className={styles.sectionHeader}>
              <h2>Pilot Overview</h2>
              <button className={styles.generateBtn} onClick={() => {
                const sampleData = {
                  pilotOverview: {
                    purpose: 'Test the effectiveness of new standardized work procedures in reducing defect rates',
                    scope: 'Assembly line A, shift 1, 20 operators, 4-week duration',
                    objectives: 'Reduce defect rate by 50%, improve cycle time by 15%, increase operator satisfaction',
                    hypothesis: 'Standardized work procedures will reduce variation and improve quality outcomes',
                    successCriteria: 'Defect rate < 2%, cycle time improvement ≥ 10%, operator satisfaction score ≥ 4/5',
                    duration: '4 weeks',
                    location: 'Assembly Line A, Building 2',
                    participants: '20 operators, 2 supervisors, 1 quality inspector'
                  },
                  solutionDetails: {
                    solutionName: 'Standardized Work Procedures',
                    description: 'Implementation of visual work instructions, SOPs, and quality checkpoints',
                    category: 'process',
                    changeType: 'incremental',
                    complexity: 'medium',
                    resources: '40 hours training, $5,000 materials, 2 weeks preparation',
                    dependencies: 'Training completion, visual aids installation, supervisor buy-in'
                  },
                  pilotDesign: {
                    pilotType: 'parallel',
                    sampleSize: '20 operators',
                    selectionCriteria: 'Day shift operators with >6 months experience, representative skill mix',
                    controlGroup: true,
                    controlGroupSize: '20 operators (Assembly Line B)',
                    randomization: false,
                    blindingType: 'single',
                    dataCollection: 'Daily defect counts, cycle time measurements, weekly surveys'
                  },
                  timeline: {
                    startDate: new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString().split('T')[0],
                    endDate: new Date(Date.now() + 35 * 24 * 60 * 60 * 1000).toISOString().split('T')[0]
                  }
                };
                setPilotData(prev => ({
                  ...prev,
                  pilotOverview: sampleData.pilotOverview,
                  solutionDetails: sampleData.solutionDetails,
                  pilotDesign: sampleData.pilotDesign,
                  timeline: {
                    ...prev.timeline,
                    startDate: sampleData.timeline.startDate,
                    endDate: sampleData.timeline.endDate
                  },
                  lastUpdated: new Date().toISOString().split('T')[0]
                }));
              }}>
                <i className="fas fa-magic"></i>
                Generate Sample Data
              </button>
            </div>
            
            <div className={styles.overviewGrid}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Purpose <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={pilotData.pilotOverview.purpose}
                  onChange={(e) => handleOverviewChange('purpose', e.target.value)}
                  placeholder="What is the purpose of this pilot?"
                  rows="3"
                />
              </div>
              
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Scope <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={pilotData.pilotOverview.scope}
                  onChange={(e) => handleOverviewChange('scope', e.target.value)}
                  placeholder="Define the pilot scope (who, what, where, when)"
                  rows="3"
                />
              </div>
              
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Objectives <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={pilotData.pilotOverview.objectives}
                  onChange={(e) => handleOverviewChange('objectives', e.target.value)}
                  placeholder="What specific objectives will this pilot achieve?"
                  rows="3"
                />
              </div>
              
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Hypothesis</label>
                  <textarea
                    className={styles.textareaInput}
                    value={pilotData.pilotOverview.hypothesis}
                    onChange={(e) => handleOverviewChange('hypothesis', e.target.value)}
                    placeholder="What do you expect to happen?"
                    rows="2"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Success Criteria</label>
                  <textarea
                    className={styles.textareaInput}
                    value={pilotData.pilotOverview.successCriteria}
                    onChange={(e) => handleOverviewChange('successCriteria', e.target.value)}
                    placeholder="How will you measure success?"
                    rows="2"
                  />
                </div>
              </div>
              
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Duration</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={pilotData.pilotOverview.duration}
                    onChange={(e) => handleOverviewChange('duration', e.target.value)}
                    placeholder="e.g., 4 weeks"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Location</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={pilotData.pilotOverview.location}
                    onChange={(e) => handleOverviewChange('location', e.target.value)}
                    placeholder="Where will the pilot run?"
                  />
                </div>
              </div>
              
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Participants</label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={pilotData.pilotOverview.participants}
                  onChange={(e) => handleOverviewChange('participants', e.target.value)}
                  placeholder="Who will participate in the pilot?"
                />
              </div>
            </div>
          </div>

          {/* Solution Details Card */}
          <div className={styles.solutionCard}>
            <div className={styles.sectionHeader}>
              <h2>Solution Details</h2>
            </div>
            
            <div className={styles.solutionGrid}>
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>
                    Solution Name <span className={styles.required}>*</span>
                  </label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={pilotData.solutionDetails.solutionName}
                    onChange={(e) => handleSolutionChange('solutionName', e.target.value)}
                    placeholder="Name of the solution being piloted"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Category</label>
                  <select
                    className={styles.selectInput}
                    value={pilotData.solutionDetails.category}
                    onChange={(e) => handleSolutionChange('category', e.target.value)}
                  >
                    <option value="process">Process Improvement</option>
                    <option value="technology">Technology Solution</option>
                    <option value="people">People/Training</option>
                    <option value="policy">Policy/Organizational</option>
                  </select>
                </div>
              </div>
              
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Description <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={pilotData.solutionDetails.description}
                  onChange={(e) => handleSolutionChange('description', e.target.value)}
                  placeholder="Detailed description of the solution"
                  rows="3"
                />
              </div>
              
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Change Type</label>
                  <select
                    className={styles.selectInput}
                    value={pilotData.solutionDetails.changeType}
                    onChange={(e) => handleSolutionChange('changeType', e.target.value)}
                  >
                    <option value="incremental">Incremental</option>
                    <option value="radical">Radical</option>
                    <option value="transformational">Transformational</option>
                  </select>
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Complexity</label>
                  <select
                    className={styles.selectInput}
                    value={pilotData.solutionDetails.complexity}
                    onChange={(e) => handleSolutionChange('complexity', e.target.value)}
                  >
                    <option value="low">Low</option>
                    <option value="medium">Medium</option>
                    <option value="high">High</option>
                  </select>
                </div>
              </div>
              
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Resources Required</label>
                <textarea
                  className={styles.textareaInput}
                  value={pilotData.solutionDetails.resources}
                  onChange={(e) => handleSolutionChange('resources', e.target.value)}
                  placeholder="What resources are needed for the pilot?"
                  rows="2"
                />
              </div>
              
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Dependencies</label>
                <textarea
                  className={styles.textareaInput}
                  value={pilotData.solutionDetails.dependencies}
                  onChange={(e) => handleSolutionChange('dependencies', e.target.value)}
                  placeholder="What must be completed before the pilot can start?"
                  rows="2"
                />
              </div>
            </div>
          </div>

          {/* Pilot Design Card */}
          <div className={styles.pilotDesignCard}>
            <div className={styles.sectionHeader}>
              <h2>Pilot Design</h2>
            </div>
            
            <div className={styles.designGrid}>
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Pilot Type</label>
                  <select
                    className={styles.selectInput}
                    value={pilotData.pilotDesign.pilotType}
                    onChange={(e) => handleDesignChange('pilotType', e.target.value)}
                  >
                    <option value="parallel">Parallel (runs alongside current process)</option>
                    <option value="sequential">Sequential (replaces current process temporarily)</option>
                    <option value="before-after">Before-After (compare results over time)</option>
                  </select>
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Sample Size</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={pilotData.pilotDesign.sampleSize}
                    onChange={(e) => handleDesignChange('sampleSize', e.target.value)}
                    placeholder="Number of participants/units"
                  />
                </div>
              </div>
              
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Selection Criteria</label>
                <textarea
                  className={styles.textareaInput}
                  value={pilotData.pilotDesign.selectionCriteria}
                  onChange={(e) => handleDesignChange('selectionCriteria', e.target.value)}
                  placeholder="How will you select pilot participants?"
                  rows="2"
                />
              </div>
              
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.checkboxLabel}>
                    <input
                      type="checkbox"
                      checked={pilotData.pilotDesign.controlGroup}
                      onChange={(e) => handleDesignChange('controlGroup', e.target.checked)}
                    />
                    Use Control Group
                  </label>
                  {pilotData.pilotDesign.controlGroup && (
                    <input
                      type="text"
                      className={styles.textInput}
                      value={pilotData.pilotDesign.controlGroupSize}
                      onChange={(e) => handleDesignChange('controlGroupSize', e.target.value)}
                      placeholder="Control group size"
                      style={{ marginTop: '0.5rem' }}
                    />
                  )}
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.checkboxLabel}>
                    <input
                      type="checkbox"
                      checked={pilotData.pilotDesign.randomization}
                      onChange={(e) => handleDesignChange('randomization', e.target.checked)}
                    />
                    Use Randomization
                  </label>
                  <select
                    className={styles.selectInput}
                    value={pilotData.pilotDesign.blindingType}
                    onChange={(e) => handleDesignChange('blindingType', e.target.value)}
                    style={{ marginTop: '0.5rem' }}
                  >
                    <option value="none">No Blinding</option>
                    <option value="single">Single Blind</option>
                    <option value="double">Double Blind</option>
                  </select>
                </div>
              </div>
              
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Data Collection Plan</label>
                <textarea
                  className={styles.textareaInput}
                  value={pilotData.pilotDesign.dataCollection}
                  onChange={(e) => handleDesignChange('dataCollection', e.target.value)}
                  placeholder="How will you collect and track data during the pilot?"
                  rows="3"
                />
              </div>
            </div>
          </div>

          {/* Success Metrics Card */}
          <div className={styles.metricsCard}>
            <div className={styles.sectionHeader}>
              <h2>Success Metrics</h2>
              <button className={styles.addBtn} onClick={() => {
                const newMetric = {
                  id: Date.now(),
                  name: '',
                  description: '',
                  type: 'quantitative',
                  unit: '',
                  baseline: '',
                  target: '',
                  measurementMethod: '',
                  frequency: 'daily'
                };
                setPilotData(prev => ({
                  ...prev,
                  successMetrics: [...prev.successMetrics, newMetric],
                  lastUpdated: new Date().toISOString().split('T')[0]
                }));
              }}>
                <i className="fas fa-plus"></i>
                Add Metric
              </button>
            </div>
            
            <div className={styles.metricsGrid}>
              {pilotData.successMetrics.map((metric, idx) => (
                <div key={metric.id} className={styles.metricCard}>
                  <div className={styles.metricHeader}>
                    <h3>Metric {idx + 1}</h3>
                    {pilotData.successMetrics.length > 1 && (
                      <button
                        className={styles.removeBtn}
                        onClick={() => {
                          if (pilotData.successMetrics.length > 1) {
                            setPilotData(prev => ({
                              ...prev,
                              successMetrics: prev.successMetrics.filter(m => m.id !== metric.id),
                              lastUpdated: new Date().toISOString().split('T')[0]
                            }));
                          }
                        }}
                      >
                        <i className="fas fa-times"></i>
                      </button>
                    )}
                  </div>
                  
                  <div className={styles.metricFields}>
                    <div className={styles.fieldRow}>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Metric Name</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={metric.name}
                          onChange={(e) => handleMetricChange(metric.id, 'name', e.target.value)}
                          placeholder="e.g., Defect Rate"
                        />
                      </div>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Type</label>
                        <select
                          className={styles.selectInput}
                          value={metric.type}
                          onChange={(e) => handleMetricChange(metric.id, 'type', e.target.value)}
                        >
                          <option value="quantitative">Quantitative</option>
                          <option value="qualitative">Qualitative</option>
                        </select>
                      </div>
                    </div>
                    
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Description</label>
                      <textarea
                        className={styles.textareaInput}
                        value={metric.description}
                        onChange={(e) => handleMetricChange(metric.id, 'description', e.target.value)}
                        placeholder="Describe what this metric measures"
                        rows="2"
                      />
                    </div>
                    
                    <div className={styles.fieldRow}>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Unit</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={metric.unit}
                          onChange={(e) => handleMetricChange(metric.id, 'unit', e.target.value)}
                          placeholder="e.g., %, seconds, count"
                        />
                      </div>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Frequency</label>
                        <select
                          className={styles.selectInput}
                          value={metric.frequency}
                          onChange={(e) => handleMetricChange(metric.id, 'frequency', e.target.value)}
                        >
                          <option value="continuous">Continuous</option>
                          <option value="daily">Daily</option>
                          <option value="weekly">Weekly</option>
                          <option value="monthly">Monthly</option>
                        </select>
                      </div>
                    </div>
                    
                    <div className={styles.fieldRow}>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Baseline</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={metric.baseline}
                          onChange={(e) => handleMetricChange(metric.id, 'baseline', e.target.value)}
                          placeholder="Current performance"
                        />
                      </div>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Target</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={metric.target}
                          onChange={(e) => handleMetricChange(metric.id, 'target', e.target.value)}
                          placeholder="Target performance"
                        />
                      </div>
                    </div>
                    
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Measurement Method</label>
                      <input
                        type="text"
                        className={styles.textInput}
                        value={metric.measurementMethod}
                        onChange={(e) => handleMetricChange(metric.id, 'measurementMethod', e.target.value)}
                        placeholder="How will this be measured?"
                      />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Timeline Card */}
          <div className={styles.timelineCard}>
            <div className={styles.sectionHeader}>
              <h2>Timeline & Milestones</h2>
            </div>
            
            <div className={styles.timelineGrid}>
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Start Date</label>
                  <input
                    type="date"
                    className={styles.textInput}
                    value={pilotData.timeline.startDate}
                    onChange={(e) => handleTimelineChange('startDate', e.target.value)}
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>End Date</label>
                  <input
                    type="date"
                    className={styles.textInput}
                    value={pilotData.timeline.endDate}
                    onChange={(e) => handleTimelineChange('endDate', e.target.value)}
                  />
                </div>
              </div>
              
              <div className={styles.phasesSection}>
                <h3>Pilot Phases</h3>
                <div className={styles.phasesGrid}>
                  {pilotData.timeline.phases.map((phase) => (
                    <div key={phase.id} className={styles.phaseCard}>
                      <div className={styles.phaseHeader}>
                        <h4>{phase.name}</h4>
                        <span className={`${styles.statusBadge} ${styles[phase.status]}`}>
                          {phase.status.replace('-', ' ')}
                        </span>
                      </div>
                      
                      <div className={styles.phaseFields}>
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
                        
                        <div className={styles.fieldGroup}>
                          <label className={styles.fieldLabel}>Description</label>
                          <textarea
                            className={styles.textareaInput}
                            value={phase.description}
                            onChange={(e) => handlePhaseChange(phase.id, 'description', e.target.value)}
                            placeholder="What happens in this phase?"
                            rows="2"
                          />
                        </div>
                        
                        <div className={styles.fieldGroup}>
                          <label className={styles.fieldLabel}>Deliverables</label>
                          <input
                            type="text"
                            className={styles.textInput}
                            value={phase.deliverables}
                            onChange={(e) => handlePhaseChange(phase.id, 'deliverables', e.target.value)}
                            placeholder="Key deliverables"
                          />
                        </div>
                        
                        <div className={styles.fieldGroup}>
                          <label className={styles.fieldLabel}>Responsible</label>
                          <input
                            type="text"
                            className={styles.textInput}
                            value={phase.responsible}
                            onChange={(e) => handlePhaseChange(phase.id, 'responsible', e.target.value)}
                            placeholder="Who is responsible?"
                          />
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* Risk Management Card */}
          <div className={styles.riskCard}>
            <div className={styles.sectionHeader}>
              <h2>Risk Management</h2>
              <button
                className={styles.addBtn}
                onClick={() => {
                  const newRisk = {
                    id: Date.now(),
                    risk: '',
                    probability: 'medium',
                    impact: 'medium',
                    mitigation: '',
                    contingency: '',
                    owner: ''
                  };
                  setPilotData(prev => ({
                    ...prev,
                    riskManagement: {
                      ...prev.riskManagement,
                      riskAssessment: [...prev.riskManagement.riskAssessment, newRisk]
                    },
                    lastUpdated: new Date().toISOString().split('T')[0]
                  }));
                }}
              >
                <i className="fas fa-plus"></i>
                Add Risk
              </button>
            </div>
            
            <div className={styles.riskGrid}>
              {pilotData.riskManagement.riskAssessment.map((risk, idx) => (
                <div key={risk.id} className={styles.riskItemCard}>
                  <div className={styles.riskHeader}>
                    <h3>Risk {idx + 1}</h3>
                    <div className={styles.riskActions}>
                      <span className={`${styles.priorityBadge} ${styles[`priority-${getRiskPriority(risk.probability, risk.impact)}`]}`}>
                        Priority: {getRiskPriority(risk.probability, risk.impact)}
                      </span>
                      {pilotData.riskManagement.riskAssessment.length > 1 && (
                        <button 
                          className={styles.removeBtn}
                          onClick={() => {
                            if (pilotData.riskManagement.riskAssessment.length > 1) {
                              setPilotData(prev => ({
                                ...prev,
                                riskManagement: {
                                  ...prev.riskManagement,
                                  riskAssessment: prev.riskManagement.riskAssessment.filter(r => r.id !== risk.id)
                                },
                                lastUpdated: new Date().toISOString().split('T')[0]
                              }));
                            }
                          }}
                        >
                          <i className="fas fa-times"></i>
                        </button>
                      )}
                    </div>
                  </div>
                  
                  <div className={styles.riskFields}>
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Risk Description</label>
                      <textarea
                        className={styles.textareaInput}
                        value={risk.risk}
                        onChange={(e) => handleRiskChange(risk.id, 'risk', e.target.value)}
                        placeholder="Describe the risk"
                        rows="2"
                      />
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
                    
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Mitigation Strategy</label>
                      <textarea
                        className={styles.textareaInput}
                        value={risk.mitigation}
                        onChange={(e) => handleRiskChange(risk.id, 'mitigation', e.target.value)}
                        placeholder="How will you prevent or reduce this risk?"
                        rows="2"
                      />
                    </div>
                    
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Contingency Plan</label>
                      <textarea
                        className={styles.textareaInput}
                        value={risk.contingency}
                        onChange={(e) => handleRiskChange(risk.id, 'contingency', e.target.value)}
                        placeholder="What will you do if this risk occurs?"
                        rows="2"
                      />
                    </div>
                    
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Risk Owner</label>
                      <input
                        type="text"
                        className={styles.textInput}
                        value={risk.owner}
                        onChange={(e) => handleRiskChange(risk.id, 'owner', e.target.value)}
                        placeholder="Who is responsible for managing this risk?"
                      />
                    </div>
                  </div>
                </div>
              ))}
            </div>
            
            <div className={styles.riskPlanningSection}>
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Rollback Plan</label>
                  <textarea
                    className={styles.textareaInput}
                    value={pilotData.riskManagement.rollbackPlan}
                    onChange={(e) => setPilotData(prev => ({
                      ...prev,
                      riskManagement: { ...prev.riskManagement, rollbackPlan: e.target.value }
                    }))}
                    placeholder="How will you return to the original state if needed?"
                    rows="3"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Escalation Procedure</label>
                  <textarea
                    className={styles.textareaInput}
                    value={pilotData.riskManagement.escalationProcedure}
                    onChange={(e) => setPilotData(prev => ({
                      ...prev,
                      riskManagement: { ...prev.riskManagement, escalationProcedure: e.target.value }
                    }))}
                    placeholder="When and how should issues be escalated?"
                    rows="3"
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Communication Plan Card */}
          <div className={styles.communicationCard}>
            <div className={styles.sectionHeader}>
              <h2>Communication Plan</h2>
              <button
                className={styles.addBtn}
                onClick={() => {
                  const newStakeholder = {
                    id: Date.now(),
                    name: '',
                    role: '',
                    interest: 'high',
                    influence: 'high',
                    communicationMethod: 'email',
                    frequency: 'weekly'
                  };
                  setPilotData(prev => ({
                    ...prev,
                    communicationPlan: {
                      ...prev.communicationPlan,
                      stakeholders: [...prev.communicationPlan.stakeholders, newStakeholder]
                    },
                    lastUpdated: new Date().toISOString().split('T')[0]
                  }));
                }}
              >
                <i className="fas fa-plus"></i>
                Add Stakeholder
              </button>
            </div>
            
            <div className={styles.stakeholdersGrid}>
              {pilotData.communicationPlan.stakeholders.map((stakeholder, idx) => (
                <div key={stakeholder.id} className={styles.stakeholderCard}>
                  <div className={styles.stakeholderHeader}>
                    <h3>Stakeholder {idx + 1}</h3>
                    {pilotData.communicationPlan.stakeholders.length > 1 && (
                      <button 
                        className={styles.removeBtn}
                        onClick={() => {
                          if (pilotData.communicationPlan.stakeholders.length > 1) {
                            setPilotData(prev => ({
                              ...prev,
                              communicationPlan: {
                                ...prev.communicationPlan,
                                stakeholders: prev.communicationPlan.stakeholders.filter(s => s.id !== stakeholder.id)
                              },
                              lastUpdated: new Date().toISOString().split('T')[0]
                            }));
                          }
                        }}
                      >
                        <i className="fas fa-times"></i>
                      </button>
                    )}
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
                          placeholder="Role/title"
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
                    
                    <div className={styles.fieldRow}>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Communication Method</label>
                        <select
                          className={styles.selectInput}
                          value={stakeholder.communicationMethod}
                          onChange={(e) => handleStakeholderChange(stakeholder.id, 'communicationMethod', e.target.value)}
                        >
                          <option value="email">Email</option>
                          <option value="meeting">Meeting</option>
                          <option value="report">Report</option>
                          <option value="dashboard">Dashboard</option>
                        </select>
                      </div>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Frequency</label>
                        <select
                          className={styles.selectInput}
                          value={stakeholder.frequency}
                          onChange={(e) => handleStakeholderChange(stakeholder.id, 'frequency', e.target.value)}
                        >
                          <option value="daily">Daily</option>
                          <option value="weekly">Weekly</option>
                          <option value="bi-weekly">Bi-weekly</option>
                          <option value="monthly">Monthly</option>
                        </select>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
            
            <div className={styles.communicationDetailsSection}>
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Reporting Schedule</label>
                  <textarea
                    className={styles.textareaInput}
                    value={pilotData.communicationPlan.reportingSchedule}
                    onChange={(e) => setPilotData(prev => ({
                      ...prev,
                      communicationPlan: { ...prev.communicationPlan, reportingSchedule: e.target.value }
                    }))}
                    placeholder="When and what will be reported?"
                    rows="2"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Communication Channels</label>
                  <textarea
                    className={styles.textareaInput}
                    value={pilotData.communicationPlan.communicationChannels}
                    onChange={(e) => setPilotData(prev => ({
                      ...prev,
                      communicationPlan: { ...prev.communicationPlan, communicationChannels: e.target.value }
                    }))}
                    placeholder="What channels will be used for communication?"
                    rows="2"
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Results & Evaluation Card */}
          <div className={styles.resultsCard}>
            <div className={styles.sectionHeader}>
              <h2>Results & Evaluation</h2>
            </div>
            
            <div className={styles.resultsGrid}>
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Pilot Status</label>
                  <select
                    className={styles.selectInput}
                    value={pilotData.results.pilotStatus}
                    onChange={(e) => handleResultsChange('pilotStatus', e.target.value)}
                  >
                    <option value="planning">Planning</option>
                    <option value="in-progress">In Progress</option>
                    <option value="completed">Completed</option>
                    <option value="cancelled">Cancelled</option>
                  </select>
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.checkboxLabel}>
                    <input
                      type="checkbox"
                      checked={pilotData.results.metricsAchieved}
                      onChange={(e) => handleResultsChange('metricsAchieved', e.target.checked)}
                    />
                    Success Metrics Achieved
                  </label>
                </div>
              </div>
              
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Actual Start Date</label>
                  <input
                    type="date"
                    className={styles.textInput}
                    value={pilotData.results.actualStartDate}
                    onChange={(e) => handleResultsChange('actualStartDate', e.target.value)}
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Actual End Date</label>
                  <input
                    type="date"
                    className={styles.textInput}
                    value={pilotData.results.actualEndDate}
                    onChange={(e) => handleResultsChange('actualEndDate', e.target.value)}
                  />
                </div>
              </div>
              
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Lessons Learned</label>
                <textarea
                  className={styles.textareaInput}
                  value={pilotData.results.lessonsLearned}
                  onChange={(e) => handleResultsChange('lessonsLearned', e.target.value)}
                  placeholder="What did you learn from this pilot?"
                  rows="4"
                />
              </div>
              
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Recommendations</label>
                <textarea
                  className={styles.textareaInput}
                  value={pilotData.results.recommendations}
                  onChange={(e) => handleResultsChange('recommendations', e.target.value)}
                  placeholder="What are your recommendations based on pilot results?"
                  rows="4"
                />
              </div>
              
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Scale-Up Plan</label>
                <textarea
                  className={styles.textareaInput}
                  value={pilotData.results.scaleUpPlan}
                  onChange={(e) => handleResultsChange('scaleUpPlan', e.target.value)}
                  placeholder="How will you scale this solution if successful?"
                  rows="3"
                />
              </div>
              
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Next Steps</label>
                <textarea
                  className={styles.textareaInput}
                  value={pilotData.results.nextSteps}
                  onChange={(e) => handleResultsChange('nextSteps', e.target.value)}
                  placeholder="What are the immediate next steps?"
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
              <span>Pilot Plan {completionPercentage}% Complete</span>
            </div>
            <div className={styles.footerActions}>
              <button className={styles.secondaryBtn}>
                <i className="fas fa-eye"></i>
                Preview
              </button>
              <button 
                className={styles.primaryBtn}
                disabled={completionPercentage < 80}
              >
                <i className="fas fa-rocket"></i>
                Launch Pilot
              </button>
            </div>
          </div>
        </div>
      </div>
    </ResourcePageWrapper>
  );
};

export default PilotPlan;
