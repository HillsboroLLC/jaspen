// src/pages/GapAnalysis.jsx
import React, { useState, useEffect } from 'react';
import ResourcePageWrapper from '../../All/components/ResourcePageWrapper';
import { useAdminSettings } from '../context/AdminContext';
import styles from './GapAnalysis.module.css';

const GapAnalysis = () => {
  const { adminSettings } = useAdminSettings();

  // Gap Analysis structure
  const [gapData, setGapData] = useState({
    analysisTitle: '',
    analyst: '',
    dateCreated: new Date().toISOString().split('T')[0],
    lastUpdated: new Date().toISOString().split('T')[0],
    analysisSetup: {
      purpose: '',
      scope: '',
      timeframe: '',
      stakeholders: '',
      successCriteria: ''
    },
    currentState: {
      description: '',
      strengths: [],
      weaknesses: [],
      capabilities: [],
      resources: [],
      processes: [],
      performance: []
    },
    futureState: {
      description: '',
      vision: '',
      objectives: [],
      requirements: [],
      capabilities: [],
      resources: [],
      processes: [],
      performance: []
    },
    gaps: [],
    prioritization: {
      criteria: {
        impact: 'High impact on business objectives',
        urgency: 'Time-sensitive requirements',
        feasibility: 'Realistic to implement',
        cost: 'Cost-effective solution'
      },
      prioritizedGaps: []
    },
    actionPlan: {
      initiatives: [],
      timeline: '',
      budget: '',
      resources: '',
      risks: '',
      dependencies: ''
    },
    monitoring: {
      kpis: [],
      milestones: [],
      reviewFrequency: 'monthly',
      reportingStructure: '',
      successMetrics: ''
    },
    documentation: {
      assumptions: '',
      constraints: '',
      recommendations: '',
      nextSteps: '',
      approver: '',
      approvalDate: ''
    }
  });

  const [completionPercentage, setCompletionPercentage] = useState(0);

  // Calculate completion percentage
  useEffect(() => {
    const calculateCompletion = () => {
      let totalFields = 0;
      let completedFields = 0;

      totalFields += 3;
      if (gapData.analysisTitle) completedFields++;
      if (gapData.analyst) completedFields++;
      if (gapData.analysisSetup.purpose) completedFields++;

      totalFields += 2;
      if (gapData.analysisSetup.scope) completedFields++;
      if (gapData.currentState.description) completedFields++;

      totalFields += 2;
      if (gapData.futureState.description) completedFields++;
      if (gapData.gaps.length > 0) completedFields++;

      totalFields += 2;
      if (gapData.actionPlan.timeline) completedFields++;
      if (gapData.monitoring.reviewFrequency) completedFields++;

      totalFields += 1;
      if (gapData.documentation.assumptions) completedFields++;

      const percentage = totalFields > 0 ? Math.round((completedFields / totalFields) * 100) : 0;
      setCompletionPercentage(percentage);
    };

    calculateCompletion();
  }, [gapData]);

  // Handlers (unchanged intent)
  const handleBasicInfoChange = (field, value) => {
    setGapData(prev => ({
      ...prev,
      [field]: value,
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleSetupChange = (field, value) => {
    setGapData(prev => ({
      ...prev,
      analysisSetup: { ...prev.analysisSetup, [field]: value },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleCurrentStateChange = (field, value) => {
    setGapData(prev => ({
      ...prev,
      currentState: { ...prev.currentState, [field]: value },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleFutureStateChange = (field, value) => {
    setGapData(prev => ({
      ...prev,
      futureState: { ...prev.futureState, [field]: value },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const addArrayItem = (section, field) => {
    const newItem = {
      id: Date.now(),
      description: '',
      category: '',
      priority: 'medium',
      status: 'identified'
    };
    setGapData(prev => ({
      ...prev,
      [section]: { ...prev[section], [field]: [...prev[section][field], newItem] },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const removeArrayItem = (section, field, itemId) => {
    setGapData(prev => ({
      ...prev,
      [section]: { ...prev[section], [field]: prev[section][field].filter(i => i.id !== itemId) },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleArrayItemChange = (section, field, itemId, property, value) => {
    setGapData(prev => ({
      ...prev,
      [section]: {
        ...prev[section],
        [field]: prev[section][field].map(i => (i.id === itemId ? { ...i, [property]: value } : i))
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const addGap = () => {
    const newGap = {
      id: Date.now(),
      title: '',
      description: '',
      category: 'capability',
      currentState: '',
      futureState: '',
      gapSize: 'medium',
      impact: 'medium',
      urgency: 'medium',
      feasibility: 'medium',
      cost: 'medium',
      priority: '',
      riskOfNotAddressing: '',
      potentialSolutions: '',
      estimatedEffort: '',
      estimatedCost: '',
      expectedBenefit: '',
      dependencies: '',
      status: 'identified'
    };
    setGapData(prev => ({
      ...prev,
      gaps: [...prev.gaps, newGap],
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const removeGap = gapId => {
    setGapData(prev => ({
      ...prev,
      gaps: prev.gaps.filter(gap => gap.id !== gapId),
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleGapChange = (gapId, field, value) => {
    setGapData(prev => ({
      ...prev,
      gaps: prev.gaps.map(gap => {
        if (gap.id !== gapId) return gap;
        const updated = { ...gap, [field]: value };

        // Why: keep priority auto-derived when impact/urgency/feasibility change.
        if (['impact', 'urgency', 'feasibility'].includes(field)) {
          const impact = field === 'impact' ? value : gap.impact;
          const urgency = field === 'urgency' ? value : gap.urgency;
          const feasibility = field === 'feasibility' ? value : gap.feasibility;
          const scores = { low: 1, medium: 2, high: 3 };
          const score = (scores[impact] + scores[urgency] + scores[feasibility]) / 3;
          updated.priority = score >= 2.5 ? 'High' : score >= 2 ? 'Medium' : 'Low';
        }

        return updated;
      }),
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handlePrioritizationChange = (field, value) => {
    setGapData(prev => ({
      ...prev,
      prioritization: { ...prev.prioritization, [field]: value },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleActionPlanChange = (field, value) => {
    setGapData(prev => ({
      ...prev,
      actionPlan: { ...prev.actionPlan, [field]: value },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleMonitoringChange = (field, value) => {
    setGapData(prev => ({
      ...prev,
      monitoring: { ...prev.monitoring, [field]: value },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleDocumentationChange = (field, value) => {
    setGapData(prev => ({
      ...prev,
      documentation: { ...prev.documentation, [field]: value },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const addInitiative = () => {
    const newInitiative = {
      id: Date.now(),
      title: '',
      description: '',
      gapAddressed: '',
      owner: '',
      startDate: '',
      endDate: '',
      budget: '',
      resources: '',
      milestones: '',
      status: 'planned'
    };
    setGapData(prev => ({
      ...prev,
      actionPlan: { ...prev.actionPlan, initiatives: [...prev.actionPlan.initiatives, newInitiative] },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const removeInitiative = initiativeId => {
    setGapData(prev => ({
      ...prev,
      actionPlan: {
        ...prev.actionPlan,
        initiatives: prev.actionPlan.initiatives.filter(i => i.id !== initiativeId)
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleInitiativeChange = (initiativeId, field, value) => {
    setGapData(prev => ({
      ...prev,
      actionPlan: {
        ...prev.actionPlan,
        initiatives: prev.actionPlan.initiatives.map(i => (i.id === initiativeId ? { ...i, [field]: value } : i))
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const addKPI = () => {
    const newKPI = {
      id: Date.now(),
      metric: '',
      currentValue: '',
      targetValue: '',
      unit: '',
      frequency: 'monthly',
      owner: '',
      status: 'active'
    };
    setGapData(prev => ({
      ...prev,
      monitoring: { ...prev.monitoring, kpis: [...prev.monitoring.kpis, newKPI] },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const removeKPI = kpiId => {
    setGapData(prev => ({
      ...prev,
      monitoring: { ...prev.monitoring, kpis: prev.monitoring.kpis.filter(k => k.id !== kpiId) },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleKPIChange = (kpiId, field, value) => {
    setGapData(prev => ({
      ...prev,
      monitoring: {
        ...prev.monitoring,
        kpis: prev.monitoring.kpis.map(k => (k.id === kpiId ? { ...k, [field]: value } : k))
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleSave = () => {
    console.log('Saving Gap Analysis draft:', gapData);
  };

  const handleExport = () => {
    console.log('Exporting Gap Analysis to PDF:', gapData);
  };

  return (
    <ResourcePageWrapper
      pageName="Gap Analysis"
      toolName="gapanalysis"
      adminSettings={adminSettings}
    >
      <div className={styles.rcaContainer} style={{ paddingBottom: 0 }}>
        {/* Header */}
        <div className={styles.header}>
          <div className={styles.headerContent}>
            <h1>Gap Analysis</h1>
            <div className={styles.progressSection}>
              <div className={styles.progressBar}>
                <div
                  className={styles.progressFill}
                  style={{
                    width: `${completionPercentage}%`,
                    backgroundImage: 'none',         // ensure no gradient
                    backgroundColor: '#161f3b'       // solid dark navy
                  }}
                />
              </div>
              <span className={styles.progressText}>{completionPercentage}% Complete</span>
            </div>
          </div>
          <div className={styles.headerActions}>
            <button className={styles.saveBtn} onClick={handleSave}>
              <i className="fas fa-save"></i> Save Draft
            </button>
            <button className={styles.exportBtn} onClick={handleExport}>
              <i className="fas fa-download"></i> Export PDF
            </button>
          </div>
        </div>

        {/* Main Content */}
        <div className={styles.mainContent} style={{ paddingBottom: 0 }}>
          {/* Top Section: Analysis Information ONLY (full width) */}
          <div className={styles.topSection}>
            <div className={styles.processInfoCard} style={{ gridColumn: '1 / -1', width: '100%' }}>
              <h2>Analysis Information</h2>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Analysis Title <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={gapData.analysisTitle}
                  onChange={(e) => handleBasicInfoChange('analysisTitle', e.target.value)}
                  placeholder="Enter the title for your gap analysis"
                />
              </div>

              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>
                    Analyst <span className={styles.required}>*</span>
                  </label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={gapData.analyst}
                    onChange={(e) => handleBasicInfoChange('analyst', e.target.value)}
                    placeholder="Who is conducting this analysis?"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Date Created</label>
                  <input
                    type="date"
                    className={styles.textInput}
                    value={gapData.dateCreated}
                    onChange={(e) => handleBasicInfoChange('dateCreated', e.target.value)}
                  />
                </div>
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Purpose <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={gapData.analysisSetup.purpose}
                  onChange={(e) => handleSetupChange('purpose', e.target.value)}
                  placeholder="What is the purpose of this gap analysis?"
                  rows={2}
                />
              </div>

              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Scope</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={gapData.analysisSetup.scope}
                    onChange={(e) => handleSetupChange('scope', e.target.value)}
                    placeholder="What is included in this analysis?"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Timeframe</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={gapData.analysisSetup.timeframe}
                    onChange={(e) => handleSetupChange('timeframe', e.target.value)}
                    placeholder="What timeframe are we analyzing?"
                  />
                </div>
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Key Stakeholders</label>
                <textarea
                  className={styles.textareaInput}
                  value={gapData.analysisSetup.stakeholders}
                  onChange={(e) => handleSetupChange('stakeholders', e.target.value)}
                  placeholder="Who are the key stakeholders involved?"
                  rows={2}
                />
              </div>
            </div>
          </div>

          {/* Current State Assessment Section */}
          <div className={styles.analysisCard}>
            <h2>Current State Assessment</h2>
            <div className={styles.stateGrid}>
              <div className={styles.stateDescription}>
                <label className={styles.fieldLabel}>
                  Current State Description <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={gapData.currentState.description}
                  onChange={(e) => handleCurrentStateChange('description', e.target.value)}
                  placeholder="Describe the current state in detail"
                  rows={4}
                />
              </div>

              <div className={styles.stateCategories}>
                <div className={styles.categorySection}>
                  <div className={styles.categoryHeader}>
                    <h3>Strengths</h3>
                    <button className={styles.addBtn} onClick={() => addArrayItem('currentState', 'strengths')}>
                      <i className="fas fa-plus"></i> Add
                    </button>
                  </div>
                  <div className={styles.categoryList}>
                    {gapData.currentState.strengths.map((strength) => (
                      <div key={strength.id} className={styles.categoryItem}>
                        <input
                          type="text"
                          className={styles.categoryInput}
                          value={strength.description}
                          onChange={(e) =>
                            handleArrayItemChange('currentState', 'strengths', strength.id, 'description', e.target.value)
                          }
                          placeholder="Describe a current strength"
                        />
                        <button className={styles.removeBtn} onClick={() => removeArrayItem('currentState', 'strengths', strength.id)}>
                          <i className="fas fa-times"></i>
                        </button>
                      </div>
                    ))}
                  </div>
                </div>

                <div className={styles.categorySection}>
                  <div className={styles.categoryHeader}>
                    <h3>Weaknesses</h3>
                    <button className={styles.addBtn} onClick={() => addArrayItem('currentState', 'weaknesses')}>
                      <i className="fas fa-plus"></i> Add
                    </button>
                  </div>
                  <div className={styles.categoryList}>
                    {gapData.currentState.weaknesses.map((weakness) => (
                      <div key={weakness.id} className={styles.categoryItem}>
                        <input
                          type="text"
                          className={styles.categoryInput}
                          value={weakness.description}
                          onChange={(e) =>
                            handleArrayItemChange('currentState', 'weaknesses', weakness.id, 'description', e.target.value)
                          }
                          placeholder="Describe a current weakness"
                        />
                        <button className={styles.removeBtn} onClick={() => removeArrayItem('currentState', 'weaknesses', weakness.id)}>
                          <i className="fas fa-times"></i>
                        </button>
                      </div>
                    ))}
                  </div>
                </div>

                <div className={styles.categorySection}>
                  <div className={styles.categoryHeader}>
                    <h3>Current Capabilities</h3>
                    <button className={styles.addBtn} onClick={() => addArrayItem('currentState', 'capabilities')}>
                      <i className="fas fa-plus"></i> Add
                    </button>
                  </div>
                  <div className={styles.categoryList}>
                    {gapData.currentState.capabilities.map((capability) => (
                      <div key={capability.id} className={styles.categoryItem}>
                        <input
                          type="text"
                          className={styles.categoryInput}
                          value={capability.description}
                          onChange={(e) =>
                            handleArrayItemChange('currentState', 'capabilities', capability.id, 'description', e.target.value)
                          }
                          placeholder="Describe a current capability"
                        />
                        <button className={styles.removeBtn} onClick={() => removeArrayItem('currentState', 'capabilities', capability.id)}>
                          <i className="fas fa-times"></i>
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Future State Vision Section */}
          <div className={styles.analysisCard}>
            <h2>Future State Vision</h2>
            <div className={styles.stateGrid}>
              <div className={styles.stateDescription}>
                <label className={styles.fieldLabel}>
                  Future State Description <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={gapData.futureState.description}
                  onChange={(e) => handleFutureStateChange('description', e.target.value)}
                  placeholder="Describe the desired future state in detail"
                  rows={4}
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Vision Statement</label>
                <textarea
                  className={styles.textareaInput}
                  value={gapData.futureState.vision}
                  onChange={(e) => handleFutureStateChange('vision', e.target.value)}
                  placeholder="What is the vision for the future state?"
                  rows={2}
                />
              </div>

              <div className={styles.stateCategories}>
                <div className={styles.categorySection}>
                  <div className={styles.categoryHeader}>
                    <h3>Future Objectives</h3>
                    <button className={styles.addBtn} onClick={() => addArrayItem('futureState', 'objectives')}>
                      <i className="fas fa-plus"></i> Add
                    </button>
                  </div>
                  <div className={styles.categoryList}>
                    {gapData.futureState.objectives.map((objective) => (
                      <div key={objective.id} className={styles.categoryItem}>
                        <input
                          type="text"
                          className={styles.categoryInput}
                          value={objective.description}
                          onChange={(e) =>
                            handleArrayItemChange('futureState', 'objectives', objective.id, 'description', e.target.value)
                          }
                          placeholder="Describe a future objective"
                        />
                        <button className={styles.removeBtn} onClick={() => removeArrayItem('futureState', 'objectives', objective.id)}>
                          <i className="fas fa-times"></i>
                        </button>
                      </div>
                    ))}
                  </div>
                </div>

                <div className={styles.categorySection}>
                  <div className={styles.categoryHeader}>
                    <h3>Required Capabilities</h3>
                    <button className={styles.addBtn} onClick={() => addArrayItem('futureState', 'capabilities')}>
                      <i className="fas fa-plus"></i> Add
                    </button>
                  </div>
                  <div className={styles.categoryList}>
                    {gapData.futureState.capabilities.map((capability) => (
                      <div key={capability.id} className={styles.categoryItem}>
                        <input
                          type="text"
                          className={styles.categoryInput}
                          value={capability.description}
                          onChange={(e) =>
                            handleArrayItemChange('futureState', 'capabilities', capability.id, 'description', e.target.value)
                          }
                          placeholder="Describe a required capability"
                        />
                        <button className={styles.removeBtn} onClick={() => removeArrayItem('futureState', 'capabilities', capability.id)}>
                          <i className="fas fa-times"></i>
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Gap Identification Section */}
          <div className={styles.analysisCard}>
            <div className={styles.sectionHeader}>
              <h2>Gap Identification</h2>
              <button className={styles.addBtn} onClick={addGap}>
                <i className="fas fa-plus"></i> Add Gap
              </button>
            </div>

            <div className={styles.gapsTable}>
              <table className={styles.gapTable}>
                <thead>
                  <tr>
                    <th>Gap Title</th>
                    <th>Category</th>
                    <th>Current State</th>
                    <th>Future State</th>
                    <th>Gap Size</th>
                    <th>Impact</th>
                    <th>Urgency</th>
                    <th>Feasibility</th>
                    <th>Priority</th>
                    <th>Status</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {gapData.gaps.map((gap) => (
                    <tr key={gap.id}>
                      <td>
                        <input
                          type="text"
                          className={styles.tableInput}
                          value={gap.title}
                          onChange={(e) => handleGapChange(gap.id, 'title', e.target.value)}
                          placeholder="Gap title"
                        />
                      </td>
                      <td>
                        <select
                          className={styles.tableSelect}
                          value={gap.category}
                          onChange={(e) => handleGapChange(gap.id, 'category', e.target.value)}
                        >
                          <option value="capability">Capability</option>
                          <option value="resource">Resource</option>
                          <option value="process">Process</option>
                          <option value="performance">Performance</option>
                          <option value="technology">Technology</option>
                          <option value="skill">Skill</option>
                        </select>
                      </td>
                      <td>
                        <input
                          type="text"
                          className={styles.tableInput}
                          value={gap.currentState}
                          onChange={(e) => handleGapChange(gap.id, 'currentState', e.target.value)}
                          placeholder="Current state"
                        />
                      </td>
                      <td>
                        <input
                          type="text"
                          className={styles.tableInput}
                          value={gap.futureState}
                          onChange={(e) => handleGapChange(gap.id, 'futureState', e.target.value)}
                          placeholder="Future state"
                        />
                      </td>
                      <td>
                        <select
                          className={styles.gapSizeSelect}
                          value={gap.gapSize}
                          onChange={(e) => handleGapChange(gap.id, 'gapSize', e.target.value)}
                        >
                          <option value="small">Small</option>
                          <option value="medium">Medium</option>
                          <option value="large">Large</option>
                        </select>
                      </td>
                      <td>
                        <select
                          className={styles.impactSelect}
                          value={gap.impact}
                          onChange={(e) => handleGapChange(gap.id, 'impact', e.target.value)}
                        >
                          <option value="low">Low</option>
                          <option value="medium">Medium</option>
                          <option value="high">High</option>
                        </select>
                      </td>
                      <td>
                        <select
                          className={styles.urgencySelect}
                          value={gap.urgency}
                          onChange={(e) => handleGapChange(gap.id, 'urgency', e.target.value)}
                        >
                          <option value="low">Low</option>
                          <option value="medium">Medium</option>
                          <option value="high">High</option>
                        </select>
                      </td>
                      <td>
                        <select
                          className={styles.feasibilitySelect}
                          value={gap.feasibility}
                          onChange={(e) => handleGapChange(gap.id, 'feasibility', e.target.value)}
                        >
                          <option value="low">Low</option>
                          <option value="medium">Medium</option>
                          <option value="high">High</option>
                        </select>
                      </td>
                      <td>
                        <span className={`${styles.priorityBadge} ${styles[gap.priority?.toLowerCase()]}`}>
                          {gap.priority}
                        </span>
                      </td>
                      <td>
                        <select
                          className={styles.statusSelect}
                          value={gap.status}
                          onChange={(e) => handleGapChange(gap.id, 'status', e.target.value)}
                        >
                          <option value="identified">Identified</option>
                          <option value="analyzed">Analyzed</option>
                          <option value="planned">Planned</option>
                          <option value="in-progress">In Progress</option>
                          <option value="closed">Closed</option>
                        </select>
                      </td>
                      <td>
                        <button className={styles.removeBtn} onClick={() => removeGap(gap.id)}>
                          <i className="fas fa-times"></i>
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Gap Prioritization Section */}
          <div className={styles.analysisCard}>
            <h2>Gap Prioritization</h2>
            <div className={styles.prioritizationGrid}>
              <div className={styles.prioritySection}>
                <h3>High Priority Gaps</h3>
                <div className={styles.priorityList}>
                  {gapData.gaps.filter(g => g.priority === 'High').map(gap => (
                    <div key={gap.id} className={styles.gapCard}>
                      <div className={styles.gapCardHeader}>
                        <span className={styles.gapTitle}>{gap.title}</span>
                        <span className={`${styles.priorityBadge} ${styles.high}`}>High</span>
                      </div>
                      <div className={styles.gapCardDetails}>
                        <span>Category: {gap.category}</span>
                        <span>Size: {gap.gapSize}</span>
                        <span>Impact: {gap.impact}</span>
                        <span>Urgency: {gap.urgency}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className={styles.prioritySection}>
                <h3>Medium Priority Gaps</h3>
                <div className={styles.priorityList}>
                  {gapData.gaps.filter(g => g.priority === 'Medium').map(gap => (
                    <div key={gap.id} className={styles.gapCard}>
                      <div className={styles.gapCardHeader}>
                        <span className={styles.gapTitle}>{gap.title}</span>
                        <span className={`${styles.priorityBadge} ${styles.medium}`}>Medium</span>
                      </div>
                      <div className={styles.gapCardDetails}>
                        <span>Category: {gap.category}</span>
                        <span>Size: {gap.gapSize}</span>
                        <span>Impact: {gap.impact}</span>
                        <span>Urgency: {gap.urgency}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className={styles.prioritySection}>
                <h3>Low Priority Gaps</h3>
                <div className={styles.priorityList}>
                  {gapData.gaps.filter(g => g.priority === 'Low').map(gap => (
                    <div key={gap.id} className={styles.gapCard}>
                      <div className={styles.gapCardHeader}>
                        <span className={styles.gapTitle}>{gap.title}</span>
                        <span className={`${styles.priorityBadge} ${styles.low}`}>Low</span>
                      </div>
                      <div className={styles.gapCardDetails}>
                        <span>Category: {gap.category}</span>
                        <span>Size: {gap.gapSize}</span>
                        <span>Impact: {gap.impact}</span>
                        <span>Urgency: {gap.urgency}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* Action Planning Section */}
          <div className={styles.analysisCard}>
            <h2>Action Planning</h2>
            <div className={styles.actionPlanSection}>
              <div className={styles.sectionHeader}>
                <h3>Gap Closure Initiatives</h3>
                <button className={styles.addBtn} onClick={addInitiative}>
                  <i className="fas fa-plus"></i> Add Initiative
                </button>
              </div>

              <div className={styles.initiativesTable}>
                <table className={styles.initiativeTable}>
                  <thead>
                    <tr>
                      <th>Initiative Title</th>
                      <th>Gap Addressed</th>
                      <th>Owner</th>
                      <th>Start Date</th>
                      <th>End Date</th>
                      <th>Budget</th>
                      <th>Status</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {gapData.actionPlan.initiatives.map((initiative) => (
                      <tr key={initiative.id}>
                        <td>
                          <input
                            type="text"
                            className={styles.tableInput}
                            value={initiative.title}
                            onChange={(e) => handleInitiativeChange(initiative.id, 'title', e.target.value)}
                            placeholder="Initiative title"
                          />
                        </td>
                        <td>
                          <select
                            className={styles.tableSelect}
                            value={initiative.gapAddressed}
                            onChange={(e) => handleInitiativeChange(initiative.id, 'gapAddressed', e.target.value)}
                          >
                            <option value="">Select gap</option>
                            {gapData.gaps.map((gap) => (
                              <option key={gap.id} value={gap.title}>
                                {gap.title}
                              </option>
                            ))}
                          </select>
                        </td>
                        <td>
                          <input
                            type="text"
                            className={styles.tableInput}
                            value={initiative.owner}
                            onChange={(e) => handleInitiativeChange(initiative.id, 'owner', e.target.value)}
                            placeholder="Owner"
                          />
                        </td>
                        <td>
                          <input
                            type="date"
                            className={styles.tableInput}
                            value={initiative.startDate}
                            onChange={(e) => handleInitiativeChange(initiative.id, 'startDate', e.target.value)}
                          />
                        </td>
                        <td>
                          <input
                            type="date"
                            className={styles.tableInput}
                            value={initiative.endDate}
                            onChange={(e) => handleInitiativeChange(initiative.id, 'endDate', e.target.value)}
                          />
                        </td>
                        <td>
                          <input
                            type="text"
                            className={styles.tableInput}
                            value={initiative.budget}
                            onChange={(e) => handleInitiativeChange(initiative.id, 'budget', e.target.value)}
                            placeholder="Budget"
                          />
                        </td>
                        <td>
                          <select
                            className={styles.statusSelect}
                            value={initiative.status}
                            onChange={(e) => handleInitiativeChange(initiative.id, 'status', e.target.value)}
                          >
                            <option value="planned">Planned</option>
                            <option value="in-progress">In Progress</option>
                            <option value="completed">Completed</option>
                            <option value="on-hold">On Hold</option>
                          </select>
                        </td>
                        <td>
                          <button className={styles.removeBtn} onClick={() => removeInitiative(initiative.id)}>
                            <i className="fas fa-times"></i>
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className={styles.actionPlanDetails}>
                <div className={styles.fieldRow}>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Overall Timeline</label>
                    <textarea
                      className={styles.textareaInput}
                      value={gapData.actionPlan.timeline}
                      onChange={(e) => handleActionPlanChange('timeline', e.target.value)}
                      placeholder="What is the overall timeline for gap closure?"
                      rows={2}
                    />
                  </div>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Total Budget</label>
                    <input
                      type="text"
                      className={styles.textInput}
                      value={gapData.actionPlan.budget}
                      onChange={(e) => handleActionPlanChange('budget', e.target.value)}
                      placeholder="Total budget required"
                    />
                  </div>
                </div>

                <div className={styles.fieldRow}>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Resources Required</label>
                    <textarea
                      className={styles.textareaInput}
                      value={gapData.actionPlan.resources}
                      onChange={(e) => handleActionPlanChange('resources', e.target.value)}
                      placeholder="What resources are needed?"
                      rows={2}
                    />
                  </div>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Key Dependencies</label>
                    <textarea
                      className={styles.textareaInput}
                      value={gapData.actionPlan.dependencies}
                      onChange={(e) => handleActionPlanChange('dependencies', e.target.value)}
                      placeholder="What are the key dependencies?"
                      rows={2}
                    />
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Monitoring & Measurement Section */}
          <div className={styles.analysisCard}>
            <h2>Monitoring & Measurement</h2>
            <div className={styles.monitoringSection}>
              <div className={styles.sectionHeader}>
                <h3>Key Performance Indicators</h3>
                <button className={styles.addBtn} onClick={addKPI}>
                  <i className="fas fa-plus"></i> Add KPI
                </button>
              </div>

              <div className={styles.kpiTable}>
                <table className={styles.monitoringTable}>
                  <thead>
                    <tr>
                      <th>Metric</th>
                      <th>Current Value</th>
                      <th>Target Value</th>
                      <th>Unit</th>
                      <th>Frequency</th>
                      <th>Owner</th>
                      <th>Status</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {gapData.monitoring.kpis.map((kpi) => (
                      <tr key={kpi.id}>
                        <td>
                          <input
                            type="text"
                            className={styles.tableInput}
                            value={kpi.metric}
                            onChange={(e) => handleKPIChange(kpi.id, 'metric', e.target.value)}
                            placeholder="KPI metric"
                          />
                        </td>
                        <td>
                          <input
                            type="text"
                            className={styles.tableInput}
                            value={kpi.currentValue}
                            onChange={(e) => handleKPIChange(kpi.id, 'currentValue', e.target.value)}
                            placeholder="Current"
                          />
                        </td>
                        <td>
                          <input
                            type="text"
                            className={styles.tableInput}
                            value={kpi.targetValue}
                            onChange={(e) => handleKPIChange(kpi.id, 'targetValue', e.target.value)}
                            placeholder="Target"
                          />
                        </td>
                        <td>
                          <input
                            type="text"
                            className={styles.tableInput}
                            value={kpi.unit}
                            onChange={(e) => handleKPIChange(kpi.id, 'unit', e.target.value)}
                            placeholder="Unit"
                          />
                        </td>
                        <td>
                          <select
                            className={styles.tableSelect}
                            value={kpi.frequency}
                            onChange={(e) => handleKPIChange(kpi.id, 'frequency', e.target.value)}
                          >
                            <option value="daily">Daily</option>
                            <option value="weekly">Weekly</option>
                            <option value="monthly">Monthly</option>
                            <option value="quarterly">Quarterly</option>
                          </select>
                        </td>
                        <td>
                          <input
                            type="text"
                            className={styles.tableInput}
                            value={kpi.owner}
                            onChange={(e) => handleKPIChange(kpi.id, 'owner', e.target.value)}
                            placeholder="Owner"
                          />
                        </td>
                        <td>
                          <select
                            className={styles.statusSelect}
                            value={kpi.status}
                            onChange={(e) => handleKPIChange(kpi.id, 'status', e.target.value)}
                          >
                            <option value="active">Active</option>
                            <option value="inactive">Inactive</option>
                            <option value="achieved">Achieved</option>
                          </select>
                        </td>
                        <td>
                          <button className={styles.removeBtn} onClick={() => removeKPI(kpi.id)}>
                            <i className="fas fa-times"></i>
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className={styles.monitoringDetails}>
                <div className={styles.fieldRow}>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Review Frequency</label>
                    <select
                      className={styles.selectInput}
                      value={gapData.monitoring.reviewFrequency}
                      onChange={(e) => handleMonitoringChange('reviewFrequency', e.target.value)}
                    >
                      <option value="weekly">Weekly</option>
                      <option value="monthly">Monthly</option>
                      <option value="quarterly">Quarterly</option>
                      <option value="annually">Annually</option>
                    </select>
                  </div>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Reporting Structure</label>
                    <input
                      type="text"
                      className={styles.textInput}
                      value={gapData.monitoring.reportingStructure}
                      onChange={(e) => handleMonitoringChange('reportingStructure', e.target.value)}
                      placeholder="Who reports to whom?"
                    />
                  </div>
                </div>

                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Success Metrics</label>
                  <textarea
                    className={styles.textareaInput}
                    value={gapData.monitoring.successMetrics}
                    onChange={(e) => handleMonitoringChange('successMetrics', e.target.value)}
                    placeholder="How will success be measured?"
                    rows={2}
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Documentation & Summary Section (last card -> no bottom margin) */}
          <div className={styles.analysisCard} style={{ marginBottom: 0 }}>
            <h2>Documentation & Summary</h2>
            <div className={styles.documentationGrid}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Assumptions <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={gapData.documentation.assumptions}
                  onChange={(e) => handleDocumentationChange('assumptions', e.target.value)}
                  placeholder="What assumptions were made during the analysis?"
                  rows={3}
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Constraints</label>
                <textarea
                  className={styles.textareaInput}
                  value={gapData.documentation.constraints}
                  onChange={(e) => handleDocumentationChange('constraints', e.target.value)}
                  placeholder="What constraints affect the gap closure?"
                  rows={3}
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Recommendations</label>
                <textarea
                  className={styles.textareaInput}
                  value={gapData.documentation.recommendations}
                  onChange={(e) => handleDocumentationChange('recommendations', e.target.value)}
                  placeholder="What are your recommendations for gap closure?"
                  rows={3}
                />
              </div>

              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Next Steps</label>
                  <textarea
                    className={styles.textareaInput}
                    value={gapData.documentation.nextSteps}
                    onChange={(e) => handleDocumentationChange('nextSteps', e.target.value)}
                    placeholder="What are the immediate next steps?"
                    rows={2}
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Approver</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={gapData.documentation.approver}
                    onChange={(e) => handleDocumentationChange('approver', e.target.value)}
                    placeholder="Who approved this analysis?"
                  />
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </ResourcePageWrapper>
  );
};

export default GapAnalysis;
