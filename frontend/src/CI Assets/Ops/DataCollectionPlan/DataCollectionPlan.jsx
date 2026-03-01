// ============================================================================
// File: src/Ops/DataCollectionPlan/DataCollectionPlan.jsx
// Purpose: Data Collection Plan with floating chat via ResourcePageWrapper,
//          solid progress bar, no duplicate wrapper at bottom, and all
//          original functionality/styles preserved.
// ============================================================================

import React, { useState, useEffect, useCallback } from 'react';
import styles from './DataCollectionPlan.module.css';
import { useAdminSettings } from '../context/AdminContext';
import ResourcePageWrapper from '../../All/components/ResourcePageWrapper';
import '@fortawesome/fontawesome-free/css/all.min.css';

const DataCollectionPlan = () => {
  const { adminSettings } = useAdminSettings();

  // Data Collection Plan data structure
  const [dcpData, setDcpData] = useState({
    projectName: '',
    processOwner: '',
    dcpTeam: '',
    dateCreated: new Date().toISOString().split('T')[0],
    lastUpdated: new Date().toISOString().split('T')[0],

    // Measurement objectives
    objectives: {
      purpose: '',
      scope: '',
      timeline: '',
      resources: '',
    },

    // Metrics and KPIs
    metrics: [],

    // Data sources
    dataSources: [],

    // Sampling plan
    samplingPlan: {
      populationSize: '',
      sampleSize: '',
      samplingMethod: 'random', // 'random', 'systematic', 'stratified', 'cluster'
      frequency: '',
      duration: '',
      confidence: '95',
      marginError: '5',
    },

    // Collection methods
    collectionMethods: [],

    // Responsibilities
    responsibilities: [],

    // Data validation
    validation: {
      accuracy: '',
      precision: '',
      completeness: '',
      consistency: '',
      timeliness: '',
    },
  });

  const [completionPercentage, setCompletionPercentage] = useState(0);

  // Allow floating chat to update data dynamically
  const handleKiiDataUpdate = useCallback((extracted = {}) => {
    setDcpData((prev) => {
      const next = { ...prev };

      // Top-level
      if (extracted.projectName) next.projectName = extracted.projectName;
      if (extracted.processOwner) next.processOwner = extracted.processOwner;
      if (extracted.dcpTeam) next.dcpTeam = extracted.dcpTeam;

      // Objectives (object or flat keys)
      if (extracted.objectives) {
        next.objectives = { ...next.objectives, ...extracted.objectives };
      } else {
        ['purpose', 'scope', 'timeline', 'resources'].forEach((k) => {
          if (extracted[k]) next.objectives[k] = extracted[k];
        });
      }

      // Sampling Plan
      if (extracted.samplingPlan) {
        next.samplingPlan = { ...next.samplingPlan, ...extracted.samplingPlan };
      }

      // Validation
      if (extracted.validation) {
        next.validation = { ...next.validation, ...extracted.validation };
      }

      // Arrays
      if (Array.isArray(extracted.metrics)) {
        next.metrics = extracted.metrics.map((m, idx) => ({
          id: m.id || Date.now() + idx,
          name: m.name ?? '',
          definition: m.definition ?? '',
          type: m.type ?? 'continuous',
          unit: m.unit ?? '',
          target: m.target ?? '',
          specification: m.specification ?? '',
          dataType: m.dataType ?? 'quantitative',
          priority: m.priority ?? 'high',
        }));
      }

      if (Array.isArray(extracted.dataSources)) {
        next.dataSources = extracted.dataSources.map((s, idx) => ({
          id: s.id || Date.now() + idx,
          name: s.name ?? '',
          type: s.type ?? 'system',
          location: s.location ?? '',
          access: s.access ?? '',
          format: s.format ?? '',
          availability: s.availability ?? '',
          reliability: s.reliability ?? 'high',
        }));
      }

      if (Array.isArray(extracted.collectionMethods)) {
        next.collectionMethods = extracted.collectionMethods.map((cm, idx) => ({
          id: cm.id || Date.now() + idx,
          method: cm.method ?? '',
          description: cm.description ?? '',
          tools: cm.tools ?? '',
          frequency: cm.frequency ?? '',
          responsible: cm.responsible ?? '',
          cost: cm.cost ?? '',
          effort: cm.effort ?? 'medium',
        }));
      }

      if (Array.isArray(extracted.responsibilities)) {
        next.responsibilities = extracted.responsibilities.map((r, idx) => ({
          id: r.id || Date.now() + idx,
          role: r.role ?? '',
          person: r.person ?? '',
          task: r.task ?? '',
          deadline: r.deadline ?? '',
          status: r.status ?? 'assigned',
        }));
      }

      next.lastUpdated = new Date().toISOString().split('T')[0];
      return next;
    });
  }, []);

  // Calculate completion percentage
  useEffect(() => {
    const calculateCompletion = () => {
      let totalFields = 0;
      let completedFields = 0;

      // Basic info
      totalFields += 3;
      if (dcpData.projectName) completedFields++;
      if (dcpData.processOwner) completedFields++;
      if (dcpData.dcpTeam) completedFields++;

      // Objectives
      totalFields += 4;
      if (dcpData.objectives.purpose) completedFields++;
      if (dcpData.objectives.scope) completedFields++;
      if (dcpData.objectives.timeline) completedFields++;
      if (dcpData.objectives.resources) completedFields++;

      // Metrics
      totalFields += 1;
      if (dcpData.metrics.length > 0) completedFields++;

      // Data sources
      totalFields += 1;
      if (dcpData.dataSources.length > 0) completedFields++;

      // Sampling plan
      totalFields += 5;
      if (dcpData.samplingPlan.populationSize) completedFields++;
      if (dcpData.samplingPlan.sampleSize) completedFields++;
      if (dcpData.samplingPlan.frequency) completedFields++;
      if (dcpData.samplingPlan.duration) completedFields++;
      if (dcpData.samplingPlan.samplingMethod) completedFields++;

      // Collection methods
      totalFields += 1;
      if (dcpData.collectionMethods.length > 0) completedFields++;

      // Responsibilities
      totalFields += 1;
      if (dcpData.responsibilities.length > 0) completedFields++;

      // Validation
      totalFields += 5;
      if (dcpData.validation.accuracy) completedFields++;
      if (dcpData.validation.precision) completedFields++;
      if (dcpData.validation.completeness) completedFields++;
      if (dcpData.validation.consistency) completedFields++;
      if (dcpData.validation.timeliness) completedFields++;

      const percentage = totalFields > 0 ? Math.round((completedFields / totalFields) * 100) : 0;
      setCompletionPercentage(percentage);
    };

    calculateCompletion();
  }, [dcpData]);

  // Handlers
  const handleBasicInfoChange = (field, value) => {
    setDcpData((prev) => ({
      ...prev,
      [field]: value,
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  const handleObjectiveChange = (field, value) => {
    setDcpData((prev) => ({
      ...prev,
      objectives: {
        ...prev.objectives,
        [field]: value,
      },
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  const handleSamplingChange = (field, value) => {
    setDcpData((prev) => ({
      ...prev,
      samplingPlan: {
        ...prev.samplingPlan,
        [field]: value,
      },
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  const handleValidationChange = (field, value) => {
    setDcpData((prev) => ({
      ...prev,
      validation: {
        ...prev.validation,
        [field]: value,
      },
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  // Metrics
  const addMetric = () => {
    const newMetric = {
      id: Date.now(),
      name: '',
      definition: '',
      type: 'continuous',
      unit: '',
      target: '',
      specification: '',
      dataType: 'quantitative',
      priority: 'high',
    };
    setDcpData((prev) => ({
      ...prev,
      metrics: [...prev.metrics, newMetric],
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  const updateMetric = (id, field, value) => {
    setDcpData((prev) => ({
      ...prev,
      metrics: prev.metrics.map((metric) =>
        metric.id === id ? { ...metric, [field]: value } : metric
      ),
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  const removeMetric = (id) => {
    setDcpData((prev) => ({
      ...prev,
      metrics: prev.metrics.filter((m) => m.id !== id),
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  // Data sources
  const addDataSource = () => {
    const newSource = {
      id: Date.now(),
      name: '',
      type: 'system',
      location: '',
      access: '',
      format: '',
      availability: '',
      reliability: 'high',
    };
    setDcpData((prev) => ({
      ...prev,
      dataSources: [...prev.dataSources, newSource],
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  const updateDataSource = (id, field, value) => {
    setDcpData((prev) => ({
      ...prev,
      dataSources: prev.dataSources.map((s) => (s.id === id ? { ...s, [field]: value } : s)),
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  const removeDataSource = (id) => {
    setDcpData((prev) => ({
      ...prev,
      dataSources: prev.dataSources.filter((s) => s.id !== id),
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  // Collection methods
  const addCollectionMethod = () => {
    const newMethod = {
      id: Date.now(),
      method: '',
      description: '',
      tools: '',
      frequency: '',
      responsible: '',
      cost: '',
      effort: 'medium',
    };
    setDcpData((prev) => ({
      ...prev,
      collectionMethods: [...prev.collectionMethods, newMethod],
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  const updateCollectionMethod = (id, field, value) => {
    setDcpData((prev) => ({
      ...prev,
      collectionMethods: prev.collectionMethods.map((m) =>
        m.id === id ? { ...m, [field]: value } : m
      ),
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  const removeCollectionMethod = (id) => {
    setDcpData((prev) => ({
      ...prev,
      collectionMethods: prev.collectionMethods.filter((m) => m.id !== id),
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  // Responsibilities
  const addResponsibility = () => {
    const newResponsibility = {
      id: Date.now(),
      role: '',
      person: '',
      task: '',
      deadline: '',
      status: 'assigned',
    };
    setDcpData((prev) => ({
      ...prev,
      responsibilities: [...prev.responsibilities, newResponsibility],
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  const updateResponsibility = (id, field, value) => {
    setDcpData((prev) => ({
      ...prev,
      responsibilities: prev.responsibilities.map((r) =>
        r.id === id ? { ...r, [field]: value } : r
      ),
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  const removeResponsibility = (id) => {
    setDcpData((prev) => ({
      ...prev,
      responsibilities: prev.responsibilities.filter((r) => r.id !== id),
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  // Optional actions
  const handleSave = () => console.log('Saving DCP draft:', dcpData);
  const handleExport = () => console.log('Exporting DCP PDF:', dcpData);

  return (
    <ResourcePageWrapper
      pageName="Data Collection Plan"
      toolName="Data Collection Plan"
      adminSettings={adminSettings}
      currentData={dcpData}
      onDataUpdate={handleKiiDataUpdate}
    >
      <div className={styles.dcpContainer} style={{ paddingBottom: 0 }}>
        {/* Header */}
        <div className={styles.header}>
          <div className={styles.headerContent}>
            <h1>Data Collection Plan</h1>
            <div className={styles.progressSection}>
              {/* Solid (no gradient) */}
              <div
                className={styles.progressBar}
                style={{ background: 'var(--lss-gray-200)', backgroundImage: 'none' }}
              >
                <div
                  className={styles.progressFill}
                  style={{
                    width: `${completionPercentage}%`,
                    background: 'var(--lss-primary)',
                    backgroundImage: 'none',
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
          {/* Top Section: DCP Information (floating chat handled by wrapper) */}
          <div className={styles.topSection} style={{ display: 'block', marginBottom: 0 }}>
            <div className={styles.processInfoCard} style={{ width: '100%' }}>
              <h2>Data Collection Plan Information</h2>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Project Name <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={dcpData.projectName}
                  onChange={(e) => handleBasicInfoChange('projectName', e.target.value)}
                  placeholder="Enter the project name for this data collection plan"
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
                    value={dcpData.processOwner}
                    onChange={(e) => handleBasicInfoChange('processOwner', e.target.value)}
                    placeholder="Who owns the process being measured?"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>
                    DCP Team <span className={styles.required}>*</span>
                  </label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={dcpData.dcpTeam}
                    onChange={(e) => handleBasicInfoChange('dcpTeam', e.target.value)}
                    placeholder="List team members involved in data collection"
                  />
                </div>
              </div>

              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Date Created</label>
                  <input
                    type="date"
                    className={styles.textInput}
                    value={dcpData.dateCreated}
                    onChange={(e) => handleBasicInfoChange('dateCreated', e.target.value)}
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Last Updated</label>
                  <input type="date" className={styles.textInput} value={dcpData.lastUpdated} readOnly />
                </div>
              </div>
            </div>
          </div>

          {/* Measurement Objectives Section */}
          <div className={styles.objectivesCard}>
            <div className={styles.sectionHeader}>
              <h2>Measurement Objectives</h2>
            </div>

            <div className={styles.objectivesGrid}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Purpose <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={dcpData.objectives.purpose}
                  onChange={(e) => handleObjectiveChange('purpose', e.target.value)}
                  placeholder="Why are you collecting this data? What decisions will it support?"
                  rows={3}
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Scope <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={dcpData.objectives.scope}
                  onChange={(e) => handleObjectiveChange('scope', e.target.value)}
                  placeholder="What processes, products, or services will be measured?"
                  rows={3}
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Timeline <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={dcpData.objectives.timeline}
                  onChange={(e) => handleObjectiveChange('timeline', e.target.value)}
                  placeholder="When will data collection start and end? Key milestones?"
                  rows={3}
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Resources <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={dcpData.objectives.resources}
                  onChange={(e) => handleObjectiveChange('resources', e.target.value)}
                  placeholder="What people, tools, and budget are available?"
                  rows={3}
                />
              </div>
            </div>
          </div>

          {/* Metrics and KPIs Section */}
          <div className={styles.metricsCard}>
            <div className={styles.sectionHeader}>
              <h2>Metrics and KPIs</h2>
              <button className={styles.addBtn} onClick={addMetric}>
                <i className="fas fa-plus"></i> Add Metric
              </button>
            </div>

            <div className={styles.metricsList}>
              {dcpData.metrics.length === 0 ? (
                <div className={styles.emptyState}>
                  <i className="fas fa-chart-line"></i>
                  <p>No metrics defined yet. Add metrics to measure your process performance.</p>
                </div>
              ) : (
                dcpData.metrics.map((metric) => (
                  <div key={metric.id} className={styles.metricItem}>
                    <div className={styles.metricHeader}>
                      <input
                        type="text"
                        className={styles.metricName}
                        value={metric.name}
                        onChange={(e) => updateMetric(metric.id, 'name', e.target.value)}
                        placeholder="Metric name (e.g., Cycle Time, Defect Rate)"
                      />
                      <select
                        className={styles.metricType}
                        value={metric.type}
                        onChange={(e) => updateMetric(metric.id, 'type', e.target.value)}
                      >
                        <option value="continuous">Continuous</option>
                        <option value="discrete">Discrete</option>
                        <option value="attribute">Attribute</option>
                      </select>
                      <select
                        className={styles.metricPriority}
                        value={metric.priority}
                        onChange={(e) => updateMetric(metric.id, 'priority', e.target.value)}
                      >
                        <option value="high">High Priority</option>
                        <option value="medium">Medium Priority</option>
                        <option value="low">Low Priority</option>
                      </select>
                      <button className={styles.removeBtn} onClick={() => removeMetric(metric.id)}>
                        <i className="fas fa-times"></i>
                      </button>
                    </div>

                    <div className={styles.metricDetails}>
                      <div className={styles.detailField}>
                        <label>Definition</label>
                        <textarea
                          value={metric.definition}
                          onChange={(e) => updateMetric(metric.id, 'definition', e.target.value)}
                          placeholder="Clear definition of what this metric measures"
                        />
                      </div>
                      <div className={styles.detailField}>
                        <label>Unit of Measure</label>
                        <input
                          type="text"
                          value={metric.unit}
                          onChange={(e) => updateMetric(metric.id, 'unit', e.target.value)}
                          placeholder="e.g., minutes, %, count, dollars"
                        />
                      </div>
                      <div className={styles.detailField}>
                        <label>Target Value</label>
                        <input
                          type="text"
                          value={metric.target}
                          onChange={(e) => updateMetric(metric.id, 'target', e.target.value)}
                          placeholder="Target or goal for this metric"
                        />
                      </div>
                      <div className={styles.detailField}>
                        <label>Specification Limits</label>
                        <input
                          type="text"
                          value={metric.specification}
                          onChange={(e) =>
                            updateMetric(metric.id, 'specification', e.target.value)
                          }
                          placeholder="Upper/lower limits or acceptance criteria"
                        />
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* Data Sources Section */}
          <div className={styles.dataSourcesCard}>
            <div className={styles.sectionHeader}>
              <h2>Data Sources</h2>
              <button className={styles.addBtn} onClick={addDataSource}>
                <i className="fas fa-plus"></i> Add Data Source
              </button>
            </div>

            <div className={styles.dataSourcesList}>
              {dcpData.dataSources.length === 0 ? (
                <div className={styles.emptyState}>
                  <i className="fas fa-database"></i>
                  <p>No data sources identified yet. Add sources where your data will come from.</p>
                </div>
              ) : (
                dcpData.dataSources.map((source) => (
                  <div key={source.id} className={styles.dataSourceItem}>
                    <div className={styles.sourceHeader}>
                      <input
                        type="text"
                        className={styles.sourceName}
                        value={source.name}
                        onChange={(e) => updateDataSource(source.id, 'name', e.target.value)}
                        placeholder="Data source name"
                      />
                      <select
                        className={styles.sourceType}
                        value={source.type}
                        onChange={(e) => updateDataSource(source.id, 'type', e.target.value)}
                      >
                        <option value="system">System/Database</option>
                        <option value="manual">Manual Records</option>
                        <option value="sensor">Sensor/IoT</option>
                        <option value="survey">Survey/Interview</option>
                        <option value="observation">Direct Observation</option>
                      </select>
                      <select
                        className={styles.sourceReliability}
                        value={source.reliability}
                        onChange={(e) => updateDataSource(source.id, 'reliability', e.target.value)}
                      >
                        <option value="high">High Reliability</option>
                        <option value="medium">Medium Reliability</option>
                        <option value="low">Low Reliability</option>
                      </select>
                      <button
                        className={styles.removeBtn}
                        onClick={() => removeDataSource(source.id)}
                      >
                        <i className="fas fa-times"></i>
                      </button>
                    </div>

                    <div className={styles.sourceDetails}>
                      <div className={styles.detailField}>
                        <label>Location/Access</label>
                        <input
                          type="text"
                          value={source.location}
                          onChange={(e) => updateDataSource(source.id, 'location', e.target.value)}
                          placeholder="Where is this data located? How to access it?"
                        />
                      </div>
                      <div className={styles.detailField}>
                        <label>Data Format</label>
                        <input
                          type="text"
                          value={source.format}
                          onChange={(e) => updateDataSource(source.id, 'format', e.target.value)}
                          placeholder="Format of the data (CSV, Excel, API, etc.)"
                        />
                      </div>
                      <div className={styles.detailField}>
                        <label>Availability</label>
                        <input
                          type="text"
                          value={source.availability}
                          onChange={(e) =>
                            updateDataSource(source.id, 'availability', e.target.value)
                          }
                          placeholder="When is this data available? Real-time, daily, etc."
                        />
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* Sampling Plan Section */}
          <div className={styles.samplingCard}>
            <div className={styles.sectionHeader}>
              <h2>Sampling Plan</h2>
              <div className={styles.samplingInfo}>
                <i className="fas fa-info-circle"></i>
                <span>Define how you'll select representative data from your population</span>
              </div>
            </div>

            <div className={styles.samplingGrid}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Population Size</label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={dcpData.samplingPlan.populationSize}
                  onChange={(e) => handleSamplingChange('populationSize', e.target.value)}
                  placeholder="Total size of population to sample from"
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Sample Size</label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={dcpData.samplingPlan.sampleSize}
                  onChange={(e) => handleSamplingChange('sampleSize', e.target.value)}
                  placeholder="Number of samples to collect"
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Sampling Method</label>
                <select
                  className={styles.selectInput}
                  value={dcpData.samplingPlan.samplingMethod}
                  onChange={(e) => handleSamplingChange('samplingMethod', e.target.value)}
                >
                  <option value="random">Random Sampling</option>
                  <option value="systematic">Systematic Sampling</option>
                  <option value="stratified">Stratified Sampling</option>
                  <option value="cluster">Cluster Sampling</option>
                </select>
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Collection Frequency</label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={dcpData.samplingPlan.frequency}
                  onChange={(e) => handleSamplingChange('frequency', e.target.value)}
                  placeholder="How often to collect samples (hourly, daily, etc.)"
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Collection Duration</label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={dcpData.samplingPlan.duration}
                  onChange={(e) => handleSamplingChange('duration', e.target.value)}
                  placeholder="How long to collect data (days, weeks, etc.)"
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Confidence Level</label>
                <select
                  className={styles.selectInput}
                  value={dcpData.samplingPlan.confidence}
                  onChange={(e) => handleSamplingChange('confidence', e.target.value)}
                >
                  <option value="90">90%</option>
                  <option value="95">95%</option>
                  <option value="99">99%</option>
                </select>
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Margin of Error</label>
                <select
                  className={styles.selectInput}
                  value={dcpData.samplingPlan.marginError}
                  onChange={(e) => handleSamplingChange('marginError', e.target.value)}
                >
                  <option value="1">±1%</option>
                  <option value="3">±3%</option>
                  <option value="5">±5%</option>
                  <option value="10">±10%</option>
                </select>
              </div>
            </div>
          </div>

          {/* Collection Methods Section */}
          <div className={styles.methodsCard}>
            <div className={styles.sectionHeader}>
              <h2>Collection Methods</h2>
              <button className={styles.addBtn} onClick={addCollectionMethod}>
                <i className="fas fa-plus"></i> Add Method
              </button>
            </div>

            <div className={styles.methodsList}>
              {dcpData.collectionMethods.length === 0 ? (
                <div className={styles.emptyState}>
                  <i className="fas fa-clipboard-list"></i>
                  <p>No collection methods defined yet. Add methods for gathering your data.</p>
                </div>
              ) : (
                dcpData.collectionMethods.map((method) => (
                  <div key={method.id} className={styles.methodItem}>
                    <div className={styles.methodHeader}>
                      <input
                        type="text"
                        className={styles.methodName}
                        value={method.method}
                        onChange={(e) => updateCollectionMethod(method.id, 'method', e.target.value)}
                        placeholder="Collection method name"
                      />
                      <input
                        type="text"
                        className={styles.methodFrequency}
                        value={method.frequency}
                        onChange={(e) =>
                          updateCollectionMethod(method.id, 'frequency', e.target.value)
                        }
                        placeholder="Frequency"
                      />
                      <input
                        type="text"
                        className={styles.methodResponsible}
                        value={method.responsible}
                        onChange={(e) =>
                          updateCollectionMethod(method.id, 'responsible', e.target.value)
                        }
                        placeholder="Who is responsible?"
                      />
                      <select
                        className={styles.methodEffort}
                        value={method.effort}
                        onChange={(e) => updateCollectionMethod(method.id, 'effort', e.target.value)}
                      >
                        <option value="low">Low Effort</option>
                        <option value="medium">Medium Effort</option>
                        <option value="high">High Effort</option>
                      </select>
                      <button
                        className={styles.removeBtn}
                        onClick={() => removeCollectionMethod(method.id)}
                      >
                        <i className="fas fa-times"></i>
                      </button>
                    </div>

                    <div className={styles.methodDetails}>
                      <div className={styles.detailField}>
                        <label>Description</label>
                        <textarea
                          value={method.description}
                          onChange={(e) =>
                            updateCollectionMethod(method.id, 'description', e.target.value)
                          }
                          placeholder="Detailed description of this collection method"
                        />
                      </div>
                      <div className={styles.detailField}>
                        <label>Tools Required</label>
                        <input
                          type="text"
                          value={method.tools}
                          onChange={(e) => updateCollectionMethod(method.id, 'tools', e.target.value)}
                          placeholder="What tools, software, or equipment is needed?"
                        />
                      </div>
                      <div className={styles.detailField}>
                        <label>Estimated Cost</label>
                        <input
                          type="text"
                          value={method.cost}
                          onChange={(e) => updateCollectionMethod(method.id, 'cost', e.target.value)}
                          placeholder="Estimated cost for this method"
                        />
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* Responsibilities Section */}
          <div className={styles.responsibilitiesCard}>
            <div className={styles.sectionHeader}>
              <h2>Roles and Responsibilities</h2>
              <button className={styles.addBtn} onClick={addResponsibility}>
                <i className="fas fa-plus"></i> Add Responsibility
              </button>
            </div>

            <div className={styles.responsibilitiesList}>
              {dcpData.responsibilities.length === 0 ? (
                <div className={styles.emptyState}>
                  <i className="fas fa-users"></i>
                  <p>
                    No responsibilities assigned yet. Define who will do what in your data
                    collection.
                  </p>
                </div>
              ) : (
                dcpData.responsibilities.map((resp) => (
                  <div key={resp.id} className={styles.responsibilityItem}>
                    <div className={styles.responsibilityHeader}>
                      <input
                        type="text"
                        className={styles.respRole}
                        value={resp.role}
                        onChange={(e) => updateResponsibility(resp.id, 'role', e.target.value)}
                        placeholder="Role/Position"
                      />
                      <input
                        type="text"
                        className={styles.respPerson}
                        value={resp.person}
                        onChange={(e) => updateResponsibility(resp.id, 'person', e.target.value)}
                        placeholder="Person Name"
                      />
                      <input
                        type="text"
                        className={styles.respTask}
                        value={resp.task}
                        onChange={(e) => updateResponsibility(resp.id, 'task', e.target.value)}
                        placeholder="Specific task/responsibility"
                      />
                      <input
                        type="date"
                        className={styles.respDeadline}
                        value={resp.deadline}
                        onChange={(e) => updateResponsibility(resp.id, 'deadline', e.target.value)}
                      />
                      <select
                        className={styles.respStatus}
                        value={resp.status}
                        onChange={(e) => updateResponsibility(resp.id, 'status', e.target.value)}
                      >
                        <option value="assigned">Assigned</option>
                        <option value="in-progress">In Progress</option>
                        <option value="completed">Completed</option>
                      </select>
                      <button
                        className={styles.removeBtn}
                        onClick={() => removeResponsibility(resp.id)}
                      >
                        <i className="fas fa-times"></i>
                      </button>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* Data Validation Section */}
          <div className={styles.validationCard}>
            <div className={styles.sectionHeader}>
              <h2>Data Validation Plan</h2>
              <div className={styles.validationInfo}>
                <i className="fas fa-info-circle"></i>
                <span>Define how you'll ensure data quality and reliability</span>
              </div>
            </div>

            <div className={styles.validationGrid}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Accuracy <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={dcpData.validation.accuracy}
                  onChange={(e) => handleValidationChange('accuracy', e.target.value)}
                  placeholder="How will you ensure data is correct and error-free?"
                  rows={3}
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Precision <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={dcpData.validation.precision}
                  onChange={(e) => handleValidationChange('precision', e.target.value)}
                  placeholder="How will you ensure consistent, repeatable measurements?"
                  rows={3}
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Completeness <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={dcpData.validation.completeness}
                  onChange={(e) => handleValidationChange('completeness', e.target.value)}
                  placeholder="How will you handle missing data and ensure complete datasets?"
                  rows={3}
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Consistency <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={dcpData.validation.consistency}
                  onChange={(e) => handleValidationChange('consistency', e.target.value)}
                  placeholder="How will you ensure data follows the same format and standards?"
                  rows={3}
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Timeliness <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={dcpData.validation.timeliness}
                  onChange={(e) => handleValidationChange('timeliness', e.target.value)}
                  placeholder="How will you ensure data is collected and available when needed?"
                  rows={3}
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
              <span>Data Collection Plan {completionPercentage}% Complete</span>
            </div>
            <div className={styles.footerActions}>
              <button className={styles.secondaryBtn}>
                <i className="fas fa-eye"></i> Preview
              </button>
              <button className={styles.primaryBtn} disabled={completionPercentage < 80}>
                <i className="fas fa-check"></i> Complete Plan
              </button>
            </div>
          </div>
        </div>
      </div>
    </ResourcePageWrapper>
  );
};

export default DataCollectionPlan;
