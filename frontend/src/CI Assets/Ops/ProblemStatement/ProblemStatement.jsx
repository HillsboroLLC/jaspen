import React, { useState, useEffect } from 'react';
import { useAdminSettings } from '../context/AdminContext';
import ResourcePageWrapper from '../../All/components/ResourcePageWrapper';
import styles from './ProblemStatement.module.css';

const ProblemStatement = () => {
  const { adminSettings } = useAdminSettings();

  // Problem Statement structure
  const [problemData, setProblemData] = useState({
    // Basic Information
    statementTitle: '',
    author: '',
    dateCreated: new Date().toISOString().split('T')[0],
    lastUpdated: new Date().toISOString().split('T')[0],

    // Problem Definition
    problemDefinition: {
      problemDescription: '',
      problemType: '', // 'quality', 'cost', 'delivery', 'safety', 'morale', 'other'
      businessImpact: '',
      urgency: '', // 'low', 'medium', 'high', 'critical'
      scope: '',
      boundaries: ''
    },

    // Current State
    currentState: {
      whatIsHappening: '',
      whereIsItOccurring: '',
      whenDoesItOccur: '',
      whoIsAffected: '',
      howOftenDoesItOccur: '',
      magnitude: ''
    },

    // Quantification
    quantification: {
      metrics: [],
      baseline: '',
      target: '',
      gap: '',
      financialImpact: '',
      customerImpact: '',
      operationalImpact: ''
    },

    // Stakeholders
    stakeholders: {
      primaryStakeholders: [],
      secondaryStakeholders: [],
      processOwner: '',
      sponsor: '',
      teamMembers: []
    },

    // Context & Background
    context: {
      backgroundInformation: '',
      previousAttempts: '',
      constraints: '',
      assumptions: '',
      dependencies: ''
    },

    // Success Criteria
    successCriteria: {
      primaryObjectives: [],
      secondaryObjectives: [],
      successMetrics: [],
      timeline: '',
      resources: ''
    },

    // Validation
    validation: {
      dataSource: '',
      evidenceType: '', // 'quantitative', 'qualitative', 'mixed'
      validationMethod: '',
      confidence: '', // 'low', 'medium', 'high'
      reviewers: [],
      approvalStatus: 'draft' // 'draft', 'review', 'approved', 'rejected'
    }
  });

  const [completionPercentage, setCompletionPercentage] = useState(0);

  // Completion %
  useEffect(() => {
    const calculateCompletion = () => {
      let total = 0;
      let done = 0;

      total += 3;
      if (problemData.statementTitle) done++;
      if (problemData.author) done++;
      if (problemData.problemDefinition.problemDescription) done++;

      total += 3;
      if (problemData.problemDefinition.problemType) done++;
      if (problemData.problemDefinition.businessImpact) done++;
      if (problemData.problemDefinition.scope) done++;

      total += 3;
      if (problemData.currentState.whatIsHappening) done++;
      if (problemData.currentState.whereIsItOccurring) done++;
      if (problemData.currentState.whenDoesItOccur) done++;

      total += 2;
      if (problemData.quantification.baseline) done++;
      if (problemData.quantification.target) done++;

      total += 1;
      if (problemData.stakeholders.processOwner) done++;

      total += 1;
      if (problemData.successCriteria.primaryObjectives.length > 0) done++;

      setCompletionPercentage(total ? Math.round((done / total) * 100) : 0);
    };
    calculateCompletion();
  }, [problemData]);

  // Basic handlers
  const handleBasicInfoChange = (field, value) => {
    setProblemData(prev => ({
      ...prev,
      [field]: value,
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleProblemDefinitionChange = (field, value) => {
    setProblemData(prev => ({
      ...prev,
      problemDefinition: { ...prev.problemDefinition, [field]: value },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleCurrentStateChange = (field, value) => {
    setProblemData(prev => ({
      ...prev,
      currentState: { ...prev.currentState, [field]: value },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleQuantificationChange = (field, value) => {
    setProblemData(prev => ({
      ...prev,
      quantification: { ...prev.quantification, [field]: value },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleStakeholderChange = (field, value) => {
    setProblemData(prev => ({
      ...prev,
      stakeholders: { ...prev.stakeholders, [field]: value },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleContextChange = (field, value) => {
    setProblemData(prev => ({
      ...prev,
      context: { ...prev.context, [field]: value },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleSuccessCriteriaChange = (field, value) => {
    setProblemData(prev => ({
      ...prev,
      successCriteria: { ...prev.successCriteria, [field]: value },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleValidationChange = (field, value) => {
    setProblemData(prev => ({
      ...prev,
      validation: { ...prev.validation, [field]: value },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Metrics helpers
  const addMetric = () => {
    const m = { id: Date.now(), name: '', currentValue: '', targetValue: '', unit: '', frequency: 'daily' };
    setProblemData(prev => ({
      ...prev,
      quantification: { ...prev.quantification, metrics: [...prev.quantification.metrics, m] },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };
  const removeMetric = (id) => {
    setProblemData(prev => ({
      ...prev,
      quantification: { ...prev.quantification, metrics: prev.quantification.metrics.filter(x => x.id !== id) },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };
  const handleMetricChange = (id, field, value) => {
    setProblemData(prev => ({
      ...prev,
      quantification: {
        ...prev.quantification,
        metrics: prev.quantification.metrics.map(m => (m.id === id ? { ...m, [field]: value } : m))
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Stakeholder list helpers
  const addStakeholder = (type) => {
    const s = { id: Date.now(), name: '', role: '', department: '', influence: 'medium', interest: 'medium' };
    setProblemData(prev => ({
      ...prev,
      stakeholders: { ...prev.stakeholders, [type]: [...prev.stakeholders[type], s] },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };
  const removeStakeholder = (type, id) => {
    setProblemData(prev => ({
      ...prev,
      stakeholders: { ...prev.stakeholders, [type]: prev.stakeholders[type].filter(s => s.id !== id) },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };
  const handleStakeholderItemChange = (type, id, field, value) => {
    setProblemData(prev => ({
      ...prev,
      stakeholders: {
        ...prev.stakeholders,
        [type]: prev.stakeholders[type].map(s => (s.id === id ? { ...s, [field]: value } : s))
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Objectives helpers
  const addObjective = (type) => {
    const o = { id: Date.now(), objective: '', metric: '', target: '', timeline: '' };
    setProblemData(prev => ({
      ...prev,
      successCriteria: { ...prev.successCriteria, [type]: [...prev.successCriteria[type], o] },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };
  const removeObjective = (type, id) => {
    setProblemData(prev => ({
      ...prev,
      successCriteria: { ...prev.successCriteria, [type]: prev.successCriteria[type].filter(o => o.id !== id) },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };
  const handleObjectiveChange = (type, id, field, value) => {
    setProblemData(prev => ({
      ...prev,
      successCriteria: {
        ...prev.successCriteria,
        [type]: prev.successCriteria[type].map(o => (o.id === id ? { ...o, [field]: value } : o))
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Success metrics helpers
  const addSuccessMetric = () => {
    const m = { id: Date.now(), metric: '', baseline: '', target: '', measurement: '' };
    setProblemData(prev => ({
      ...prev,
      successCriteria: { ...prev.successCriteria, successMetrics: [...prev.successCriteria.successMetrics, m] },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };
  const removeSuccessMetric = (id) => {
    setProblemData(prev => ({
      ...prev,
      successCriteria: {
        ...prev.successCriteria,
        successMetrics: prev.successCriteria.successMetrics.filter(m => m.id !== id)
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };
  const handleSuccessMetricChange = (id, field, value) => {
    setProblemData(prev => ({
      ...prev,
      successCriteria: {
        ...prev.successCriteria,
        successMetrics: prev.successCriteria.successMetrics.map(m => (m.id === id ? { ...m, [field]: value } : m))
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Save / Export stubs
  const handleSave = () => console.log('Saving Problem Statement draft:', problemData);
  const handleExport = () => console.log('Exporting Problem Statement to PDF:', problemData);

  return (
    <ResourcePageWrapper
      pageName="Problem Statement"
      toolName="Problem Statement"
      adminSettings={adminSettings}
    >
      <div className={styles.rcaContainer}>
        {/* Header */}
        <div className={styles.header}>
          <div className={styles.headerContent}>
            <h1>Problem Statement</h1>
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
          {/* Full-width info card */}
          <div className={styles.processInfoCard}>
            <h2>Statement Information</h2>

            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel}>
                Problem Statement Title <span className={styles.required}>*</span>
              </label>
              <input
                type="text"
                className={styles.textInput}
                value={problemData.statementTitle}
                onChange={(e) => handleBasicInfoChange('statementTitle', e.target.value)}
                placeholder="Enter a descriptive title for your problem statement"
              />
            </div>

            <div className={styles.fieldRow}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Author <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={problemData.author}
                  onChange={(e) => handleBasicInfoChange('author', e.target.value)}
                  placeholder="Who is creating this problem statement?"
                />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Date Created</label>
                <input
                  type="date"
                  className={styles.textInput}
                  value={problemData.dateCreated}
                  onChange={(e) => handleBasicInfoChange('dateCreated', e.target.value)}
                />
              </div>
            </div>

            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel}>
                Problem Description <span className={styles.required}>*</span>
              </label>
              <textarea
                className={styles.textareaInput}
                value={problemData.problemDefinition.problemDescription}
                onChange={(e) => handleProblemDefinitionChange('problemDescription', e.target.value)}
                placeholder="Provide a clear, concise description of the problem"
                rows={3}
              />
            </div>

            <div className={styles.fieldRow}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Problem Type</label>
                <select
                  className={styles.selectInput}
                  value={problemData.problemDefinition.problemType}
                  onChange={(e) => handleProblemDefinitionChange('problemType', e.target.value)}
                >
                  <option value="">Select problem type</option>
                  <option value="quality">Quality</option>
                  <option value="cost">Cost</option>
                  <option value="delivery">Delivery</option>
                  <option value="safety">Safety</option>
                  <option value="morale">Morale</option>
                  <option value="other">Other</option>
                </select>
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Urgency</label>
                <select
                  className={styles.selectInput}
                  value={problemData.problemDefinition.urgency}
                  onChange={(e) => handleProblemDefinitionChange('urgency', e.target.value)}
                >
                  <option value="">Select urgency</option>
                  <option value="low">Low</option>
                  <option value="medium">Medium</option>
                  <option value="high">High</option>
                  <option value="critical">Critical</option>
                </select>
              </div>
            </div>
          </div>

          {/* Problem Definition */}
          <div className={styles.analysisCard}>
            <h2>Problem Definition</h2>
            <div className={styles.problemDefinitionSection}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Business Impact <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={problemData.problemDefinition.businessImpact}
                  onChange={(e) => handleProblemDefinitionChange('businessImpact', e.target.value)}
                  placeholder="Describe the business impact of this problem"
                  rows={3}
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Scope <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={problemData.problemDefinition.scope}
                  onChange={(e) => handleProblemDefinitionChange('scope', e.target.value)}
                  placeholder="Define what is included and excluded from this problem"
                  rows={3}
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Boundaries</label>
                <textarea
                  className={styles.textareaInput}
                  value={problemData.problemDefinition.boundaries}
                  onChange={(e) => handleProblemDefinitionChange('boundaries', e.target.value)}
                  placeholder="Define the boundaries of the problem (process, organizational, time)"
                  rows={2}
                />
              </div>
            </div>
          </div>

          {/* Current State */}
          <div className={styles.analysisCard}>
            <h2>Current State Analysis (5W Framework)</h2>
            <div className={styles.currentStateGrid}>
              <div className={styles.currentStateCard}>
                <h3>What is happening?</h3>
                <textarea
                  className={styles.textareaInput}
                  value={problemData.currentState.whatIsHappening}
                  onChange={(e) => handleCurrentStateChange('whatIsHappening', e.target.value)}
                  placeholder="Describe what exactly is happening"
                  rows={3}
                />
              </div>

              <div className={styles.currentStateCard}>
                <h3>Where is it occurring?</h3>
                <textarea
                  className={styles.textareaInput}
                  value={problemData.currentState.whereIsItOccurring}
                  onChange={(e) => handleCurrentStateChange('whereIsItOccurring', e.target.value)}
                  placeholder="Specify the location, process, or area where the problem occurs"
                  rows={3}
                />
              </div>

              <div className={styles.currentStateCard}>
                <h3>When does it occur?</h3>
                <textarea
                  className={styles.textareaInput}
                  value={problemData.currentState.whenDoesItOccur}
                  onChange={(e) => handleCurrentStateChange('whenDoesItOccur', e.target.value)}
                  placeholder="Describe the timing, frequency, or conditions when the problem occurs"
                  rows={3}
                />
              </div>

              <div className={styles.currentStateCard}>
                <h3>Who is affected?</h3>
                <textarea
                  className={styles.textareaInput}
                  value={problemData.currentState.whoIsAffected}
                  onChange={(e) => handleCurrentStateChange('whoIsAffected', e.target.value)}
                  placeholder="Identify who is impacted by this problem"
                  rows={3}
                />
              </div>

              <div className={styles.currentStateCard}>
                <h3>How often does it occur?</h3>
                <textarea
                  className={styles.textareaInput}
                  value={problemData.currentState.howOftenDoesItOccur}
                  onChange={(e) => handleCurrentStateChange('howOftenDoesItOccur', e.target.value)}
                  placeholder="Describe the frequency or pattern of occurrence"
                  rows={3}
                />
              </div>

              <div className={styles.currentStateCard}>
                <h3>What is the magnitude?</h3>
                <textarea
                  className={styles.textareaInput}
                  value={problemData.currentState.magnitude}
                  onChange={(e) => handleCurrentStateChange('magnitude', e.target.value)}
                  placeholder="Quantify the size or scale of the problem"
                  rows={3}
                />
              </div>
            </div>
          </div>

          {/* Quantification */}
          <div className={styles.analysisCard}>
            <h2>Problem Quantification</h2>
            <div className={styles.quantificationSection}>
              <div className={styles.metricsSection}>
                <div className={styles.sectionHeader}>
                  <h3>Key Metrics</h3>
                  <button className={styles.addBtn} onClick={addMetric}>
                    <i className="fas fa-plus"></i> Add Metric
                  </button>
                </div>

                <div className={styles.metricsTable}>
                  <table className={styles.dataTable}>
                    <thead>
                      <tr>
                        <th>Metric Name</th>
                        <th>Current Value</th>
                        <th>Target Value</th>
                        <th>Unit</th>
                        <th>Frequency</th>
                        <th>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {problemData.quantification.metrics.map((metric) => (
                        <tr key={metric.id}>
                          <td>
                            <input
                              type="text"
                              className={styles.tableInput}
                              value={metric.name}
                              onChange={(e) => handleMetricChange(metric.id, 'name', e.target.value)}
                              placeholder="Metric name"
                            />
                          </td>
                          <td>
                            <input
                              type="text"
                              className={styles.tableInput}
                              value={metric.currentValue}
                              onChange={(e) => handleMetricChange(metric.id, 'currentValue', e.target.value)}
                              placeholder="Current"
                            />
                          </td>
                          <td>
                            <input
                              type="text"
                              className={styles.tableInput}
                              value={metric.targetValue}
                              onChange={(e) => handleMetricChange(metric.id, 'targetValue', e.target.value)}
                              placeholder="Target"
                            />
                          </td>
                          <td>
                            <input
                              type="text"
                              className={styles.tableInput}
                              value={metric.unit}
                              onChange={(e) => handleMetricChange(metric.id, 'unit', e.target.value)}
                              placeholder="Unit"
                            />
                          </td>
                          <td>
                            <select
                              className={styles.tableSelect}
                              value={metric.frequency}
                              onChange={(e) => handleMetricChange(metric.id, 'frequency', e.target.value)}
                            >
                              <option value="daily">Daily</option>
                              <option value="weekly">Weekly</option>
                              <option value="monthly">Monthly</option>
                              <option value="quarterly">Quarterly</option>
                            </select>
                          </td>
                          <td>
                            <button className={styles.removeBtn} onClick={() => removeMetric(metric.id)}>
                              <i className="fas fa-times"></i>
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className={styles.impactAssessment}>
                <h3>Impact Assessment</h3>
                <div className={styles.impactGrid}>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Baseline Performance</label>
                    <textarea
                      className={styles.textareaInput}
                      value={problemData.quantification.baseline}
                      onChange={(e) => handleQuantificationChange('baseline', e.target.value)}
                      placeholder="Describe current baseline performance"
                      rows={2}
                    />
                  </div>

                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Target Performance</label>
                    <textarea
                      className={styles.textareaInput}
                      value={problemData.quantification.target}
                      onChange={(e) => handleQuantificationChange('target', e.target.value)}
                      placeholder="Describe desired target performance"
                      rows={2}
                    />
                  </div>

                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Performance Gap</label>
                    <textarea
                      className={styles.textareaInput}
                      value={problemData.quantification.gap}
                      onChange={(e) => handleQuantificationChange('gap', e.target.value)}
                      placeholder="Quantify the gap between current and target"
                      rows={2}
                    />
                  </div>

                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Financial Impact</label>
                    <textarea
                      className={styles.textareaInput}
                      value={problemData.quantification.financialImpact}
                      onChange={(e) => handleQuantificationChange('financialImpact', e.target.value)}
                      placeholder="Estimate financial impact (cost, revenue, savings)"
                      rows={2}
                    />
                  </div>

                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Customer Impact</label>
                    <textarea
                      className={styles.textareaInput}
                      value={problemData.quantification.customerImpact}
                      onChange={(e) => handleQuantificationChange('customerImpact', e.target.value)}
                      placeholder="Describe impact on customers"
                      rows={2}
                    />
                  </div>

                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Operational Impact</label>
                    <textarea
                      className={styles.textareaInput}
                      value={problemData.quantification.operationalImpact}
                      onChange={(e) => handleQuantificationChange('operationalImpact', e.target.value)}
                      placeholder="Describe operational impact"
                      rows={2}
                    />
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Stakeholders */}
          <div className={styles.analysisCard}>
            <h2>Stakeholder Analysis</h2>
            <div className={styles.stakeholdersSection}>
              <div className={styles.stakeholderRoles}>
                <div className={styles.fieldRow}>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Process Owner</label>
                    <input
                      type="text"
                      className={styles.textInput}
                      value={problemData.stakeholders.processOwner}
                      onChange={(e) => handleStakeholderChange('processOwner', e.target.value)}
                      placeholder="Who owns the process?"
                    />
                  </div>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Sponsor</label>
                    <input
                      type="text"
                      className={styles.textInput}
                      value={problemData.stakeholders.sponsor}
                      onChange={(e) => handleStakeholderChange('sponsor', e.target.value)}
                      placeholder="Who is sponsoring this initiative?"
                    />
                  </div>
                </div>
              </div>

              <div className={styles.stakeholderGroups}>
                <div className={styles.stakeholderGroup}>
                  <div className={styles.sectionHeader}>
                    <h3>Primary Stakeholders</h3>
                    <button className={styles.addBtn} onClick={() => addStakeholder('primaryStakeholders')}>
                      <i className="fas fa-plus"></i> Add Primary
                    </button>
                  </div>

                  <div className={styles.stakeholderList}>
                    {problemData.stakeholders.primaryStakeholders.map((s) => (
                      <div key={s.id} className={styles.stakeholderCard}>
                        <div className={styles.stakeholderInputs}>
                          <input
                            type="text"
                            className={styles.stakeholderInput}
                            value={s.name}
                            onChange={(e) => handleStakeholderItemChange('primaryStakeholders', s.id, 'name', e.target.value)}
                            placeholder="Name"
                          />
                          <input
                            type="text"
                            className={styles.stakeholderInput}
                            value={s.role}
                            onChange={(e) => handleStakeholderItemChange('primaryStakeholders', s.id, 'role', e.target.value)}
                            placeholder="Role"
                          />
                          <input
                            type="text"
                            className={styles.stakeholderInput}
                            value={s.department}
                            onChange={(e) => handleStakeholderItemChange('primaryStakeholders', s.id, 'department', e.target.value)}
                            placeholder="Department"
                          />
                          <select
                            className={styles.stakeholderSelect}
                            value={s.influence}
                            onChange={(e) => handleStakeholderItemChange('primaryStakeholders', s.id, 'influence', e.target.value)}
                          >
                            <option value="low">Low Influence</option>
                            <option value="medium">Medium Influence</option>
                            <option value="high">High Influence</option>
                          </select>
                          <select
                            className={styles.stakeholderSelect}
                            value={s.interest}
                            onChange={(e) => handleStakeholderItemChange('primaryStakeholders', s.id, 'interest', e.target.value)}
                          >
                            <option value="low">Low Interest</option>
                            <option value="medium">Medium Interest</option>
                            <option value="high">High Interest</option>
                          </select>
                          <button className={styles.removeBtn} onClick={() => removeStakeholder('primaryStakeholders', s.id)}>
                            <i className="fas fa-times"></i>
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                <div className={styles.stakeholderGroup}>
                  <div className={styles.sectionHeader}>
                    <h3>Secondary Stakeholders</h3>
                    <button className={styles.addBtn} onClick={() => addStakeholder('secondaryStakeholders')}>
                      <i className="fas fa-plus"></i> Add Secondary
                    </button>
                  </div>

                  <div className={styles.stakeholderList}>
                    {problemData.stakeholders.secondaryStakeholders.map((s) => (
                      <div key={s.id} className={styles.stakeholderCard}>
                        <div className={styles.stakeholderInputs}>
                          <input
                            type="text"
                            className={styles.stakeholderInput}
                            value={s.name}
                            onChange={(e) => handleStakeholderItemChange('secondaryStakeholders', s.id, 'name', e.target.value)}
                            placeholder="Name"
                          />
                          <input
                            type="text"
                            className={styles.stakeholderInput}
                            value={s.role}
                            onChange={(e) => handleStakeholderItemChange('secondaryStakeholders', s.id, 'role', e.target.value)}
                            placeholder="Role"
                          />
                          <input
                            type="text"
                            className={styles.stakeholderInput}
                            value={s.department}
                            onChange={(e) => handleStakeholderItemChange('secondaryStakeholders', s.id, 'department', e.target.value)}
                            placeholder="Department"
                          />
                          <select
                            className={styles.stakeholderSelect}
                            value={s.influence}
                            onChange={(e) => handleStakeholderItemChange('secondaryStakeholders', s.id, 'influence', e.target.value)}
                          >
                            <option value="low">Low Influence</option>
                            <option value="medium">Medium Influence</option>
                            <option value="high">High Influence</option>
                          </select>
                          <select
                            className={styles.stakeholderSelect}
                            value={s.interest}
                            onChange={(e) => handleStakeholderItemChange('secondaryStakeholders', s.id, 'interest', e.target.value)}
                          >
                            <option value="low">Low Interest</option>
                            <option value="medium">Medium Interest</option>
                            <option value="high">High Interest</option>
                          </select>
                          <button className={styles.removeBtn} onClick={() => removeStakeholder('secondaryStakeholders', s.id)}>
                            <i className="fas fa-times"></i>
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Success Criteria */}
          <div className={styles.analysisCard}>
            <h2>Success Criteria</h2>
            <div className={styles.successCriteriaSection}>
              <div className={styles.objectivesSection}>
                <div className={styles.objectiveGroup}>
                  <div className={styles.sectionHeader}>
                    <h3>Primary Objectives</h3>
                    <button className={styles.addBtn} onClick={() => addObjective('primaryObjectives')}>
                      <i className="fas fa-plus"></i> Add Primary
                    </button>
                  </div>

                  <div className={styles.objectivesList}>
                    {problemData.successCriteria.primaryObjectives.map((o) => (
                      <div key={o.id} className={styles.objectiveCard}>
                        <div className={styles.objectiveInputs}>
                          <input
                            type="text"
                            className={styles.objectiveInput}
                            value={o.objective}
                            onChange={(e) => handleObjectiveChange('primaryObjectives', o.id, 'objective', e.target.value)}
                            placeholder="Objective description"
                          />
                          <input
                            type="text"
                            className={styles.objectiveInput}
                            value={o.metric}
                            onChange={(e) => handleObjectiveChange('primaryObjectives', o.id, 'metric', e.target.value)}
                            placeholder="Success metric"
                          />
                          <input
                            type="text"
                            className={styles.objectiveInput}
                            value={o.target}
                            onChange={(e) => handleObjectiveChange('primaryObjectives', o.id, 'target', e.target.value)}
                            placeholder="Target value"
                          />
                          <input
                            type="text"
                            className={styles.objectiveInput}
                            value={o.timeline}
                            onChange={(e) => handleObjectiveChange('primaryObjectives', o.id, 'timeline', e.target.value)}
                            placeholder="Timeline"
                          />
                          <button className={styles.removeBtn} onClick={() => removeObjective('primaryObjectives', o.id)}>
                            <i className="fas fa-times"></i>
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                <div className={styles.objectiveGroup}>
                  <div className={styles.sectionHeader}>
                    <h3>Secondary Objectives</h3>
                    <button className={styles.addBtn} onClick={() => addObjective('secondaryObjectives')}>
                      <i className="fas fa-plus"></i> Add Secondary
                    </button>
                  </div>

                  <div className={styles.objectivesList}>
                    {problemData.successCriteria.secondaryObjectives.map((o) => (
                      <div key={o.id} className={styles.objectiveCard}>
                        <div className={styles.objectiveInputs}>
                          <input
                            type="text"
                            className={styles.objectiveInput}
                            value={o.objective}
                            onChange={(e) => handleObjectiveChange('secondaryObjectives', o.id, 'objective', e.target.value)}
                            placeholder="Objective description"
                          />
                          <input
                            type="text"
                            className={styles.objectiveInput}
                            value={o.metric}
                            onChange={(e) => handleObjectiveChange('secondaryObjectives', o.id, 'metric', e.target.value)}
                            placeholder="Success metric"
                          />
                          <input
                            type="text"
                            className={styles.objectiveInput}
                            value={o.target}
                            onChange={(e) => handleObjectiveChange('secondaryObjectives', o.id, 'target', e.target.value)}
                            placeholder="Target value"
                          />
                          <input
                            type="text"
                            className={styles.objectiveInput}
                            value={o.timeline}
                            onChange={(e) => handleObjectiveChange('secondaryObjectives', o.id, 'timeline', e.target.value)}
                            placeholder="Timeline"
                          />
                          <button className={styles.removeBtn} onClick={() => removeObjective('secondaryObjectives', o.id)}>
                            <i className="fas fa-times"></i>
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              <div className={styles.successMetricsSection}>
                <div className={styles.sectionHeader}>
                  <h3>Success Metrics</h3>
                  <button className={styles.addBtn} onClick={addSuccessMetric}>
                    <i className="fas fa-plus"></i> Add Metric
                  </button>
                </div>

                <div className={styles.successMetricsTable}>
                  <table className={styles.dataTable}>
                    <thead>
                      <tr>
                        <th>Metric</th>
                        <th>Baseline</th>
                        <th>Target</th>
                        <th>Measurement Method</th>
                        <th>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {problemData.successCriteria.successMetrics.map((m) => (
                        <tr key={m.id}>
                          <td>
                            <input
                              type="text"
                              className={styles.tableInput}
                              value={m.metric}
                              onChange={(e) => handleSuccessMetricChange(m.id, 'metric', e.target.value)}
                              placeholder="Success metric"
                            />
                          </td>
                          <td>
                            <input
                              type="text"
                              className={styles.tableInput}
                              value={m.baseline}
                              onChange={(e) => handleSuccessMetricChange(m.id, 'baseline', e.target.value)}
                              placeholder="Baseline"
                            />
                          </td>
                          <td>
                            <input
                              type="text"
                              className={styles.tableInput}
                              value={m.target}
                              onChange={(e) => handleSuccessMetricChange(m.id, 'target', e.target.value)}
                              placeholder="Target"
                            />
                          </td>
                          <td>
                            <input
                              type="text"
                              className={styles.tableInput}
                              value={m.measurement}
                              onChange={(e) => handleSuccessMetricChange(m.id, 'measurement', e.target.value)}
                              placeholder="How to measure"
                            />
                          </td>
                          <td>
                            <button className={styles.removeBtn} onClick={() => removeSuccessMetric(m.id)}>
                              <i className="fas fa-times"></i>
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className={styles.projectDetails}>
                <div className={styles.fieldRow}>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Timeline</label>
                    <input
                      type="text"
                      className={styles.textInput}
                      value={problemData.successCriteria.timeline}
                      onChange={(e) => handleSuccessCriteriaChange('timeline', e.target.value)}
                      placeholder="Project timeline"
                    />
                  </div>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Resources Required</label>
                    <input
                      type="text"
                      className={styles.textInput}
                      value={problemData.successCriteria.resources}
                      onChange={(e) => handleSuccessCriteriaChange('resources', e.target.value)}
                      placeholder="Required resources"
                    />
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Validation */}
          <div className={styles.analysisCard}>
            <h2>Validation & Approval</h2>
            <div className={styles.validationSection}>
              <div className={styles.validationDetails}>
                <div className={styles.fieldRow}>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Data Source</label>
                    <input
                      type="text"
                      className={styles.textInput}
                      value={problemData.validation.dataSource}
                      onChange={(e) => handleValidationChange('dataSource', e.target.value)}
                      placeholder="Source of validation data"
                    />
                  </div>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Evidence Type</label>
                    <select
                      className={styles.selectInput}
                      value={problemData.validation.evidenceType}
                      onChange={(e) => handleValidationChange('evidenceType', e.target.value)}
                    >
                      <option value="">Select evidence type</option>
                      <option value="quantitative">Quantitative</option>
                      <option value="qualitative">Qualitative</option>
                      <option value="mixed">Mixed</option>
                    </select>
                  </div>
                </div>

                <div className={styles.fieldRow}>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Validation Method</label>
                    <input
                      type="text"
                      className={styles.textInput}
                      value={problemData.validation.validationMethod}
                      onChange={(e) => handleValidationChange('validationMethod', e.target.value)}
                      placeholder="How was the problem validated?"
                    />
                  </div>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Confidence Level</label>
                    <select
                      className={styles.selectInput}
                      value={problemData.validation.confidence}
                      onChange={(e) => handleValidationChange('confidence', e.target.value)}
                    >
                      <option value="">Select confidence</option>
                      <option value="low">Low</option>
                      <option value="medium">Medium</option>
                      <option value="high">High</option>
                    </select>
                  </div>
                </div>
              </div>

              {/* Reviewers */}
              <div className={styles.reviewersSection}>
                <div className={styles.sectionHeader}>
                  <h3>Reviewers & Approval</h3>
                  <button
                    className={styles.addBtn}
                    onClick={() => {
                      const r = { id: Date.now(), name: '', role: '', reviewDate: '', status: 'pending', comments: '' };
                      setProblemData(prev => ({
                        ...prev,
                        validation: { ...prev.validation, reviewers: [...prev.validation.reviewers, r] },
                        lastUpdated: new Date().toISOString().split('T')[0]
                      }));
                    }}
                  >
                    <i className="fas fa-plus"></i> Add Reviewer
                  </button>
                </div>

                <div className={styles.reviewersTable}>
                  <table className={styles.dataTable}>
                    <thead>
                      <tr>
                        <th>Reviewer Name</th>
                        <th>Role</th>
                        <th>Review Date</th>
                        <th>Status</th>
                        <th>Comments</th>
                        <th>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {problemData.validation.reviewers.map((rev) => (
                        <tr key={rev.id}>
                          <td>
                            <input
                              type="text"
                              className={styles.tableInput}
                              value={rev.name}
                              onChange={(e) =>
                                setProblemData(prev => ({
                                  ...prev,
                                  validation: {
                                    ...prev.validation,
                                    reviewers: prev.validation.reviewers.map(r =>
                                      r.id === rev.id ? { ...r, name: e.target.value } : r
                                    )
                                  },
                                  lastUpdated: new Date().toISOString().split('T')[0]
                                }))
                              }
                              placeholder="Reviewer name"
                            />
                          </td>
                          <td>
                            <input
                              type="text"
                              className={styles.tableInput}
                              value={rev.role}
                              onChange={(e) =>
                                setProblemData(prev => ({
                                  ...prev,
                                  validation: {
                                    ...prev.validation,
                                    reviewers: prev.validation.reviewers.map(r =>
                                      r.id === rev.id ? { ...r, role: e.target.value } : r
                                    )
                                  },
                                  lastUpdated: new Date().toISOString().split('T')[0]
                                }))
                              }
                              placeholder="Role"
                            />
                          </td>
                          <td>
                            <input
                              type="date"
                              className={styles.tableInput}
                              value={rev.reviewDate}
                              onChange={(e) =>
                                setProblemData(prev => ({
                                  ...prev,
                                  validation: {
                                    ...prev.validation,
                                    reviewers: prev.validation.reviewers.map(r =>
                                      r.id === rev.id ? { ...r, reviewDate: e.target.value } : r
                                    )
                                  },
                                  lastUpdated: new Date().toISOString().split('T')[0]
                                }))
                              }
                            />
                          </td>
                          <td>
                            <select
                              className={styles.tableSelect}
                              value={rev.status}
                              onChange={(e) =>
                                setProblemData(prev => ({
                                  ...prev,
                                  validation: {
                                    ...prev.validation,
                                    reviewers: prev.validation.reviewers.map(r =>
                                      r.id === rev.id ? { ...r, status: e.target.value } : r
                                    )
                                  },
                                  lastUpdated: new Date().toISOString().split('T')[0]
                                }))
                              }
                            >
                              <option value="pending">Pending</option>
                              <option value="approved">Approved</option>
                              <option value="rejected">Rejected</option>
                              <option value="needs-revision">Needs Revision</option>
                            </select>
                          </td>
                          <td>
                            <input
                              type="text"
                              className={styles.tableInput}
                              value={rev.comments}
                              onChange={(e) =>
                                setProblemData(prev => ({
                                  ...prev,
                                  validation: {
                                    ...prev.validation,
                                    reviewers: prev.validation.reviewers.map(r =>
                                      r.id === rev.id ? { ...r, comments: e.target.value } : r
                                    )
                                  },
                                  lastUpdated: new Date().toISOString().split('T')[0]
                                }))
                              }
                              placeholder="Comments"
                            />
                          </td>
                          <td>
                            <button
                              className={styles.removeBtn}
                              onClick={() =>
                                setProblemData(prev => ({
                                  ...prev,
                                  validation: {
                                    ...prev.validation,
                                    reviewers: prev.validation.reviewers.filter(r => r.id !== rev.id)
                                  },
                                  lastUpdated: new Date().toISOString().split('T')[0]
                                }))
                              }
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

              <div className={styles.approvalStatus}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Approval Status</label>
                  <select
                    className={styles.selectInput}
                    value={problemData.validation.approvalStatus}
                    onChange={(e) => handleValidationChange('approvalStatus', e.target.value)}
                  >
                    <option value="draft">Draft</option>
                    <option value="review">Under Review</option>
                    <option value="approved">Approved</option>
                    <option value="rejected">Rejected</option>
                  </select>
                </div>
              </div>
            </div>
          </div>
        </div> {/* /mainContent */}
      </div> {/* /rcaContainer */}
    </ResourcePageWrapper>
  );
};

export default ProblemStatement;
