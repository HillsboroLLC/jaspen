import React, { useState, useEffect } from 'react';
import { useAdminSettings } from '../context/AdminContext';
import ResourcePageWrapper from '../../All/components/ResourcePageWrapper';
import styles from './ScatterPlot.module.css';

const ScatterPlot = () => {
  const { adminSettings } = useAdminSettings();

  const [analysisData, setAnalysisData] = useState({
    analysisInfo: {
      analysisName: '',
      analyst: '',
      department: '',
      dateCreated: new Date().toISOString().split('T')[0],
      purpose: '',
      scope: '',
      xVariable: '',
      yVariable: '',
      xUnits: '',
      yUnits: '',
      dataSource: '',
      sampleSize: '',
      timeFrame: ''
    },
    dataPoints: [],
    correlationAnalysis: {
      correlationCoefficient: null,
      pValue: null,
      significance: '',
      strength: '',
      direction: '',
      interpretation: ''
    },
    regressionAnalysis: {
      enabled: false,
      equation: '',
      rSquared: null,
      slope: null,
      intercept: null,
      standardError: null,
      confidenceLevel: 95
    },
    outlierAnalysis: {
      outliers: [],
      detectionMethod: 'z-score',
      threshold: 3,
      investigation: []
    },
    insights: {
      patterns: '',
      businessImplications: '',
      recommendations: '',
      limitations: '',
      nextSteps: ''
    },
    actionItems: []
  });

  // Progress (same logic you had)
  const calculateProgress = () => {
    let completed = 0;
    let total = 8;

    if (analysisData.analysisInfo.analysisName && analysisData.analysisInfo.xVariable && analysisData.analysisInfo.yVariable) completed++;
    if (analysisData.dataPoints.length >= 10) completed++;
    if (analysisData.correlationAnalysis.correlationCoefficient !== null) completed++;
    if (analysisData.regressionAnalysis.enabled && analysisData.regressionAnalysis.equation) completed++;
    if (analysisData.outlierAnalysis.outliers.length > 0 || analysisData.outlierAnalysis.investigation.length > 0) completed++;
    if (analysisData.insights.patterns) completed++;
    if (analysisData.insights.recommendations) completed++;
    if (analysisData.actionItems.length > 0) completed++;

    return Math.round((completed / total) * 100);
  };

  // Handlers (unchanged)
  const handleAnalysisInfoChange = (field, value) => {
    setAnalysisData(prev => ({
      ...prev,
      analysisInfo: {
        ...prev.analysisInfo,
        [field]: value
      }
    }));
  };

  const addDataPoint = () => {
    const newPoint = {
      id: Date.now(),
      sequence: analysisData.dataPoints.length + 1,
      xValue: '',
      yValue: '',
      label: '',
      category: '',
      notes: ''
    };
    setAnalysisData(prev => ({
      ...prev,
      dataPoints: [...prev.dataPoints, newPoint]
    }));
  };

  const removeDataPoint = (id) => {
    setAnalysisData(prev => ({
      ...prev,
      dataPoints: prev.dataPoints
        .filter(point => point.id !== id)
        .map((point, index) => ({ ...point, sequence: index + 1 }))
    }));
  };

  const handleDataPointChange = (id, field, value) => {
    setAnalysisData(prev => ({
      ...prev,
      dataPoints: prev.dataPoints.map(point =>
        point.id === id ? { ...point, [field]: value } : point
      )
    }));
  };

  const handleCorrelationChange = (field, value) => {
    setAnalysisData(prev => ({
      ...prev,
      correlationAnalysis: {
        ...prev.correlationAnalysis,
        [field]: value
      }
    }));
  };

  const handleRegressionChange = (field, value) => {
    setAnalysisData(prev => ({
      ...prev,
      regressionAnalysis: {
        ...prev.regressionAnalysis,
        [field]: value
      }
    }));
  };

  const addOutlier = () => {
    const newOutlier = {
      id: Date.now(),
      xValue: '',
      yValue: '',
      label: '',
      reason: '',
      action: 'investigate'
    };
    setAnalysisData(prev => ({
      ...prev,
      outlierAnalysis: {
        ...prev.outlierAnalysis,
        outliers: [...prev.outlierAnalysis.outliers, newOutlier]
      }
    }));
  };

  const removeOutlier = (id) => {
    setAnalysisData(prev => ({
      ...prev,
      outlierAnalysis: {
        ...prev.outlierAnalysis,
        outliers: prev.outlierAnalysis.outliers.filter(outlier => outlier.id !== id)
      }
    }));
  };

  const handleOutlierChange = (id, field, value) => {
    setAnalysisData(prev => ({
      ...prev,
      outlierAnalysis: {
        ...prev.outlierAnalysis,
        outliers: prev.outlierAnalysis.outliers.map(outlier =>
          outlier.id === id ? { ...outlier, [field]: value } : outlier
        )
      }
    }));
  };

  const handleOutlierAnalysisChange = (field, value) => {
    setAnalysisData(prev => ({
      ...prev,
      outlierAnalysis: {
        ...prev.outlierAnalysis,
        [field]: value
      }
    }));
  };

  const handleInsightsChange = (field, value) => {
    setAnalysisData(prev => ({
      ...prev,
      insights: {
        ...prev.insights,
        [field]: value
      }
    }));
  };

  const addActionItem = () => {
    const newItem = {
      id: Date.now(),
      description: '',
      owner: '',
      dueDate: '',
      priority: 'medium',
      status: 'open'
    };
    setAnalysisData(prev => ({
      ...prev,
      actionItems: [...prev.actionItems, newItem]
    }));
  };

  const removeActionItem = (id) => {
    setAnalysisData(prev => ({
      ...prev,
      actionItems: prev.actionItems.filter(item => item.id !== id)
    }));
  };

  const handleActionItemChange = (id, field, value) => {
    setAnalysisData(prev => ({
      ...prev,
      actionItems: prev.actionItems.map(item =>
        item.id === id ? { ...item, [field]: value } : item
      )
    }));
  };

  const handleSave = () => {
    console.log('Saving scatter plot analysis:', analysisData);
  };

  const handleExport = () => {
    console.log('Exporting scatter plot analysis:', analysisData);
  };

  return (
    <ResourcePageWrapper
      pageName="Scatter Plot Analysis"
      toolName="scatterPlot"
      adminSettings={adminSettings}
    >
      <div className={styles.rcaContainer}>
        {/* Header */}
        <div className={styles.header}>
          <div className={styles.headerContent}>
            <div>
              <h1>Scatter Plot Analysis</h1>
              <div className={styles.progressSection}>
                <div className={styles.progressBar}>
                  <div
                    className={styles.progressFill}
                    style={{ width: `${calculateProgress()}%` }}
                  ></div>
                </div>
                <span className={styles.progressText}>{calculateProgress()}% Complete</span>
              </div>
            </div>
            <div className={styles.headerActions}>
              <button className={styles.saveBtn} onClick={handleSave}>
                <i className="fas fa-save"></i>
                Save Analysis
              </button>
              <button className={styles.exportBtn} onClick={handleExport}>
                <i className="fas fa-download"></i>
                Export
              </button>
            </div>
          </div>
        </div>

        {/* Main Content — FULL WIDTH */}
        <div className={styles.mainContent} style={{ display: 'block' }}>
          {/* Top Section (single column, chat removed) */}
          <div className={styles.topSection} style={{ display: 'block' }}>
            {/* Analysis Info Card */}
            <div className={styles.processInfoCard}>
              <h2>Analysis Information</h2>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Analysis Name <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={analysisData.analysisInfo.analysisName}
                  onChange={(e) => handleAnalysisInfoChange('analysisName', e.target.value)}
                  placeholder="Enter analysis name"
                />
              </div>

              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Analyst</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={analysisData.analysisInfo.analyst}
                    onChange={(e) => handleAnalysisInfoChange('analyst', e.target.value)}
                    placeholder="Analyst name"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Department</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={analysisData.analysisInfo.department}
                    onChange={(e) => handleAnalysisInfoChange('department', e.target.value)}
                    placeholder="Department"
                  />
                </div>
              </div>

              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>X Variable <span className={styles.required}>*</span></label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={analysisData.analysisInfo.xVariable}
                    onChange={(e) => handleAnalysisInfoChange('xVariable', e.target.value)}
                    placeholder="Independent variable"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Y Variable <span className={styles.required}>*</span></label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={analysisData.analysisInfo.yVariable}
                    onChange={(e) => handleAnalysisInfoChange('yVariable', e.target.value)}
                    placeholder="Dependent variable"
                  />
                </div>
              </div>

              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>X Units</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={analysisData.analysisInfo.xUnits}
                    onChange={(e) => handleAnalysisInfoChange('xUnits', e.target.value)}
                    placeholder="Units of measurement"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Y Units</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={analysisData.analysisInfo.yUnits}
                    onChange={(e) => handleAnalysisInfoChange('yUnits', e.target.value)}
                    placeholder="Units of measurement"
                  />
                </div>
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Purpose</label>
                <textarea
                  className={styles.textareaInput}
                  value={analysisData.analysisInfo.purpose}
                  onChange={(e) => handleAnalysisInfoChange('purpose', e.target.value)}
                  placeholder="What is the purpose of this analysis?"
                  rows="3"
                />
              </div>
            </div>
          </div>

          {/* Scatter Plot Visualization Section */}
          <div className={styles.analysisCard}>
            <h2>Scatter Plot Visualization</h2>
            <div className={styles.chartVisualizationSection}>
              <div className={styles.chartContainer}>
                <div className={styles.chartPlaceholder}>
                  <div className={styles.chartPlaceholderContent}>
                    <i className="fas fa-chart-scatter" style={{ fontSize: '3rem', color: 'var(--lss-gray-400)', marginBottom: '1rem' }}></i>
                    <h3>Scatter Plot Will Display Here</h3>
                    <p>Once you add data points and integrate with AI/Minitab, your scatter plot will be visualized in this area.</p>
                    <div className={styles.chartFeatures}>
                      <div className={styles.featureItem}>
                        <i className="fas fa-circle" style={{ color: 'var(--lss-primary)' }}></i>
                        <span>Data Points</span>
                      </div>
                      <div className={styles.featureItem}>
                        <i className="fas fa-chart-line" style={{ color: 'var(--lss-success)' }}></i>
                        <span>Trend Line</span>
                      </div>
                      <div className={styles.featureItem}>
                        <i className="fas fa-exclamation-triangle" style={{ color: 'var(--lss-warning)' }}></i>
                        <span>Outlier Highlights</span>
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
                        <span>Show Trend Line</span>
                      </label>
                      <label className={styles.checkboxLabel}>
                        <input type="checkbox" defaultChecked />
                        <span>Display R²</span>
                      </label>
                      <label className={styles.checkboxLabel}>
                        <input type="checkbox" defaultChecked />
                        <span>Show Equation</span>
                      </label>
                      <label className={styles.checkboxLabel}>
                        <input type="checkbox" />
                        <span>Highlight Outliers</span>
                      </label>
                      <label className={styles.checkboxLabel}>
                        <input type="checkbox" />
                        <span>Confidence Bands</span>
                      </label>
                      <label className={styles.checkboxLabel}>
                        <input type="checkbox" />
                        <span>Point Labels</span>
                      </label>
                    </div>
                  </div>
                  
                  <div className={styles.controlGroup}>
                    <h4>Chart Actions</h4>
                    <div className={styles.chartActions}>
                      <button className={styles.chartActionBtn} disabled>
                        <i className="fas fa-sync-alt"></i>
                        Generate Plot
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
                    <span className={styles.statusValue}>{analysisData.dataPoints.length}</span>
                  </div>
                  <div className={styles.statusItem}>
                    <span className={styles.statusLabel}>Correlation:</span>
                    <span className={styles.statusValue}>{analysisData.correlationAnalysis.correlationCoefficient || 'N/A'}</span>
                  </div>
                  <div className={styles.statusItem}>
                    <span className={styles.statusLabel}>Chart Ready:</span>
                    <span className={`${styles.statusValue} ${analysisData.dataPoints.length >= 10 ? styles.statusReady : styles.statusNotReady}`}>
                      {analysisData.dataPoints.length >= 10 ? 'Yes' : 'Need 10+ points'}
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
                  Enter your data points for scatter plot analysis. Include both X and Y values with optional labels and categories.
                </p>
                <button className={styles.addBtn} onClick={addDataPoint}>
                  <i className="fas fa-plus"></i>
                  Add Data Point
                </button>
              </div>

              <div className={styles.dataPointsTable}>
                <table className={styles.dataTable}>
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>X Value</th>
                      <th>Y Value</th>
                      <th>Label</th>
                      <th>Category</th>
                      <th>Notes</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {analysisData.dataPoints.map((point) => (
                      <tr key={point.id}>
                        <td>
                          <span className={styles.sequenceNumber}>{point.sequence}</span>
                        </td>
                        <td>
                          <input
                            type="number"
                            className={styles.tableInput}
                            value={point.xValue}
                            onChange={(e) => handleDataPointChange(point.id, 'xValue', e.target.value)}
                            placeholder="X value"
                            step="any"
                          />
                        </td>
                        <td>
                          <input
                            type="number"
                            className={styles.tableInput}
                            value={point.yValue}
                            onChange={(e) => handleDataPointChange(point.id, 'yValue', e.target.value)}
                            placeholder="Y value"
                            step="any"
                          />
                        </td>
                        <td>
                          <input
                            type="text"
                            className={styles.tableInput}
                            value={point.label}
                            onChange={(e) => handleDataPointChange(point.id, 'label', e.target.value)}
                            placeholder="Point label"
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
                            <i className="fas fa-trash"></i>
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          {/* Correlation Analysis Section */}
          <div className={styles.analysisCard}>
            <h2>Correlation Analysis</h2>
            <div className={styles.correlationSection}>
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Correlation Coefficient (r)</label>
                  <input
                    type="number"
                    className={styles.textInput}
                    value={analysisData.correlationAnalysis.correlationCoefficient || ''}
                    onChange={(e) => handleCorrelationChange('correlationCoefficient', parseFloat(e.target.value))}
                    placeholder="e.g., 0.75"
                    step="0.01"
                    min="-1"
                    max="1"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>P-Value</label>
                  <input
                    type="number"
                    className={styles.textInput}
                    value={analysisData.correlationAnalysis.pValue || ''}
                    onChange={(e) => handleCorrelationChange('pValue', parseFloat(e.target.value))}
                    placeholder="e.g., 0.001"
                    step="0.001"
                    min="0"
                    max="1"
                  />
                </div>
              </div>

              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Significance Level</label>
                  <select
                    className={styles.textInput}
                    value={analysisData.correlationAnalysis.significance}
                    onChange={(e) => handleCorrelationChange('significance', e.target.value)}
                  >
                    <option value="">Select significance</option>
                    <option value="highly_significant">Highly Significant (p &lt; 0.01)</option>
                    <option value="significant">Significant (p &lt; 0.05)</option>
                    <option value="not_significant">Not Significant (p ≥ 0.05)</option>
                  </select>
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Correlation Strength</label>
                  <select
                    className={styles.textInput}
                    value={analysisData.correlationAnalysis.strength}
                    onChange={(e) => handleCorrelationChange('strength', e.target.value)}
                  >
                    <option value="">Select strength</option>
                    <option value="very_strong">Very Strong (|r| ≥ 0.9)</option>
                    <option value="strong">Strong (0.7 ≤ |r| &lt; 0.9)</option>
                    <option value="moderate">Moderate (0.3 ≤ |r| &lt; 0.7)</option>
                    <option value="weak">Weak (|r| &lt; 0.3)</option>
                  </select>
                </div>
              </div>

              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Direction</label>
                  <select
                    className={styles.textInput}
                    value={analysisData.correlationAnalysis.direction}
                    onChange={(e) => handleCorrelationChange('direction', e.target.value)}
                  >
                    <option value="">Select direction</option>
                    <option value="positive">Positive (r &gt; 0)</option>
                    <option value="negative">Negative (r &lt; 0)</option>
                    <option value="no_correlation">No Correlation (r ≈ 0)</option>
                  </select>
                </div>
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Interpretation</label>
                <textarea
                  className={styles.textareaInput}
                  value={analysisData.correlationAnalysis.interpretation}
                  onChange={(e) => handleCorrelationChange('interpretation', e.target.value)}
                  placeholder="Interpret the correlation results and their business implications..."
                  rows="4"
                />
              </div>
            </div>
          </div>

          {/* Regression Analysis Section */}
          <div className={styles.analysisCard}>
            <h2>Regression Analysis</h2>
            <div className={styles.regressionSection}>
              <div className={styles.fieldGroup}>
                <label className={styles.checkboxLabel}>
                  <input
                    type="checkbox"
                    checked={analysisData.regressionAnalysis.enabled}
                    onChange={(e) => handleRegressionChange('enabled', e.target.checked)}
                  />
                  <span>Enable Regression Analysis</span>
                </label>
              </div>

              {analysisData.regressionAnalysis.enabled && (
                <>
                  <div className={styles.fieldRow}>
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Regression Equation</label>
                      <input
                        type="text"
                        className={styles.textInput}
                        value={analysisData.regressionAnalysis.equation}
                        onChange={(e) => handleRegressionChange('equation', e.target.value)}
                        placeholder="e.g., Y = 2.5X + 10.3"
                      />
                    </div>
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>R-Squared (R²)</label>
                      <input
                        type="number"
                        className={styles.textInput}
                        value={analysisData.regressionAnalysis.rSquared || ''}
                        onChange={(e) => handleRegressionChange('rSquared', parseFloat(e.target.value))}
                        placeholder="e.g., 0.85"
                        step="0.01"
                        min="0"
                        max="1"
                      />
                    </div>
                  </div>

                  <div className={styles.fieldRow}>
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Slope</label>
                      <input
                        type="number"
                        className={styles.textInput}
                        value={analysisData.regressionAnalysis.slope || ''}
                        onChange={(e) => handleRegressionChange('slope', parseFloat(e.target.value))}
                        placeholder="e.g., 2.5"
                        step="any"
                      />
                    </div>
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Intercept</label>
                      <input
                        type="number"
                        className={styles.textInput}
                        value={analysisData.regressionAnalysis.intercept || ''}
                        onChange={(e) => handleRegressionChange('intercept', parseFloat(e.target.value))}
                        placeholder="e.g., 10.3"
                        step="any"
                      />
                    </div>
                  </div>

                  <div className={styles.fieldRow}>
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Standard Error</label>
                      <input
                        type="number"
                        className={styles.textInput}
                        value={analysisData.regressionAnalysis.standardError || ''}
                        onChange={(e) => handleRegressionChange('standardError', parseFloat(e.target.value))}
                        placeholder="e.g., 1.25"
                        step="any"
                        min="0"
                      />
                    </div>
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Confidence Level (%)</label>
                      <select
                        className={styles.textInput}
                        value={analysisData.regressionAnalysis.confidenceLevel}
                        onChange={(e) => handleRegressionChange('confidenceLevel', parseInt(e.target.value))}
                      >
                        <option value={90}>90%</option>
                        <option value={95}>95%</option>
                        <option value={99}>99%</option>
                      </select>
                    </div>
                  </div>
                </>
              )}
            </div>
          </div>

          {/* Outlier Analysis Section */}
          <div className={styles.analysisCard}>
            <h2>Outlier Analysis</h2>
            <div className={styles.outlierSection}>
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Detection Method</label>
                  <select
                    className={styles.textInput}
                    value={analysisData.outlierAnalysis.detectionMethod}
                    onChange={(e) => handleOutlierAnalysisChange('detectionMethod', e.target.value)}
                  >
                    <option value="z-score">Z-Score Method</option>
                    <option value="iqr">IQR Method</option>
                    <option value="visual">Visual Inspection</option>
                    <option value="statistical">Statistical Tests</option>
                  </select>
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Threshold</label>
                  <input
                    type="number"
                    className={styles.textInput}
                    value={analysisData.outlierAnalysis.threshold}
                    onChange={(e) => handleOutlierAnalysisChange('threshold', parseFloat(e.target.value))}
                    placeholder="e.g., 3 for Z-score"
                    step="0.1"
                    min="0"
                  />
                </div>
              </div>

              <div className={styles.sectionHeader}>
                <p className={styles.sectionDescription}>
                  Identify and document outliers that may influence your analysis results.
                </p>
                <button className={styles.addBtn} onClick={addOutlier}>
                  <i className="fas fa-plus"></i>
                  Add Outlier
                </button>
              </div>

              <div className={styles.outlierTable}>
                <table className={styles.dataTable}>
                  <thead>
                    <tr>
                      <th>X Value</th>
                      <th>Y Value</th>
                      <th>Label</th>
                      <th>Reason</th>
                      <th>Action</th>
                      <th>Remove</th>
                    </tr>
                  </thead>
                  <tbody>
                    {analysisData.outlierAnalysis.outliers.map((outlier) => (
                      <tr key={outlier.id}>
                        <td>
                          <input
                            type="number"
                            className={styles.tableInput}
                            value={outlier.xValue}
                            onChange={(e) => handleOutlierChange(outlier.id, 'xValue', e.target.value)}
                            placeholder="X value"
                            step="any"
                          />
                        </td>
                        <td>
                          <input
                            type="number"
                            className={styles.tableInput}
                            value={outlier.yValue}
                            onChange={(e) => handleOutlierChange(outlier.id, 'yValue', e.target.value)}
                            placeholder="Y value"
                            step="any"
                          />
                        </td>
                        <td>
                          <input
                            type="text"
                            className={styles.tableInput}
                            value={outlier.label}
                            onChange={(e) => handleOutlierChange(outlier.id, 'label', e.target.value)}
                            placeholder="Point label"
                          />
                        </td>
                        <td>
                          <input
                            type="text"
                            className={styles.tableInput}
                            value={outlier.reason}
                            onChange={(e) => handleOutlierChange(outlier.id, 'reason', e.target.value)}
                            placeholder="Why is this an outlier?"
                          />
                        </td>
                        <td>
                          <select
                            className={styles.tableSelect}
                            value={outlier.action}
                            onChange={(e) => handleOutlierChange(outlier.id, 'action', e.target.value)}
                          >
                            <option value="investigate">Investigate</option>
                            <option value="keep">Keep</option>
                            <option value="remove">Remove</option>
                            <option value="transform">Transform</option>
                          </select>
                        </td>
                        <td>
                          <button
                            className={styles.removeBtn}
                            onClick={() => removeOutlier(outlier.id)}
                          >
                            <i className="fas fa-trash"></i>
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          {/* Insights & Interpretation Section */}
          <div className={styles.analysisCard}>
            <h2>Insights & Interpretation</h2>
            <div className={styles.insightsSection}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Patterns Observed</label>
                <textarea
                  className={styles.textareaInput}
                  value={analysisData.insights.patterns}
                  onChange={(e) => handleInsightsChange('patterns', e.target.value)}
                  placeholder="Describe the patterns you observe in the scatter plot (linear, non-linear, clusters, etc.)..."
                  rows="4"
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Business Implications</label>
                <textarea
                  className={styles.textareaInput}
                  value={analysisData.insights.businessImplications}
                  onChange={(e) => handleInsightsChange('businessImplications', e.target.value)}
                  placeholder="What do these findings mean for the business or process?"
                  rows="4"
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Recommendations</label>
                <textarea
                  className={styles.textareaInput}
                  value={analysisData.insights.recommendations}
                  onChange={(e) => handleInsightsChange('recommendations', e.target.value)}
                  placeholder="What actions should be taken based on this analysis?"
                  rows="4"
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Limitations</label>
                <textarea
                  className={styles.textareaInput}
                  value={analysisData.insights.limitations}
                  onChange={(e) => handleInsightsChange('limitations', e.target.value)}
                  placeholder="What are the limitations of this analysis? (sample size, data quality, assumptions, etc.)"
                  rows="3"
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Next Steps</label>
                <textarea
                  className={styles.textareaInput}
                  value={analysisData.insights.nextSteps}
                  onChange={(e) => handleInsightsChange('nextSteps', e.target.value)}
                  placeholder="What additional analysis or data collection is needed?"
                  rows="3"
                />
              </div>
            </div>
          </div>

          {/* Action Items Section */}
          <div className={styles.analysisCard}>
            <h2>Action Items</h2>
            <div className={styles.actionItemsSection}>
              <div className={styles.sectionHeader}>
                <p className={styles.sectionDescription}>
                  Track follow-up actions based on your scatter plot analysis findings.
                </p>
                <button className={styles.addBtn} onClick={addActionItem}>
                  <i className="fas fa-plus"></i>
                  Add Action Item
                </button>
              </div>

              <div className={styles.actionItemsTable}>
                <table className={styles.dataTable}>
                  <thead>
                    <tr>
                      <th>Description</th>
                      <th>Owner</th>
                      <th>Due Date</th>
                      <th>Priority</th>
                      <th>Status</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {analysisData.actionItems.map((item) => (
                      <tr key={item.id}>
                        <td>
                          <input
                            type="text"
                            className={styles.tableInput}
                            value={item.description}
                            onChange={(e) => handleActionItemChange(item.id, 'description', e.target.value)}
                            placeholder="Action description"
                          />
                        </td>
                        <td>
                          <input
                            type="text"
                            className={styles.tableInput}
                            value={item.owner}
                            onChange={(e) => handleActionItemChange(item.id, 'owner', e.target.value)}
                            placeholder="Responsible person"
                          />
                        </td>
                        <td>
                          <input
                            type="date"
                            className={styles.tableInput}
                            value={item.dueDate}
                            onChange={(e) => handleActionItemChange(item.id, 'dueDate', e.target.value)}
                          />
                        </td>
                        <td>
                          <select
                            className={styles.tableSelect}
                            value={item.priority}
                            onChange={(e) => handleActionItemChange(item.id, 'priority', e.target.value)}
                          >
                            <option value="low">Low</option>
                            <option value="medium">Medium</option>
                            <option value="high">High</option>
                          </select>
                        </td>
                        <td>
                          <select
                            className={styles.tableSelect}
                            value={item.status}
                            onChange={(e) => handleActionItemChange(item.id, 'status', e.target.value)}
                          >
                            <option value="open">Open</option>
                            <option value="in_progress">In Progress</option>
                            <option value="completed">Completed</option>
                          </select>
                        </td>
                        <td>
                          <button
                            className={styles.removeBtn}
                            onClick={() => removeActionItem(item.id)}
                          >
                            <i className="fas fa-trash"></i>
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
    </ResourcePageWrapper>
  );
};

export default ScatterPlot;
