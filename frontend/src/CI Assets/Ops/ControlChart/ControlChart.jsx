// ControlChart.jsx
import React, { useState, useEffect } from 'react';
import styles from './ControlChart.module.css';
import { useAdminSettings } from '../context/AdminContext';
import ResourcePageWrapper from '../../All/components/ResourcePageWrapper';

const ControlChart = () => {
  const { adminSettings } = useAdminSettings();

  // Control Chart data structure
  const [controlChartData, setControlChartData] = useState({
    // Project Information
    chartTitle: '',
    analyst: '',
    dateCreated: new Date().toISOString().split('T')[0],
    lastUpdated: new Date().toISOString().split('T')[0],
    
    // Chart Configuration
    chartConfig: {
      chartType: 'xbar-r', // 'xbar-r', 'xbar-s', 'individuals', 'p-chart', 'np-chart', 'c-chart', 'u-chart'
      process: '',
      characteristic: '',
      unit: '',
      sampleSize: 5,
      subgroupFrequency: 'hourly', // 'continuous', 'hourly', 'daily', 'weekly', 'batch'
      specification: {
        target: '',
        upperLimit: '',
        lowerLimit: '',
        hasSpecs: false
      },
      purpose: ''
    },
    
    // Data Collection
    dataCollection: {
      subgroups: [],
      operator: '',
      shift: '',
      equipment: '',
      environment: {
        temperature: '',
        humidity: '',
        notes: ''
      }
    },
    
    // Control Limits
    controlLimits: {
      method: 'calculated', // 'calculated', 'historical', 'specification'
      xbar: {
        centerLine: '',
        ucl: '',
        lcl: '',
        aFactor: 0.577 // A2 factor for n=5
      },
      range: {
        centerLine: '',
        ucl: '',
        lcl: '',
        d3Factor: 0,
        d4Factor: 2.114
      },
      individuals: {
        centerLine: '',
        ucl: '',
        lcl: '',
        movingRange: ''
      },
      attribute: {
        centerLine: '',
        ucl: '',
        lcl: '',
        sampleSize: ''
      }
    },
    
    // SPC Analysis
    spcAnalysis: {
      outOfControlPoints: [],
      patterns: {
        trends: [],
        shifts: [],
        cycles: [],
        mixtures: []
      },
      rules: {
        rule1: { enabled: true, violations: [] }, // Point beyond control limits
        rule2: { enabled: true, violations: [] }, // 9 points on same side
        rule3: { enabled: true, violations: [] }, // 6 points trending
        rule4: { enabled: true, violations: [] }, // 14 points alternating
        rule5: { enabled: true, violations: [] }, // 2 of 3 beyond 2 sigma
        rule6: { enabled: true, violations: [] }, // 4 of 5 beyond 1 sigma
        rule7: { enabled: true, violations: [] }, // 15 points within 1 sigma
        rule8: { enabled: true, violations: [] }  // 8 points beyond 1 sigma
      },
      processCapability: {
        cp: '',
        cpk: '',
        pp: '',
        ppk: '',
        sigma: ''
      }
    },
    
    // Actions & Documentation
    actions: {
      investigations: [],
      correctiveActions: [],
      processChanges: [],
      recommendations: '',
      nextReview: '',
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

      // Basic info (3 fields)
      totalFields += 3;
      if (controlChartData.chartTitle) completedFields++;
      if (controlChartData.analyst) completedFields++;
      if (controlChartData.chartConfig.purpose) completedFields++;

      // Configuration (3 fields)
      totalFields += 3;
      if (controlChartData.chartConfig.process) completedFields++;
      if (controlChartData.chartConfig.characteristic) completedFields++;
      if (controlChartData.chartConfig.unit) completedFields++;

      // Data collection (1 field)
      totalFields += 1;
      if (controlChartData.dataCollection.subgroups.length > 0) completedFields++;

      // Control limits (1 field)
      totalFields += 1;
      if (controlChartData.controlLimits.xbar.centerLine) completedFields++;

      // Analysis (1 field)
      totalFields += 1;
      if (controlChartData.spcAnalysis.outOfControlPoints.length > 0 || 
          Object.values(controlChartData.spcAnalysis.rules).some(rule => rule.violations.length > 0)) {
        completedFields++;
      }

      // Documentation (1 field)
      totalFields += 1;
      if (controlChartData.actions.recommendations) completedFields++;

      const percentage = totalFields > 0 ? Math.round((completedFields / totalFields) * 100) : 0;
      setCompletionPercentage(percentage);
    };

    calculateCompletion();
  }, [controlChartData]);

  // Handlers
  const handleBasicInfoChange = (field, value) => {
    setControlChartData(prev => ({
      ...prev,
      [field]: value,
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleConfigChange = (field, value) => {
    setControlChartData(prev => ({
      ...prev,
      chartConfig: {
        ...prev.chartConfig,
        [field]: value
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleSpecificationChange = (field, value) => {
    setControlChartData(prev => ({
      ...prev,
      chartConfig: {
        ...prev.chartConfig,
        specification: {
          ...prev.chartConfig.specification,
          [field]: value
        }
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleControlLimitsChange = (chartType, field, value) => {
    setControlChartData(prev => ({
      ...prev,
      controlLimits: {
        ...prev.controlLimits,
        [chartType]: {
          ...prev.controlLimits[chartType],
          [field]: value
        }
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Subgroups
  const addSubgroup = () => {
    const newSubgroup = {
      id: Date.now(),
      timestamp: new Date().toISOString(),
      operator: controlChartData.dataCollection.operator,
      shift: controlChartData.dataCollection.shift,
      measurements: Array(controlChartData.chartConfig.sampleSize).fill(''),
      average: '',
      range: '',
      standardDeviation: '',
      notes: ''
    };
    
    setControlChartData(prev => ({
      ...prev,
      dataCollection: {
        ...prev.dataCollection,
        subgroups: [...prev.dataCollection.subgroups, newSubgroup]
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const removeSubgroup = (subgroupId) => {
    setControlChartData(prev => ({
      ...prev,
      dataCollection: {
        ...prev.dataCollection,
        subgroups: prev.dataCollection.subgroups.filter(subgroup => subgroup.id !== subgroupId)
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleSubgroupChange = (subgroupId, field, value) => {
    setControlChartData(prev => ({
      ...prev,
      dataCollection: {
        ...prev.dataCollection,
        subgroups: prev.dataCollection.subgroups.map(subgroup =>
          subgroup.id === subgroupId ? { ...subgroup, [field]: value } : subgroup
        )
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleMeasurementChange = (subgroupId, measurementIndex, value) => {
    setControlChartData(prev => ({
      ...prev,
      dataCollection: {
        ...prev.dataCollection,
        subgroups: prev.dataCollection.subgroups.map(subgroup =>
          subgroup.id === subgroupId ? {
            ...subgroup,
            measurements: subgroup.measurements.map((measurement, index) =>
              index === measurementIndex ? value : measurement
            )
          } : subgroup
        )
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Calculate control limits (Xbar-R demo for n=5)
  const calculateControlLimits = () => {
    const subgroups = controlChartData.dataCollection.subgroups;
    if (subgroups.length === 0) return;

    // Calculate averages and ranges for each subgroup
    const calculatedSubgroups = subgroups.map(subgroup => {
      const measurements = subgroup.measurements
        .map(m => parseFloat(m))
        .filter(m => !isNaN(m));
      
      if (measurements.length === 0) return subgroup;
      
      const average = measurements.reduce((sum, val) => sum + val, 0) / measurements.length;
      const range = Math.max(...measurements) - Math.min(...measurements);
      const variance = measurements.reduce((sum, val) => sum + Math.pow(val - average, 2), 0) / (measurements.length - 1);
      const standardDeviation = Math.sqrt(variance);
      
      return {
        ...subgroup,
        average: parseFloat(average.toFixed(4)),
        range: parseFloat(range.toFixed(4)),
        standardDeviation: parseFloat(standardDeviation.toFixed(4))
      };
    });

    // Calculate overall statistics
    const averages = calculatedSubgroups.map(sg => sg.average).filter(avg => !isNaN(avg));
    const ranges = calculatedSubgroups.map(sg => sg.range).filter(r => !isNaN(r));
    
    if (averages.length === 0) return;
    
    const grandAverage = averages.reduce((sum, avg) => sum + avg, 0) / averages.length;
    const averageRange = ranges.reduce((sum, r) => sum + r, 0) / ranges.length;
    
    // Control limit factors (for n=5)
    const A2 = 0.577;
    const D3 = 0;
    const D4 = 2.114;
    
    // Calculate control limits
    const xbarUCL = grandAverage + (A2 * averageRange);
    const xbarLCL = grandAverage - (A2 * averageRange);
    const rangeUCL = D4 * averageRange;
    const rangeLCL = D3 * averageRange;
    
    setControlChartData(prev => ({
      ...prev,
      dataCollection: {
        ...prev.dataCollection,
        subgroups: calculatedSubgroups
      },
      controlLimits: {
        ...prev.controlLimits,
        xbar: {
          ...prev.controlLimits.xbar,
          centerLine: parseFloat(grandAverage.toFixed(4)),
          ucl: parseFloat(xbarUCL.toFixed(4)),
          lcl: parseFloat(xbarLCL.toFixed(4))
        },
        range: {
          ...prev.controlLimits.range,
          centerLine: parseFloat(averageRange.toFixed(4)),
          ucl: parseFloat(rangeUCL.toFixed(4)),
          lcl: parseFloat(rangeLCL.toFixed(4))
        }
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // SPC + Actions
  const handleSPCAnalysisChange = (section, field, value) => {
    setControlChartData(prev => ({
      ...prev,
      spcAnalysis: {
        ...prev.spcAnalysis,
        [section]: {
          ...prev.spcAnalysis[section],
          [field]: value
        }
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleRuleChange = (ruleNumber, field, value) => {
    setControlChartData(prev => ({
      ...prev,
      spcAnalysis: {
        ...prev.spcAnalysis,
        rules: {
          ...prev.spcAnalysis.rules,
          [`rule${ruleNumber}`]: {
            ...prev.spcAnalysis.rules[`rule${ruleNumber}`],
            [field]: value
          }
        }
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleActionsChange = (field, value) => {
    setControlChartData(prev => ({
      ...prev,
      actions: {
        ...prev.actions,
        [field]: value
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const addInvestigation = () => {
    const newInvestigation = {
      id: Date.now(),
      point: '',
      issue: '',
      rootCause: '',
      action: '',
      responsible: '',
      dueDate: '',
      status: 'open'
    };
    
    setControlChartData(prev => ({
      ...prev,
      actions: {
        ...prev.actions,
        investigations: [...prev.actions.investigations, newInvestigation]
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const removeInvestigation = (investigationId) => {
    setControlChartData(prev => ({
      ...prev,
      actions: {
        ...prev.actions,
        investigations: prev.actions.investigations.filter(inv => inv.id !== investigationId)
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleInvestigationChange = (investigationId, field, value) => {
    setControlChartData(prev => ({
      ...prev,
      actions: {
        ...prev.actions,
        investigations: prev.actions.investigations.map(inv =>
          inv.id === investigationId ? { ...inv, [field]: value } : inv
        )
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Save/Export
  const handleSave = () => {
    console.log('Saving Control Chart draft:', controlChartData);
  };

  const handleExport = () => {
    console.log('Exporting Control Chart to PDF:', controlChartData);
  };

  return (
    <div
      className={styles.rcaContainer}
      style={{ paddingBottom: 0, marginBottom: 0 }}
    >
      {/* Header */}
      <div className={styles.header}>
        <div className={styles.headerContent}>
          <h1>Control Chart Analysis</h1>
          <div className={styles.progressSection}>
            <div className={styles.progressBar}>
              <div 
                className={styles.progressFill} 
                style={{ width: `${completionPercentage}%` }}
              ></div>
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
      <div
        className={styles.mainContent}
        style={{
          paddingBottom: 0,
          marginBottom: 0,
          display: 'flow-root' // prevent margin-collapsing at the bottom
        }}
      >
        {/* Control Chart Information */}
        <div className={styles.processInfoCard}>
          <h2>Control Chart Information</h2>
          
          <div className={styles.fieldGroup}>
            <label className={styles.fieldLabel}>
              Chart Title <span className={styles.required}>*</span>
            </label>
            <input
              type="text"
              className={styles.textInput}
              value={controlChartData.chartTitle}
              onChange={(e) => handleBasicInfoChange('chartTitle', e.target.value)}
              placeholder="Enter the title for your control chart"
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
                value={controlChartData.analyst}
                onChange={(e) => handleBasicInfoChange('analyst', e.target.value)}
                placeholder="Who is conducting the analysis?"
              />
            </div>
            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel}>
                Date Created
              </label>
              <input
                type="date"
                className={styles.textInput}
                value={controlChartData.dateCreated}
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
              value={controlChartData.chartConfig.purpose}
              onChange={(e) => handleConfigChange('purpose', e.target.value)}
              placeholder="What is the purpose of this control chart?"
              rows={2}
            />
          </div>

          <div className={styles.fieldRow}>
            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel}>Process</label>
              <input
                type="text"
                className={styles.textInput}
                value={controlChartData.chartConfig.process}
                onChange={(e) => handleConfigChange('process', e.target.value)}
                placeholder="Process being monitored"
              />
            </div>
            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel}>Characteristic</label>
              <input
                type="text"
                className={styles.textInput}
                value={controlChartData.chartConfig.characteristic}
                onChange={(e) => handleConfigChange('characteristic', e.target.value)}
                placeholder="Quality characteristic measured"
              />
            </div>
          </div>

          <div className={styles.fieldRow}>
            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel}>Chart Type</label>
              <select
                className={styles.selectInput}
                value={controlChartData.chartConfig.chartType}
                onChange={(e) => handleConfigChange('chartType', e.target.value)}
              >
                <option value="xbar-r">X̄-R Chart</option>
                <option value="xbar-s">X̄-S Chart</option>
                <option value="individuals">I-MR Chart</option>
                <option value="p-chart">p-Chart</option>
                <option value="np-chart">np-Chart</option>
                <option value="c-chart">c-Chart</option>
                <option value="u-chart">u-Chart</option>
              </select>
            </div>
            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel}>Unit</label>
              <input
                type="text"
                className={styles.textInput}
                value={controlChartData.chartConfig.unit}
                onChange={(e) => handleConfigChange('unit', e.target.value)}
                placeholder="mm, kg, %, count"
              />
            </div>
          </div>
        </div>

        {/* Chart Configuration Section */}
        <div className={styles.analysisCard}>
          <h2>Chart Configuration</h2>
          <div className={styles.configGrid}>
            <div className={styles.samplingConfig}>
              <h3>Sampling Configuration</h3>
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Sample Size (n)</label>
                  <input
                    type="number"
                    className={styles.textInput}
                    value={controlChartData.chartConfig.sampleSize}
                    onChange={(e) => handleConfigChange('sampleSize', parseInt(e.target.value) || 5)}
                    min="1"
                    max="25"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Subgroup Frequency</label>
                  <select
                    className={styles.selectInput}
                    value={controlChartData.chartConfig.subgroupFrequency}
                    onChange={(e) => handleConfigChange('subgroupFrequency', e.target.value)}
                  >
                    <option value="continuous">Continuous</option>
                    <option value="hourly">Hourly</option>
                    <option value="daily">Daily</option>
                    <option value="weekly">Weekly</option>
                    <option value="batch">Per Batch</option>
                  </select>
                </div>
              </div>
            </div>
            
            <div className={styles.specificationConfig}>
              <h3>Specifications</h3>
              <div className={styles.specToggle}>
                <label className={styles.enableToggle}>
                  <input
                    type="checkbox"
                    checked={controlChartData.chartConfig.specification.hasSpecs}
                    onChange={(e) => handleSpecificationChange('hasSpecs', e.target.checked)}
                  />
                  Include Specification Limits
                </label>
              </div>
              
              {controlChartData.chartConfig.specification.hasSpecs && (
                <div className={styles.specFields}>
                  <div className={styles.fieldRow}>
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Target</label>
                      <input
                        type="text"
                        className={styles.textInput}
                        value={controlChartData.chartConfig.specification.target}
                        onChange={(e) => handleSpecificationChange('target', e.target.value)}
                        placeholder="Target value"
                      />
                    </div>
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>USL</label>
                      <input
                        type="text"
                        className={styles.textInput}
                        value={controlChartData.chartConfig.specification.upperLimit}
                        onChange={(e) => handleSpecificationChange('upperLimit', e.target.value)}
                        placeholder="Upper spec limit"
                      />
                    </div>
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>LSL</label>
                      <input
                        type="text"
                        className={styles.textInput}
                        value={controlChartData.chartConfig.specification.lowerLimit}
                        onChange={(e) => handleSpecificationChange('lowerLimit', e.target.value)}
                        placeholder="Lower spec limit"
                      />
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Data Collection Section */}
        <div className={styles.analysisCard}>
          <div className={styles.sectionHeader}>
            <h2>Data Collection</h2>
            <div className={styles.dataActions}>
              <button className={styles.addBtn} onClick={addSubgroup}>
                <i className="fas fa-plus"></i> Add Subgroup
              </button>
              <button className={styles.calculateBtn} onClick={calculateControlLimits}>
                <i className="fas fa-calculator"></i> Calculate Limits
              </button>
            </div>
          </div>
          
          <div className={styles.collectionInfo}>
            <div className={styles.fieldRow}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Current Operator</label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={controlChartData.dataCollection.operator}
                  onChange={(e) => setControlChartData(prev => ({
                    ...prev,
                    dataCollection: { ...prev.dataCollection, operator: e.target.value }
                  }))}
                  placeholder="Operator name"
                />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Shift</label>
                <select
                  className={styles.selectInput}
                  value={controlChartData.dataCollection.shift}
                  onChange={(e) => setControlChartData(prev => ({
                    ...prev,
                    dataCollection: { ...prev.dataCollection, shift: e.target.value }
                  }))}
                >
                  <option value="">Select shift</option>
                  <option value="day">Day Shift</option>
                  <option value="evening">Evening Shift</option>
                  <option value="night">Night Shift</option>
                </select>
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Equipment</label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={controlChartData.dataCollection.equipment}
                  onChange={(e) => setControlChartData(prev => ({
                    ...prev,
                    dataCollection: { ...prev.dataCollection, equipment: e.target.value }
                  }))}
                  placeholder="Equipment used"
                />
              </div>
            </div>
          </div>

          <div className={styles.dataTable}>
            <table className={styles.subgroupTable}>
              <thead>
                <tr>
                  <th>Subgroup</th>
                  <th>Timestamp</th>
                  <th>Operator</th>
                  {Array.from({ length: controlChartData.chartConfig.sampleSize }, (_, i) => (
                    <th key={i}>X{i + 1}</th>
                  ))}
                  <th>X̄</th>
                  <th>R</th>
                  <th>Notes</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {controlChartData.dataCollection.subgroups.map((subgroup, index) => (
                  <tr key={subgroup.id}>
                    <td className={styles.subgroupNumber}>{index + 1}</td>
                    <td className={styles.timestampCell}>
                      {new Date(subgroup.timestamp).toLocaleString()}
                    </td>
                    <td>
                      <input
                        type="text"
                        className={styles.tableInput}
                        value={subgroup.operator}
                        onChange={(e) => handleSubgroupChange(subgroup.id, 'operator', e.target.value)}
                        placeholder="Operator"
                      />
                    </td>
                    {subgroup.measurements.map((measurement, measurementIndex) => (
                      <td key={measurementIndex}>
                        <input
                          type="text"
                          className={styles.tableInput}
                          value={measurement}
                          onChange={(e) => handleMeasurementChange(subgroup.id, measurementIndex, e.target.value)}
                          placeholder="Value"
                        />
                      </td>
                    ))}
                    <td className={styles.statisticCell}>{subgroup.average || '-'}</td>
                    <td className={styles.statisticCell}>{subgroup.range || '-'}</td>
                    <td>
                      <input
                        type="text"
                        className={styles.tableInput}
                        value={subgroup.notes}
                        onChange={(e) => handleSubgroupChange(subgroup.id, 'notes', e.target.value)}
                        placeholder="Notes"
                      />
                    </td>
                    <td>
                      <button
                        className={styles.removeBtn}
                        onClick={() => removeSubgroup(subgroup.id)}
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

        {/* Control Limits Section */}
        <div className={styles.analysisCard}>
          <h2>Control Limits</h2>
          <div className={styles.controlLimitsGrid}>
            <div className={styles.xbarLimits}>
              <h3>X̄ Chart Limits</h3>
              <div className={styles.limitsTable}>
                <div className={styles.limitRow}>
                  <label className={styles.limitLabel}>UCL</label>
                  <input
                    type="text"
                    className={styles.limitInput}
                    value={controlChartData.controlLimits.xbar.ucl}
                    onChange={(e) => handleControlLimitsChange('xbar', 'ucl', e.target.value)}
                    placeholder="Upper control limit"
                  />
                </div>
                <div className={styles.limitRow}>
                  <label className={styles.limitLabel}>CL</label>
                  <input
                    type="text"
                    className={styles.limitInput}
                    value={controlChartData.controlLimits.xbar.centerLine}
                    onChange={(e) => handleControlLimitsChange('xbar', 'centerLine', e.target.value)}
                    placeholder="Center line (X̄̄)"
                  />
                </div>
                <div className={styles.limitRow}>
                  <label className={styles.limitLabel}>LCL</label>
                  <input
                    type="text"
                    className={styles.limitInput}
                    value={controlChartData.controlLimits.xbar.lcl}
                    onChange={(e) => handleControlLimitsChange('xbar', 'lcl', e.target.value)}
                    placeholder="Lower control limit"
                  />
                </div>
              </div>
            </div>
            
            <div className={styles.rangeLimits}>
              <h3>R Chart Limits</h3>
              <div className={styles.limitsTable}>
                <div className={styles.limitRow}>
                  <label className={styles.limitLabel}>UCL</label>
                  <input
                    type="text"
                    className={styles.limitInput}
                    value={controlChartData.controlLimits.range.ucl}
                    onChange={(e) => handleControlLimitsChange('range', 'ucl', e.target.value)}
                    placeholder="Upper control limit"
                  />
                </div>
                <div className={styles.limitRow}>
                  <label className={styles.limitLabel}>CL</label>
                  <input
                    type="text"
                    className={styles.limitInput}
                    value={controlChartData.controlLimits.range.centerLine}
                    onChange={(e) => handleControlLimitsChange('range', 'centerLine', e.target.value)}
                    placeholder="Center line (R̄)"
                  />
                </div>
                <div className={styles.limitRow}>
                  <label className={styles.limitLabel}>LCL</label>
                  <input
                    type="text"
                    className={styles.limitInput}
                    value={controlChartData.controlLimits.range.lcl}
                    onChange={(e) => handleControlLimitsChange('range', 'lcl', e.target.value)}
                    placeholder="Lower control limit"
                  />
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* SPC Rules Analysis Section */}
        <div className={styles.analysisCard}>
          <h2>SPC Rules Analysis</h2>
          <div className={styles.rulesGrid}>
            {[1, 2, 3, 4, 5, 6, 7, 8].map(ruleNumber => (
              <div key={ruleNumber} className={styles.ruleCard}>
                <div className={styles.ruleHeader}>
                  <label className={styles.ruleToggle}>
                    <input
                      type="checkbox"
                      checked={controlChartData.spcAnalysis.rules[`rule${ruleNumber}`].enabled}
                      onChange={(e) => handleRuleChange(ruleNumber, 'enabled', e.target.checked)}
                    />
                    <span className={styles.ruleNumber}>Rule {ruleNumber}</span>
                  </label>
                </div>
                <div className={styles.ruleDescription}>
                  {getRuleDescription(ruleNumber)}
                </div>
                <div className={styles.violationCount}>
                  Violations: {controlChartData.spcAnalysis.rules[`rule${ruleNumber}`].violations.length}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Pattern Analysis Section */}
        <div className={styles.analysisCard}>
          <h2>Pattern Analysis</h2>
          <div className={styles.patternGrid}>
            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel}>Trends</label>
              <textarea
                className={styles.textareaInput}
                value={controlChartData.spcAnalysis.patterns.trends.join('\n')}
                onChange={(e) => handleSPCAnalysisChange('patterns', 'trends', e.target.value.split('\n'))}
                placeholder="Describe any trending patterns observed"
                rows={2}
              />
            </div>
            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel}>Shifts</label>
              <textarea
                className={styles.textareaInput}
                value={controlChartData.spcAnalysis.patterns.shifts.join('\n')}
                onChange={(e) => handleSPCAnalysisChange('patterns', 'shifts', e.target.value.split('\n'))}
                placeholder="Describe any level shifts observed"
                rows={2}
              />
            </div>
            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel}>Cycles</label>
              <textarea
                className={styles.textareaInput}
                value={controlChartData.spcAnalysis.patterns.cycles.join('\n')}
                onChange={(e) => handleSPCAnalysisChange('patterns', 'cycles', e.target.value.split('\n'))}
                placeholder="Describe any cyclical patterns observed"
                rows={2}
              />
            </div>
            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel}>Mixtures</label>
              <textarea
                className={styles.textareaInput}
                value={controlChartData.spcAnalysis.patterns.mixtures.join('\n')}
                onChange={(e) => handleSPCAnalysisChange('patterns', 'mixtures', e.target.value.split('\n'))}
                placeholder="Describe any mixture patterns observed"
                rows={2}
              />
            </div>
          </div>
        </div>

        {/* Investigations & Actions Section */}
        <div className={styles.analysisCard}>
          <div className={styles.sectionHeader}>
            <h2>Investigations & Actions</h2>
            <button className={styles.addBtn} onClick={addInvestigation}>
              <i className="fas fa-plus"></i> Add Investigation
            </button>
          </div>
          
          <div className={styles.investigationsTable}>
            <table className={styles.actionTable}>
              <thead>
                <tr>
                  <th>Point/Issue</th>
                  <th>Root Cause</th>
                  <th>Action</th>
                  <th>Responsible</th>
                  <th>Due Date</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {controlChartData.actions.investigations.map((investigation) => (
                  <tr key={investigation.id}>
                    <td>
                      <input
                        type="text"
                        className={styles.tableInput}
                        value={investigation.point}
                        onChange={(e) => handleInvestigationChange(investigation.id, 'point', e.target.value)}
                        placeholder="Point or issue"
                      />
                    </td>
                    <td>
                      <input
                        type="text"
                        className={styles.tableInput}
                        value={investigation.rootCause}
                        onChange={(e) => handleInvestigationChange(investigation.id, 'rootCause', e.target.value)}
                        placeholder="Root cause"
                      />
                    </td>
                    <td>
                      <input
                        type="text"
                        className={styles.tableInput}
                        value={investigation.action}
                        onChange={(e) => handleInvestigationChange(investigation.id, 'action', e.target.value)}
                        placeholder="Corrective action"
                      />
                    </td>
                    <td>
                      <input
                        type="text"
                        className={styles.tableInput}
                        value={investigation.responsible}
                        onChange={(e) => handleInvestigationChange(investigation.id, 'responsible', e.target.value)}
                        placeholder="Who is responsible"
                      />
                    </td>
                    <td>
                      <input
                        type="date"
                        className={styles.tableInput}
                        value={investigation.dueDate}
                        onChange={(e) => handleInvestigationChange(investigation.id, 'dueDate', e.target.value)}
                      />
                    </td>
                    <td>
                      <select
                        className={styles.statusSelect}
                        value={investigation.status}
                        onChange={(e) => handleInvestigationChange(investigation.id, 'status', e.target.value)}
                      >
                        <option value="open">Open</option>
                        <option value="in-progress">In Progress</option>
                        <option value="completed">Completed</option>
                        <option value="closed">Closed</option>
                      </select>
                    </td>
                    <td>
                      <button
                        className={styles.removeBtn}
                        onClick={() => removeInvestigation(investigation.id)}
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

        {/* Process Capability Section */}
        <div className={styles.analysisCard}>
          <h2>Process Capability</h2>
          <div className={styles.capabilityGrid}>
            <div className={styles.capabilityIndices}>
              <h3>Capability Indices</h3>
              <div className={styles.indicesRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Cp</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={controlChartData.spcAnalysis.processCapability.cp}
                    onChange={(e) => handleSPCAnalysisChange('processCapability', 'cp', e.target.value)}
                    placeholder="Potential capability"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Cpk</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={controlChartData.spcAnalysis.processCapability.cpk}
                    onChange={(e) => handleSPCAnalysisChange('processCapability', 'cpk', e.target.value)}
                    placeholder="Actual capability"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Pp</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={controlChartData.spcAnalysis.processCapability.pp}
                    onChange={(e) => handleSPCAnalysisChange('processCapability', 'pp', e.target.value)}
                    placeholder="Performance potential"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Ppk</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={controlChartData.spcAnalysis.processCapability.ppk}
                    onChange={(e) => handleSPCAnalysisChange('processCapability', 'ppk', e.target.value)}
                    placeholder="Performance actual"
                  />
                </div>
              </div>
            </div>
            
            <div className={styles.sigmaLevel}>
              <h3>Process Performance</h3>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Sigma Level</label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={controlChartData.spcAnalysis.processCapability.sigma}
                  onChange={(e) => handleSPCAnalysisChange('processCapability', 'sigma', e.target.value)}
                  placeholder="Process sigma level"
                />
              </div>
            </div>
          </div>
        </div>

        {/* Documentation & Summary Section (LAST CONTENT BLOCK) */}
        <div className={styles.analysisCard} style={{ marginBottom: 0 }}>
          <h2>Documentation & Summary</h2>
          <div className={styles.documentationGrid}>
            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel}>
                Recommendations <span className={styles.required}>*</span>
              </label>
              <textarea
                className={styles.textareaInput}
                value={controlChartData.actions.recommendations}
                onChange={(e) => handleActionsChange('recommendations', e.target.value)}
                placeholder="What actions or improvements are recommended based on this control chart analysis?"
                rows={3}
              />
            </div>
            <div className={styles.fieldRow}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Next Review Date</label>
                <input
                  type="date"
                  className={styles.textInput}
                  value={controlChartData.actions.nextReview}
                  onChange={(e) => handleActionsChange('nextReview', e.target.value)}
                />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Approver</label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={controlChartData.actions.approver}
                  onChange={(e) => handleActionsChange('approver', e.target.value)}
                  placeholder="Who approved this analysis?"
                />
              </div>
            </div>
          </div>
        </div>

        {/* Keep this wrapper INSIDE mainContent and flush */}
        <div style={{ margin: 0, padding: 0 }}>
          <ResourcePageWrapper 
            pageName="Control Chart"
            toolName="Control Chart"
            adminSettings={adminSettings}
          />
        </div>
      </div>
    </div>
  );
};

// Helper function for SPC rule descriptions
const getRuleDescription = (ruleNumber) => {
  const descriptions = {
    1: "One point beyond the control limits",
    2: "Nine points in a row on same side of center line",
    3: "Six points in a row trending up or down",
    4: "Fourteen points in a row alternating up and down",
    5: "Two out of three points beyond 2σ from center line",
    6: "Four out of five points beyond 1σ from center line",
    7: "Fifteen points in a row within 1σ of center line",
    8: "Eight points in a row beyond 1σ from center line"
  };
  return descriptions[ruleNumber] || "";
};

export default ControlChart;
