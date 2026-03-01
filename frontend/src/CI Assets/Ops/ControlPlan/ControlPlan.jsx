// src/pages/ControlPlan.jsx
import React, { useState, useEffect } from 'react';
import styles from './ControlPlan.module.css';
import { useAdminSettings } from '../context/AdminContext';
import ResourcePageWrapper from '../../All/components/ResourcePageWrapper';

const ControlPlan = () => {
  const { adminSettings } = useAdminSettings();

  // why: keep original tool data & behavior intact
  const [controlData, setControlData] = useState({
    projectName: '',
    processName: '',
    controlPlanOwner: '',
    dateCreated: new Date().toISOString().split('T')[0],
    lastUpdated: new Date().toISOString().split('T')[0],
    version: '1.0',
    processOverview: {
      processDescription: '',
      processScope: '',
      keyOutputs: '',
      customers: '',
      processFlow: '',
      criticalSteps: '',
      processOwner: '',
      teamMembers: ''
    },
    controlCharacteristics: [
      {
        id: 1,
        characteristic: '',
        specification: '',
        measurementMethod: '',
        sampleSize: '',
        frequency: '',
        responsiblePerson: '',
        controlMethod: 'spc',
        reactionPlan: '',
        priority: 'medium'
      }
    ],
    controlMethods: {
      statisticalProcessControl: {
        enabled: false,
        controlCharts: [],
        controlLimits: '',
        samplingPlan: '',
        dataCollection: '',
        analysisFrequency: ''
      },
      visualControls: {
        enabled: false,
        visualAids: [],
        standardsDisplayed: '',
        errorProofing: '',
        workInstructions: ''
      },
      proceduralControls: {
        enabled: false,
        standardOperatingProcedures: [],
        checkSheets: [],
        auditSchedule: '',
        trainingRequirements: ''
      },
      automatedControls: {
        enabled: false,
        automatedSystems: [],
        alarmSettings: '',
        dataLogging: '',
        systemMaintenance: ''
      }
    },
    monitoringPlan: {
      keyMetrics: [],
      reportingSchedule: '',
      reviewMeetings: '',
      escalationProcedures: '',
      performanceDashboard: '',
      trendAnalysis: ''
    },
    responsePlans: [
      {
        id: 1,
        trigger: '',
        condition: '',
        immediateAction: '',
        investigation: '',
        correctionAction: '',
        preventiveAction: '',
        responsible: '',
        timeframe: '',
        verification: ''
      }
    ],
    trainingCompetency: {
      trainingRequirements: [],
      competencyMatrix: [],
      certificationNeeds: '',
      refresherTraining: '',
      trainingRecords: '',
      skillAssessment: ''
    },
    documentation: {
      controlDocuments: [],
      recordKeeping: '',
      documentControl: '',
      archivePolicy: '',
      accessRights: '',
      backupProcedures: ''
    },
    reviewImprovement: {
      reviewSchedule: '',
      reviewCriteria: '',
      improvementOpportunities: '',
      changeControl: '',
      lessonsLearned: '',
      bestPractices: ''
    },
    status: {
      implementationStatus: 'draft',
      approvalDate: '',
      approvedBy: '',
      implementationDate: '',
      nextReviewDate: '',
      effectiveness: '',
      issues: '',
      improvements: ''
    }
  });

  const [completionPercentage, setCompletionPercentage] = useState(0);

  // Completion %
  useEffect(() => {
    let totalFields = 0;
    let completedFields = 0;

    // Basic info
    totalFields += 3;
    if (controlData.projectName) completedFields++;
    if (controlData.processName) completedFields++;
    if (controlData.controlPlanOwner) completedFields++;

    // Process overview
    totalFields += 4;
    if (controlData.processOverview.processDescription) completedFields++;
    if (controlData.processOverview.processScope) completedFields++;
    if (controlData.processOverview.keyOutputs) completedFields++;
    if (controlData.processOverview.processOwner) completedFields++;

    // Control characteristics
    totalFields += 1;
    const hasCompleteCharacteristic = controlData.controlCharacteristics.some(
      (char) =>
        char.characteristic &&
        char.specification &&
        char.measurementMethod &&
        char.responsiblePerson
    );
    if (hasCompleteCharacteristic) completedFields++;

    // Control methods
    totalFields += 1;
    const hasEnabledMethod = Object.values(controlData.controlMethods).some(
      (m) => m.enabled
    );
    if (hasEnabledMethod) completedFields++;

    // Monitoring plan
    totalFields += 2;
    if (controlData.monitoringPlan.keyMetrics.length > 0) completedFields++;
    if (controlData.monitoringPlan.reportingSchedule) completedFields++;

    // Response plans
    totalFields += 1;
    const hasCompleteResponse = controlData.responsePlans.some(
      (p) => p.trigger && p.immediateAction && p.responsible
    );
    if (hasCompleteResponse) completedFields++;

    // Training
    totalFields += 1;
    if (controlData.trainingCompetency.trainingRequirements.length > 0)
      completedFields++;

    // Documentation
    totalFields += 1;
    if (controlData.documentation.recordKeeping) completedFields++;

    const percentage =
      totalFields > 0 ? Math.round((completedFields / totalFields) * 100) : 0;
    setCompletionPercentage(percentage);
  }, [controlData]);

  // Handlers
  const handleBasicInfoChange = (field, value) =>
    setControlData((prev) => ({
      ...prev,
      [field]: value,
      lastUpdated: new Date().toISOString().split('T')[0]
    }));

  const handleOverviewChange = (field, value) =>
    setControlData((prev) => ({
      ...prev,
      processOverview: { ...prev.processOverview, [field]: value },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));

  const handleCharacteristicChange = (charId, field, value) =>
    setControlData((prev) => ({
      ...prev,
      controlCharacteristics: prev.controlCharacteristics.map((char) =>
        char.id === charId ? { ...char, [field]: value } : char
      ),
      lastUpdated: new Date().toISOString().split('T')[0]
    }));

  const handleControlMethodChange = (method, field, value) =>
    setControlData((prev) => ({
      ...prev,
      controlMethods: {
        ...prev.controlMethods,
        [method]: { ...prev.controlMethods[method], [field]: value }
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));

  const handleMonitoringChange = (field, value) =>
    setControlData((prev) => ({
      ...prev,
      monitoringPlan: { ...prev.monitoringPlan, [field]: value },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));

  const handleResponsePlanChange = (planId, field, value) =>
    setControlData((prev) => ({
      ...prev,
      responsePlans: prev.responsePlans.map((p) =>
        p.id === planId ? { ...p, [field]: value } : p
      ),
      lastUpdated: new Date().toISOString().split('T')[0]
    }));

  const handleTrainingChange = (field, value) =>
    setControlData((prev) => ({
      ...prev,
      trainingCompetency: { ...prev.trainingCompetency, [field]: value },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));

  const handleDocumentationChange = (field, value) =>
    setControlData((prev) => ({
      ...prev,
      documentation: { ...prev.documentation, [field]: value },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));

  const handleStatusChange = (field, value) =>
    setControlData((prev) => ({
      ...prev,
      status: { ...prev.status, [field]: value },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));

  const addCharacteristic = () => {
    const newCharacteristic = {
      id: Date.now(),
      characteristic: '',
      specification: '',
      measurementMethod: '',
      sampleSize: '',
      frequency: '',
      responsiblePerson: '',
      controlMethod: 'spc',
      reactionPlan: '',
      priority: 'medium'
    };
    setControlData((prev) => ({
      ...prev,
      controlCharacteristics: [...prev.controlCharacteristics, newCharacteristic],
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const removeCharacteristic = (charId) => {
    if (controlData.controlCharacteristics.length <= 1) return;
    setControlData((prev) => ({
      ...prev,
      controlCharacteristics: prev.controlCharacteristics.filter(
        (c) => c.id !== charId
      ),
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const addResponsePlan = () => {
    const newPlan = {
      id: Date.now(),
      trigger: '',
      condition: '',
      immediateAction: '',
      investigation: '',
      correctionAction: '',
      preventiveAction: '',
      responsible: '',
      timeframe: '',
      verification: ''
    };
    setControlData((prev) => ({
      ...prev,
      responsePlans: [...prev.responsePlans, newPlan],
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const removeResponsePlan = (planId) => {
    if (controlData.responsePlans.length <= 1) return;
    setControlData((prev) => ({
      ...prev,
      responsePlans: prev.responsePlans.filter((p) => p.id !== planId),
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const addMetric = () => {
    const newMetric = {
      id: Date.now(),
      name: '',
      target: '',
      measurement: '',
      frequency: '',
      responsible: ''
    };
    setControlData((prev) => ({
      ...prev,
      monitoringPlan: {
        ...prev.monitoringPlan,
        keyMetrics: [...prev.monitoringPlan.keyMetrics, newMetric]
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const removeMetric = (metricId) =>
    setControlData((prev) => ({
      ...prev,
      monitoringPlan: {
        ...prev.monitoringPlan,
        keyMetrics: prev.monitoringPlan.keyMetrics.filter(
          (m) => m.id !== metricId
        )
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));

  const handleMetricChange = (metricId, field, value) =>
    setControlData((prev) => ({
      ...prev,
      monitoringPlan: {
        ...prev.monitoringPlan,
        keyMetrics: prev.monitoringPlan.keyMetrics.map((m) =>
          m.id === metricId ? { ...m, [field]: value } : m
        )
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));

  const handleSave = () => {
    console.log('Saving Control Plan draft:', controlData); // why: integrate with persistence
  };

  const handleExport = () => {
    console.log('Exporting Control Plan to PDF:', controlData); // why: hook into exporter
  };

  return (
    <ResourcePageWrapper
      pageName="Control Plan"
      toolName="Control Plan"
      adminSettings={adminSettings}
    >
      <div className={styles.rcaContainer}>
        {/* Header */}
        <div className={styles.header}>
          <div className={styles.headerContent}>
            <h1>Control Plan</h1>
            <div className={styles.progressSection}>
              <div className={styles.progressBar}>
                <div
                  className={styles.progressFill}
                  style={{ width: `${completionPercentage}%` }}
                />
              </div>
              <span className={styles.progressText}>
                {completionPercentage}% Complete
              </span>
            </div>
          </div>
          <div className={styles.headerActions}>
            <button className={styles.saveBtn} onClick={handleSave}>
              <i className="fas fa-save" /> Save Draft
            </button>
            <button className={styles.exportBtn} onClick={handleExport}>
              <i className="fas fa-download" /> Export PDF
            </button>
          </div>
        </div>

        {/* Main Content */}
        <div className={styles.mainContent}>
          {/* Process Information */}
          <div className={styles.processInfoCard}>
            <h2>Process Information</h2>
            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel}>
                Project Name <span className={styles.required}>*</span>
              </label>
              <input
                type="text"
                className={styles.textInput}
                value={controlData.projectName}
                onChange={(e) =>
                  handleBasicInfoChange('projectName', e.target.value)
                }
                placeholder="Enter the project name"
              />
            </div>

            <div className={styles.fieldRow}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Process Name <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={controlData.processName}
                  onChange={(e) =>
                    handleBasicInfoChange('processName', e.target.value)
                  }
                  placeholder="Process to be controlled"
                />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Control Plan Owner <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={controlData.controlPlanOwner}
                  onChange={(e) =>
                    handleBasicInfoChange('controlPlanOwner', e.target.value)
                  }
                  placeholder="Who owns this control plan?"
                />
              </div>
            </div>

            <div className={styles.fieldRow}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Date Created</label>
                <input
                  type="date"
                  className={styles.textInput}
                  value={controlData.dateCreated}
                  onChange={(e) =>
                    handleBasicInfoChange('dateCreated', e.target.value)
                  }
                />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Version</label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={controlData.version}
                  onChange={(e) =>
                    handleBasicInfoChange('version', e.target.value)
                  }
                  placeholder="1.0"
                />
              </div>
            </div>
          </div>

          {/* Process Overview */}
          <div className={styles.analysisCard}>
            <div className={styles.sectionHeader}>
              <h2>Process Overview</h2>
            </div>
            <div className={styles.overviewGrid}>
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Process Description</label>
                  <textarea
                    className={styles.textareaInput}
                    value={controlData.processOverview.processDescription}
                    onChange={(e) =>
                      handleOverviewChange('processDescription', e.target.value)
                    }
                    placeholder="Describe the process to be controlled"
                    rows={3}
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Process Scope</label>
                  <textarea
                    className={styles.textareaInput}
                    value={controlData.processOverview.processScope}
                    onChange={(e) =>
                      handleOverviewChange('processScope', e.target.value)
                    }
                    placeholder="Define the boundaries of this process"
                    rows={3}
                  />
                </div>
              </div>
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Key Outputs</label>
                  <textarea
                    className={styles.textareaInput}
                    value={controlData.processOverview.keyOutputs}
                    onChange={(e) =>
                      handleOverviewChange('keyOutputs', e.target.value)
                    }
                    placeholder="What are the critical outputs of this process?"
                    rows={2}
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Customers</label>
                  <textarea
                    className={styles.textareaInput}
                    value={controlData.processOverview.customers}
                    onChange={(e) =>
                      handleOverviewChange('customers', e.target.value)
                    }
                    placeholder="Who receives the outputs?"
                    rows={2}
                  />
                </div>
              </div>
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Process Owner</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={controlData.processOverview.processOwner}
                    onChange={(e) =>
                      handleOverviewChange('processOwner', e.target.value)
                    }
                    placeholder="Who owns this process?"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Team Members</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={controlData.processOverview.teamMembers}
                    onChange={(e) =>
                      handleOverviewChange('teamMembers', e.target.value)
                    }
                    placeholder="Key team members involved"
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Control Characteristics */}
          <div className={styles.analysisCard}>
            <div className={styles.sectionHeader}>
              <h2>Control Characteristics</h2>
              <button className={styles.addBtn} onClick={addCharacteristic}>
                <i className="fas fa-plus" /> Add Characteristic
              </button>
            </div>
            <div className={styles.characteristicsGrid}>
              {controlData.controlCharacteristics.map((characteristic) => (
                <div key={characteristic.id} className={styles.characteristicCard}>
                  <div className={styles.characteristicHeader}>
                    <h3>Characteristic {characteristic.id}</h3>
                    <div className={styles.characteristicActions}>
                      <span
                        className={`${styles.priorityBadge} ${styles[characteristic.priority]}`}
                      >
                        {characteristic.priority}
                      </span>
                      <button
                        className={styles.removeBtn}
                        onClick={() => removeCharacteristic(characteristic.id)}
                        disabled={controlData.controlCharacteristics.length <= 1}
                      >
                        <i className="fas fa-times" />
                      </button>
                    </div>
                  </div>
                  <div className={styles.characteristicFields}>
                    <div className={styles.fieldRow}>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Characteristic</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={characteristic.characteristic}
                          onChange={(e) =>
                            handleCharacteristicChange(
                              characteristic.id,
                              'characteristic',
                              e.target.value
                            )
                          }
                          placeholder="What characteristic to control?"
                        />
                      </div>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Specification</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={characteristic.specification}
                          onChange={(e) =>
                            handleCharacteristicChange(
                              characteristic.id,
                              'specification',
                              e.target.value
                            )
                          }
                          placeholder="Target value or range"
                        />
                      </div>
                    </div>
                    <div className={styles.fieldRow}>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>
                          Measurement Method
                        </label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={characteristic.measurementMethod}
                          onChange={(e) =>
                            handleCharacteristicChange(
                              characteristic.id,
                              'measurementMethod',
                              e.target.value
                            )
                          }
                          placeholder="How to measure this characteristic"
                        />
                      </div>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Sample Size</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={characteristic.sampleSize}
                          onChange={(e) =>
                            handleCharacteristicChange(
                              characteristic.id,
                              'sampleSize',
                              e.target.value
                            )
                          }
                          placeholder="How many samples to take"
                        />
                      </div>
                    </div>
                    <div className={styles.fieldRow}>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Frequency</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={characteristic.frequency}
                          onChange={(e) =>
                            handleCharacteristicChange(
                              characteristic.id,
                              'frequency',
                              e.target.value
                            )
                          }
                          placeholder="How often to measure"
                        />
                      </div>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Responsible Person</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={characteristic.responsiblePerson}
                          onChange={(e) =>
                            handleCharacteristicChange(
                              characteristic.id,
                              'responsiblePerson',
                              e.target.value
                            )
                          }
                          placeholder="Who is responsible"
                        />
                      </div>
                    </div>
                    <div className={styles.fieldRow}>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Control Method</label>
                        <select
                          className={styles.selectInput}
                          value={characteristic.controlMethod}
                          onChange={(e) =>
                            handleCharacteristicChange(
                              characteristic.id,
                              'controlMethod',
                              e.target.value
                            )
                          }
                        >
                          <option value="spc">Statistical Process Control</option>
                          <option value="checklist">Checklist</option>
                          <option value="visual">Visual Control</option>
                          <option value="automated">Automated Control</option>
                        </select>
                      </div>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Priority</label>
                        <select
                          className={styles.selectInput}
                          value={characteristic.priority}
                          onChange={(e) =>
                            handleCharacteristicChange(
                              characteristic.id,
                              'priority',
                              e.target.value
                            )
                          }
                        >
                          <option value="low">Low</option>
                          <option value="medium">Medium</option>
                          <option value="high">High</option>
                          <option value="critical">Critical</option>
                        </select>
                      </div>
                    </div>
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Reaction Plan</label>
                      <textarea
                        className={styles.textareaInput}
                        value={characteristic.reactionPlan}
                        onChange={(e) =>
                          handleCharacteristicChange(
                            characteristic.id,
                            'reactionPlan',
                            e.target.value
                          )
                        }
                        placeholder="What to do when out of specification"
                        rows={2}
                      />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Control Methods */}
          <div className={styles.analysisCard}>
            <div className={styles.sectionHeader}>
              <h2>Control Methods</h2>
            </div>
            <div className={styles.methodsGrid}>
              {/* SPC */}
              <div className={styles.methodSection}>
                <div className={styles.methodHeader}>
                  <label className={styles.checkboxLabel}>
                    <input
                      type="checkbox"
                      checked={
                        controlData.controlMethods.statisticalProcessControl.enabled
                      }
                      onChange={(e) =>
                        handleControlMethodChange(
                          'statisticalProcessControl',
                          'enabled',
                          e.target.checked
                        )
                      }
                    />
                    <h3>Statistical Process Control (SPC)</h3>
                  </label>
                </div>
                {controlData.controlMethods.statisticalProcessControl.enabled && (
                  <div className={styles.methodFields}>
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Control Charts</label>
                      <textarea
                        className={styles.textareaInput}
                        value={controlData.controlMethods.statisticalProcessControl.controlCharts.join(
                          '\n'
                        )}
                        onChange={(e) =>
                          handleControlMethodChange(
                            'statisticalProcessControl',
                            'controlCharts',
                            e.target.value.split('\n').filter((x) => x.trim())
                          )
                        }
                        placeholder="List control charts to be used (one per line)"
                        rows={3}
                      />
                    </div>
                    <div className={styles.fieldRow}>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Control Limits</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={
                            controlData.controlMethods.statisticalProcessControl
                              .controlLimits
                          }
                          onChange={(e) =>
                            handleControlMethodChange(
                              'statisticalProcessControl',
                              'controlLimits',
                              e.target.value
                            )
                          }
                          placeholder="How control limits are calculated"
                        />
                      </div>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Sampling Plan</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={
                            controlData.controlMethods.statisticalProcessControl
                              .samplingPlan
                          }
                          onChange={(e) =>
                            handleControlMethodChange(
                              'statisticalProcessControl',
                              'samplingPlan',
                              e.target.value
                            )
                          }
                          placeholder="Subgroup size and frequency"
                        />
                      </div>
                    </div>
                  </div>
                )}
              </div>

              {/* Visual Controls */}
              <div className={styles.methodSection}>
                <div className={styles.methodHeader}>
                  <label className={styles.checkboxLabel}>
                    <input
                      type="checkbox"
                      checked={controlData.controlMethods.visualControls.enabled}
                      onChange={(e) =>
                        handleControlMethodChange(
                          'visualControls',
                          'enabled',
                          e.target.checked
                        )
                      }
                    />
                    <h3>Visual Controls</h3>
                  </label>
                </div>
                {controlData.controlMethods.visualControls.enabled && (
                  <div className={styles.methodFields}>
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Visual Aids</label>
                      <textarea
                        className={styles.textareaInput}
                        value={controlData.controlMethods.visualControls.visualAids.join(
                          '\n'
                        )}
                        onChange={(e) =>
                          handleControlMethodChange(
                            'visualControls',
                            'visualAids',
                            e.target.value.split('\n').filter((x) => x.trim())
                          )
                        }
                        placeholder="List visual aids to be used (one per line)"
                        rows={3}
                      />
                    </div>
                    <div className={styles.fieldRow}>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>
                          Standards Displayed
                        </label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={
                            controlData.controlMethods.visualControls
                              .standardsDisplayed
                          }
                          onChange={(e) =>
                            handleControlMethodChange(
                              'visualControls',
                              'standardsDisplayed',
                              e.target.value
                            )
                          }
                          placeholder="What standards are visually displayed"
                        />
                      </div>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Error Proofing</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={
                            controlData.controlMethods.visualControls.errorProofing
                          }
                          onChange={(e) =>
                            handleControlMethodChange(
                              'visualControls',
                              'errorProofing',
                              e.target.value
                            )
                          }
                          placeholder="Error proofing devices used"
                        />
                      </div>
                    </div>
                  </div>
                )}
              </div>

              {/* Procedural Controls */}
              <div className={styles.methodSection}>
                <div className={styles.methodHeader}>
                  <label className={styles.checkboxLabel}>
                    <input
                      type="checkbox"
                      checked={
                        controlData.controlMethods.proceduralControls.enabled
                      }
                      onChange={(e) =>
                        handleControlMethodChange(
                          'proceduralControls',
                          'enabled',
                          e.target.checked
                        )
                      }
                    />
                    <h3>Procedural Controls</h3>
                  </label>
                </div>
                {controlData.controlMethods.proceduralControls.enabled && (
                  <div className={styles.methodFields}>
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>
                        Standard Operating Procedures
                      </label>
                      <textarea
                        className={styles.textareaInput}
                        value={controlData.controlMethods.proceduralControls.standardOperatingProcedures.join(
                          '\n'
                        )}
                        onChange={(e) =>
                          handleControlMethodChange(
                            'proceduralControls',
                            'standardOperatingProcedures',
                            e.target.value.split('\n').filter((x) => x.trim())
                          )
                        }
                        placeholder="List SOPs required (one per line)"
                        rows={3}
                      />
                    </div>
                    <div className={styles.fieldRow}>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Audit Schedule</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={
                            controlData.controlMethods.proceduralControls
                              .auditSchedule
                          }
                          onChange={(e) =>
                            handleControlMethodChange(
                              'proceduralControls',
                              'auditSchedule',
                              e.target.value
                            )
                          }
                          placeholder="How often to audit procedures"
                        />
                      </div>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>
                          Training Requirements
                        </label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={
                            controlData.controlMethods.proceduralControls
                              .trainingRequirements
                          }
                          onChange={(e) =>
                            handleControlMethodChange(
                              'proceduralControls',
                              'trainingRequirements',
                              e.target.value
                            )
                          }
                          placeholder="Training needed for procedures"
                        />
                      </div>
                    </div>
                  </div>
                )}
              </div>

              {/* Automated Controls */}
              <div className={styles.methodSection}>
                <div className={styles.methodHeader}>
                  <label className={styles.checkboxLabel}>
                    <input
                      type="checkbox"
                      checked={
                        controlData.controlMethods.automatedControls.enabled
                      }
                      onChange={(e) =>
                        handleControlMethodChange(
                          'automatedControls',
                          'enabled',
                          e.target.checked
                        )
                      }
                    />
                    <h3>Automated Controls</h3>
                  </label>
                </div>
                {controlData.controlMethods.automatedControls.enabled && (
                  <div className={styles.methodFields}>
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>
                        Automated Systems
                      </label>
                      <textarea
                        className={styles.textareaInput}
                        value={controlData.controlMethods.automatedControls.automatedSystems.join(
                          '\n'
                        )}
                        onChange={(e) =>
                          handleControlMethodChange(
                            'automatedControls',
                            'automatedSystems',
                            e.target.value.split('\n').filter((x) => x.trim())
                          )
                        }
                        placeholder="List automated control systems (one per line)"
                        rows={3}
                      />
                    </div>
                    <div className={styles.fieldRow}>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Alarm Settings</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={
                            controlData.controlMethods.automatedControls
                              .alarmSettings
                          }
                          onChange={(e) =>
                            handleControlMethodChange(
                              'automatedControls',
                              'alarmSettings',
                              e.target.value
                            )
                          }
                          placeholder="Alarm configuration and thresholds"
                        />
                      </div>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Data Logging</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={
                            controlData.controlMethods.automatedControls
                              .dataLogging
                          }
                          onChange={(e) =>
                            handleControlMethodChange(
                              'automatedControls',
                              'dataLogging',
                              e.target.value
                            )
                          }
                          placeholder="What data is automatically logged"
                        />
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Monitoring Plan */}
          <div className={styles.analysisCard}>
            <div className={styles.sectionHeader}>
              <h2>Monitoring Plan</h2>
              <button className={styles.addBtn} onClick={addMetric}>
                <i className="fas fa-plus" /> Add Metric
              </button>
            </div>
            <div className={styles.metricsGrid}>
              {controlData.monitoringPlan.keyMetrics.map((metric) => (
                <div key={metric.id} className={styles.metricCard}>
                  <div className={styles.metricHeader}>
                    <h3>Metric {metric.id}</h3>
                    <button
                      className={styles.removeBtn}
                      onClick={() => removeMetric(metric.id)}
                    >
                      <i className="fas fa-times" />
                    </button>
                  </div>
                  <div className={styles.metricFields}>
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Metric Name</label>
                      <input
                        type="text"
                        className={styles.textInput}
                        value={metric.name}
                        onChange={(e) =>
                          handleMetricChange(metric.id, 'name', e.target.value)
                        }
                        placeholder="Name of the metric"
                      />
                    </div>
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Target</label>
                      <input
                        type="text"
                        className={styles.textInput}
                        value={metric.target}
                        onChange={(e) =>
                          handleMetricChange(metric.id, 'target', e.target.value)
                        }
                        placeholder="Target value or range"
                      />
                    </div>
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>
                        Measurement Method
                      </label>
                      <input
                        type="text"
                        className={styles.textInput}
                        value={metric.measurement}
                        onChange={(e) =>
                          handleMetricChange(
                            metric.id,
                            'measurement',
                            e.target.value
                          )
                        }
                        placeholder="How to measure this metric"
                      />
                    </div>
                    <div className={styles.fieldRow}>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Frequency</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={metric.frequency}
                          onChange={(e) =>
                            handleMetricChange(
                              metric.id,
                              'frequency',
                              e.target.value
                            )
                          }
                          placeholder="How often to measure"
                        />
                      </div>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Responsible</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={metric.responsible}
                          onChange={(e) =>
                            handleMetricChange(
                              metric.id,
                              'responsible',
                              e.target.value
                            )
                          }
                          placeholder="Who is responsible"
                        />
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>

            <div className={styles.monitoringDetailsSection}>
              <h3>Monitoring Details</h3>
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Reporting Schedule</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={controlData.monitoringPlan.reportingSchedule}
                    onChange={(e) =>
                      handleMonitoringChange('reportingSchedule', e.target.value)
                    }
                    placeholder="How often to report results"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Review Meetings</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={controlData.monitoringPlan.reviewMeetings}
                    onChange={(e) =>
                      handleMonitoringChange('reviewMeetings', e.target.value)
                    }
                    placeholder="Regular review meeting schedule"
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Response Plans */}
          <div className={styles.analysisCard}>
            <div className={styles.sectionHeader}>
              <h2>Response Plans</h2>
              <button className={styles.addBtn} onClick={addResponsePlan}>
                <i className="fas fa-plus" /> Add Response Plan
              </button>
            </div>
            <div className={styles.responseGrid}>
              {controlData.responsePlans.map((plan) => (
                <div key={plan.id} className={styles.responsePlanCard}>
                  <div className={styles.responsePlanHeader}>
                    <h3>Response Plan {plan.id}</h3>
                    <button
                      className={styles.removeBtn}
                      onClick={() => removeResponsePlan(plan.id)}
                      disabled={controlData.responsePlans.length <= 1}
                    >
                      <i className="fas fa-times" />
                    </button>
                  </div>
                  <div className={styles.responsePlanFields}>
                    <div className={styles.fieldRow}>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Trigger</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={plan.trigger}
                          onChange={(e) =>
                            handleResponsePlanChange(plan.id, 'trigger', e.target.value)
                          }
                          placeholder="What triggers this response?"
                        />
                      </div>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Condition</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={plan.condition}
                          onChange={(e) =>
                            handleResponsePlanChange(plan.id, 'condition', e.target.value)
                          }
                          placeholder="Specific condition or threshold"
                        />
                      </div>
                    </div>
                    <div className={styles.fieldRow}>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Immediate Action</label>
                        <textarea
                          className={styles.textareaInput}
                          value={plan.immediateAction}
                          onChange={(e) =>
                            handleResponsePlanChange(
                              plan.id,
                              'immediateAction',
                              e.target.value
                            )
                          }
                          placeholder="Immediate containment actions"
                          rows={2}
                        />
                      </div>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Investigation</label>
                        <textarea
                          className={styles.textareaInput}
                          value={plan.investigation}
                          onChange={(e) =>
                            handleResponsePlanChange(
                              plan.id,
                              'investigation',
                              e.target.value
                            )
                          }
                          placeholder="How to investigate the root cause"
                          rows={2}
                        />
                      </div>
                    </div>
                    <div className={styles.fieldRow}>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Responsible</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={plan.responsible}
                          onChange={(e) =>
                            handleResponsePlanChange(plan.id, 'responsible', e.target.value)
                          }
                          placeholder="Who is responsible for this response"
                        />
                      </div>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Timeframe</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={plan.timeframe}
                          onChange={(e) =>
                            handleResponsePlanChange(plan.id, 'timeframe', e.target.value)
                          }
                          placeholder="Response timeframe"
                        />
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Status */}
          <div className={styles.analysisCard}>
            <div className={styles.sectionHeader}>
              <h2>Control Plan Status</h2>
            </div>
            <div className={styles.statusGrid}>
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Implementation Status</label>
                  <select
                    className={styles.selectInput}
                    value={controlData.status.implementationStatus}
                    onChange={(e) =>
                      handleStatusChange('implementationStatus', e.target.value)
                    }
                  >
                    <option value="draft">Draft</option>
                    <option value="approved">Approved</option>
                    <option value="implemented">Implemented</option>
                    <option value="active">Active</option>
                    <option value="under-review">Under Review</option>
                  </select>
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Approved By</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={controlData.status.approvedBy}
                    onChange={(e) =>
                      handleStatusChange('approvedBy', e.target.value)
                    }
                    placeholder="Who approved this control plan"
                  />
                </div>
              </div>
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Implementation Date</label>
                  <input
                    type="date"
                    className={styles.textInput}
                    value={controlData.status.implementationDate}
                    onChange={(e) =>
                      handleStatusChange('implementationDate', e.target.value)
                    }
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Next Review Date</label>
                  <input
                    type="date"
                    className={styles.textInput}
                    value={controlData.status.nextReviewDate}
                    onChange={(e) =>
                      handleStatusChange('nextReviewDate', e.target.value)
                    }
                  />
                </div>
              </div>
            </div>
          </div>
        </div>
        {/* End Main Content */}
      </div>
    </ResourcePageWrapper>
  );
};

export default ControlPlan;
