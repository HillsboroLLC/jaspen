import React, { useState, useEffect } from 'react';
import ResourcePageWrapper from '../../All/components/ResourcePageWrapper';
import { useAdminSettings } from '../context/AdminContext';
import styles from './Histogram.module.css';

const Histogram = () => {
  const { adminSettings } = useAdminSettings();

  // Histogram structure
  const [histogramData, setHistogramData] = useState({
    // Analysis Information
    analysisTitle: '',
    analyst: '',
    dateCreated: new Date().toISOString().split('T')[0],
    lastUpdated: new Date().toISOString().split('T')[0],
    
    // Analysis Setup
    analysisSetup: {
      purpose: '',
      dataSource: '',
      sampleSize: '',
      timeframe: '',
      variable: '',
      unit: ''
    },
    
    // Data Input
    dataInput: {
      method: 'manual', // 'manual', 'import', 'paste'
      rawData: [],
      pastedData: ''
    },
    
    // Histogram Configuration
    configuration: {
      binMethod: 'auto', // 'auto', 'manual', 'sturges', 'scott', 'freedman'
      numberOfBins: 10,
      binWidth: '',
      startValue: '',
      endValue: '',
      showNormalCurve: false,
      showMean: true,
      showMedian: true,
      showMode: true,
      showOutliers: true,
      title: '',
      xAxisLabel: '',
      yAxisLabel: 'Frequency'
    },
    
    // Statistical Analysis
    statistics: {
      descriptive: {
        count: 0,
        mean: 0,
        median: 0,
        mode: 0,
        standardDeviation: 0,
        variance: 0,
        range: 0,
        minimum: 0,
        maximum: 0,
        q1: 0,
        q3: 0,
        iqr: 0,
        skewness: 0,
        kurtosis: 0
      },
      distribution: {
        shape: '',
        normalityTest: '',
        pValue: 0,
        isNormal: false,
        outliers: [],
        bins: []
      }
    },
    
    // Process Capability (if applicable)
    processCapability: {
      enabled: false,
      lsl: '',
      usl: '',
      target: '',
      cp: 0,
      cpk: 0,
      pp: 0,
      ppk: 0,
      sigmaLevel: 0,
      defectRate: 0,
      yield: 0
    },
    
    // Insights & Interpretation
    insights: {
      distributionAnalysis: '',
      processInsights: '',
      recommendations: '',
      actionItems: [],
      followUpRequired: false,
      nextSteps: ''
    },
    
    // Documentation
    documentation: {
      dataQuality: '',
      limitations: '',
      assumptions: '',
      methodology: '',
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
      if (histogramData.analysisTitle) completedFields++;
      if (histogramData.analyst) completedFields++;
      if (histogramData.analysisSetup.purpose) completedFields++;

      // Setup (3 fields)
      totalFields += 3;
      if (histogramData.analysisSetup.dataSource) completedFields++;
      if (histogramData.analysisSetup.variable) completedFields++;
      if (histogramData.dataInput.rawData.length > 0 || histogramData.dataInput.pastedData) completedFields++;

      // Configuration (2 fields)
      totalFields += 2;
      if (histogramData.configuration.title) completedFields++;
      if (histogramData.configuration.xAxisLabel) completedFields++;

      // Analysis (1 field)
      totalFields += 1;
      if (histogramData.insights.distributionAnalysis) completedFields++;

      // Documentation (1 field)
      totalFields += 1;
      if (histogramData.documentation.methodology) completedFields++;

      const percentage = totalFields > 0 ? Math.round((completedFields / totalFields) * 100) : 0;
      setCompletionPercentage(percentage);
    };

    calculateCompletion();
  }, [histogramData]);

  // Handle basic info changes
  const handleBasicInfoChange = (field, value) => {
    setHistogramData(prev => ({
      ...prev,
      [field]: value,
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Handle setup changes
  const handleSetupChange = (field, value) => {
    setHistogramData(prev => ({
      ...prev,
      analysisSetup: {
        ...prev.analysisSetup,
        [field]: value
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Handle data input changes
  const handleDataInputChange = (field, value) => {
    setHistogramData(prev => ({
      ...prev,
      dataInput: {
        ...prev.dataInput,
        [field]: value
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Handle configuration changes
  const handleConfigurationChange = (field, value) => {
    setHistogramData(prev => ({
      ...prev,
      configuration: {
        ...prev.configuration,
        [field]: value
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Handle process capability changes
  const handleCapabilityChange = (field, value) => {
    setHistogramData(prev => ({
      ...prev,
      processCapability: {
        ...prev.processCapability,
        [field]: value
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Handle insights changes
  const handleInsightsChange = (field, value) => {
    setHistogramData(prev => ({
      ...prev,
      insights: {
        ...prev.insights,
        [field]: value
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Handle documentation changes
  const handleDocumentationChange = (field, value) => {
    setHistogramData(prev => ({
      ...prev,
      documentation: {
        ...prev.documentation,
        [field]: value
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Add data point
  const addDataPoint = () => {
    const newDataPoint = {
      id: Date.now(),
      value: '',
      label: '',
      category: ''
    };
    
    setHistogramData(prev => ({
      ...prev,
      dataInput: {
        ...prev.dataInput,
        rawData: [...prev.dataInput.rawData, newDataPoint]
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Remove data point
  const removeDataPoint = (pointId) => {
    setHistogramData(prev => ({
      ...prev,
      dataInput: {
        ...prev.dataInput,
        rawData: prev.dataInput.rawData.filter(point => point.id !== pointId)
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Handle data point changes
  const handleDataPointChange = (pointId, field, value) => {
    setHistogramData(prev => ({
      ...prev,
      dataInput: {
        ...prev.dataInput,
        rawData: prev.dataInput.rawData.map(point =>
          point.id === pointId ? { ...point, [field]: value } : point
        )
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Process pasted data
  const processPastedData = () => {
    if (!histogramData.dataInput.pastedData.trim()) return;
    
    const lines = histogramData.dataInput.pastedData.trim().split('\n');
    const newDataPoints = lines.map((line, index) => {
      const value = parseFloat(line.trim());
      return {
        id: Date.now() + index,
        value: isNaN(value) ? line.trim() : value,
        label: `Point ${index + 1}`,
        category: ''
      };
    }).filter(point => point.value !== '');
    
    setHistogramData(prev => ({
      ...prev,
      dataInput: {
        ...prev.dataInput,
        rawData: [...prev.dataInput.rawData, ...newDataPoints],
        pastedData: ''
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Calculate statistics (simplified for demo)
  const calculateStatistics = () => {
    const values = histogramData.dataInput.rawData
      .map(point => parseFloat(point.value))
      .filter(value => !isNaN(value))
      .sort((a, b) => a - b);
    
    if (values.length === 0) return;
    
    const count = values.length;
    const sum = values.reduce((acc, val) => acc + val, 0);
    const mean = sum / count;
    const median = count % 2 === 0 
      ? (values[count / 2 - 1] + values[count / 2]) / 2 
      : values[Math.floor(count / 2)];
    const minimum = values[0];
    const maximum = values[count - 1];
    const range = maximum - minimum;
    
    const variance = values.reduce((acc, val) => acc + Math.pow(val - mean, 2), 0) / count;
    const standardDeviation = Math.sqrt(variance);
    
    const q1Index = Math.floor(count * 0.25);
    const q3Index = Math.floor(count * 0.75);
    const q1 = values[q1Index];
    const q3 = values[q3Index];
    const iqr = q3 - q1;
    
    setHistogramData(prev => ({
      ...prev,
      statistics: {
        ...prev.statistics,
        descriptive: {
          count,
          mean: Math.round(mean * 100) / 100,
          median: Math.round(median * 100) / 100,
          mode: 0,
          standardDeviation: Math.round(standardDeviation * 100) / 100,
          variance: Math.round(variance * 100) / 100,
          range: Math.round(range * 100) / 100,
          minimum: Math.round(minimum * 100) / 100,
          maximum: Math.round(maximum * 100) / 100,
          q1: Math.round(q1 * 100) / 100,
          q3: Math.round(q3 * 100) / 100,
          iqr: Math.round(iqr * 100) / 100,
          skewness: 0,
          kurtosis: 0
        }
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Add action item
  const addActionItem = () => {
    const newAction = {
      id: Date.now(),
      action: '',
      owner: '',
      dueDate: '',
      priority: 'medium',
      status: 'planned'
    };
    
    setHistogramData(prev => ({
      ...prev,
      insights: {
        ...prev.insights,
        actionItems: [...prev.insights.actionItems, newAction]
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Remove action item
  const removeActionItem = (actionId) => {
    setHistogramData(prev => ({
      ...prev,
      insights: {
        ...prev.insights,
        actionItems: prev.insights.actionItems.filter(action => action.id !== actionId)
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Handle action item changes
  const handleActionItemChange = (actionId, field, value) => {
    setHistogramData(prev => ({
      ...prev,
      insights: {
        ...prev.insights,
        actionItems: prev.insights.actionItems.map(action =>
          action.id === actionId ? { ...action, [field]: value } : action
        )
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Save / Export
  const handleSave = () => {
    console.log('Saving Histogram Analysis draft:', histogramData);
  };

  const handleExport = () => {
    console.log('Exporting Histogram Analysis to PDF:', histogramData);
  };

  return (
    <ResourcePageWrapper
      pageName="Histogram Analysis"
      toolName="histogram"
      adminSettings={adminSettings}
    >
      <div className={styles.rcaContainer} style={{ paddingBottom: 0 }}>
        {/* Header */}
        <div className={styles.header}>
          <div className={styles.headerContent}>
            <h1>Histogram Analysis</h1>
            <div className={styles.progressSection}>
              <div className={styles.progressBar}>
                <div
                  className={styles.progressFill}
                  style={{
                    width: `${completionPercentage}%`,
                    backgroundImage: 'none',
                    backgroundColor: '#161f3b'
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
                  value={histogramData.analysisTitle}
                  onChange={(e) => handleBasicInfoChange('analysisTitle', e.target.value)}
                  placeholder="Enter the title for your histogram analysis"
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
                    value={histogramData.analyst}
                    onChange={(e) => handleBasicInfoChange('analyst', e.target.value)}
                    placeholder="Who is conducting this analysis?"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Date Created</label>
                  <input
                    type="date"
                    className={styles.textInput}
                    value={histogramData.dateCreated}
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
                  value={histogramData.analysisSetup.purpose}
                  onChange={(e) => handleSetupChange('purpose', e.target.value)}
                  placeholder="What is the purpose of this histogram analysis?"
                  rows={2}
                />
              </div>

              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Data Source</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={histogramData.analysisSetup.dataSource}
                    onChange={(e) => handleSetupChange('dataSource', e.target.value)}
                    placeholder="Where does the data come from?"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Sample Size</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={histogramData.analysisSetup.sampleSize}
                    onChange={(e) => handleSetupChange('sampleSize', e.target.value)}
                    placeholder="How many data points?"
                  />
                </div>
              </div>

              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Variable</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={histogramData.analysisSetup.variable}
                    onChange={(e) => handleSetupChange('variable', e.target.value)}
                    placeholder="What variable are you measuring?"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Unit</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={histogramData.analysisSetup.unit}
                    onChange={(e) => handleSetupChange('unit', e.target.value)}
                    placeholder="Unit of measurement"
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Data Input Section */}
          <div className={styles.analysisCard}>
            <h2>Data Input</h2>
            <div className={styles.dataInputSection}>
              <div className={styles.inputMethodSelector}>
                <label className={styles.fieldLabel}>Input Method</label>
                <div className={styles.methodButtons}>
                  <button 
                    className={`${styles.methodBtn} ${histogramData.dataInput.method === 'manual' ? styles.active : ''}`}
                    onClick={() => handleDataInputChange('method', 'manual')}
                  >
                    Manual Entry
                  </button>
                  <button 
                    className={`${styles.methodBtn} ${histogramData.dataInput.method === 'paste' ? styles.active : ''}`}
                    onClick={() => handleDataInputChange('method', 'paste')}
                  >
                    Paste Data
                  </button>
                </div>
              </div>
              
              {histogramData.dataInput.method === 'manual' && (
                <div className={styles.manualInput}>
                  <div className={styles.sectionHeader}>
                    <h3>Manual Data Entry</h3>
                    <button className={styles.addBtn} onClick={addDataPoint}>
                      <i className="fas fa-plus"></i> Add Data Point
                    </button>
                  </div>
                  
                  <div className={styles.dataTable}>
                    <table className={styles.dataEntryTable}>
                      <thead>
                        <tr>
                          <th>Value</th>
                          <th>Label</th>
                          <th>Category</th>
                          <th>Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {histogramData.dataInput.rawData.map((point) => (
                          <tr key={point.id}>
                            <td>
                              <input
                                type="number"
                                step="any"
                                className={styles.tableInput}
                                value={point.value}
                                onChange={(e) => handleDataPointChange(point.id, 'value', e.target.value)}
                                placeholder="Value"
                              />
                            </td>
                            <td>
                              <input
                                type="text"
                                className={styles.tableInput}
                                value={point.label}
                                onChange={(e) => handleDataPointChange(point.id, 'label', e.target.value)}
                                placeholder="Label"
                              />
                            </td>
                            <td>
                              <input
                                type="text"
                                className={styles.tableInput}
                                value={point.category}
                                onChange={(e) => handleDataPointChange(point.id, 'category', e.target.value)}
                                placeholder="Category"
                              />
                            </td>
                            <td>
                              <button
                                className={styles.removeBtn}
                                onClick={() => removeDataPoint(point.id)}
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
              )}
              
              {histogramData.dataInput.method === 'paste' && (
                <div className={styles.pasteInput}>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Paste Data (one value per line)</label>
                    <textarea
                      className={styles.textareaInput}
                      value={histogramData.dataInput.pastedData}
                      onChange={(e) => handleDataInputChange('pastedData', e.target.value)}
                      placeholder="Paste your data here, one value per line..."
                      rows={8}
                    />
                  </div>
                  <button className={styles.processBtn} onClick={processPastedData}>
                    <i className="fas fa-upload"></i> Process Data
                  </button>
                </div>
              )}
              
              <div className={styles.dataStats}>
                <div className={styles.statCard}>
                  <span className={styles.statLabel}>Data Points</span>
                  <span className={styles.statValue}>{histogramData.dataInput.rawData.length}</span>
                </div>
                <button className={styles.calculateBtn} onClick={calculateStatistics}>
                  <i className="fas fa-calculator"></i> Calculate Statistics
                </button>
              </div>
            </div>
          </div>

          {/* Histogram Configuration Section */}
          <div className={styles.analysisCard}>
            <h2>Histogram Configuration</h2>
            <div className={styles.configurationGrid}>
              <div className={styles.binConfiguration}>
                <h3>Bin Configuration</h3>
                <div className={styles.fieldRow}>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Bin Method</label>
                    <select
                      className={styles.selectInput}
                      value={histogramData.configuration.binMethod}
                      onChange={(e) => handleConfigurationChange('binMethod', e.target.value)}
                    >
                      <option value="auto">Automatic</option>
                      <option value="manual">Manual</option>
                      <option value="sturges">Sturges' Rule</option>
                      <option value="scott">Scott's Rule</option>
                      <option value="freedman">Freedman-Diaconis</option>
                    </select>
                  </div>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Number of Bins</label>
                    <input
                      type="number"
                      min="1"
                      max="50"
                      className={styles.textInput}
                      value={histogramData.configuration.numberOfBins}
                      onChange={(e) => handleConfigurationChange('numberOfBins', parseInt(e.target.value))}
                      disabled={histogramData.configuration.binMethod !== 'manual'}
                    />
                  </div>
                </div>
                
                <div className={styles.fieldRow}>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Start Value</label>
                    <input
                      type="number"
                      step="any"
                      className={styles.textInput}
                      value={histogramData.configuration.startValue}
                      onChange={(e) => handleConfigurationChange('startValue', e.target.value)}
                      placeholder="Auto-calculated"
                    />
                  </div>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>End Value</label>
                    <input
                      type="number"
                      step="any"
                      className={styles.textInput}
                      value={histogramData.configuration.endValue}
                      onChange={(e) => handleConfigurationChange('endValue', e.target.value)}
                      placeholder="Auto-calculated"
                    />
                  </div>
                </div>
              </div>
              
              <div className={styles.displayOptions}>
                <h3>Display Options</h3>
                <div className={styles.checkboxGrid}>
                  <label className={styles.checkboxLabel}>
                    <input
                      type="checkbox"
                      checked={histogramData.configuration.showNormalCurve}
                      onChange={(e) => handleConfigurationChange('showNormalCurve', e.target.checked)}
                    />
                    Show Normal Curve Overlay
                  </label>
                  <label className={styles.checkboxLabel}>
                    <input
                      type="checkbox"
                      checked={histogramData.configuration.showMean}
                      onChange={(e) => handleConfigurationChange('showMean', e.target.checked)}
                    />
                    Show Mean Line
                  </label>
                  <label className={styles.checkboxLabel}>
                    <input
                      type="checkbox"
                      checked={histogramData.configuration.showMedian}
                      onChange={(e) => handleConfigurationChange('showMedian', e.target.checked)}
                    />
                    Show Median Line
                  </label>
                  <label className={styles.checkboxLabel}>
                    <input
                      type="checkbox"
                      checked={histogramData.configuration.showMode}
                      onChange={(e) => handleConfigurationChange('showMode', e.target.checked)}
                    />
                    Show Mode
                  </label>
                  <label className={styles.checkboxLabel}>
                    <input
                      type="checkbox"
                      checked={histogramData.configuration.showOutliers}
                      onChange={(e) => handleConfigurationChange('showOutliers', e.target.checked)}
                    />
                    Highlight Outliers
                  </label>
                </div>
              </div>
              
              <div className={styles.chartLabels}>
                <h3>Chart Labels</h3>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Chart Title</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={histogramData.configuration.title}
                    onChange={(e) => handleConfigurationChange('title', e.target.value)}
                    placeholder="Histogram title"
                  />
                </div>
                <div className={styles.fieldRow}>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>X-Axis Label</label>
                    <input
                      type="text"
                      className={styles.textInput}
                      value={histogramData.configuration.xAxisLabel}
                      onChange={(e) => handleConfigurationChange('xAxisLabel', e.target.value)}
                      placeholder="X-axis label"
                    />
                  </div>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Y-Axis Label</label>
                    <input
                      type="text"
                      className={styles.textInput}
                      value={histogramData.configuration.yAxisLabel}
                      onChange={(e) => handleConfigurationChange('yAxisLabel', e.target.value)}
                      placeholder="Y-axis label"
                    />
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Statistical Analysis Section */}
          <div className={styles.analysisCard}>
            <h2>Statistical Analysis</h2>
            <div className={styles.statisticsGrid}>
              <div className={styles.descriptiveStats}>
                <h3>Descriptive Statistics</h3>
                <div className={styles.statsTable}>
                  <table className={styles.statisticsTable}>
                    <tbody>
                      <tr><td className={styles.statLabel}>Count</td><td className={styles.statValue}>{histogramData.statistics.descriptive.count}</td></tr>
                      <tr><td className={styles.statLabel}>Mean</td><td className={styles.statValue}>{histogramData.statistics.descriptive.mean}</td></tr>
                      <tr><td className={styles.statLabel}>Median</td><td className={styles.statValue}>{histogramData.statistics.descriptive.median}</td></tr>
                      <tr><td className={styles.statLabel}>Standard Deviation</td><td className={styles.statValue}>{histogramData.statistics.descriptive.standardDeviation}</td></tr>
                      <tr><td className={styles.statLabel}>Variance</td><td className={styles.statValue}>{histogramData.statistics.descriptive.variance}</td></tr>
                      <tr><td className={styles.statLabel}>Range</td><td className={styles.statValue}>{histogramData.statistics.descriptive.range}</td></tr>
                      <tr><td className={styles.statLabel}>Minimum</td><td className={styles.statValue}>{histogramData.statistics.descriptive.minimum}</td></tr>
                      <tr><td className={styles.statLabel}>Maximum</td><td className={styles.statValue}>{histogramData.statistics.descriptive.maximum}</td></tr>
                      <tr><td className={styles.statLabel}>Q1 (25th percentile)</td><td className={styles.statValue}>{histogramData.statistics.descriptive.q1}</td></tr>
                      <tr><td className={styles.statLabel}>Q3 (75th percentile)</td><td className={styles.statValue}>{histogramData.statistics.descriptive.q3}</td></tr>
                      <tr><td className={styles.statLabel}>IQR</td><td className={styles.statValue}>{histogramData.statistics.descriptive.iqr}</td></tr>
                    </tbody>
                  </table>
                </div>
              </div>
              
              <div className={styles.distributionAnalysis}>
                <h3>Distribution Analysis</h3>
                <div className={styles.distributionCard}>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Distribution Shape</label>
                    <select
                      className={styles.selectInput}
                      value={histogramData.statistics.distribution.shape}
                      onChange={(e) => setHistogramData(prev => ({
                        ...prev,
                        statistics: {
                          ...prev.statistics,
                          distribution: {
                            ...prev.statistics.distribution,
                            shape: e.target.value
                          }
                        }
                      }))}
                    >
                      <option value="">Select shape</option>
                      <option value="normal">Normal</option>
                      <option value="skewed-left">Skewed Left</option>
                      <option value="skewed-right">Skewed Right</option>
                      <option value="bimodal">Bimodal</option>
                      <option value="uniform">Uniform</option>
                      <option value="other">Other</option>
                    </select>
                  </div>
                  
                  <div className={styles.fieldRow}>
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Normality Test</label>
                      <select
                        className={styles.selectInput}
                        value={histogramData.statistics.distribution.normalityTest}
                        onChange={(e) => setHistogramData(prev => ({
                          ...prev,
                          statistics: {
                            ...prev.statistics,
                            distribution: {
                              ...prev.statistics.distribution,
                              normalityTest: e.target.value
                            }
                          }
                        }))}
                      >
                        <option value="">Select test</option>
                        <option value="shapiro-wilk">Shapiro-Wilk</option>
                        <option value="anderson-darling">Anderson-Darling</option>
                        <option value="kolmogorov-smirnov">Kolmogorov-Smirnov</option>
                        <option value="jarque-bera">Jarque-Bera</option>
                      </select>
                    </div>
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>P-Value</label>
                      <input
                        type="number"
                        step="0.001"
                        min="0"
                        max="1"
                        className={styles.textInput}
                        value={histogramData.statistics.distribution.pValue}
                        onChange={(e) => setHistogramData(prev => ({
                          ...prev,
                          statistics: {
                            ...prev.statistics,
                            distribution: {
                              ...prev.statistics.distribution,
                              pValue: parseFloat(e.target.value)
                            }
                          }
                        }))}
                        placeholder="P-value"
                      />
                    </div>
                  </div>
                  
                  <div className={styles.normalityResult}>
                    <label className={styles.checkboxLabel}>
                      <input
                        type="checkbox"
                        checked={histogramData.statistics.distribution.isNormal}
                        onChange={(e) => setHistogramData(prev => ({
                          ...prev,
                          statistics: {
                            ...prev.statistics,
                            distribution: {
                              ...prev.statistics.distribution,
                              isNormal: e.target.checked
                            }
                          }
                        }))}
                      />
                      Data is approximately normal (p &gt; 0.05)
                    </label>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Process Capability Section */}
          <div className={styles.analysisCard}>
            <h2>Process Capability Analysis</h2>
            <div className={styles.capabilitySection}>
              <div className={styles.capabilityToggle}>
                <label className={styles.checkboxLabel}>
                  <input
                    type="checkbox"
                    checked={histogramData.processCapability.enabled}
                    onChange={(e) => handleCapabilityChange('enabled', e.target.checked)}
                  />
                  Enable Process Capability Analysis
                </label>
              </div>
              
              {histogramData.processCapability.enabled && (
                <div className={styles.capabilityContent}>
                  <div className={styles.specificationLimits}>
                    <h3>Specification Limits</h3>
                    <div className={styles.fieldRow}>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Lower Specification Limit (LSL)</label>
                        <input
                          type="number"
                          step="any"
                          className={styles.textInput}
                          value={histogramData.processCapability.lsl}
                          onChange={(e) => handleCapabilityChange('lsl', e.target.value)}
                          placeholder="LSL"
                        />
                      </div>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Target Value</label>
                        <input
                          type="number"
                          step="any"
                          className={styles.textInput}
                          value={histogramData.processCapability.target}
                          onChange={(e) => handleCapabilityChange('target', e.target.value)}
                          placeholder="Target"
                        />
                      </div>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Upper Specification Limit (USL)</label>
                        <input
                          type="number"
                          step="any"
                          className={styles.textInput}
                          value={histogramData.processCapability.usl}
                          onChange={(e) => handleCapabilityChange('usl', e.target.value)}
                          placeholder="USL"
                        />
                      </div>
                    </div>
                  </div>
                  
                  <div className={styles.capabilityIndices}>
                    <h3>Capability Indices</h3>
                    <div className={styles.indicesGrid}>
                      <div className={styles.indexCard}>
                        <span className={styles.indexLabel}>Cp</span>
                        <span className={styles.indexValue}>{histogramData.processCapability.cp}</span>
                        <span className={styles.indexDescription}>Potential Capability</span>
                      </div>
                      <div className={styles.indexCard}>
                        <span className={styles.indexLabel}>Cpk</span>
                        <span className={styles.indexValue}>{histogramData.processCapability.cpk}</span>
                        <span className={styles.indexDescription}>Actual Capability</span>
                      </div>
                      <div className={styles.indexCard}>
                        <span className={styles.indexLabel}>Pp</span>
                        <span className={styles.indexValue}>{histogramData.processCapability.pp}</span>
                        <span className={styles.indexDescription}>Process Performance</span>
                      </div>
                      <div className={styles.indexCard}>
                        <span className={styles.indexLabel}>Ppk</span>
                        <span className={styles.indexValue}>{histogramData.processCapability.ppk}</span>
                        <span className={styles.indexDescription}>Process Performance Index</span>
                      </div>
                      <div className={styles.indexCard}>
                        <span className={styles.indexLabel}>Sigma Level</span>
                        <span className={styles.indexValue}>{histogramData.processCapability.sigmaLevel}</span>
                        <span className={styles.indexDescription}>Process Sigma</span>
                      </div>
                      <div className={styles.indexCard}>
                        <span className={styles.indexLabel}>Yield</span>
                        <span className={styles.indexValue}>{histogramData.processCapability.yield}%</span>
                        <span className={styles.indexDescription}>Process Yield</span>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Insights & Interpretation Section */}
          <div className={styles.analysisCard}>
            <h2>Insights & Interpretation</h2>
            <div className={styles.insightsSection}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Distribution Analysis <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={histogramData.insights.distributionAnalysis}
                  onChange={(e) => handleInsightsChange('distributionAnalysis', e.target.value)}
                  placeholder="What does the distribution shape tell you about the process?"
                  rows={3}
                />
              </div>
              
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Process Insights</label>
                <textarea
                  className={styles.textareaInput}
                  value={histogramData.insights.processInsights}
                  onChange={(e) => handleInsightsChange('processInsights', e.target.value)}
                  placeholder="What insights about the process can you derive from this histogram?"
                  rows={3}
                />
              </div>
              
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Recommendations</label>
                <textarea
                  className={styles.textareaInput}
                  value={histogramData.insights.recommendations}
                  onChange={(e) => handleInsightsChange('recommendations', e.target.value)}
                  placeholder="What recommendations do you have based on this analysis?"
                  rows={3}
                />
              </div>
              
              <div className={styles.actionItemsSection}>
                <div className={styles.sectionHeader}>
                  <h3>Action Items</h3>
                  <button className={styles.addBtn} onClick={addActionItem}>
                    <i className="fas fa-plus"></i> Add Action
                  </button>
                </div>
                
                <div className={styles.actionItemsList}>
                  {histogramData.insights.actionItems.map((action) => (
                    <div key={action.id} className={styles.actionItem}>
                      <input
                        type="text"
                        className={styles.actionInput}
                        value={action.action}
                        onChange={(e) => handleActionItemChange(action.id, 'action', e.target.value)}
                        placeholder="Action item"
                      />
                      <input
                        type="text"
                        className={styles.actionInput}
                        value={action.owner}
                        onChange={(e) => handleActionItemChange(action.id, 'owner', e.target.value)}
                        placeholder="Owner"
                      />
                      <input
                        type="date"
                        className={styles.actionInput}
                        value={action.dueDate}
                        onChange={(e) => handleActionItemChange(action.id, 'dueDate', e.target.value)}
                      />
                      <select
                        className={styles.actionSelect}
                        value={action.priority}
                        onChange={(e) => handleActionItemChange(action.id, 'priority', e.target.value)}
                      >
                        <option value="low">Low</option>
                        <option value="medium">Medium</option>
                        <option value="high">High</option>
                      </select>
                      <button
                        className={styles.removeBtn}
                        onClick={() => removeActionItem(action.id)}
                      >
                        <i className="fas fa-times"></i>
                      </button>
                    </div>
                  ))}
                </div>
              </div>
              
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Follow-up Required</label>
                  <label className={styles.checkboxLabel}>
                    <input
                      type="checkbox"
                      checked={histogramData.insights.followUpRequired}
                      onChange={(e) => handleInsightsChange('followUpRequired', e.target.checked)}
                    />
                    Additional analysis or data collection needed
                  </label>
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Next Steps</label>
                  <textarea
                    className={styles.textareaInput}
                    value={histogramData.insights.nextSteps}
                    onChange={(e) => handleInsightsChange('nextSteps', e.target.value)}
                    placeholder="What are the next steps?"
                    rows={2}
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Documentation Section (last card -> no bottom margin) */}
          <div className={styles.analysisCard} style={{ marginBottom: 0 }}>
            <h2>Documentation</h2>
            <div className={styles.documentationGrid}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Methodology <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={histogramData.documentation.methodology}
                  onChange={(e) => handleDocumentationChange('methodology', e.target.value)}
                  placeholder="Describe the methodology used for data collection and analysis"
                  rows={3}
                />
              </div>
              
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Data Quality Assessment</label>
                <textarea
                  className={styles.textareaInput}
                  value={histogramData.documentation.dataQuality}
                  onChange={(e) => handleDocumentationChange('dataQuality', e.target.value)}
                  placeholder="Assess the quality and reliability of the data"
                  rows={3}
                />
              </div>
              
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Limitations</label>
                <textarea
                  className={styles.textareaInput}
                  value={histogramData.documentation.limitations}
                  onChange={(e) => handleDocumentationChange('limitations', e.target.value)}
                  placeholder="What are the limitations of this analysis?"
                  rows={3}
                />
              </div>
              
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Assumptions</label>
                  <textarea
                    className={styles.textareaInput}
                    value={histogramData.documentation.assumptions}
                    onChange={(e) => handleDocumentationChange('assumptions', e.target.value)}
                    placeholder="What assumptions were made?"
                    rows={2}
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Approver</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={histogramData.documentation.approver}
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

export default Histogram;
