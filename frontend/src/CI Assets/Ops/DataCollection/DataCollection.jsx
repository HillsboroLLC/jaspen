// src/pages/DataCollection.jsx
import React, { useState, useEffect } from 'react';
import styles from './DataCollection.module.css';
import { useAdminSettings } from '../context/AdminContext';
import ResourcePageWrapper from '../../All/components/ResourcePageWrapper';

const DataCollection = () => {
  const { adminSettings } = useAdminSettings();

  const [dataCollectionData, setDataCollectionData] = useState({
    collectionTitle: '',
    collector: '',
    dateStarted: new Date().toISOString().split('T')[0],
    lastUpdated: new Date().toISOString().split('T')[0],
    collectionSetup: {
      dataType: 'continuous',
      collectionMethod: 'manual',
      frequency: 'real-time',
      targetSampleSize: 30,
      currentSampleSize: 0,
      purpose: '',
      process: '',
      characteristic: '',
      unit: '',
      operationalDefinition: ''
    },
    dataEntries: [],
    validation: {
      rules: [],
      outliers: [],
      missingData: [],
      duplicates: [],
      validationStatus: 'pending'
    },
    statistics: {
      count: 0,
      mean: '',
      median: '',
      mode: '',
      standardDeviation: '',
      variance: '',
      range: '',
      minimum: '',
      maximum: '',
      q1: '',
      q3: '',
      iqr: '',
      skewness: '',
      kurtosis: ''
    },
    dataQuality: {
      completeness: 0,
      accuracy: 0,
      consistency: 0,
      timeliness: 0,
      validity: 0,
      issues: [],
      qualityScore: 0
    },
    progress: {
      status: 'active',
      milestones: [],
      currentPhase: 'collection',
      estimatedCompletion: '',
      actualCompletion: ''
    },
    documentation: {
      observations: '',
      issues: '',
      deviations: '',
      recommendations: '',
      nextSteps: '',
      approver: '',
      approvalDate: ''
    }
  });

  const [completionPercentage, setCompletionPercentage] = useState(0);

  useEffect(() => {
    let totalFields = 0;
    let completedFields = 0;

    // Basic info
    totalFields += 3;
    if (dataCollectionData.collectionTitle) completedFields++;
    if (dataCollectionData.collector) completedFields++;
    if (dataCollectionData.collectionSetup.purpose) completedFields++;

    // Setup
    totalFields += 4;
    if (dataCollectionData.collectionSetup.process) completedFields++;
    if (dataCollectionData.collectionSetup.characteristic) completedFields++;
    if (dataCollectionData.collectionSetup.unit) completedFields++;
    if (dataCollectionData.collectionSetup.operationalDefinition) completedFields++;

    // Data entries
    totalFields += 1;
    if (dataCollectionData.dataEntries.length > 0) completedFields++;

    // Validation
    totalFields += 1;
    if (dataCollectionData.validation.validationStatus === 'completed') completedFields++;

    // Documentation
    totalFields += 1;
    if (dataCollectionData.documentation.observations) completedFields++;

    const percentage = totalFields > 0 ? Math.round((completedFields / totalFields) * 100) : 0;
    setCompletionPercentage(percentage);
  }, [dataCollectionData]);

  const stamp = () => new Date().toISOString().split('T')[0];

  const handleBasicInfoChange = (field, value) => {
    setDataCollectionData(prev => ({
      ...prev,
      [field]: value,
      lastUpdated: stamp()
    }));
  };

  const handleSetupChange = (field, value) => {
    setDataCollectionData(prev => ({
      ...prev,
      collectionSetup: {
        ...prev.collectionSetup,
        [field]: value
      },
      lastUpdated: stamp()
    }));
  };

  const addDataEntry = () => {
    const newEntry = {
      id: Date.now(),
      timestamp: new Date().toISOString(),
      operator: dataCollectionData.collector,
      value: '',
      unit: dataCollectionData.collectionSetup.unit,
      conditions: {
        temperature: '',
        humidity: '',
        equipment: '',
        batch: '',
        shift: ''
      },
      notes: '',
      validated: false,
      flagged: false
    };

    setDataCollectionData(prev => ({
      ...prev,
      dataEntries: [...prev.dataEntries, newEntry],
      collectionSetup: {
        ...prev.collectionSetup,
        currentSampleSize: prev.dataEntries.length + 1
      },
      lastUpdated: stamp()
    }));
  };

  const removeDataEntry = (entryId) => {
    setDataCollectionData(prev => {
      const next = prev.dataEntries.filter(entry => entry.id !== entryId);
      return {
        ...prev,
        dataEntries: next,
        collectionSetup: {
          ...prev.collectionSetup,
          currentSampleSize: next.length
        },
        lastUpdated: stamp()
      };
    });
  };

  const handleDataEntryChange = (entryId, field, value) => {
    setDataCollectionData(prev => ({
      ...prev,
      dataEntries: prev.dataEntries.map(entry =>
        entry.id === entryId ? { ...entry, [field]: value } : entry
      ),
      lastUpdated: stamp()
    }));
  };

  const handleConditionChange = (entryId, condition, value) => {
    setDataCollectionData(prev => ({
      ...prev,
      dataEntries: prev.dataEntries.map(entry =>
        entry.id === entryId
          ? { ...entry, conditions: { ...entry.conditions, [condition]: value } }
          : entry
      ),
      lastUpdated: stamp()
    }));
  };

  const calculateStatistics = () => {
    const values = dataCollectionData.dataEntries
      .map(entry => parseFloat(entry.value))
      .filter(value => !isNaN(value));

    if (values.length === 0) return;

    const sorted = [...values].sort((a, b) => a - b);
    const n = values.length;
    const sum = values.reduce((acc, val) => acc + val, 0);
    const mean = sum / n;

    const variance = values.reduce((acc, val) => acc + Math.pow(val - mean, 2), 0) / (n - 1);
    const standardDeviation = Math.sqrt(variance);

    const median = n % 2 === 0
      ? (sorted[n / 2 - 1] + sorted[n / 2]) / 2
      : sorted[Math.floor(n / 2)];

    const q1 = sorted[Math.floor(n * 0.25)];
    const q3 = sorted[Math.floor(n * 0.75)];
    const iqr = q3 - q1;

    const skewness = values.reduce((acc, val) => acc + Math.pow((val - mean) / standardDeviation, 3), 0) / n;
    const kurtosis = values.reduce((acc, val) => acc + Math.pow((val - mean) / standardDeviation, 4), 0) / n - 3;

    setDataCollectionData(prev => ({
      ...prev,
      statistics: {
        count: n,
        mean: parseFloat(mean.toFixed(4)),
        median: parseFloat(median.toFixed(4)),
        standardDeviation: parseFloat(standardDeviation.toFixed(4)),
        variance: parseFloat(variance.toFixed(4)),
        range: parseFloat((sorted[n - 1] - sorted[0]).toFixed(4)),
        minimum: sorted[0],
        maximum: sorted[n - 1],
        q1: parseFloat(q1.toFixed(4)),
        q3: parseFloat(q3.toFixed(4)),
        iqr: parseFloat(iqr.toFixed(4)),
        skewness: parseFloat(skewness.toFixed(4)),
        kurtosis: parseFloat(kurtosis.toFixed(4))
      },
      lastUpdated: stamp()
    }));
  };

  const validateData = () => {
    const outliers = [];
    const missingData = [];
    const duplicates = [];

    const values = dataCollectionData.dataEntries.map(entry => parseFloat(entry.value));
    const validValues = values.filter(value => !isNaN(value));

    if (validValues.length > 0) {
      const mean = validValues.reduce((sum, val) => sum + val, 0) / validValues.length;
      const std = Math.sqrt(
        validValues.reduce((sum, val) => sum + Math.pow(val - mean, 2), 0) /
          (validValues.length - 1 || 1)
      );

      dataCollectionData.dataEntries.forEach((entry, index) => {
        const value = parseFloat(entry.value);
        if (!isNaN(value) && std > 0) {
          const zScore = Math.abs((value - mean) / std);
          if (zScore > 3) {
            outliers.push({
              entryId: entry.id,
              index: index + 1,
              value,
              zScore: parseFloat(zScore.toFixed(3))
            });
          }
        } else if (entry.value === '') {
          missingData.push({ entryId: entry.id, index: index + 1 });
        }
      });
    }

    setDataCollectionData(prev => ({
      ...prev,
      validation: {
        ...prev.validation,
        outliers,
        missingData,
        duplicates,
        validationStatus: 'completed'
      },
      lastUpdated: stamp()
    }));
  };

  const handleValidationChange = (field, value) => {
    setDataCollectionData(prev => ({
      ...prev,
      validation: {
        ...prev.validation,
        [field]: value
      },
      lastUpdated: stamp()
    }));
  };

  const handleProgressChange = (field, value) => {
    setDataCollectionData(prev => ({
      ...prev,
      progress: {
        ...prev.progress,
        [field]: value
      },
      lastUpdated: stamp()
    }));
  };

  const handleDocumentationChange = (field, value) => {
    setDataCollectionData(prev => ({
      ...prev,
      documentation: {
        ...prev.documentation,
        [field]: value
      },
      lastUpdated: stamp()
    }));
  };

  const addValidationRule = () => {
    const newRule = {
      id: Date.now(),
      type: 'range',
      description: '',
      condition: '',
      action: 'flag',
      enabled: true
    };

    setDataCollectionData(prev => ({
      ...prev,
      validation: {
        ...prev.validation,
        rules: [...prev.validation.rules, newRule]
      },
      lastUpdated: stamp()
    }));
  };

  const removeValidationRule = (ruleId) => {
    setDataCollectionData(prev => ({
      ...prev,
      validation: {
        ...prev.validation,
        rules: prev.validation.rules.filter(rule => rule.id !== ruleId)
      },
      lastUpdated: stamp()
    }));
  };

  const handleValidationRuleChange = (ruleId, field, value) => {
    setDataCollectionData(prev => ({
      ...prev,
      validation: {
        ...prev.validation,
        rules: prev.validation.rules.map(rule =>
          rule.id === ruleId ? { ...rule, [field]: value } : rule
        )
      },
      lastUpdated: stamp()
    }));
  };

  const addQualityIssue = () => {
    const newIssue = {
      id: Date.now(),
      timestamp: new Date().toISOString(),
      type: 'accuracy',
      description: '',
      impact: 'medium',
      action: '',
      responsible: '',
      status: 'open'
    };

    setDataCollectionData(prev => ({
      ...prev,
      dataQuality: {
        ...prev.dataQuality,
        issues: [...prev.dataQuality.issues, newIssue]
      },
      lastUpdated: stamp()
    }));
  };

  const removeQualityIssue = (issueId) => {
    setDataCollectionData(prev => ({
      ...prev,
      dataQuality: {
        ...prev.dataQuality,
        issues: prev.dataQuality.issues.filter(issue => issue.id !== issueId)
      },
      lastUpdated: stamp()
    }));
  };

  const handleQualityIssueChange = (issueId, field, value) => {
    setDataCollectionData(prev => ({
      ...prev,
      dataQuality: {
        ...prev.dataQuality,
        issues: prev.dataQuality.issues.map(issue =>
          issue.id === issueId ? { ...issue, [field]: value } : issue
        )
      },
      lastUpdated: stamp()
    }));
  };

  const handleSave = () => {
    console.log('Saving Data Collection draft:', dataCollectionData);
    // integrate with persistence layer
  };

  const handleExport = () => {
    console.log('Exporting Data Collection to PDF:', dataCollectionData);
    // integrate with exporter
  };

  return (
    <ResourcePageWrapper
      pageName="Data Collection"
      toolName="Data Collection"
      adminSettings={adminSettings}
    >
      <div className={styles.rcaContainer}>
        {/* Header */}
        <div className={styles.header}>
          <div className={styles.headerContent}>
            <h1>Data Collection</h1>
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
              <i className="fas fa-save"></i> Save Draft
            </button>
            <button className={styles.exportBtn} onClick={handleExport}>
              <i className="fas fa-download"></i> Export PDF
            </button>
          </div>
        </div>

        {/* Main Content */}
        <div className={styles.mainContent}>
          {/* Full-width Collection Information (chat removed) */}
          <div className={styles.processInfoCard}>
            <h2>Collection Information</h2>

            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel}>
                Collection Title <span className={styles.required}>*</span>
              </label>
              <input
                type="text"
                className={styles.textInput}
                value={dataCollectionData.collectionTitle}
                onChange={(e) => handleBasicInfoChange('collectionTitle', e.target.value)}
                placeholder="Enter the title for your data collection"
              />
            </div>

            <div className={styles.fieldRow}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Data Collector <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={dataCollectionData.collector}
                  onChange={(e) => handleBasicInfoChange('collector', e.target.value)}
                  placeholder="Who is collecting the data?"
                />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Date Started</label>
                <input
                  type="date"
                  className={styles.textInput}
                  value={dataCollectionData.dateStarted}
                  onChange={(e) => handleBasicInfoChange('dateStarted', e.target.value)}
                />
              </div>
            </div>

            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel}>
                Purpose <span className={styles.required}>*</span>
              </label>
              <textarea
                className={styles.textareaInput}
                value={dataCollectionData.collectionSetup.purpose}
                onChange={(e) => handleSetupChange('purpose', e.target.value)}
                placeholder="What is the purpose of this data collection?"
                rows={2}
              />
            </div>

            <div className={styles.fieldRow}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Process</label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={dataCollectionData.collectionSetup.process}
                  onChange={(e) => handleSetupChange('process', e.target.value)}
                  placeholder="Process being measured"
                />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Characteristic</label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={dataCollectionData.collectionSetup.characteristic}
                  onChange={(e) => handleSetupChange('characteristic', e.target.value)}
                  placeholder="Quality characteristic"
                />
              </div>
            </div>

            <div className={styles.fieldRow}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Data Type</label>
                <select
                  className={styles.selectInput}
                  value={dataCollectionData.collectionSetup.dataType}
                  onChange={(e) => handleSetupChange('dataType', e.target.value)}
                >
                  <option value="continuous">Continuous</option>
                  <option value="discrete">Discrete</option>
                  <option value="attribute">Attribute</option>
                  <option value="mixed">Mixed</option>
                </select>
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Unit</label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={dataCollectionData.collectionSetup.unit}
                  onChange={(e) => handleSetupChange('unit', e.target.value)}
                  placeholder="mm, kg, %, count"
                />
              </div>
            </div>

            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel}>
                Operational Definition <span className={styles.required}>*</span>
              </label>
              <textarea
                className={styles.textareaInput}
                value={dataCollectionData.collectionSetup.operationalDefinition}
                onChange={(e) => handleSetupChange('operationalDefinition', e.target.value)}
                placeholder="Clear, precise definition of what is being measured and how"
                rows={3}
              />
            </div>
          </div>

          {/* Collection Status Dashboard */}
          <div className={styles.analysisCard}>
            <h2>Collection Status Dashboard</h2>
            <div className={styles.statusGrid}>
              <div className={styles.statusCard}>
                <div className={styles.statusIcon}>
                  <i className="fas fa-database"></i>
                </div>
                <div className={styles.statusInfo}>
                  <div className={styles.statusValue}>{dataCollectionData.collectionSetup.currentSampleSize}</div>
                  <div className={styles.statusLabel}>Data Points Collected</div>
                  <div className={styles.statusTarget}>Target: {dataCollectionData.collectionSetup.targetSampleSize}</div>
                </div>
              </div>

              <div className={styles.statusCard}>
                <div className={styles.statusIcon}>
                  <i className="fas fa-check-circle"></i>
                </div>
                <div className={styles.statusInfo}>
                  <div className={styles.statusValue}>{dataCollectionData.validation.validationStatus}</div>
                  <div className={styles.statusLabel}>Validation Status</div>
                  <div className={styles.statusTarget}>Quality: {dataCollectionData.dataQuality.qualityScore}%</div>
                </div>
              </div>

              <div className={styles.statusCard}>
                <div className={styles.statusIcon}>
                  <i className="fas fa-exclamation-triangle"></i>
                </div>
                <div className={styles.statusInfo}>
                  <div className={styles.statusValue}>{dataCollectionData.validation.outliers.length}</div>
                  <div className={styles.statusLabel}>Outliers Detected</div>
                  <div className={styles.statusTarget}>Missing: {dataCollectionData.validation.missingData.length}</div>
                </div>
              </div>

              <div className={styles.statusCard}>
                <div className={styles.statusIcon}>
                  <i className="fas fa-clock"></i>
                </div>
                <div className={styles.statusInfo}>
                  <div className={styles.statusValue}>{dataCollectionData.progress.status}</div>
                  <div className={styles.statusLabel}>Collection Status</div>
                  <div className={styles.statusTarget}>Phase: {dataCollectionData.progress.currentPhase}</div>
                </div>
              </div>
            </div>
          </div>

          {/* Data Entry Section */}
          <div className={styles.analysisCard}>
            <div className={styles.sectionHeader}>
              <h2>Data Entry</h2>
              <div className={styles.dataActions}>
                <button className={styles.addBtn} onClick={addDataEntry}>
                  <i className="fas fa-plus"></i> Add Data Point
                </button>
                <button className={styles.calculateBtn} onClick={calculateStatistics}>
                  <i className="fas fa-calculator"></i> Calculate Stats
                </button>
                <button className={styles.validateBtn} onClick={validateData}>
                  <i className="fas fa-check"></i> Validate Data
                </button>
              </div>
            </div>

            <div className={styles.collectionConfig}>
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Collection Method</label>
                  <select
                    className={styles.selectInput}
                    value={dataCollectionData.collectionSetup.collectionMethod}
                    onChange={(e) => handleSetupChange('collectionMethod', e.target.value)}
                  >
                    <option value="manual">Manual Entry</option>
                    <option value="automated">Automated</option>
                    <option value="hybrid">Hybrid</option>
                  </select>
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Frequency</label>
                  <select
                    className={styles.selectInput}
                    value={dataCollectionData.collectionSetup.frequency}
                    onChange={(e) => handleSetupChange('frequency', e.target.value)}
                  >
                    <option value="real-time">Real-time</option>
                    <option value="batch">Batch</option>
                    <option value="scheduled">Scheduled</option>
                  </select>
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Target Sample Size</label>
                  <input
                    type="number"
                    className={styles.textInput}
                    value={dataCollectionData.collectionSetup.targetSampleSize}
                    onChange={(e) => handleSetupChange('targetSampleSize', parseInt(e.target.value, 10) || 30)}
                    min="1"
                  />
                </div>
              </div>
            </div>

            <div className={styles.dataTable}>
              <table className={styles.entryTable}>
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Timestamp</th>
                    <th>Operator</th>
                    <th>Value</th>
                    <th>Unit</th>
                    <th>Temperature</th>
                    <th>Equipment</th>
                    <th>Batch</th>
                    <th>Notes</th>
                    <th>Status</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {dataCollectionData.dataEntries.map((entry, index) => (
                    <tr key={entry.id} className={entry.flagged ? styles.flaggedRow : ''}>
                      <td className={styles.entryNumber}>{index + 1}</td>
                      <td className={styles.timestampCell}>{new Date(entry.timestamp).toLocaleString()}</td>
                      <td>
                        <input
                          type="text"
                          className={styles.tableInput}
                          value={entry.operator}
                          onChange={(e) => handleDataEntryChange(entry.id, 'operator', e.target.value)}
                          placeholder="Operator"
                        />
                      </td>
                      <td>
                        <input
                          type="text"
                          className={styles.tableInput}
                          value={entry.value}
                          onChange={(e) => handleDataEntryChange(entry.id, 'value', e.target.value)}
                          placeholder="Value"
                        />
                      </td>
                      <td className={styles.unitCell}>{entry.unit}</td>
                      <td>
                        <input
                          type="text"
                          className={styles.tableInput}
                          value={entry.conditions.temperature}
                          onChange={(e) => handleConditionChange(entry.id, 'temperature', e.target.value)}
                          placeholder="°C"
                        />
                      </td>
                      <td>
                        <input
                          type="text"
                          className={styles.tableInput}
                          value={entry.conditions.equipment}
                          onChange={(e) => handleConditionChange(entry.id, 'equipment', e.target.value)}
                          placeholder="Equipment"
                        />
                      </td>
                      <td>
                        <input
                          type="text"
                          className={styles.tableInput}
                          value={entry.conditions.batch}
                          onChange={(e) => handleConditionChange(entry.id, 'batch', e.target.value)}
                          placeholder="Batch"
                        />
                      </td>
                      <td>
                        <input
                          type="text"
                          className={styles.tableInput}
                          value={entry.notes}
                          onChange={(e) => handleDataEntryChange(entry.id, 'notes', e.target.value)}
                          placeholder="Notes"
                        />
                      </td>
                      <td>
                        <span className={`${styles.statusBadge} ${styles[entry.validated ? 'validated' : 'pending']}`}>
                          {entry.validated ? 'Validated' : 'Pending'}
                        </span>
                      </td>
                      <td>
                        <button className={styles.removeBtn} onClick={() => removeDataEntry(entry.id)}>
                          <i className="fas fa-times"></i>
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Real-time Statistics Section */}
          <div className={styles.analysisCard}>
            <h2>Real-time Statistics</h2>
            <div className={styles.statisticsGrid}>
              <div className={styles.basicStats}>
                <h3>Descriptive Statistics</h3>
                <div className={styles.statsTable}>
                  <div className={styles.statRow}>
                    <span className={styles.statLabel}>Count:</span>
                    <span className={styles.statValue}>{dataCollectionData.statistics.count}</span>
                  </div>
                  <div className={styles.statRow}>
                    <span className={styles.statLabel}>Mean:</span>
                    <span className={styles.statValue}>{dataCollectionData.statistics.mean}</span>
                  </div>
                  <div className={styles.statRow}>
                    <span className={styles.statLabel}>Median:</span>
                    <span className={styles.statValue}>{dataCollectionData.statistics.median}</span>
                  </div>
                  <div className={styles.statRow}>
                    <span className={styles.statLabel}>Std Dev:</span>
                    <span className={styles.statValue}>{dataCollectionData.statistics.standardDeviation}</span>
                  </div>
                  <div className={styles.statRow}>
                    <span className={styles.statLabel}>Range:</span>
                    <span className={styles.statValue}>{dataCollectionData.statistics.range}</span>
                  </div>
                  <div className={styles.statRow}>
                    <span className={styles.statLabel}>Min:</span>
                    <span className={styles.statValue}>{dataCollectionData.statistics.minimum}</span>
                  </div>
                  <div className={styles.statRow}>
                    <span className={styles.statLabel}>Max:</span>
                    <span className={styles.statValue}>{dataCollectionData.statistics.maximum}</span>
                  </div>
                </div>
              </div>

              <div className={styles.distributionStats}>
                <h3>Distribution Statistics</h3>
                <div className={styles.statsTable}>
                  <div className={styles.statRow}>
                    <span className={styles.statLabel}>Q1:</span>
                    <span className={styles.statValue}>{dataCollectionData.statistics.q1}</span>
                  </div>
                  <div className={styles.statRow}>
                    <span className={styles.statLabel}>Q3:</span>
                    <span className={styles.statValue}>{dataCollectionData.statistics.q3}</span>
                  </div>
                  <div className={styles.statRow}>
                    <span className={styles.statLabel}>IQR:</span>
                    <span className={styles.statValue}>{dataCollectionData.statistics.iqr}</span>
                  </div>
                  <div className={styles.statRow}>
                    <span className={styles.statLabel}>Skewness:</span>
                    <span className={styles.statValue}>{dataCollectionData.statistics.skewness}</span>
                  </div>
                  <div className={styles.statRow}>
                    <span className={styles.statLabel}>Kurtosis:</span>
                    <span className={styles.statValue}>{dataCollectionData.statistics.kurtosis}</span>
                  </div>
                  <div className={styles.statRow}>
                    <span className={styles.statLabel}>Variance:</span>
                    <span className={styles.statValue}>{dataCollectionData.statistics.variance}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Data Validation Section */}
          <div className={styles.analysisCard}>
            <div className={styles.sectionHeader}>
              <h2>Data Validation</h2>
              <button className={styles.addBtn} onClick={addValidationRule}>
                <i className="fas fa-plus"></i> Add Rule
              </button>
            </div>

            <div className={styles.validationRules}>
              <h3>Validation Rules</h3>
              <table className={styles.rulesTable}>
                <thead>
                  <tr>
                    <th>Type</th>
                    <th>Description</th>
                    <th>Condition</th>
                    <th>Action</th>
                    <th>Enabled</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {dataCollectionData.validation.rules.map((rule) => (
                    <tr key={rule.id}>
                      <td>
                        <select
                          className={styles.tableSelect}
                          value={rule.type}
                          onChange={(e) => handleValidationRuleChange(rule.id, 'type', e.target.value)}
                        >
                          <option value="range">Range Check</option>
                          <option value="format">Format Check</option>
                          <option value="logic">Logic Check</option>
                          <option value="custom">Custom Rule</option>
                        </select>
                      </td>
                      <td>
                        <input
                          type="text"
                          className={styles.tableInput}
                          value={rule.description}
                          onChange={(e) => handleValidationRuleChange(rule.id, 'description', e.target.value)}
                          placeholder="Rule description"
                        />
                      </td>
                      <td>
                        <input
                          type="text"
                          className={styles.tableInput}
                          value={rule.condition}
                          onChange={(e) => handleValidationRuleChange(rule.id, 'condition', e.target.value)}
                          placeholder="Condition"
                        />
                      </td>
                      <td>
                        <select
                          className={styles.tableSelect}
                          value={rule.action}
                          onChange={(e) => handleValidationRuleChange(rule.id, 'action', e.target.value)}
                        >
                          <option value="flag">Flag</option>
                          <option value="reject">Reject</option>
                          <option value="warn">Warn</option>
                        </select>
                      </td>
                      <td>
                        <input
                          type="checkbox"
                          checked={rule.enabled}
                          onChange={(e) => handleValidationRuleChange(rule.id, 'enabled', e.target.checked)}
                        />
                      </td>
                      <td>
                        <button className={styles.removeBtn} onClick={() => removeValidationRule(rule.id)}>
                          <i className="fas fa-times"></i>
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className={styles.validationResults}>
              <div className={styles.validationGrid}>
                <div className={styles.validationCard}>
                  <h4>Outliers ({dataCollectionData.validation.outliers.length})</h4>
                  <div className={styles.validationList}>
                    {dataCollectionData.validation.outliers.map((outlier) => (
                      <div key={outlier.entryId} className={styles.validationItem}>
                        <span className={styles.validationIndex}>#{outlier.index}</span>
                        <span className={styles.validationValue}>Value: {outlier.value}</span>
                        <span className={styles.validationScore}>Z-Score: {outlier.zScore}</span>
                      </div>
                    ))}
                  </div>
                </div>

                <div className={styles.validationCard}>
                  <h4>Missing Data ({dataCollectionData.validation.missingData.length})</h4>
                  <div className={styles.validationList}>
                    {dataCollectionData.validation.missingData.map((missing) => (
                      <div key={missing.entryId} className={styles.validationItem}>
                        <span className={styles.validationIndex}>#{missing.index}</span>
                        <span className={styles.validationValue}>Missing value</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Data Quality Monitoring Section */}
          <div className={styles.analysisCard}>
            <div className={styles.sectionHeader}>
              <h2>Data Quality Monitoring</h2>
              <button className={styles.addBtn} onClick={addQualityIssue}>
                <i className="fas fa-plus"></i> Add Issue
              </button>
            </div>

            <div className={styles.qualityDimensions}>
              <h3>Quality Dimensions</h3>
              <div className={styles.dimensionsGrid}>
                <div className={styles.dimensionCard}>
                  <div className={styles.dimensionHeader}>
                    <span className={styles.dimensionName}>Completeness</span>
                    <span className={styles.dimensionScore}>{dataCollectionData.dataQuality.completeness}%</span>
                  </div>
                  <div className={styles.dimensionBar}>
                    <div className={styles.dimensionFill} style={{ width: `${dataCollectionData.dataQuality.completeness}%` }} />
                  </div>
                </div>

                <div className={styles.dimensionCard}>
                  <div className={styles.dimensionHeader}>
                    <span className={styles.dimensionName}>Accuracy</span>
                    <span className={styles.dimensionScore}>{dataCollectionData.dataQuality.accuracy}%</span>
                  </div>
                  <div className={styles.dimensionBar}>
                    <div className={styles.dimensionFill} style={{ width: `${dataCollectionData.dataQuality.accuracy}%` }} />
                  </div>
                </div>

                <div className={styles.dimensionCard}>
                  <div className={styles.dimensionHeader}>
                    <span className={styles.dimensionName}>Consistency</span>
                    <span className={styles.dimensionScore}>{dataCollectionData.dataQuality.consistency}%</span>
                  </div>
                  <div className={styles.dimensionBar}>
                    <div className={styles.dimensionFill} style={{ width: `${dataCollectionData.dataQuality.consistency}%` }} />
                  </div>
                </div>

                <div className={styles.dimensionCard}>
                  <div className={styles.dimensionHeader}>
                    <span className={styles.dimensionName}>Timeliness</span>
                    <span className={styles.dimensionScore}>{dataCollectionData.dataQuality.timeliness}%</span>
                  </div>
                  <div className={styles.dimensionBar}>
                    <div className={styles.dimensionFill} style={{ width: `${dataCollectionData.dataQuality.timeliness}%` }} />
                  </div>
                </div>

                <div className={styles.dimensionCard}>
                  <div className={styles.dimensionHeader}>
                    <span className={styles.dimensionName}>Validity</span>
                    <span className={styles.dimensionScore}>{dataCollectionData.dataQuality.validity}%</span>
                  </div>
                  <div className={styles.dimensionBar}>
                    <div className={styles.dimensionFill} style={{ width: `${dataCollectionData.dataQuality.validity}%` }} />
                  </div>
                </div>
              </div>
            </div>

            <div className={styles.qualityIssues}>
              <h3>Quality Issues</h3>
              <table className={styles.issuesTable}>
                <thead>
                  <tr>
                    <th>Timestamp</th>
                    <th>Type</th>
                    <th>Description</th>
                    <th>Impact</th>
                    <th>Action</th>
                    <th>Responsible</th>
                    <th>Status</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {dataCollectionData.dataQuality.issues.map((issue) => (
                    <tr key={issue.id}>
                      <td className={styles.timestampCell}>{new Date(issue.timestamp).toLocaleString()}</td>
                      <td>
                        <select
                          className={styles.tableSelect}
                          value={issue.type}
                          onChange={(e) => handleQualityIssueChange(issue.id, 'type', e.target.value)}
                        >
                          <option value="accuracy">Accuracy</option>
                          <option value="completeness">Completeness</option>
                          <option value="consistency">Consistency</option>
                          <option value="timeliness">Timeliness</option>
                          <option value="validity">Validity</option>
                        </select>
                      </td>
                      <td>
                        <input
                          type="text"
                          className={styles.tableInput}
                          value={issue.description}
                          onChange={(e) => handleQualityIssueChange(issue.id, 'description', e.target.value)}
                          placeholder="Issue description"
                        />
                      </td>
                      <td>
                        <select
                          className={styles.impactSelect}
                          value={issue.impact}
                          onChange={(e) => handleQualityIssueChange(issue.id, 'impact', e.target.value)}
                        >
                          <option value="low">Low</option>
                          <option value="medium">Medium</option>
                          <option value="high">High</option>
                          <option value="critical">Critical</option>
                        </select>
                      </td>
                      <td>
                        <input
                          type="text"
                          className={styles.tableInput}
                          value={issue.action}
                          onChange={(e) => handleQualityIssueChange(issue.id, 'action', e.target.value)}
                          placeholder="Corrective action"
                        />
                      </td>
                      <td>
                        <input
                          type="text"
                          className={styles.tableInput}
                          value={issue.responsible}
                          onChange={(e) => handleQualityIssueChange(issue.id, 'responsible', e.target.value)}
                          placeholder="Who is responsible"
                        />
                      </td>
                      <td>
                        <select
                          className={styles.statusSelect}
                          value={issue.status}
                          onChange={(e) => handleQualityIssueChange(issue.id, 'status', e.target.value)}
                        >
                          <option value="open">Open</option>
                          <option value="in-progress">In Progress</option>
                          <option value="resolved">Resolved</option>
                        </select>
                      </td>
                      <td>
                        <button className={styles.removeBtn} onClick={() => removeQualityIssue(issue.id)}>
                          <i className="fas fa-times"></i>
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Collection Progress Section */}
          <div className={styles.analysisCard}>
            <h2>Collection Progress</h2>
            <div className={styles.progressGrid}>
              <div className={styles.progressInfo}>
                <h3>Progress Information</h3>
                <div className={styles.fieldRow}>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Status</label>
                    <select
                      className={styles.selectInput}
                      value={dataCollectionData.progress.status}
                      onChange={(e) => handleProgressChange('status', e.target.value)}
                    >
                      <option value="planning">Planning</option>
                      <option value="active">Active</option>
                      <option value="paused">Paused</option>
                      <option value="completed">Completed</option>
                      <option value="cancelled">Cancelled</option>
                    </select>
                  </div>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Current Phase</label>
                    <select
                      className={styles.selectInput}
                      value={dataCollectionData.progress.currentPhase}
                      onChange={(e) => handleProgressChange('currentPhase', e.target.value)}
                    >
                      <option value="setup">Setup</option>
                      <option value="collection">Collection</option>
                      <option value="validation">Validation</option>
                      <option value="analysis">Analysis</option>
                      <option value="documentation">Documentation</option>
                    </select>
                  </div>
                </div>

                <div className={styles.fieldRow}>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Estimated Completion</label>
                    <input
                      type="date"
                      className={styles.textInput}
                      value={dataCollectionData.progress.estimatedCompletion}
                      onChange={(e) => handleProgressChange('estimatedCompletion', e.target.value)}
                    />
                  </div>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Actual Completion</label>
                    <input
                      type="date"
                      className={styles.textInput}
                      value={dataCollectionData.progress.actualCompletion}
                      onChange={(e) => handleProgressChange('actualCompletion', e.target.value)}
                    />
                  </div>
                </div>
              </div>

              <div className={styles.progressChart}>
                <h3>Sample Size Progress</h3>
                <div className={styles.progressVisualization}>
                  <div className={styles.progressBarLarge}>
                    <div
                      className={styles.progressFillLarge}
                      style={{
                        width: `${Math.min(
                          (dataCollectionData.collectionSetup.currentSampleSize /
                            dataCollectionData.collectionSetup.targetSampleSize) * 100,
                          100
                        )}%`
                      }}
                    />
                  </div>
                  <div className={styles.progressLabels}>
                    <span>Current: {dataCollectionData.collectionSetup.currentSampleSize}</span>
                    <span>Target: {dataCollectionData.collectionSetup.targetSampleSize}</span>
                    <span>
                      {Math.round(
                        (dataCollectionData.collectionSetup.currentSampleSize /
                          dataCollectionData.collectionSetup.targetSampleSize) * 100
                      )}
                      %
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Documentation & Summary Section */}
          <div className={styles.analysisCard}>
            <h2>Documentation & Summary</h2>
            <div className={styles.documentationGrid}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Observations <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={dataCollectionData.documentation.observations}
                  onChange={(e) => handleDocumentationChange('observations', e.target.value)}
                  placeholder="What observations were made during data collection?"
                  rows={3}
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Issues & Deviations</label>
                <textarea
                  className={styles.textareaInput}
                  value={dataCollectionData.documentation.issues}
                  onChange={(e) => handleDocumentationChange('issues', e.target.value)}
                  placeholder="Document any issues or deviations from the collection plan"
                  rows={3}
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Recommendations</label>
                <textarea
                  className={styles.textareaInput}
                  value={dataCollectionData.documentation.recommendations}
                  onChange={(e) => handleDocumentationChange('recommendations', e.target.value)}
                  placeholder="What recommendations do you have for future data collection?"
                  rows={3}
                />
              </div>

              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Next Steps</label>
                  <textarea
                    className={styles.textareaInput}
                    value={dataCollectionData.documentation.nextSteps}
                    onChange={(e) => handleDocumentationChange('nextSteps', e.target.value)}
                    placeholder="What are the next steps after this data collection?"
                    rows={2}
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Approver</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={dataCollectionData.documentation.approver}
                    onChange={(e) => handleDocumentationChange('approver', e.target.value)}
                    placeholder="Who approved this data collection?"
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

export default DataCollection;
