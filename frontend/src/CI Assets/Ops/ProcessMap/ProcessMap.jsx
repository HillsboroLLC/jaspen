import React, { useState, useEffect } from 'react';
import { useAdminSettings } from '../context/AdminContext';
import ResourcePageWrapper from '../../All/components/ResourcePageWrapper';
import styles from './ProcessMap.module.css';

const ProcessMap = () => {
  const { adminSettings } = useAdminSettings();

  // Process Map structure
  const [processData, setProcessData] = useState({
    // Basic Information
    processName: '',
    processOwner: '',
    dateCreated: new Date().toISOString().split('T')[0],
    lastUpdated: new Date().toISOString().split('T')[0],
    version: '1.0',

    // Process Overview
    processOverview: {
      purpose: '',
      scope: '',
      boundaries: '',
      customers: '',
      suppliers: '',
      triggerEvent: '',
      endEvent: ''
    },

    // Process Steps
    processSteps: [],

    // Swimlanes
    swimlanes: [],

    // Decision Points
    decisionPoints: [],

    // Handoffs
    handoffs: [],

    // Process Metrics
    processMetrics: {
      cycleTime: '',
      leadTime: '',
      processingTime: '',
      waitTime: '',
      qualityMetrics: [],
      costMetrics: []
    },

    // Risks & Issues
    risksIssues: {
      risks: [],
      issues: [],
      controls: []
    },

    // Improvement Opportunities
    improvements: {
      wasteIdentified: [],
      improvementIdeas: [],
      prioritization: []
    },

    // Documentation
    documentation: {
      relatedDocuments: [],
      workInstructions: [],
      forms: [],
      systems: []
    }
  });

  const [completionPercentage, setCompletionPercentage] = useState(0);

  // Calculate completion percentage
  useEffect(() => {
    const calculateCompletion = () => {
      let totalFields = 0;
      let completedFields = 0;

      // Basic info (3 fields)
      totalFields += 3;
      if (processData.processName) completedFields++;
      if (processData.processOwner) completedFields++;
      if (processData.processOverview.purpose) completedFields++;

      // Process overview (3 fields)
      totalFields += 3;
      if (processData.processOverview.scope) completedFields++;
      if (processData.processOverview.triggerEvent) completedFields++;
      if (processData.processOverview.endEvent) completedFields++;

      // Process steps (1 field)
      totalFields += 1;
      if (processData.processSteps.length > 0) completedFields++;

      // Swimlanes (1 field)
      totalFields += 1;
      if (processData.swimlanes.length > 0) completedFields++;

      // Metrics (1 field)
      totalFields += 1;
      if (processData.processMetrics.cycleTime) completedFields++;

      const percentage = totalFields > 0 ? Math.round((completedFields / totalFields) * 100) : 0;
      setCompletionPercentage(percentage);
    };

    calculateCompletion();
  }, [processData]);

  // Handle basic info changes
  const handleBasicInfoChange = (field, value) => {
    setProcessData(prev => ({
      ...prev,
      [field]: value,
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Handle process overview changes
  const handleProcessOverviewChange = (field, value) => {
    setProcessData(prev => ({
      ...prev,
      processOverview: {
        ...prev.processOverview,
        [field]: value
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Handle process metrics changes
  const handleProcessMetricsChange = (field, value) => {
    setProcessData(prev => ({
      ...prev,
      processMetrics: {
        ...prev.processMetrics,
        [field]: value
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Add process step
  const addProcessStep = () => {
    const newStep = {
      id: Date.now(),
      stepNumber: processData.processSteps.length + 1,
      stepName: '',
      description: '',
      responsible: '',
      duration: '',
      type: 'activity', // 'activity', 'decision', 'delay', 'inspection'
      valueAdded: 'yes', // 'yes', 'no', 'business'
      inputs: '',
      outputs: '',
      tools: '',
      risks: ''
    };

    setProcessData(prev => ({
      ...prev,
      processSteps: [...prev.processSteps, newStep],
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Remove process step
  const removeProcessStep = (stepId) => {
    setProcessData(prev => ({
      ...prev,
      processSteps: prev.processSteps.filter(step => step.id !== stepId),
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Handle process step changes
  const handleProcessStepChange = (stepId, field, value) => {
    setProcessData(prev => ({
      ...prev,
      processSteps: prev.processSteps.map(step =>
        step.id === stepId ? { ...step, [field]: value } : step
      ),
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Add swimlane
  const addSwimlane = () => {
    const newSwimlane = {
      id: Date.now(),
      name: '',
      type: 'person', // 'person', 'department', 'system'
      description: '',
      responsibilities: ''
    };

    setProcessData(prev => ({
      ...prev,
      swimlanes: [...prev.swimlanes, newSwimlane],
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Remove swimlane
  const removeSwimlane = (swimlaneId) => {
    setProcessData(prev => ({
      ...prev,
      swimlanes: prev.swimlanes.filter(swimlane => swimlane.id !== swimlaneId),
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Handle swimlane changes
  const handleSwimlaneChange = (swimlaneId, field, value) => {
    setProcessData(prev => ({
      ...prev,
      swimlanes: prev.swimlanes.map(swimlane =>
        swimlane.id === swimlaneId ? { ...swimlane, [field]: value } : swimlane
      ),
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Add decision point
  const addDecisionPoint = () => {
    const newDecision = {
      id: Date.now(),
      stepNumber: '',
      question: '',
      criteria: '',
      yesPath: '',
      noPath: '',
      responsible: ''
    };

    setProcessData(prev => ({
      ...prev,
      decisionPoints: [...prev.decisionPoints, newDecision],
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Remove decision point
  const removeDecisionPoint = (decisionId) => {
    setProcessData(prev => ({
      ...prev,
      decisionPoints: prev.decisionPoints.filter(decision => decision.id !== decisionId),
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Handle decision point changes
  const handleDecisionPointChange = (decisionId, field, value) => {
    setProcessData(prev => ({
      ...prev,
      decisionPoints: prev.decisionPoints.map(decision =>
        decision.id === decisionId ? { ...decision, [field]: value } : decision
      ),
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Add handoff
  const addHandoff = () => {
    const newHandoff = {
      id: Date.now(),
      fromStep: '',
      toStep: '',
      fromRole: '',
      toRole: '',
      whatTransferred: '',
      method: '',
      duration: '',
      risks: ''
    };

    setProcessData(prev => ({
      ...prev,
      handoffs: [...prev.handoffs, newHandoff],
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Remove handoff
  const removeHandoff = (handoffId) => {
    setProcessData(prev => ({
      ...prev,
      handoffs: prev.handoffs.filter(handoff => handoff.id !== handoffId),
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Handle handoff changes
  const handleHandoffChange = (handoffId, field, value) => {
    setProcessData(prev => ({
      ...prev,
      handoffs: prev.handoffs.map(handoff =>
        handoff.id === handoffId ? { ...handoff, [field]: value } : handoff
      ),
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Add quality metric
  const addQualityMetric = () => {
    const newMetric = {
      id: Date.now(),
      metric: '',
      target: '',
      current: '',
      measurement: ''
    };

    setProcessData(prev => ({
      ...prev,
      processMetrics: {
        ...prev.processMetrics,
        qualityMetrics: [...prev.processMetrics.qualityMetrics, newMetric]
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Remove quality metric
  const removeQualityMetric = (metricId) => {
    setProcessData(prev => ({
      ...prev,
      processMetrics: {
        ...prev.processMetrics,
        qualityMetrics: prev.processMetrics.qualityMetrics.filter(metric => metric.id !== metricId)
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Handle quality metric changes
  const handleQualityMetricChange = (metricId, field, value) => {
    setProcessData(prev => ({
      ...prev,
      processMetrics: {
        ...prev.processMetrics,
        qualityMetrics: prev.processMetrics.qualityMetrics.map(metric =>
          metric.id === metricId ? { ...metric, [field]: value } : metric
        )
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Add risk
  const addRisk = () => {
    const newRisk = {
      id: Date.now(),
      step: '',
      risk: '',
      impact: 'medium', // 'low', 'medium', 'high'
      probability: 'medium', // 'low', 'medium', 'high'
      mitigation: ''
    };

    setProcessData(prev => ({
      ...prev,
      risksIssues: {
        ...prev.risksIssues,
        risks: [...prev.risksIssues.risks, newRisk]
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Remove risk
  const removeRisk = (riskId) => {
    setProcessData(prev => ({
      ...prev,
      risksIssues: {
        ...prev.risksIssues,
        risks: prev.risksIssues.risks.filter(risk => risk.id !== riskId)
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Handle risk changes
  const handleRiskChange = (riskId, field, value) => {
    setProcessData(prev => ({
      ...prev,
      risksIssues: {
        ...prev.risksIssues,
        risks: prev.risksIssues.risks.map(risk =>
          risk.id === riskId ? { ...risk, [field]: value } : risk
        )
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Add waste
  const addWaste = () => {
    const newWaste = {
      id: Date.now(),
      step: '',
      wasteType: '', // 'transport', 'inventory', 'motion', 'waiting', 'overproduction', 'overprocessing', 'defects', 'skills'
      description: '',
      impact: '',
      solution: ''
    };

    setProcessData(prev => ({
      ...prev,
      improvements: {
        ...prev.improvements,
        wasteIdentified: [...prev.improvements.wasteIdentified, newWaste]
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Remove waste
  const removeWaste = (wasteId) => {
    setProcessData(prev => ({
      ...prev,
      improvements: {
        ...prev.improvements,
        wasteIdentified: prev.improvements.wasteIdentified.filter(waste => waste.id !== wasteId)
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Handle waste changes
  const handleWasteChange = (wasteId, field, value) => {
    setProcessData(prev => ({
      ...prev,
      improvements: {
        ...prev.improvements,
        wasteIdentified: prev.improvements.wasteIdentified.map(waste =>
          waste.id === wasteId ? { ...waste, [field]: value } : waste
        )
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Add improvement idea
  const addImprovementIdea = () => {
    const newIdea = {
      id: Date.now(),
      area: '',
      description: '',
      benefit: '',
      effort: 'medium', // 'low', 'medium', 'high'
      impact: 'medium', // 'low', 'medium', 'high'
      priority: 'medium' // 'low', 'medium', 'high'
    };

    setProcessData(prev => ({
      ...prev,
      improvements: {
        ...prev.improvements,
        improvementIdeas: [...prev.improvements.improvementIdeas, newIdea]
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Remove improvement idea
  const removeImprovementIdea = (ideaId) => {
    setProcessData(prev => ({
      ...prev,
      improvements: {
        ...prev.improvements,
        improvementIdeas: prev.improvements.improvementIdeas.filter(idea => idea.id !== ideaId)
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Handle improvement idea changes
  const handleImprovementIdeaChange = (ideaId, field, value) => {
    setProcessData(prev => ({
      ...prev,
      improvements: {
        ...prev.improvements,
        improvementIdeas: prev.improvements.improvementIdeas.map(idea =>
          idea.id === ideaId ? { ...idea, [field]: value } : idea
        )
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Save draft
  const handleSave = () => {
    console.log('Saving Process Map draft:', processData);
    // Implement save functionality
  };

  // Export PDF
  const handleExport = () => {
    console.log('Exporting Process Map to PDF:', processData);
    // Implement export functionality
  };

  return (
    <ResourcePageWrapper
      pageName="Process Map"
      toolName="Process Map"
      adminSettings={adminSettings}
    >
      <div className={styles.rcaContainer}>
        {/* Header - Exact match to other tools */}
        <div className={styles.header}>
          <div className={styles.headerContent}>
            <h1>Process Map</h1>
            <div
              className={styles.progressSection}
              style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}
            >
              <div
                className={styles.progressBar}
                style={{
                  width: 220,
                  height: 8,
                  borderRadius: 9999,
                  background: 'rgba(0,0,0,0.08)',
                  overflow: 'hidden',
                  flexShrink: 0
                }}
              >
                <div
                  className={styles.progressFill}
                  style={{
                    width: `${completionPercentage}%`,
                    height: '100%',
                    background: '#0B1A33',
                    backgroundImage: 'none',
                    transition: 'width 200ms ease'
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
        <div className={styles.mainContent}>
          {/* Top Section: Process Information ONLY (full width) */}
          <div className={styles.processInfoCard}>
            <h2>Process Information</h2>

            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel}>
                Process Name <span className={styles.required}>*</span>
              </label>
              <input
                type="text"
                className={styles.textInput}
                value={processData.processName}
                onChange={(e) => handleBasicInfoChange('processName', e.target.value)}
                placeholder="Enter the name of the process to be mapped"
              />
            </div>

            <div className={styles.fieldRow}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Process Owner <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={processData.processOwner}
                  onChange={(e) => handleBasicInfoChange('processOwner', e.target.value)}
                  placeholder="Who owns this process?"
                />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Version</label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={processData.version}
                  onChange={(e) => handleBasicInfoChange('version', e.target.value)}
                  placeholder="Process version"
                />
              </div>
            </div>

            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel}>
                Process Purpose <span className={styles.required}>*</span>
              </label>
              <textarea
                className={styles.textareaInput}
                value={processData.processOverview.purpose}
                onChange={(e) => handleProcessOverviewChange('purpose', e.target.value)}
                placeholder="What is the purpose of this process?"
                rows={3}
              />
            </div>

            <div className={styles.fieldRow}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Trigger Event</label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={processData.processOverview.triggerEvent}
                  onChange={(e) => handleProcessOverviewChange('triggerEvent', e.target.value)}
                  placeholder="What starts this process?"
                />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>End Event</label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={processData.processOverview.endEvent}
                  onChange={(e) => handleProcessOverviewChange('endEvent', e.target.value)}
                  placeholder="What ends this process?"
                />
              </div>
            </div>
          </div>

          {/* Process Overview Section */}
          <div className={styles.analysisCard}>
            <h2>Process Overview</h2>
            <div className={styles.processOverviewSection}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Scope <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={processData.processOverview.scope}
                  onChange={(e) => handleProcessOverviewChange('scope', e.target.value)}
                  placeholder="Define what is included and excluded from this process"
                  rows={3}
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Boundaries</label>
                <textarea
                  className={styles.textareaInput}
                  value={processData.processOverview.boundaries}
                  onChange={(e) => handleProcessOverviewChange('boundaries', e.target.value)}
                  placeholder="Define the start and end boundaries of the process"
                  rows={2}
                />
              </div>

              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Customers</label>
                  <textarea
                    className={styles.textareaInput}
                    value={processData.processOverview.customers}
                    onChange={(e) => handleProcessOverviewChange('customers', e.target.value)}
                    placeholder="Who receives the output of this process?"
                    rows={2}
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Suppliers</label>
                  <textarea
                    className={styles.textareaInput}
                    value={processData.processOverview.suppliers}
                    onChange={(e) => handleProcessOverviewChange('suppliers', e.target.value)}
                    placeholder="Who provides inputs to this process?"
                    rows={2}
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Swimlanes Section */}
          <div className={styles.analysisCard}>
            <h2>Swimlanes (Responsible Parties)</h2>
            <div className={styles.swimlanesSection}>
              <div className={styles.sectionHeader}>
                <p className={styles.sectionDescription}>
                  Define the roles, departments, or systems involved in this process. Each swimlane represents a different actor.
                </p>
                <button className={styles.addBtn} onClick={addSwimlane}>
                  <i className="fas fa-plus"></i> Add Swimlane
                </button>
              </div>

              <div className={styles.swimlanesGrid}>
                {processData.swimlanes.map((swimlane) => (
                  <div key={swimlane.id} className={styles.swimlaneCard}>
                    <div className={styles.swimlaneHeader}>
                      <input
                        type="text"
                        className={styles.swimlaneNameInput}
                        value={swimlane.name}
                        onChange={(e) => handleSwimlaneChange(swimlane.id, 'name', e.target.value)}
                        placeholder="Swimlane name"
                      />
                      <select
                        className={styles.swimlaneTypeSelect}
                        value={swimlane.type}
                        onChange={(e) => handleSwimlaneChange(swimlane.id, 'type', e.target.value)}
                      >
                        <option value="person">Person</option>
                        <option value="department">Department</option>
                        <option value="system">System</option>
                      </select>
                      <button
                        className={styles.removeBtn}
                        onClick={() => removeSwimlane(swimlane.id)}
                      >
                        <i className="fas fa-times"></i>
                      </button>
                    </div>
                    <textarea
                      className={styles.swimlaneDescription}
                      value={swimlane.description}
                      onChange={(e) => handleSwimlaneChange(swimlane.id, 'description', e.target.value)}
                      placeholder="Description of this swimlane"
                      rows={2}
                    />
                    <textarea
                      className={styles.swimlaneResponsibilities}
                      value={swimlane.responsibilities}
                      onChange={(e) => handleSwimlaneChange(swimlane.id, 'responsibilities', e.target.value)}
                      placeholder="Key responsibilities in this process"
                      rows={2}
                    />
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Process Steps Section */}
          <div className={styles.analysisCard}>
            <h2>Process Steps</h2>
            <div className={styles.processStepsSection}>
              <div className={styles.sectionHeader}>
                <p className={styles.sectionDescription}>
                  Document each step in the process from start to finish. Include activities, decisions, delays, and inspections.
                </p>
                <button className={styles.addBtn} onClick={addProcessStep}>
                  <i className="fas fa-plus"></i> Add Step
                </button>
              </div>

              <div className={styles.processStepsTable}>
                <table className={styles.dataTable}>
                  <thead>
                    <tr>
                      <th>Step #</th>
                      <th>Step Name</th>
                      <th>Type</th>
                      <th>Responsible</th>
                      <th>Duration</th>
                      <th>Value Added</th>
                      <th>Description</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {processData.processSteps.map((step) => (
                      <tr key={step.id}>
                        <td>
                          <input
                            type="number"
                            className={styles.tableInput}
                            value={step.stepNumber}
                            onChange={(e) => handleProcessStepChange(step.id, 'stepNumber', e.target.value)}
                            style={{ width: '60px' }}
                          />
                        </td>
                        <td>
                          <input
                            type="text"
                            className={styles.tableInput}
                            value={step.stepName}
                            onChange={(e) => handleProcessStepChange(step.id, 'stepName', e.target.value)}
                            placeholder="Step name"
                          />
                        </td>
                        <td>
                          <select
                            className={styles.tableSelect}
                            value={step.type}
                            onChange={(e) => handleProcessStepChange(step.id, 'type', e.target.value)}
                          >
                            <option value="activity">Activity</option>
                            <option value="decision">Decision</option>
                            <option value="delay">Delay</option>
                            <option value="inspection">Inspection</option>
                          </select>
                        </td>
                        <td>
                          <input
                            type="text"
                            className={styles.tableInput}
                            value={step.responsible}
                            onChange={(e) => handleProcessStepChange(step.id, 'responsible', e.target.value)}
                            placeholder="Who"
                          />
                        </td>
                        <td>
                          <input
                            type="text"
                            className={styles.tableInput}
                            value={step.duration}
                            onChange={(e) => handleProcessStepChange(step.id, 'duration', e.target.value)}
                            placeholder="Time"
                          />
                        </td>
                        <td>
                          <select
                            className={styles.tableSelect}
                            value={step.valueAdded}
                            onChange={(e) => handleProcessStepChange(step.id, 'valueAdded', e.target.value)}
                          >
                            <option value="yes">Value Added</option>
                            <option value="business">Business Value</option>
                            <option value="no">Non-Value Added</option>
                          </select>
                        </td>
                        <td>
                          <input
                            type="text"
                            className={styles.tableInput}
                            value={step.description}
                            onChange={(e) => handleProcessStepChange(step.id, 'description', e.target.value)}
                            placeholder="Description"
                          />
                        </td>
                        <td>
                          <button
                            className={styles.removeBtn}
                            onClick={() => removeProcessStep(step.id)}
                          >
                            <i className="fas fa-times"></i>
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          {/* Decision Points Section */}
          <div className={styles.analysisCard}>
            <h2>Decision Points</h2>
            <div className={styles.decisionPointsSection}>
              <div className={styles.sectionHeader}>
                <p className={styles.sectionDescription}>
                  Document decision points where the process branches based on specific criteria.
                </p>
                <button className={styles.addBtn} onClick={addDecisionPoint}>
                  <i className="fas fa-plus"></i> Add Decision Point
                </button>
              </div>

              <div className={styles.decisionPointsTable}>
                <table className={styles.dataTable}>
                  <thead>
                    <tr>
                      <th>Step #</th>
                      <th>Decision Question</th>
                      <th>Criteria</th>
                      <th>Yes Path</th>
                      <th>No Path</th>
                      <th>Responsible</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {processData.decisionPoints.map((decision) => (
                      <tr key={decision.id}>
                        <td>
                          <input
                            type="text"
                            className={styles.tableInput}
                            value={decision.stepNumber}
                            onChange={(e) => handleDecisionPointChange(decision.id, 'stepNumber', e.target.value)}
                            placeholder="Step"
                          />
                        </td>
                        <td>
                          <input
                            type="text"
                            className={styles.tableInput}
                            value={decision.question}
                            onChange={(e) => handleDecisionPointChange(decision.id, 'question', e.target.value)}
                            placeholder="Decision question"
                          />
                        </td>
                        <td>
                          <input
                            type="text"
                            className={styles.tableInput}
                            value={decision.criteria}
                            onChange={(e) => handleDecisionPointChange(decision.id, 'criteria', e.target.value)}
                            placeholder="Decision criteria"
                          />
                        </td>
                        <td>
                          <input
                            type="text"
                            className={styles.tableInput}
                            value={decision.yesPath}
                            onChange={(e) => handleDecisionPointChange(decision.id, 'yesPath', e.target.value)}
                            placeholder="If yes, go to..."
                          />
                        </td>
                        <td>
                          <input
                            type="text"
                            className={styles.tableInput}
                            value={decision.noPath}
                            onChange={(e) => handleDecisionPointChange(decision.id, 'noPath', e.target.value)}
                            placeholder="If no, go to..."
                          />
                        </td>
                        <td>
                          <input
                            type="text"
                            className={styles.tableInput}
                            value={decision.responsible}
                            onChange={(e) => handleDecisionPointChange(decision.id, 'responsible', e.target.value)}
                            placeholder="Decision maker"
                          />
                        </td>
                        <td>
                          <button
                            className={styles.removeBtn}
                            onClick={() => removeDecisionPoint(decision.id)}
                          >
                            <i className="fas fa-times"></i>
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          {/* Handoffs Section */}
          <div className={styles.analysisCard}>
            <h2>Handoffs</h2>
            <div className={styles.handoffsSection}>
              <div className={styles.sectionHeader}>
                <p className={styles.sectionDescription}>
                  Document handoffs between people, departments, or systems. These are often sources of delays and errors.
                </p>
                <button className={styles.addBtn} onClick={addHandoff}>
                  <i className="fas fa-plus"></i> Add Handoff
                </button>
              </div>

              <div className={styles.handoffsTable}>
                <table className={styles.dataTable}>
                  <thead>
                    <tr>
                      <th>From Step</th>
                      <th>To Step</th>
                      <th>From Role</th>
                      <th>To Role</th>
                      <th>What's Transferred</th>
                      <th>Method</th>
                      <th>Duration</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {processData.handoffs.map((handoff) => (
                      <tr key={handoff.id}>
                        <td>
                          <input
                            type="text"
                            className={styles.tableInput}
                            value={handoff.fromStep}
                            onChange={(e) => handleHandoffChange(handoff.id, 'fromStep', e.target.value)}
                            placeholder="From step"
                          />
                        </td>
                        <td>
                          <input
                            type="text"
                            className={styles.tableInput}
                            value={handoff.toStep}
                            onChange={(e) => handleHandoffChange(handoff.id, 'toStep', e.target.value)}
                            placeholder="To step"
                          />
                        </td>
                        <td>
                          <input
                            type="text"
                            className={styles.tableInput}
                            value={handoff.fromRole}
                            onChange={(e) => handleHandoffChange(handoff.id, 'fromRole', e.target.value)}
                            placeholder="From role"
                          />
                        </td>
                        <td>
                          <input
                            type="text"
                            className={styles.tableInput}
                            value={handoff.toRole}
                            onChange={(e) => handleHandoffChange(handoff.id, 'toRole', e.target.value)}
                            placeholder="To role"
                          />
                        </td>
                        <td>
                          <input
                            type="text"
                            className={styles.tableInput}
                            value={handoff.whatTransferred}
                            onChange={(e) => handleHandoffChange(handoff.id, 'whatTransferred', e.target.value)}
                            placeholder="What's transferred"
                          />
                        </td>
                        <td>
                          <input
                            type="text"
                            className={styles.tableInput}
                            value={handoff.method}
                            onChange={(e) => handleHandoffChange(handoff.id, 'method', e.target.value)}
                            placeholder="How"
                          />
                        </td>
                        <td>
                          <input
                            type="text"
                            className={styles.tableInput}
                            value={handoff.duration}
                            onChange={(e) => handleHandoffChange(handoff.id, 'duration', e.target.value)}
                            placeholder="Time"
                          />
                        </td>
                        <td>
                          <button
                            className={styles.removeBtn}
                            onClick={() => removeHandoff(handoff.id)}
                          >
                            <i className="fas fa-times"></i>
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          {/* Process Metrics Section */}
          <div className={styles.analysisCard}>
            <h2>Process Metrics</h2>
            <div className={styles.processMetricsSection}>
              <div className={styles.timeMetrics}>
                <h3>Time Metrics</h3>
                <div className={styles.timeMetricsGrid}>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Cycle Time</label>
                    <input
                      type="text"
                      className={styles.textInput}
                      value={processData.processMetrics.cycleTime}
                      onChange={(e) => handleProcessMetricsChange('cycleTime', e.target.value)}
                      placeholder="Total time from start to finish"
                    />
                  </div>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Lead Time</label>
                    <input
                      type="text"
                      className={styles.textInput}
                      value={processData.processMetrics.leadTime}
                      onChange={(e) => handleProcessMetricsChange('leadTime', e.target.value)}
                      placeholder="Time including waiting"
                    />
                  </div>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Processing Time</label>
                    <input
                      type="text"
                      className={styles.textInput}
                      value={processData.processMetrics.processingTime}
                      onChange={(e) => handleProcessMetricsChange('processingTime', e.target.value)}
                      placeholder="Actual work time"
                    />
                  </div>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Wait Time</label>
                    <input
                      type="text"
                      className={styles.textInput}
                      value={processData.processMetrics.waitTime}
                      onChange={(e) => handleProcessMetricsChange('waitTime', e.target.value)}
                      placeholder="Non-value added time"
                    />
                  </div>
                </div>
              </div>

              <div className={styles.qualityMetrics}>
                <div className={styles.sectionHeader}>
                  <h3>Quality Metrics</h3>
                  <button className={styles.addBtn} onClick={addQualityMetric}>
                    <i className="fas fa-plus"></i> Add Metric
                  </button>
                </div>

                <div className={styles.qualityMetricsTable}>
                  <table className={styles.dataTable}>
                    <thead>
                      <tr>
                        <th>Metric</th>
                        <th>Target</th>
                        <th>Current</th>
                        <th>Measurement Method</th>
                        <th>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {processData.processMetrics.qualityMetrics.map((metric) => (
                        <tr key={metric.id}>
                          <td>
                            <input
                              type="text"
                              className={styles.tableInput}
                              value={metric.metric}
                              onChange={(e) => handleQualityMetricChange(metric.id, 'metric', e.target.value)}
                              placeholder="Quality metric"
                            />
                          </td>
                          <td>
                            <input
                              type="text"
                              className={styles.tableInput}
                              value={metric.target}
                              onChange={(e) => handleQualityMetricChange(metric.id, 'target', e.target.value)}
                              placeholder="Target"
                            />
                          </td>
                          <td>
                            <input
                              type="text"
                              className={styles.tableInput}
                              value={metric.current}
                              onChange={(e) => handleQualityMetricChange(metric.id, 'current', e.target.value)}
                              placeholder="Current"
                            />
                          </td>
                          <td>
                            <input
                              type="text"
                              className={styles.tableInput}
                              value={metric.measurement}
                              onChange={(e) => handleQualityMetricChange(metric.id, 'measurement', e.target.value)}
                              placeholder="How measured"
                            />
                          </td>
                          <td>
                            <button
                              className={styles.removeBtn}
                              onClick={() => removeQualityMetric(metric.id)}
                            >
                              <i className="fas fa-times"></i>
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          </div>

          {/* Risks & Issues Section */}
          <div className={styles.analysisCard}>
            <h2>Risks & Issues</h2>
            <div className={styles.risksSection}>
              <div className={styles.sectionHeader}>
                <p className={styles.sectionDescription}>
                  Identify risks and potential issues in the process that could impact quality, timing, or cost.
                </p>
                <button className={styles.addBtn} onClick={addRisk}>
                  <i className="fas fa-plus"></i> Add Risk
                </button>
              </div>

              <div className={styles.risksTable}>
                <table className={styles.dataTable}>
                  <thead>
                    <tr>
                      <th>Step</th>
                      <th>Risk/Issue</th>
                      <th>Impact</th>
                      <th>Probability</th>
                      <th>Mitigation</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {processData.risksIssues.risks.map((risk) => (
                      <tr key={risk.id}>
                        <td>
                          <input
                            type="text"
                            className={styles.tableInput}
                            value={risk.step}
                            onChange={(e) => handleRiskChange(risk.id, 'step', e.target.value)}
                            placeholder="Step"
                          />
                        </td>
                        <td>
                          <input
                            type="text"
                            className={styles.tableInput}
                            value={risk.risk}
                            onChange={(e) => handleRiskChange(risk.id, 'risk', e.target.value)}
                            placeholder="Risk description"
                          />
                        </td>
                        <td>
                          <select
                            className={styles.tableSelect}
                            value={risk.impact}
                            onChange={(e) => handleRiskChange(risk.id, 'impact', e.target.value)}
                          >
                            <option value="low">Low</option>
                            <option value="medium">Medium</option>
                            <option value="high">High</option>
                          </select>
                        </td>
                        <td>
                          <select
                            className={styles.tableSelect}
                            value={risk.probability}
                            onChange={(e) => handleRiskChange(risk.id, 'probability', e.target.value)}
                          >
                            <option value="low">Low</option>
                            <option value="medium">Medium</option>
                            <option value="high">High</option>
                          </select>
                        </td>
                        <td>
                          <input
                            type="text"
                            className={styles.tableInput}
                            value={risk.mitigation}
                            onChange={(e) => handleRiskChange(risk.id, 'mitigation', e.target.value)}
                            placeholder="Mitigation strategy"
                          />
                        </td>
                        <td>
                          <button
                            className={styles.removeBtn}
                            onClick={() => removeRisk(risk.id)}
                          >
                            <i className="fas fa-times"></i>
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          {/* Improvement Opportunities Section */}
          <div className={styles.analysisCard}>
            <h2>Improvement Opportunities</h2>
            <div className={styles.improvementsSection}>
              <div className={styles.wasteIdentification}>
                <div className={styles.sectionHeader}>
                  <h3>Waste Identification (TIMWOODS)</h3>
                  <button className={styles.addBtn} onClick={addWaste}>
                    <i className="fas fa-plus"></i> Add Waste
                  </button>
                </div>

                <div className={styles.wasteTable}>
                  <table className={styles.dataTable}>
                    <thead>
                      <tr>
                        <th>Step</th>
                        <th>Waste Type</th>
                        <th>Description</th>
                        <th>Impact</th>
                        <th>Proposed Solution</th>
                        <th>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {processData.improvements.wasteIdentified.map((waste) => (
                        <tr key={waste.id}>
                          <td>
                            <input
                              type="text"
                              className={styles.tableInput}
                              value={waste.step}
                              onChange={(e) => handleWasteChange(waste.id, 'step', e.target.value)}
                              placeholder="Step"
                            />
                          </td>
                          <td>
                            <select
                              className={styles.tableSelect}
                              value={waste.wasteType}
                              onChange={(e) => handleWasteChange(waste.id, 'wasteType', e.target.value)}
                            >
                              <option value="">Select waste type</option>
                              <option value="transport">Transport</option>
                              <option value="inventory">Inventory</option>
                              <option value="motion">Motion</option>
                              <option value="waiting">Waiting</option>
                              <option value="overproduction">Overproduction</option>
                              <option value="overprocessing">Over-processing</option>
                              <option value="defects">Defects</option>
                              <option value="skills">Skills (Unused Talent)</option>
                            </select>
                          </td>
                          <td>
                            <input
                              type="text"
                              className={styles.tableInput}
                              value={waste.description}
                              onChange={(e) => handleWasteChange(waste.id, 'description', e.target.value)}
                              placeholder="Waste description"
                            />
                          </td>
                          <td>
                            <input
                              type="text"
                              className={styles.tableInput}
                              value={waste.impact}
                              onChange={(e) => handleWasteChange(waste.id, 'impact', e.target.value)}
                              placeholder="Impact"
                            />
                          </td>
                          <td>
                            <input
                              type="text"
                              className={styles.tableInput}
                              value={waste.solution}
                              onChange={(e) => handleWasteChange(waste.id, 'solution', e.target.value)}
                              placeholder="Proposed solution"
                            />
                          </td>
                          <td>
                            <button
                              className={styles.removeBtn}
                              onClick={() => removeWaste(waste.id)}
                            >
                              <i className="fas fa-times"></i>
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className={styles.improvementIdeas}>
                <div className={styles.sectionHeader}>
                  <h3>Improvement Ideas</h3>
                  <button className={styles.addBtn} onClick={addImprovementIdea}>
                    <i className="fas fa-plus"></i> Add Idea
                  </button>
                </div>

                <div className={styles.improvementIdeasTable}>
                  <table className={styles.dataTable}>
                    <thead>
                      <tr>
                        <th>Area</th>
                        <th>Improvement Description</th>
                        <th>Benefit</th>
                        <th>Effort</th>
                        <th>Impact</th>
                        <th>Priority</th>
                        <th>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {processData.improvements.improvementIdeas.map((idea) => (
                        <tr key={idea.id}>
                          <td>
                            <input
                              type="text"
                              className={styles.tableInput}
                              value={idea.area}
                              onChange={(e) => handleImprovementIdeaChange(idea.id, 'area', e.target.value)}
                              placeholder="Area"
                            />
                          </td>
                          <td>
                            <input
                              type="text"
                              className={styles.tableInput}
                              value={idea.description}
                              onChange={(e) => handleImprovementIdeaChange(idea.id, 'description', e.target.value)}
                              placeholder="Improvement description"
                            />
                          </td>
                          <td>
                            <input
                              type="text"
                              className={styles.tableInput}
                              value={idea.benefit}
                              onChange={(e) => handleImprovementIdeaChange(idea.id, 'benefit', e.target.value)}
                              placeholder="Expected benefit"
                            />
                          </td>
                          <td>
                            <select
                              className={styles.tableSelect}
                              value={idea.effort}
                              onChange={(e) => handleImprovementIdeaChange(idea.id, 'effort', e.target.value)}
                            >
                              <option value="low">Low</option>
                              <option value="medium">Medium</option>
                              <option value="high">High</option>
                            </select>
                          </td>
                          <td>
                            <select
                              className={styles.tableSelect}
                              value={idea.impact}
                              onChange={(e) => handleImprovementIdeaChange(idea.id, 'impact', e.target.value)}
                            >
                              <option value="low">Low</option>
                              <option value="medium">Medium</option>
                              <option value="high">High</option>
                            </select>
                          </td>
                          <td>
                            <select
                              className={styles.tableSelect}
                              value={idea.priority}
                              onChange={(e) => handleImprovementIdeaChange(idea.id, 'priority', e.target.value)}
                            >
                              <option value="low">Low</option>
                              <option value="medium">Medium</option>
                              <option value="high">High</option>
                            </select>
                          </td>
                          <td>
                            <button
                              className={styles.removeBtn}
                              onClick={() => removeImprovementIdea(idea.id)}
                            >
                              <i className="fas fa-times"></i>
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>      
    </ResourcePageWrapper>
  );
};

export default ProcessMap;
