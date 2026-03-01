import React, { useState, useEffect } from 'react';
import { useAdminSettings } from '../context/AdminContext';
import ResourcePageWrapper from '../../All/components/ResourcePageWrapper';
import styles from './RunChart.module.css';

const RunChart = () => {
  const { adminSettings } = useAdminSettings();

  // Run Chart structure
  const [chartData, setChartData] = useState({
    // Basic Information
    chartName: '',
    analyst: '',
    dateCreated: new Date().toISOString().split('T')[0],
    lastUpdated: new Date().toISOString().split('T')[0],
    version: '1.0',
    
    // Chart Configuration
    chartConfig: {
      variable: '',
      units: '',
      dataSource: '',
      collectionMethod: '',
      frequency: '',
      timeFrame: '',
      yAxisLabel: '',
      xAxisLabel: 'Time/Sequence'
    },
    
    // Data Points
    dataPoints: [],
    
    // Chart Analysis
    analysis: {
      centerLine: '',
      trend: '',
      patterns: '',
      shifts: '',
      runs: '',
      cycles: '',
      outliers: []
    },
    
    // Statistical Summary
    statistics: {
      count: 0,
      mean: 0,
      median: 0,
      standardDeviation: 0,
      range: 0,
      minimum: 0,
      maximum: 0
    },
    
    // Interpretation
    interpretation: {
      trendAnalysis: '',
      patternIdentification: '',
      processStability: '',
      recommendations: '',
      actionItems: []
    },
    
    // Context Information
    context: {
      processDescription: '',
      specialCauses: [],
      environmentalFactors: '',
      operationalChanges: ''
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
      if (chartData.chartName) completedFields++;
      if (chartData.analyst) completedFields++;
      if (chartData.chartConfig.variable) completedFields++;

      // Chart config (3 fields)
      totalFields += 3;
      if (chartData.chartConfig.units) completedFields++;
      if (chartData.chartConfig.dataSource) completedFields++;
      if (chartData.chartConfig.frequency) completedFields++;

      // Data points (1 field)
      totalFields += 1;
      if (chartData.dataPoints.length >= 10) completedFields++;

      // Analysis (1 field)
      totalFields += 1;
      if (chartData.analysis.centerLine) completedFields++;

      // Interpretation (1 field)
      totalFields += 1;
      if (chartData.interpretation.trendAnalysis) completedFields++;

      const percentage = totalFields > 0 ? Math.round((completedFields / totalFields) * 100) : 0;
      setCompletionPercentage(percentage);
    };

    calculateCompletion();
  }, [chartData]);

  // Calculate statistics when data points change
  useEffect(() => {
    if (chartData.dataPoints.length > 0) {
      const values = chartData.dataPoints
        .map(point => parseFloat(point.value))
        .filter(val => !isNaN(val));
      
      if (values.length > 0) {
        const sortedValues = [...values].sort((a, b) => a - b);
        const count = values.length;
        const sum = values.reduce((acc, val) => acc + val, 0);
        const mean = sum / count;
        const median = count % 2 === 0 
          ? (sortedValues[count / 2 - 1] + sortedValues[count / 2]) / 2
          : sortedValues[Math.floor(count / 2)];
        const variance = values.reduce((acc, val) => acc + Math.pow(val - mean, 2), 0) / count;
        const standardDeviation = Math.sqrt(variance);
        const minimum = Math.min(...values);
        const maximum = Math.max(...values);
        const range = maximum - minimum;

        setChartData(prev => ({
          ...prev,
          statistics: {
            count,
            mean: parseFloat(mean.toFixed(3)),
            median: parseFloat(median.toFixed(3)),
            standardDeviation: parseFloat(standardDeviation.toFixed(3)),
            range: parseFloat(range.toFixed(3)),
            minimum: parseFloat(minimum.toFixed(3)),
            maximum: parseFloat(maximum.toFixed(3))
          },
          analysis: {
            ...prev.analysis,
            centerLine: median.toFixed(3)
          },
          lastUpdated: new Date().toISOString().split('T')[0]
        }));
      }
    }
  }, [chartData.dataPoints]);

  // Handle basic info changes
  const handleBasicInfoChange = (field, value) => {
    setChartData(prev => ({
      ...prev,
      [field]: value,
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Handle chart config changes
  const handleChartConfigChange = (field, value) => {
    setChartData(prev => ({
      ...prev,
      chartConfig: {
        ...prev.chartConfig,
        [field]: value
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Handle analysis changes
  const handleAnalysisChange = (field, value) => {
    setChartData(prev => ({
      ...prev,
      analysis: {
        ...prev.analysis,
        [field]: value
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Handle interpretation changes
  const handleInterpretationChange = (field, value) => {
    setChartData(prev => ({
      ...prev,
      interpretation: {
        ...prev.interpretation,
        [field]: value
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Handle context changes
  const handleContextChange = (field, value) => {
    setChartData(prev => ({
      ...prev,
      context: {
        ...prev.context,
        [field]: value
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Add data point
  const addDataPoint = () => {
    const newDataPoint = {
      id: Date.now(),
      sequence: chartData.dataPoints.length + 1,
      timeStamp: '',
      value: '',
      notes: '',
      operator: '',
      conditions: ''
    };
    
    setChartData(prev => ({
      ...prev,
      dataPoints: [...prev.dataPoints, newDataPoint],
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Remove data point
  const removeDataPoint = (pointId) => {
    setChartData(prev => ({
      ...prev,
      dataPoints: prev.dataPoints
        .filter(point => point.id !== pointId)
        .map((point, index) => ({ ...point, sequence: index + 1 })),
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Handle data point changes
  const handleDataPointChange = (pointId, field, value) => {
    setChartData(prev => ({
      ...prev,
      dataPoints: prev.dataPoints.map(point =>
        point.id === pointId ? { ...point, [field]: value } : point
      ),
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Add outlier
  const addOutlier = () => {
    const newOutlier = {
      id: Date.now(),
      sequence: '',
      value: '',
      investigation: '',
      cause: '',
      action: ''
    };
    
    setChartData(prev => ({
      ...prev,
      analysis: {
        ...prev.analysis,
        outliers: [...prev.analysis.outliers, newOutlier]
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Remove outlier
  const removeOutlier = (outlierId) => {
    setChartData(prev => ({
      ...prev,
      analysis: {
        ...prev.analysis,
        outliers: prev.analysis.outliers.filter(outlier => outlier.id !== outlierId)
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Handle outlier changes
  const handleOutlierChange = (outlierId, field, value) => {
    setChartData(prev => ({
      ...prev,
      analysis: {
        ...prev.analysis,
        outliers: prev.analysis.outliers.map(outlier =>
          outlier.id === outlierId ? { ...outlier, [field]: value } : outlier
        )
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Add special cause
  const addSpecialCause = () => {
    const newCause = {
      id: Date.now(),
      timeFrame: '',
      description: '',
      impact: '',
      investigation: '',
      action: ''
    };
    
    setChartData(prev => ({
      ...prev,
      context: {
        ...prev.context,
        specialCauses: [...prev.context.specialCauses, newCause]
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Remove special cause
  const removeSpecialCause = (causeId) => {
    setChartData(prev => ({
      ...prev,
      context: {
        ...prev.context,
        specialCauses: prev.context.specialCauses.filter(cause => cause.id !== causeId)
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Handle special cause changes
  const handleSpecialCauseChange = (causeId, field, value) => {
    setChartData(prev => ({
      ...prev,
      context: {
        ...prev.context,
        specialCauses: prev.context.specialCauses.map(cause =>
          cause.id === causeId ? { ...cause, [field]: value } : cause
        )
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Add action item
  const addActionItem = () => {
    const newAction = {
      id: Date.now(),
      action: '',
      responsible: '',
      dueDate: '',
      priority: 'medium', // 'low', 'medium', 'high'
      status: 'open' // 'open', 'in-progress', 'completed'
    };
    
    setChartData(prev => ({
      ...prev,
      interpretation: {
        ...prev.interpretation,
        actionItems: [...prev.interpretation.actionItems, newAction]
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Remove action item
  const removeActionItem = (actionId) => {
    setChartData(prev => ({
      ...prev,
      interpretation: {
        ...prev.interpretation,
        actionItems: prev.interpretation.actionItems.filter(action => action.id !== actionId)
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Handle action item changes
  const handleActionItemChange = (actionId, field, value) => {
    setChartData(prev => ({
      ...prev,
      interpretation: {
        ...prev.interpretation,
        actionItems: prev.interpretation.actionItems.map(action =>
          action.id === actionId ? { ...action, [field]: value } : action
        )
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Save draft
  const handleSave = () => {
    console.log('Saving Run Chart draft:', chartData);
  };

  // Export PDF
  const handleExport = () => {
    console.log('Exporting Run Chart to PDF:', chartData);
  };

  return (
    <ResourcePageWrapper
      pageName="Run Chart Analysis"
      toolName="runChart"
      adminSettings={adminSettings}
    >
      <div className={styles.rcaContainer}>
        {/* Header - Exact match to other tools */}
        <div className={styles.header}>
          <div className={styles.headerContent}>
            <h1>Run Chart Analysis</h1>
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

        {/* Main Content (FULL WIDTH; chat removed; no two-column wrapper) */}
        <div className={styles.mainContent} style={{ display: 'block' }}>
          {/* Chart Information (full width) */}
          <div className={styles.processInfoCard}>
            <h2>Chart Information</h2>
            
            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel}>
                Chart Name <span className={styles.required}>*</span>
              </label>
              <input
                type="text"
                className={styles.textInput}
                value={chartData.chartName}
                onChange={(e) => handleBasicInfoChange('chartName', e.target.value)}
                placeholder="Enter the run chart name"
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
                  value={chartData.analyst}
                  onChange={(e) => handleBasicInfoChange('analyst', e.target.value)}
                  placeholder="Analyst name"
                />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Version
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={chartData.version}
                  onChange={(e) => handleBasicInfoChange('version', e.target.value)}
                  placeholder="Chart version"
                />
              </div>
            </div>

            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel}>
                Variable/Metric <span className={styles.required}>*</span>
              </label>
              <input
                type="text"
                className={styles.textInput}
                value={chartData.chartConfig.variable}
                onChange={(e) => handleChartConfigChange('variable', e.target.value)}
                placeholder="What variable are you measuring?"
              />
            </div>

            <div className={styles.fieldRow}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Units <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={chartData.chartConfig.units}
                  onChange={(e) => handleChartConfigChange('units', e.target.value)}
                  placeholder="Units of measurement"
                />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Collection Frequency <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={chartData.chartConfig.frequency}
                  onChange={(e) => handleChartConfigChange('frequency', e.target.value)}
                  placeholder="Daily, hourly, per batch, etc."
                />
              </div>
            </div>
          </div>

          {/* Chart Configuration Section */}
          <div className={styles.analysisCard}>
            <h2>Chart Configuration</h2>
            <div className={styles.chartConfigSection}>
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Data Source</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={chartData.chartConfig.dataSource}
                    onChange={(e) => handleChartConfigChange('dataSource', e.target.value)}
                    placeholder="Where does the data come from?"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Collection Method</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={chartData.chartConfig.collectionMethod}
                    onChange={(e) => handleChartConfigChange('collectionMethod', e.target.value)}
                    placeholder="How is data collected?"
                  />
                </div>
              </div>
              
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Time Frame</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={chartData.chartConfig.timeFrame}
                    onChange={(e) => handleChartConfigChange('timeFrame', e.target.value)}
                    placeholder="Analysis period (e.g., Jan 2024 - Mar 2024)"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Y-Axis Label</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={chartData.chartConfig.yAxisLabel}
                    onChange={(e) => handleChartConfigChange('yAxisLabel', e.target.value)}
                    placeholder="Y-axis description"
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Run Chart Visualization Section */}
          <div className={styles.analysisCard}>
            <h2>Run Chart Visualization</h2>
            <div className={styles.chartVisualizationSection}>
              <div className={styles.chartContainer}>
                <div className={styles.chartPlaceholder}>
                  <div className={styles.chartPlaceholderContent}>
                    <i className="fas fa-chart-line" style={{ fontSize: '3rem', color: 'var(--lss-gray-400)', marginBottom: '1rem' }}></i>
                    <h3>Run Chart Will Display Here</h3>
                    <p>Once you add data points and integrate with AI/Minitab, your run chart will be visualized in this area.</p>
                    <div className={styles.chartFeatures}>
                      <div className={styles.featureItem}>
                        <i className="fas fa-circle" style={{ color: 'var(--lss-primary)' }}></i>
                        <span>Data Points</span>
                      </div>
                      <div className={styles.featureItem}>
                        <i className="fas fa-minus" style={{ color: 'var(--lss-error)' }}></i>
                        <span>Median Line</span>
                      </div>
                      <div className={styles.featureItem}>
                        <i className="fas fa-exclamation-triangle" style={{ color: 'var(--lss-warning)' }}></i>
                        <span>Pattern Highlights</span>
                      </div>
                      <div className={styles.featureItem}>
                        <i className="fas fa-search" style={{ color: 'var(--lss-info)' }}></i>
                        <span>Interactive Zoom</span>
                      </div>
                    </div>
                  </div>
                </div>
                
                <div className={styles.chartControls}>
                  <div className={styles.controlGroup}>
                    <h4>Display Options</h4>
                    <div className={styles.controlOptions}>
                      <label className={styles.checkboxLabel}>
                        <input type="checkbox" defaultChecked />
                        <span>Show Median Line</span>
                      </label>
                      <label className={styles.checkboxLabel}>
                        <input type="checkbox" defaultChecked />
                        <span>Highlight Trends</span>
                      </label>
                      <label className={styles.checkboxLabel}>
                        <input type="checkbox" defaultChecked />
                        <span>Mark Shifts</span>
                      </label>
                      <label className={styles.checkboxLabel}>
                        <input type="checkbox" defaultChecked />
                        <span>Show Runs</span>
                      </label>
                      <label className={styles.checkboxLabel}>
                        <input type="checkbox" />
                        <span>Highlight Outliers</span>
                      </label>
                      <label className={styles.checkboxLabel}>
                        <input type="checkbox" />
                        <span>Show Cycles</span>
                      </label>
                    </div>
                  </div>
                  
                  <div className={styles.controlGroup}>
                    <h4>Chart Actions</h4>
                    <div className={styles.chartActions}>
                      <button className={styles.chartActionBtn} disabled>
                        <i className="fas fa-sync-alt"></i>
                        Generate Chart
                      </button>
                      <button className={styles.chartActionBtn} disabled>
                        <i className="fas fa-download"></i>
                        Export Chart
                      </button>
                      <button className={styles.chartActionBtn} disabled>
                        <i className="fas fa-expand-arrows-alt"></i>
                        Full Screen
                      </button>
                      <button className={styles.chartActionBtn} disabled>
                        <i className="fas fa-cog"></i>
                        Chart Settings
                      </button>
                    </div>
                  </div>
                </div>
              </div>
              
              <div className={styles.chartInfo}>
                <div className={styles.chartInfoCard}>
                  <h4>Chart Status</h4>
                  <div className={styles.statusItem}>
                    <span className={styles.statusLabel}>Data Points:</span>
                    <span className={styles.statusValue}>{chartData.dataPoints.length}</span>
                  </div>
                  <div className={styles.statusItem}>
                    <span className={styles.statusLabel}>Median:</span>
                    <span className={styles.statusValue}>{chartData.statistics.median || 'N/A'}</span>
                  </div>
                  <div className={styles.statusItem}>
                    <span className={styles.statusLabel}>Chart Ready:</span>
                    <span className={`${styles.statusValue} ${chartData.dataPoints.length >= 10 ? styles.statusReady : styles.statusNotReady}`}>
                      {chartData.dataPoints.length >= 10 ? 'Yes' : 'Need 10+ points'}
                    </span>
                  </div>
                </div>
                
                <div className={styles.chartInfoCard}>
                  <h4>Integration Status</h4>
                  <div className={styles.integrationStatus}>
                    <div className={styles.integrationItem}>
                      <i className="fas fa-robot" style={{ color: 'var(--lss-gray-400)' }}></i>
                      <span>AI Integration: Pending</span>
                    </div>
                    <div className={styles.integrationItem}>
                      <i className="fas fa-chart-bar" style={{ color: 'var(--lss-gray-400)' }}></i>
                      <span>Minitab Integration: Pending</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Data Collection Section */}
          <div className={styles.analysisCard}>
            <h2>Data Collection</h2>
            <div className={styles.dataCollectionSection}>
              <div className={styles.sectionHeader}>
                <p className={styles.sectionDescription}>
                  Enter your data points in chronological order. Minimum 10 points recommended for meaningful analysis.
                </p>
                <button className={styles.addBtn} onClick={addDataPoint}>
                  <i className="fas fa-plus"></i> Add Data Point
                </button>
              </div>
              
              <div className={styles.dataPointsTable}>
                <table className={styles.dataTable}>
                  <thead>
                    <tr>
                      <th>Sequence</th>
                      <th>Time/Date</th>
                      <th>Value</th>
                      <th>Operator</th>
                      <th>Conditions</th>
                      <th>Notes</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {chartData.dataPoints.map((point) => (
                      <tr key={point.id}>
                        <td>
                          <span className={styles.sequenceNumber}>{point.sequence}</span>
                        </td>
                        <td>
                          <input
                            type="text"
                            className={styles.tableInput}
                            value={point.timeStamp}
                            onChange={(e) => handleDataPointChange(point.id, 'timeStamp', e.target.value)}
                            placeholder="Date/time"
                          />
                        </td>
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
                            value={point.operator}
                            onChange={(e) => handleDataPointChange(point.id, 'operator', e.target.value)}
                            placeholder="Operator"
                          />
                        </td>
                        <td>
                          <input
                            type="text"
                            className={styles.tableInput}
                            value={point.conditions}
                            onChange={(e) => handleDataPointChange(point.id, 'conditions', e.target.value)}
                            placeholder="Conditions"
                          />
                        </td>
                        <td>
                          <input
                            type="text"
                            className={styles.tableInput}
                            value={point.notes}
                            onChange={(e) => handleDataPointChange(point.id, 'notes', e.target.value)}
                            placeholder="Notes"
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
          </div>

          {/* Statistical Summary Section */}
          <div className={styles.analysisCard}>
            <h2>Statistical Summary</h2>
            <div className={styles.statisticsSection}>
              <div className={styles.statisticsGrid}>
                <div className={styles.statCard}>
                  <div className={styles.statLabel}>Count</div>
                  <div className={styles.statValue}>{chartData.statistics.count}</div>
                </div>
                <div className={styles.statCard}>
                  <div className={styles.statLabel}>Mean</div>
                  <div className={styles.statValue}>{chartData.statistics.mean}</div>
                </div>
                <div className={styles.statCard}>
                  <div className={styles.statLabel}>Median (Center Line)</div>
                  <div className={styles.statValue}>{chartData.statistics.median}</div>
                </div>
                <div className={styles.statCard}>
                  <div className={styles.statLabel}>Std Deviation</div>
                  <div className={styles.statValue}>{chartData.statistics.standardDeviation}</div>
                </div>
                <div className={styles.statCard}>
                  <div className={styles.statLabel}>Range</div>
                  <div className={styles.statValue}>{chartData.statistics.range}</div>
                </div>
                <div className={styles.statCard}>
                  <div className={styles.statLabel}>Minimum</div>
                  <div className={styles.statValue}>{chartData.statistics.minimum}</div>
                </div>
                <div className={styles.statCard}>
                  <div className={styles.statLabel}>Maximum</div>
                  <div className={styles.statValue}>{chartData.statistics.maximum}</div>
                </div>
              </div>
            </div>
          </div>

          {/* Pattern Analysis Section */}
          <div className={styles.analysisCard}>
            <h2>Pattern Analysis</h2>
            <div className={styles.patternAnalysisSection}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Trend Analysis</label>
                <textarea
                  className={styles.textareaInput}
                  value={chartData.analysis.trend}
                  onChange={(e) => handleAnalysisChange('trend', e.target.value)}
                  placeholder="Describe any trends (6+ consecutive points increasing or decreasing)"
                  rows={2}
                />
              </div>
              
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Shifts</label>
                <textarea
                  className={styles.textareaInput}
                  value={chartData.analysis.shifts}
                  onChange={(e) => handleAnalysisChange('shifts', e.target.value)}
                  placeholder="Describe any shifts (8+ consecutive points above or below median)"
                  rows={2}
                />
              </div>
              
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Runs</label>
                  <textarea
                    className={styles.textareaInput}
                    value={chartData.analysis.runs}
                    onChange={(e) => handleAnalysisChange('runs', e.target.value)}
                    placeholder="Describe any runs (8+ consecutive points on same side of median)"
                    rows={2}
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Cycles</label>
                  <textarea
                    className={styles.textareaInput}
                    value={chartData.analysis.cycles}
                    onChange={(e) => handleAnalysisChange('cycles', e.target.value)}
                    placeholder="Describe any cyclical patterns"
                    rows={2}
                  />
                </div>
              </div>
              
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Overall Patterns</label>
                <textarea
                  className={styles.textareaInput}
                  value={chartData.analysis.patterns}
                  onChange={(e) => handleAnalysisChange('patterns', e.target.value)}
                  placeholder="Describe overall patterns and observations"
                  rows={3}
                />
              </div>
            </div>
          </div>

          {/* Outlier Investigation Section */}
          <div className={styles.analysisCard}>
            <h2>Outlier Investigation</h2>
            <div className={styles.outlierSection}>
              <div className={styles.sectionHeader}>
                <p className={styles.sectionDescription}>
                  Investigate data points that appear unusually high or low compared to the typical pattern.
                </p>
                <button className={styles.addBtn} onClick={addOutlier}>
                  <i className="fas fa-plus"></i> Add Outlier
                </button>
              </div>
              
              <div className={styles.outlierTable}>
                <table className={styles.dataTable}>
                  <thead>
                    <tr>
                      <th>Sequence #</th>
                      <th>Value</th>
                      <th>Investigation</th>
                      <th>Root Cause</th>
                      <th>Action Taken</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {chartData.analysis.outliers.map((outlier) => (
                      <tr key={outlier.id}>
                        <td>
                          <input
                            type="number"
                            className={styles.tableInput}
                            value={outlier.sequence}
                            onChange={(e) => handleOutlierChange(outlier.id, 'sequence', e.target.value)}
                            placeholder="Seq #"
                            style={{ width: '80px' }}
                          />
                        </td>
                        <td>
                          <input
                            type="number"
                            step="any"
                            className={styles.tableInput}
                            value={outlier.value}
                            onChange={(e) => handleOutlierChange(outlier.id, 'value', e.target.value)}
                            placeholder="Value"
                          />
                        </td>
                        <td>
                          <input
                            type="text"
                            className={styles.tableInput}
                            value={outlier.investigation}
                            onChange={(e) => handleOutlierChange(outlier.id, 'investigation', e.target.value)}
                            placeholder="Investigation details"
                          />
                        </td>
                        <td>
                          <input
                            type="text"
                            className={styles.tableInput}
                            value={outlier.cause}
                            onChange={(e) => handleOutlierChange(outlier.id, 'cause', e.target.value)}
                            placeholder="Root cause"
                          />
                        </td>
                        <td>
                          <input
                            type="text"
                            className={styles.tableInput}
                            value={outlier.action}
                            onChange={(e) => handleOutlierChange(outlier.id, 'action', e.target.value)}
                            placeholder="Action taken"
                          />
                        </td>
                        <td>
                          <button
                            className={styles.removeBtn}
                            onClick={() => removeOutlier(outlier.id)}
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

          {/* Context & Special Causes Section */}
          <div className={styles.analysisCard}>
            <h2>Context & Special Causes</h2>
            <div className={styles.contextSection}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Process Description</label>
                <textarea
                  className={styles.textareaInput}
                  value={chartData.context.processDescription}
                  onChange={(e) => handleContextChange('processDescription', e.target.value)}
                  placeholder="Describe the process being measured"
                  rows={2}
                />
              </div>
              
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Environmental Factors</label>
                  <textarea
                    className={styles.textareaInput}
                    value={chartData.context.environmentalFactors}
                    onChange={(e) => handleContextChange('environmentalFactors', e.target.value)}
                    placeholder="Environmental conditions that may affect the process"
                    rows={2}
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Operational Changes</label>
                  <textarea
                    className={styles.textareaInput}
                    value={chartData.context.operationalChanges}
                    onChange={(e) => handleContextChange('operationalChanges', e.target.value)}
                    placeholder="Any operational changes during the time period"
                    rows={2}
                  />
                </div>
              </div>
              
              <div className={styles.specialCausesSection}>
                <div className={styles.sectionHeader}>
                  <h3>Special Causes</h3>
                  <button className={styles.addBtn} onClick={addSpecialCause}>
                    <i className="fas fa-plus"></i> Add Special Cause
                  </button>
                </div>
                
                <div className={styles.specialCausesTable}>
                  <table className={styles.dataTable}>
                    <thead>
                      <tr>
                        <th>Time Frame</th>
                        <th>Description</th>
                        <th>Impact</th>
                        <th>Investigation</th>
                        <th>Action</th>
                        <th>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {chartData.context.specialCauses.map((cause) => (
                        <tr key={cause.id}>
                          <td>
                            <input
                              type="text"
                              className={styles.tableInput}
                              value={cause.timeFrame}
                              onChange={(e) => handleSpecialCauseChange(cause.id, 'timeFrame', e.target.value)}
                              placeholder="When occurred"
                            />
                          </td>
                          <td>
                            <input
                              type="text"
                              className={styles.tableInput}
                              value={cause.description}
                              onChange={(e) => handleSpecialCauseChange(cause.id, 'description', e.target.value)}
                              placeholder="What happened"
                            />
                          </td>
                          <td>
                            <input
                              type="text"
                              className={styles.tableInput}
                              value={cause.impact}
                              onChange={(e) => handleSpecialCauseChange(cause.id, 'impact', e.target.value)}
                              placeholder="Impact on process"
                            />
                          </td>
                          <td>
                            <input
                              type="text"
                              className={styles.tableInput}
                              value={cause.investigation}
                              onChange={(e) => handleSpecialCauseChange(cause.id, 'investigation', e.target.value)}
                              placeholder="Investigation details"
                            />
                          </td>
                          <td>
                            <input
                              type="text"
                              className={styles.tableInput}
                              value={cause.action}
                              onChange={(e) => handleSpecialCauseChange(cause.id, 'action', e.target.value)}
                              placeholder="Action taken"
                            />
                          </td>
                          <td>
                            <button
                              className={styles.removeBtn}
                              onClick={() => removeSpecialCause(cause.id)}
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

          {/* Interpretation & Recommendations Section */}
          <div className={styles.analysisCard}>
            <h2>Interpretation & Recommendations</h2>
            <div className={styles.interpretationSection}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Trend Analysis Summary</label>
                <textarea
                  className={styles.textareaInput}
                  value={chartData.interpretation.trendAnalysis}
                  onChange={(e) => handleInterpretationChange('trendAnalysis', e.target.value)}
                  placeholder="Summarize the overall trends and what they indicate about the process"
                  rows={3}
                />
              </div>
              
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Pattern Identification</label>
                <textarea
                  className={styles.textareaInput}
                  value={chartData.interpretation.patternIdentification}
                  onChange={(e) => handleInterpretationChange('patternIdentification', e.target.value)}
                  placeholder="Identify key patterns and their potential causes"
                  rows={3}
                />
              </div>
              
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Process Stability Assessment</label>
                <textarea
                  className={styles.textareaInput}
                  value={chartData.interpretation.processStability}
                  onChange={(e) => handleInterpretationChange('processStability', e.target.value)}
                  placeholder="Assess whether the process is stable or shows signs of special cause variation"
                  rows={3}
                />
              </div>
              
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Recommendations</label>
                <textarea
                  className={styles.textareaInput}
                  value={chartData.interpretation.recommendations}
                  onChange={(e) => handleInterpretationChange('recommendations', e.target.value)}
                  placeholder="Provide recommendations for process improvement or further investigation"
                  rows={3}
                />
              </div>
              
              <div className={styles.actionItemsSection}>
                <div className={styles.sectionHeader}>
                  <h3>Action Items</h3>
                  <button className={styles.addBtn} onClick={addActionItem}>
                    <i className="fas fa-plus"></i> Add Action Item
                  </button>
                </div>
                
                <div className={styles.actionItemsTable}>
                  <table className={styles.dataTable}>
                    <thead>
                      <tr>
                        <th>Action</th>
                        <th>Responsible</th>
                        <th>Due Date</th>
                        <th>Priority</th>
                        <th>Status</th>
                        <th>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {chartData.interpretation.actionItems.map((action) => (
                        <tr key={action.id}>
                          <td>
                            <input
                              type="text"
                              className={styles.tableInput}
                              value={action.action}
                              onChange={(e) => handleActionItemChange(action.id, 'action', e.target.value)}
                              placeholder="Action description"
                            />
                          </td>
                          <td>
                            <input
                              type="text"
                              className={styles.tableInput}
                              value={action.responsible}
                              onChange={(e) => handleActionItemChange(action.id, 'responsible', e.target.value)}
                              placeholder="Responsible person"
                            />
                          </td>
                          <td>
                            <input
                              type="date"
                              className={styles.tableInput}
                              value={action.dueDate}
                              onChange={(e) => handleActionItemChange(action.id, 'dueDate', e.target.value)}
                            />
                          </td>
                          <td>
                            <select
                              className={styles.tableSelect}
                              value={action.priority}
                              onChange={(e) => handleActionItemChange(action.id, 'priority', e.target.value)}
                            >
                              <option value="low">Low</option>
                              <option value="medium">Medium</option>
                              <option value="high">High</option>
                            </select>
                          </td>
                          <td>
                            <select
                              className={styles.tableSelect}
                              value={action.status}
                              onChange={(e) => handleActionItemChange(action.id, 'status', e.target.value)}
                            >
                              <option value="open">Open</option>
                              <option value="in-progress">In Progress</option>
                              <option value="completed">Completed</option>
                            </select>
                          </td>
                          <td>
                            <button
                              className={styles.removeBtn}
                              onClick={() => removeActionItem(action.id)}
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

export default RunChart;
