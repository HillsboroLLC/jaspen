import React, { useState, useEffect, useCallback } from 'react';
import styles from './Checksheet.module.css';
import { useAdminSettings } from '../context/AdminContext';
import ResourcePageWrapper from '../../All/components/ResourcePageWrapper';
import '@fortawesome/fontawesome-free/css/all.min.css';

const Checksheet = () => {
  const { adminSettings } = useAdminSettings();

  // Checksheet data structure
  const [checksheetData, setChecksheetData] = useState({
    // Project Information
    checksheetTitle: '',
    inspector: '',
    dateCreated: new Date().toISOString().split('T')[0],
    lastUpdated: new Date().toISOString().split('T')[0],

    // Checksheet Configuration
    checksheetConfig: {
      purpose: '',
      process: '',
      location: '',
      shift: '',
      frequency: 'hourly', // 'continuous', 'hourly', 'daily', 'weekly', 'batch'
      sampleSize: '',
      measurementMethod: '',
      equipment: '',
      standards: '',
    },

    // Measurement Parameters
    parameters: [
      {
        id: 1,
        name: '',
        specification: '',
        unit: '',
        target: '',
        upperLimit: '',
        lowerLimit: '',
        measurementType: 'variable', // 'variable', 'attribute'
        criticalToQuality: false,
        notes: '',
      },
    ],

    // Data Collection
    dataCollection: {
      collectionMethod: 'manual', // 'manual', 'automated', 'semi-automated'
      dataPoints: [],
      currentBatch: '',
      operator: '',
      environment: {
        temperature: '',
        humidity: '',
        pressure: '',
        other: '',
      },
    },

    // Statistical Analysis
    statistics: {
      parameters: [],
      controlLimits: {
        calculated: false,
        method: 'three-sigma', // 'three-sigma', 'specification', 'historical'
        ucl: '',
        lcl: '',
        centerLine: '',
      },
      capability: {
        cp: '',
        cpk: '',
        pp: '',
        ppk: '',
        interpretation: '',
      },
    },

    // Quality Control
    qualityControl: {
      outOfSpec: [],
      nonConformances: [],
      correctiveActions: [],
      trends: '',
      alerts: [],
      escalation: {
        required: false,
        escalatedTo: '',
        escalationDate: '',
        resolution: '',
      },
    },

    // Documentation
    documentation: {
      observations: '',
      issues: '',
      recommendations: '',
      followUpActions: '',
      approver: '',
      approvalDate: '',
      nextReview: '',
    },
  });

  const [completionPercentage, setCompletionPercentage] = useState(0);

  // Allow external updates via ResourcePageWrapper (optional, safe merge)
  const handleKiiDataUpdate = useCallback((incoming = {}) => {
    setChecksheetData((prev) => {
      const next = { ...prev };

      // Shallow fields
      ['checksheetTitle', 'inspector', 'dateCreated', 'lastUpdated'].forEach((k) => {
        if (incoming[k] !== undefined) next[k] = incoming[k];
      });

      // Nested merges
      if (incoming.checksheetConfig) {
        next.checksheetConfig = { ...next.checksheetConfig, ...incoming.checksheetConfig };
      }
      if (Array.isArray(incoming.parameters)) {
        next.parameters = incoming.parameters.map((p, i) => ({
          id: p.id || Date.now() + i,
          name: p.name ?? '',
          specification: p.specification ?? '',
          unit: p.unit ?? '',
          target: p.target ?? '',
          upperLimit: p.upperLimit ?? '',
          lowerLimit: p.lowerLimit ?? '',
          measurementType: p.measurementType ?? 'variable',
          criticalToQuality: !!p.criticalToQuality,
          notes: p.notes ?? '',
        }));
      }
      if (incoming.dataCollection) {
        next.dataCollection = {
          ...next.dataCollection,
          ...incoming.dataCollection,
          environment: {
            ...next.dataCollection.environment,
            ...(incoming.dataCollection.environment || {}),
          },
        };
      }
      if (incoming.statistics) {
        next.statistics = {
          ...next.statistics,
          ...incoming.statistics,
          controlLimits: {
            ...next.statistics.controlLimits,
            ...(incoming.statistics.controlLimits || {}),
          },
          capability: {
            ...next.statistics.capability,
            ...(incoming.statistics.capability || {}),
          },
        };
      }
      if (incoming.qualityControl) {
        next.qualityControl = {
          ...next.qualityControl,
          ...incoming.qualityControl,
          escalation: {
            ...next.qualityControl.escalation,
            ...(incoming.qualityControl.escalation || {}),
          },
        };
      }
      if (incoming.documentation) {
        next.documentation = { ...next.documentation, ...incoming.documentation };
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

      // Basic info (3 fields)
      totalFields += 3;
      if (checksheetData.checksheetTitle) completedFields++;
      if (checksheetData.inspector) completedFields++;
      if (checksheetData.checksheetConfig.purpose) completedFields++;

      // Configuration (3 fields)
      totalFields += 3;
      if (checksheetData.checksheetConfig.process) completedFields++;
      if (checksheetData.checksheetConfig.location) completedFields++;
      if (checksheetData.checksheetConfig.sampleSize) completedFields++;

      // Parameters (1 field)
      totalFields += 1;
      const hasParameters = checksheetData.parameters.some((param) => param.name.trim() !== '');
      if (hasParameters) completedFields++;

      // Data collection (1 field)
      totalFields += 1;
      if (checksheetData.dataCollection.dataPoints.length > 0) completedFields++;

      // Statistics (1 field)
      totalFields += 1;
      if (checksheetData.statistics.parameters.length > 0) completedFields++;

      // Documentation (2 fields)
      totalFields += 2;
      if (checksheetData.documentation.observations) completedFields++;
      if (checksheetData.documentation.recommendations) completedFields++;

      const percentage = totalFields > 0 ? Math.round((completedFields / totalFields) * 100) : 0;
      setCompletionPercentage(percentage);
    };

    calculateCompletion();
  }, [checksheetData]);

  // Handle basic info changes
  const handleBasicInfoChange = (field, value) => {
    setChecksheetData((prev) => ({
      ...prev,
      [field]: value,
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  // Handle config changes
  const handleConfigChange = (field, value) => {
    setChecksheetData((prev) => ({
      ...prev,
      checksheetConfig: {
        ...prev.checksheetConfig,
        [field]: value,
      },
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  // Handle parameter changes
  const handleParameterChange = (parameterId, field, value) => {
    setChecksheetData((prev) => ({
      ...prev,
      parameters: prev.parameters.map((param) => (param.id === parameterId ? { ...param, [field]: value } : param)),
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  // Add parameter
  const addParameter = () => {
    const newParameter = {
      id: Date.now(),
      name: '',
      specification: '',
      unit: '',
      target: '',
      upperLimit: '',
      lowerLimit: '',
      measurementType: 'variable',
      criticalToQuality: false,
      notes: '',
    };

    setChecksheetData((prev) => ({
      ...prev,
      parameters: [...prev.parameters, newParameter],
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  // Remove parameter
  const removeParameter = (parameterId) => {
    if (checksheetData.parameters.length > 1) {
      setChecksheetData((prev) => ({
        ...prev,
        parameters: prev.parameters.filter((param) => param.id !== parameterId),
        lastUpdated: new Date().toISOString().split('T')[0],
      }));
    }
  };

  // Handle data collection changes
  const handleDataCollectionChange = (field, value) => {
    setChecksheetData((prev) => ({
      ...prev,
      dataCollection: {
        ...prev.dataCollection,
        [field]: value,
      },
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  // Handle environment changes
  const handleEnvironmentChange = (field, value) => {
    setChecksheetData((prev) => ({
      ...prev,
      dataCollection: {
        ...prev.dataCollection,
        environment: {
          ...prev.dataCollection.environment,
          [field]: value,
        },
      },
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  // Add data point
  const addDataPoint = () => {
    const newDataPoint = {
      id: Date.now(),
      timestamp: new Date().toISOString(),
      operator: checksheetData.dataCollection.operator,
      batch: checksheetData.dataCollection.currentBatch,
      measurements: checksheetData.parameters.reduce((acc, param) => {
        acc[param.id] = {
          value: '',
          inSpec: true,
          notes: '',
        };
        return acc;
      }, {}),
      overallStatus: 'pass', // 'pass', 'fail', 'review'
      notes: '',
    };

    setChecksheetData((prev) => ({
      ...prev,
      dataCollection: {
        ...prev.dataCollection,
        dataPoints: [...prev.dataCollection.dataPoints, newDataPoint],
      },
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  // Remove data point
  const removeDataPoint = (dataPointId) => {
    setChecksheetData((prev) => ({
      ...prev,
      dataCollection: {
        ...prev.dataCollection,
        dataPoints: prev.dataCollection.dataPoints.filter((point) => point.id !== dataPointId),
      },
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  // Handle data point changes
  const handleDataPointChange = (dataPointId, field, value) => {
    setChecksheetData((prev) => ({
      ...prev,
      dataCollection: {
        ...prev.dataCollection,
        dataPoints: prev.dataCollection.dataPoints.map((point) =>
          point.id === dataPointId ? { ...point, [field]: value } : point
        ),
      },
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  // Handle measurement changes
  const handleMeasurementChange = (dataPointId, parameterId, field, value) => {
    setChecksheetData((prev) => ({
      ...prev,
      dataCollection: {
        ...prev.dataCollection,
        dataPoints: prev.dataCollection.dataPoints.map((point) =>
          point.id === dataPointId
            ? {
                ...point,
                measurements: {
                  ...point.measurements,
                  [parameterId]: {
                    ...point.measurements[parameterId],
                    [field]: value,
                  },
                },
              }
            : point
        ),
      },
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  // Calculate statistics
  const calculateStatistics = () => {
    const stats = checksheetData.parameters.map((param) => {
      const measurements = checksheetData.dataCollection.dataPoints
        .map((point) => parseFloat(point.measurements[param.id]?.value))
        .filter((val) => !isNaN(val));

      if (measurements.length === 0) {
        return {
          parameterId: param.id,
          parameterName: param.name,
          n: 0,
          mean: 0,
          std: 0,
          min: 0,
          max: 0,
          range: 0,
          inSpecCount: 0,
          outOfSpecCount: 0,
          yieldPercentage: 0,
        };
      }

      const n = measurements.length;
      const mean = measurements.reduce((sum, val) => sum + val, 0) / n;
      const variance = measurements.reduce((sum, val) => sum + Math.pow(val - mean, 2), 0) / (n - 1);
      const std = Math.sqrt(variance);
      const min = Math.min(...measurements);
      const max = Math.max(...measurements);
      const range = max - min;

      const upperLimit = parseFloat(param.upperLimit);
      const lowerLimit = parseFloat(param.lowerLimit);
      let inSpecCount = 0;
      let outOfSpecCount = 0;

      if (!isNaN(upperLimit) && !isNaN(lowerLimit)) {
        measurements.forEach((val) => {
          if (val >= lowerLimit && val <= upperLimit) {
            inSpecCount++;
          } else {
            outOfSpecCount++;
          }
        });
      }

      const yieldPercentage = n > 0 ? (inSpecCount / n) * 100 : 0;

      return {
        parameterId: param.id,
        parameterName: param.name,
        n,
        mean: parseFloat(mean.toFixed(4)),
        std: parseFloat(std.toFixed(4)),
        min: parseFloat(min.toFixed(4)),
        max: parseFloat(max.toFixed(4)),
        range: parseFloat(range.toFixed(4)),
        inSpecCount,
        outOfSpecCount,
        yieldPercentage: parseFloat(yieldPercentage.toFixed(2)),
      };
    });

    setChecksheetData((prev) => ({
      ...prev,
      statistics: {
        ...prev.statistics,
        parameters: stats,
      },
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  // Handle statistics changes
  const handleStatisticsChange = (section, field, value) => {
    setChecksheetData((prev) => ({
      ...prev,
      statistics: {
        ...prev.statistics,
        [section]: {
          ...prev.statistics[section],
          [field]: value,
        },
      },
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  // Handle quality control changes
  const handleQualityControlChange = (field, value) => {
    setChecksheetData((prev) => ({
      ...prev,
      qualityControl: {
        ...prev.qualityControl,
        [field]: value,
      },
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  // Handle documentation changes
  const handleDocumentationChange = (field, value) => {
    setChecksheetData((prev) => ({
      ...prev,
      documentation: {
        ...prev.documentation,
        [field]: value,
      },
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  // Save draft
  const handleSave = () => {
    console.log('Saving Checksheet draft:', checksheetData);
  };

  // Export PDF
  const handleExport = () => {
    console.log('Exporting Checksheet to PDF:', checksheetData);
  };

  return (
    <ResourcePageWrapper
      pageName="Checksheet"
      toolName="Checksheet"
      adminSettings={adminSettings}
      currentData={checksheetData}
      onDataUpdate={handleKiiDataUpdate}
    >
      <div className={styles.rcaContainer}>
        {/* Header - Exact match to other tools */}
        <div className={styles.header}>
          <div className={styles.headerContent}>
            <h1>Checksheet Data Collection</h1>
            <div className={styles.progressSection}>
              <div className={styles.progressBar}>
                <div className={styles.progressFill} style={{ width: `${completionPercentage}%` }}></div>
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
          {/* Checksheet Information */}
          <div className={styles.processInfoCard}>
            <h2>Checksheet Information</h2>

            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel}>
                Checksheet Title <span className={styles.required}>*</span>
              </label>
              <input
                type="text"
                className={styles.textInput}
                value={checksheetData.checksheetTitle}
                onChange={(e) => handleBasicInfoChange('checksheetTitle', e.target.value)}
                placeholder="Enter the title for your checksheet"
              />
            </div>

            <div className={styles.fieldRow}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Inspector <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={checksheetData.inspector}
                  onChange={(e) => handleBasicInfoChange('inspector', e.target.value)}
                  placeholder="Who is conducting the inspection?"
                />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Date Created</label>
                <input
                  type="date"
                  className={styles.textInput}
                  value={checksheetData.dateCreated}
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
                value={checksheetData.checksheetConfig.purpose}
                onChange={(e) => handleConfigChange('purpose', e.target.value)}
                placeholder="What is the purpose of this checksheet?"
                rows={2}
              />
            </div>

            <div className={styles.fieldRow}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Process</label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={checksheetData.checksheetConfig.process}
                  onChange={(e) => handleConfigChange('process', e.target.value)}
                  placeholder="Process being monitored"
                />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Location</label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={checksheetData.checksheetConfig.location}
                  onChange={(e) => handleConfigChange('location', e.target.value)}
                  placeholder="Where is the measurement taken?"
                />
              </div>
            </div>

            <div className={styles.fieldRow}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Frequency</label>
                <select
                  className={styles.selectInput}
                  value={checksheetData.checksheetConfig.frequency}
                  onChange={(e) => handleConfigChange('frequency', e.target.value)}
                >
                  <option value="continuous">Continuous</option>
                  <option value="hourly">Hourly</option>
                  <option value="daily">Daily</option>
                  <option value="weekly">Weekly</option>
                  <option value="batch">Per Batch</option>
                </select>
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Sample Size</label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={checksheetData.checksheetConfig.sampleSize}
                  onChange={(e) => handleConfigChange('sampleSize', e.target.value)}
                  placeholder="Number of samples per measurement"
                />
              </div>
            </div>
          </div>

          {/* Measurement Parameters */}
          <div className={styles.analysisCard}>
            <div className={styles.sectionHeader}>
              <h2>Measurement Parameters</h2>
              <button className={styles.addBtn} onClick={addParameter}>
                <i className="fas fa-plus"></i> Add Parameter
              </button>
            </div>

            <div className={styles.parametersGrid}>
              {checksheetData.parameters.map((parameter) => (
                <div key={parameter.id} className={styles.parameterCard}>
                  <div className={styles.parameterHeader}>
                    <div className={styles.parameterTitle}>
                      <input
                        type="text"
                        className={styles.parameterNameInput}
                        value={parameter.name}
                        onChange={(e) => handleParameterChange(parameter.id, 'name', e.target.value)}
                        placeholder="Parameter name"
                      />
                      <label className={styles.ctqToggle}>
                        <input
                          type="checkbox"
                          checked={parameter.criticalToQuality}
                          onChange={(e) => handleParameterChange(parameter.id, 'criticalToQuality', e.target.checked)}
                        />
                        CTQ
                      </label>
                    </div>
                    <button
                      className={styles.removeBtn}
                      onClick={() => removeParameter(parameter.id)}
                      disabled={checksheetData.parameters.length <= 1}
                    >
                      <i className="fas fa-times"></i>
                    </button>
                  </div>

                  <div className={styles.parameterContent}>
                    <div className={styles.fieldRow}>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Unit</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={parameter.unit}
                          onChange={(e) => handleParameterChange(parameter.id, 'unit', e.target.value)}
                          placeholder="mm, kg, %"
                        />
                      </div>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Type</label>
                        <select
                          className={styles.selectInput}
                          value={parameter.measurementType}
                          onChange={(e) => handleParameterChange(parameter.id, 'measurementType', e.target.value)}
                        >
                          <option value="variable">Variable</option>
                          <option value="attribute">Attribute</option>
                        </select>
                      </div>
                    </div>

                    <div className={styles.specificationRow}>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Target</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={parameter.target}
                          onChange={(e) => handleParameterChange(parameter.id, 'target', e.target.value)}
                          placeholder="Target value"
                        />
                      </div>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Lower Limit</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={parameter.lowerLimit}
                          onChange={(e) => handleParameterChange(parameter.id, 'lowerLimit', e.target.value)}
                          placeholder="LSL"
                        />
                      </div>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Upper Limit</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={parameter.upperLimit}
                          onChange={(e) => handleParameterChange(parameter.id, 'upperLimit', e.target.value)}
                          placeholder="USL"
                        />
                      </div>
                    </div>

                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Specification</label>
                      <input
                        type="text"
                        className={styles.textInput}
                        value={parameter.specification}
                        onChange={(e) => handleParameterChange(parameter.id, 'specification', e.target.value)}
                        placeholder="Detailed specification or acceptance criteria"
                      />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Data Collection */}
          <div className={styles.analysisCard}>
            <div className={styles.sectionHeader}>
              <h2>Data Collection</h2>
              <div className={styles.dataActions}>
                <button className={styles.addBtn} onClick={addDataPoint}>
                  <i className="fas fa-plus"></i> Add Data Point
                </button>
                <button className={styles.calculateBtn} onClick={calculateStatistics}>
                  <i className="fas fa-calculator"></i> Calculate Statistics
                </button>
              </div>
            </div>

            <div className={styles.collectionConfig}>
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Current Operator</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={checksheetData.dataCollection.operator}
                    onChange={(e) => handleDataCollectionChange('operator', e.target.value)}
                    placeholder="Operator name"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Current Batch/Lot</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={checksheetData.dataCollection.currentBatch}
                    onChange={(e) => handleDataCollectionChange('currentBatch', e.target.value)}
                    placeholder="Batch or lot number"
                  />
                </div>
              </div>
            </div>

            <div className={styles.dataTable}>
              <table className={styles.measurementTable}>
                <thead>
                  <tr>
                    <th>Timestamp</th>
                    <th>Operator</th>
                    <th>Batch</th>
                    {checksheetData.parameters.map((param) => (
                      <th key={param.id}>
                        {param.name || 'Parameter'}
                        {param.unit && <span className={styles.unitLabel}>({param.unit})</span>}
                      </th>
                    ))}
                    <th>Status</th>
                    <th>Notes</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {checksheetData.dataCollection.dataPoints.map((dataPoint) => (
                    <tr key={dataPoint.id}>
                      <td className={styles.timestampCell}>{new Date(dataPoint.timestamp).toLocaleString()}</td>
                      <td>
                        <input
                          type="text"
                          className={styles.tableInput}
                          value={dataPoint.operator}
                          onChange={(e) => handleDataPointChange(dataPoint.id, 'operator', e.target.value)}
                          placeholder="Operator"
                        />
                      </td>
                      <td>
                        <input
                          type="text"
                          className={styles.tableInput}
                          value={dataPoint.batch}
                          onChange={(e) => handleDataPointChange(dataPoint.id, 'batch', e.target.value)}
                          placeholder="Batch"
                        />
                      </td>
                      {checksheetData.parameters.map((param) => (
                        <td key={param.id}>
                          <input
                            type="text"
                            className={styles.tableInput}
                            value={dataPoint.measurements[param.id]?.value || ''}
                            onChange={(e) => handleMeasurementChange(dataPoint.id, param.id, 'value', e.target.value)}
                            placeholder="Value"
                          />
                        </td>
                      ))}
                      <td>
                        <select
                          className={styles.statusSelect}
                          value={dataPoint.overallStatus}
                          onChange={(e) => handleDataPointChange(dataPoint.id, 'overallStatus', e.target.value)}
                        >
                          <option value="pass">Pass</option>
                          <option value="fail">Fail</option>
                          <option value="review">Review</option>
                        </select>
                      </td>
                      <td>
                        <input
                          type="text"
                          className={styles.tableInput}
                          value={dataPoint.notes}
                          onChange={(e) => handleDataPointChange(dataPoint.id, 'notes', e.target.value)}
                          placeholder="Notes"
                        />
                      </td>
                      <td>
                        <button className={styles.removeBtn} onClick={() => removeDataPoint(dataPoint.id)}>
                          <i className="fas fa-times"></i>
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Statistical Analysis */}
          <div className={styles.analysisCard}>
            <h2>Statistical Analysis</h2>
            <div className={styles.statisticsGrid}>
              <div className={styles.descriptiveStats}>
                <h3>Descriptive Statistics</h3>
                <div className={styles.statsTable}>
                  <table className={styles.statsDataTable}>
                    <thead>
                      <tr>
                        <th>Parameter</th>
                        <th>n</th>
                        <th>Mean</th>
                        <th>Std Dev</th>
                        <th>Min</th>
                        <th>Max</th>
                        <th>Range</th>
                        <th>Yield %</th>
                      </tr>
                    </thead>
                    <tbody>
                      {checksheetData.statistics.parameters.map((stat) => (
                        <tr key={stat.parameterId}>
                          <td className={styles.parameterNameCell}>{stat.parameterName}</td>
                          <td>{stat.n}</td>
                          <td>{stat.mean}</td>
                          <td>{stat.std}</td>
                          <td>{stat.min}</td>
                          <td>{stat.max}</td>
                          <td>{stat.range}</td>
                          <td className={styles.yieldCell}>{stat.yieldPercentage}%</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className={styles.controlLimits}>
                <h3>Control Limits</h3>
                <div className={styles.fieldRow}>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Method</label>
                    <select
                      className={styles.selectInput}
                      value={checksheetData.statistics.controlLimits.method}
                      onChange={(e) => handleStatisticsChange('controlLimits', 'method', e.target.value)}
                    >
                      <option value="three-sigma">3-Sigma</option>
                      <option value="specification">Specification</option>
                      <option value="historical">Historical</option>
                    </select>
                  </div>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Center Line</label>
                    <input
                      type="text"
                      className={styles.textInput}
                      value={checksheetData.statistics.controlLimits.centerLine}
                      onChange={(e) => handleStatisticsChange('controlLimits', 'centerLine', e.target.value)}
                      placeholder="Process mean"
                    />
                  </div>
                </div>
                <div className={styles.fieldRow}>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>UCL</label>
                    <input
                      type="text"
                      className={styles.textInput}
                      value={checksheetData.statistics.controlLimits.ucl}
                      onChange={(e) => handleStatisticsChange('controlLimits', 'ucl', e.target.value)}
                      placeholder="Upper control limit"
                    />
                  </div>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>LCL</label>
                    <input
                      type="text"
                      className={styles.textInput}
                      value={checksheetData.statistics.controlLimits.lcl}
                      onChange={(e) => handleStatisticsChange('controlLimits', 'lcl', e.target.value)}
                      placeholder="Lower control limit"
                    />
                  </div>
                </div>
              </div>
            </div>

            <div className={styles.capabilitySection}>
              <h3>Process Capability</h3>
              <div className={styles.capabilityGrid}>
                <div className={styles.fieldRow}>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Cp</label>
                    <input
                      type="text"
                      className={styles.textInput}
                      value={checksheetData.statistics.capability.cp}
                      onChange={(e) => handleStatisticsChange('capability', 'cp', e.target.value)}
                      placeholder="Potential capability"
                    />
                  </div>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Cpk</label>
                    <input
                      type="text"
                      className={styles.textInput}
                      value={checksheetData.statistics.capability.cpk}
                      onChange={(e) => handleStatisticsChange('capability', 'cpk', e.target.value)}
                      placeholder="Actual capability"
                    />
                  </div>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Pp</label>
                    <input
                      type="text"
                      className={styles.textInput}
                      value={checksheetData.statistics.capability.pp}
                      onChange={(e) => handleStatisticsChange('capability', 'pp', e.target.value)}
                      placeholder="Performance potential"
                    />
                  </div>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Ppk</label>
                    <input
                      type="text"
                      className={styles.textInput}
                      value={checksheetData.statistics.capability.ppk}
                      onChange={(e) => handleStatisticsChange('capability', 'ppk', e.target.value)}
                      placeholder="Performance actual"
                    />
                  </div>
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Interpretation</label>
                  <textarea
                    className={styles.textareaInput}
                    value={checksheetData.statistics.capability.interpretation}
                    onChange={(e) => handleStatisticsChange('capability', 'interpretation', e.target.value)}
                    placeholder="Interpret the capability indices and what they mean for the process"
                    rows={2}
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Quality Control */}
          <div className={styles.analysisCard}>
            <h2>Quality Control & Monitoring</h2>
            <div className={styles.qualityControlGrid}>
              <div className={styles.trendsSection}>
                <h3>Trends & Patterns</h3>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Trend Analysis</label>
                  <textarea
                    className={styles.textareaInput}
                    value={checksheetData.qualityControl.trends}
                    onChange={(e) => handleQualityControlChange('trends', e.target.value)}
                    placeholder="Describe any trends, patterns, or shifts observed in the data"
                    rows={3}
                  />
                </div>
              </div>

              <div className={styles.alertsSection}>
                <h3>Alerts & Escalation</h3>
                <div className={styles.escalationToggle}>
                  <label className={styles.enableToggle}>
                    <input
                      type="checkbox"
                      checked={checksheetData.qualityControl.escalation.required}
                      onChange={(e) =>
                        handleQualityControlChange('escalation', {
                          ...checksheetData.qualityControl.escalation,
                          required: e.target.checked,
                        })
                      }
                    />
                    Escalation Required
                  </label>
                </div>

                {checksheetData.qualityControl.escalation.required && (
                  <div className={styles.escalationFields}>
                    <div className={styles.fieldRow}>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Escalated To</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={checksheetData.qualityControl.escalation.escalatedTo}
                          onChange={(e) =>
                            handleQualityControlChange('escalation', {
                              ...checksheetData.qualityControl.escalation,
                              escalatedTo: e.target.value,
                            })
                          }
                          placeholder="Who was notified?"
                        />
                      </div>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Escalation Date</label>
                        <input
                          type="datetime-local"
                          className={styles.textInput}
                          value={checksheetData.qualityControl.escalation.escalationDate}
                          onChange={(e) =>
                            handleQualityControlChange('escalation', {
                              ...checksheetData.qualityControl.escalation,
                              escalationDate: e.target.value,
                            })
                          }
                        />
                      </div>
                    </div>
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Resolution</label>
                      <textarea
                        className={styles.textareaInput}
                        value={checksheetData.qualityControl.escalation.resolution}
                        onChange={(e) =>
                          handleQualityControlChange('escalation', {
                            ...checksheetData.qualityControl.escalation,
                            resolution: e.target.value,
                          })
                        }
                        placeholder="How was the issue resolved?"
                        rows={2}
                      />
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Environmental Conditions */}
          <div className={styles.analysisCard}>
            <h2>Environmental Conditions</h2>
            <div className={styles.environmentGrid}>
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Temperature</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={checksheetData.dataCollection.environment.temperature}
                    onChange={(e) => handleEnvironmentChange('temperature', e.target.value)}
                    placeholder="°C or °F"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Humidity</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={checksheetData.dataCollection.environment.humidity}
                    onChange={(e) => handleEnvironmentChange('humidity', e.target.value)}
                    placeholder="% RH"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Pressure</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={checksheetData.dataCollection.environment.pressure}
                    onChange={(e) => handleEnvironmentChange('pressure', e.target.value)}
                    placeholder="psi, bar, Pa"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Other Conditions</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={checksheetData.dataCollection.environment.other}
                    onChange={(e) => handleEnvironmentChange('other', e.target.value)}
                    placeholder="Other environmental factors"
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Documentation & Summary */}
          <div className={styles.analysisCard}>
            <h2>Documentation & Summary</h2>
            <div className={styles.documentationGrid}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Observations</label>
                <textarea
                  className={styles.textareaInput}
                  value={checksheetData.documentation.observations}
                  onChange={(e) => handleDocumentationChange('observations', e.target.value)}
                  placeholder="Document key observations from the data collection"
                  rows={3}
                />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Issues Identified</label>
                <textarea
                  className={styles.textareaInput}
                  value={checksheetData.documentation.issues}
                  onChange={(e) => handleDocumentationChange('issues', e.target.value)}
                  placeholder="List any issues, non-conformances, or concerns identified"
                  rows={3}
                />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Recommendations <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={checksheetData.documentation.recommendations}
                  onChange={(e) => handleDocumentationChange('recommendations', e.target.value)}
                  placeholder="What actions or improvements are recommended based on this data?"
                  rows={3}
                />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Follow-up Actions</label>
                <textarea
                  className={styles.textareaInput}
                  value={checksheetData.documentation.followUpActions}
                  onChange={(e) => handleDocumentationChange('followUpActions', e.target.value)}
                  placeholder="What specific follow-up actions are required?"
                  rows={2}
                />
              </div>
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Approver</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={checksheetData.documentation.approver}
                    onChange={(e) => handleDocumentationChange('approver', e.target.value)}
                    placeholder="Who approved this checksheet?"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Next Review Date</label>
                  <input
                    type="date"
                    className={styles.textInput}
                    value={checksheetData.documentation.nextReview}
                    onChange={(e) => handleDocumentationChange('nextReview', e.target.value)}
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

export default Checksheet;
