import React, { useState, useEffect, useCallback } from 'react';
import { DragDropContext, Droppable, Draggable } from 'react-beautiful-dnd';
import { useAdminSettings } from '../context/AdminContext';
import ResourcePageWrapper from '../../All/components/ResourcePageWrapper';
import styles from './FinY.module.css';
import { aiPredictionEngine } from './aiPredictionEngine';

const FinY = () => {
    const { adminSettings } = useAdminSettings();

  // Project information
  const [projectInfo, setProjectInfo] = useState({
    name: 'Financial Benefits Analysis',
    startDate: '',
    endDate: '',
    totalInvestment: 0,
    discountRate: 10,
    currency: 'USD'
  });

  // AI Settings
  const [aiSettings, setAiSettings] = useState({
    enabled: false,
    model: 'linear_regression',
    confidence: 95,
    seasonality: true,
    trendAnalysis: true
  });

  // Section order state - Enhanced with drag and drop
  const [sectionOrder, setSectionOrder] = useState([
    { id: 'baseline', type: 'baseline' },
    { id: 'actual', type: 'actual' },
    { id: 'projected', type: 'projected' }
  ]);

  // Metrics data
  const [metrics, setMetrics] = useState([
    {
      id: 1,
      name: 'Process Cycle Time',
      category: 'Efficiency',
      unit: 'Hours',
      financialImpact: 'Cost Reduction',
      costPerUnit: 50,
      baseline: Array(12).fill(0),
      actual: Array(12).fill(0),
      projected: Array(12).fill(0),
      target: Array(12).fill(0)
    },
    {
      id: 2,
      name: 'Quality Score',
      category: 'Quality',
      unit: 'Percentage',
      financialImpact: 'Revenue Increase',
      costPerUnit: 100,
      baseline: Array(12).fill(0),
      actual: Array(12).fill(0),
      projected: Array(12).fill(0),
      target: Array(12).fill(0)
    }
  ]);

  // Time periods
  const [periods] = useState([
    'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'
  ]);

  // Financial summary
  const [financialSummary, setFinancialSummary] = useState({
    totalBenefit: 0,
    totalCost: 0,
    netBenefit: 0,
    roi: 0,
    paybackPeriod: 0,
    npv: 0,
    irr: 0
  });


  // Handle data updates from Kii
  const handleKiiDataUpdate = useCallback((extractedData) => {
    console.log('Kii extracted data for FinY:', extractedData);
    
    if (extractedData.projectTitle) {
      setProjectInfo(prev => ({ ...prev, name: extractedData.projectTitle }));
    }

    if (extractedData.cost) {
      setProjectInfo(prev => ({
        ...prev,
        totalInvestment: parseFloat(extractedData.cost.replace(/[^0-9.-]+/g, '')) || 0
      }));
    }

    if (extractedData.timeframe) {
      const timeMatch = extractedData.timeframe.match(/(\d+)\s*(month|year)/i);
      if (timeMatch) {
        const value = parseInt(timeMatch[1]);
        const unit = timeMatch[2].toLowerCase();
        const months = unit === 'year' ? value * 12 : value;
        
        const endDate = new Date();
        endDate.setMonth(endDate.getMonth() + months);
        
        setProjectInfo(prev => ({
          ...prev,
          endDate: endDate.toISOString().split('T')[0]
        }));
      }
    }

    // Show visual feedback
    Object.keys(extractedData).forEach(fieldName => {
      const element = document.querySelector(`[data-field="${fieldName}"]`);
      if (element) {
        element.classList.add(styles.fieldUpdated);
        setTimeout(() => element.classList.remove(styles.fieldUpdated), 2000);
      }
    });
  }, []);

  // Enhanced section info helper
  const getSectionInfo = (sectionType) => {
    const sectionMap = {
      baseline: {
        title: 'Baseline Values',
        description: 'Starting performance metrics before improvements',
        icon: 'fas fa-chart-line',
        editable: true,
        color: '#3b82f6'
      },
      actual: {
        title: 'Actual Values',
        description: 'Real performance data as improvements are implemented',
        icon: 'fas fa-chart-bar',
        editable: true,
        color: '#10b981'
      },
      projected: {
        title: 'AI Projected Values',
        description: 'AI-generated predictions based on current trends and patterns',
        icon: 'fas fa-robot',
        editable: !aiSettings.enabled, // FIXED: Editable when AI is disabled
        color: '#8b5cf6'
      }
    };
    return sectionMap[sectionType];
  };

  // Enhanced drag and drop handler
  const handleDragEnd = (result) => {
    if (!result.destination) return;

    const items = Array.from(sectionOrder);
    const [reorderedItem] = items.splice(result.source.index, 1);
    items.splice(result.destination.index, 0, reorderedItem);

    setSectionOrder(items);
  };

  // Legacy section reordering functions (kept for backward compatibility)
  const moveSectionUp = (index) => {
    if (index > 0) {
      const newOrder = [...sectionOrder];
      [newOrder[index], newOrder[index - 1]] = [newOrder[index - 1], newOrder[index]];
      setSectionOrder(newOrder);
    }
  };

  const moveSectionDown = (index) => {
    if (index < sectionOrder.length - 1) {
      const newOrder = [...sectionOrder];
      [newOrder[index], newOrder[index + 1]] = [newOrder[index + 1], newOrder[index]];
      setSectionOrder(newOrder);
    }
  };

  // Enhanced metric data updates with validation
  const updateMetricValue = (metricIndex, periodIndex, type, value) => {
    const numValue = parseFloat(value) || 0;
    
    setMetrics(prev => prev.map((metric, index) => {
      if (index === metricIndex) {
        const newData = [...metric[type]];
        newData[periodIndex] = numValue;
        return { ...metric, [type]: newData };
      }
      return metric;
    }));
  };

  // Update metric financial impact
  const updateMetricImpact = (metricIndex, impact) => {
    setMetrics(prev => prev.map((metric, index) => {
      if (index === metricIndex) {
        return { ...metric, financialImpact: impact };
      }
      return metric;
    }));
  };

  // Update metric cost per unit
  const updateMetricCostPerUnit = (metricIndex, cost) => {
    setMetrics(prev => prev.map((metric, index) => {
      if (index === metricIndex) {
        return { ...metric, costPerUnit: parseFloat(cost) || 0 };
      }
      return metric;
    }));
  };

  // Enhanced add metric with better defaults
  const addMetric = () => {
    const newMetric = {
      id: Date.now(),
      name: `New Metric ${metrics.length + 1}`,
      category: 'Efficiency',
      unit: 'Units',
      financialImpact: 'Cost Reduction',
      costPerUnit: 0,
      baseline: Array(12).fill(0),
      actual: Array(12).fill(0),
      projected: Array(12).fill(0),
      target: Array(12).fill(0)
    };
    setMetrics(prev => [...prev, newMetric]);
  };

  // Remove metric
  const removeMetric = (metricIndex) => {
    if (metrics.length > 1) {
      setMetrics(prev => prev.filter((_, index) => index !== metricIndex));
    }
  };

  // Enhanced AI Prediction Engine
  const generateAIPredictions = useCallback(async (metricData, metricIndex) => {
    if (!aiSettings.enabled) {
      return metricData.baseline;
    }

    try {
      const predictions = await aiPredictionEngine.generatePredictions(
        metricData, 
        aiSettings.model, 
        {
          confidence: aiSettings.confidence,
          seasonality: aiSettings.seasonality,
          trendAnalysis: aiSettings.trendAnalysis
        }
      );
      
      // Handle both confidence interval objects and simple arrays
      if (Array.isArray(predictions)) {
        return predictions;
      } else if (predictions && typeof predictions === 'object') {
        // Extract values from confidence interval objects
        return predictions.map(pred => pred.value || pred);
      }
      
      return metricData.baseline;
    } catch (error) {
      console.error('AI prediction failed:', error);
      // Enhanced fallback with trend analysis
      const baselineSum = metricData.baseline.reduce((sum, val) => sum + val, 0);
      const actualSum = metricData.actual.reduce((sum, val) => sum + val, 0);
      const improvementRate = baselineSum > 0 ? (actualSum - baselineSum) / baselineSum : 0.05;
      
      return metricData.baseline.map((val, i) => {
        const trendFactor = 1 + (improvementRate * (i + 1) / 12);
        const seasonalFactor = 1 + 0.1 * Math.sin((i * Math.PI) / 6); // Seasonal variation
        return val * trendFactor * seasonalFactor;
      });
    }
  }, [aiSettings]);

  // Update projections when AI settings or baseline/actual data changes
  useEffect(() => {
    if (aiSettings.enabled) {
      const updateProjections = async () => {
        const updatedMetrics = await Promise.all(
          metrics.map(async (metric, index) => {
            const predictions = await generateAIPredictions(metric, index);
            return { ...metric, projected: predictions };
          })
        );
        
        // Only update if projections actually changed
        setMetrics(prevMetrics => {
          const hasChanged = prevMetrics.some((metric, index) => {
            return JSON.stringify(metric.projected) !== JSON.stringify(updatedMetrics[index].projected);
          });
          
          return hasChanged ? updatedMetrics : prevMetrics;
        });
      };
      
      updateProjections();
    }
  }, [metrics.map(m => JSON.stringify(m.baseline)).join(','), 
      metrics.map(m => JSON.stringify(m.actual)).join(','), 
      aiSettings.enabled, aiSettings.model, aiSettings.confidence, 
      aiSettings.seasonality, aiSettings.trendAnalysis, generateAIPredictions]);

  // Enhanced financial summary calculation
  useEffect(() => {
    const calculateSummary = () => {
      let totalBenefit = 0;
      let totalCost = projectInfo.totalInvestment;
      let monthlyBenefits = Array(12).fill(0);

      metrics.forEach(metric => {
        const actualSum = metric.actual.reduce((sum, val) => sum + val, 0);
        const baselineSum = metric.baseline.reduce((sum, val) => sum + val, 0);
        const improvement = actualSum - baselineSum;
        const benefit = improvement * metric.costPerUnit;
        
        // Calculate monthly benefits for better payback analysis
        metric.actual.forEach((actualVal, monthIndex) => {
          const monthlyImprovement = actualVal - (metric.baseline[monthIndex] || 0);
          const monthlyBenefit = monthlyImprovement * metric.costPerUnit;
          
          if (metric.financialImpact === 'Cost Reduction' || metric.financialImpact === 'Cost Avoidance') {
            monthlyBenefits[monthIndex] += Math.abs(monthlyBenefit);
          } else if (metric.financialImpact === 'Revenue Increase') {
            monthlyBenefits[monthIndex] += monthlyBenefit;
          }
        });
        
        if (metric.financialImpact === 'Cost Reduction' || metric.financialImpact === 'Cost Avoidance') {
          totalBenefit += Math.abs(benefit);
        } else if (metric.financialImpact === 'Revenue Increase') {
          totalBenefit += benefit;
        }
      });

      const netBenefit = totalBenefit - totalCost;
      const roi = totalCost > 0 ? (netBenefit / totalCost) * 100 : 0;
      
      // Enhanced payback period calculation
      let cumulativeBenefit = 0;
      let paybackPeriod = 0;
      for (let i = 0; i < monthlyBenefits.length; i++) {
        cumulativeBenefit += monthlyBenefits[i];
        if (cumulativeBenefit >= totalCost) {
          paybackPeriod = i + 1;
          break;
        }
      }
      if (paybackPeriod === 0 && totalBenefit > 0) {
        paybackPeriod = Math.ceil(totalCost / (totalBenefit / 12));
      }

      // Enhanced NPV calculation
      const discountRate = projectInfo.discountRate / 100 / 12; // Monthly discount rate
      let npv = -totalCost;
      monthlyBenefits.forEach((benefit, month) => {
        npv += benefit / Math.pow(1 + discountRate, month + 1);
      });

      const newSummary = {
        totalBenefit,
        totalCost,
        netBenefit,
        roi,
        paybackPeriod,
        npv,
        irr: roi // Simplified IRR approximation
      };

      // Debounce and only update if there's a significant change
      const timeoutId = setTimeout(() => {
        setFinancialSummary(prevSummary => {
          const hasSignificantChange = Object.keys(newSummary).some(key => {
            const diff = Math.abs(newSummary[key] - (prevSummary[key] || 0));
            return diff > 0.01;
          });
          
          return hasSignificantChange ? newSummary : prevSummary;
        });
      }, 100);

      return () => clearTimeout(timeoutId);
    };

    calculateSummary();
  }, [metrics, projectInfo.totalInvestment, projectInfo.discountRate]);

  // Enhanced export data with more details
  const exportData = () => {
    const exportObj = {
      projectInfo,
      metrics,
      financialSummary,
      aiSettings,
      sectionOrder,
      analysis: {
        totalMetrics: metrics.length,
        enabledFeatures: {
          aiPredictions: aiSettings.enabled,
          seasonalAnalysis: aiSettings.seasonality,
          trendAnalysis: aiSettings.trendAnalysis
        },
        performanceIndicators: {
          roi: financialSummary.roi,
          paybackMonths: financialSummary.paybackPeriod,
          npv: financialSummary.npv
        }
      },
      exportDate: new Date().toISOString(),
      version: '2.0-enhanced'
    };
    
    const dataStr = JSON.stringify(exportObj, null, 2);
    const dataBlob = new Blob([dataStr], { type: 'application/json' });
    const url = URL.createObjectURL(dataBlob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `finy-analysis-${new Date().toISOString().split('T')[0]}.json`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  return (
    <div className={styles.finYContainer}>
      {/* Header */}
      <div className={styles.header}>
        <div className={styles.headerContent}>
          <div className={styles.projectInfo}>
            <h1>
              <i className="fas fa-chart-line"></i>
              FinY Benefit Model
            </h1>
            <div className={styles.projectDetails}>
              <div className={styles.projectName} data-field="projectTitle">
                {projectInfo.name}
              </div>
              <div className={styles.projectTimeline}>
                {projectInfo.startDate && projectInfo.endDate && 
                  `${projectInfo.startDate} - ${projectInfo.endDate}`
                }
              </div>
            </div>
          </div>
        </div>
        <div className={styles.headerActions}>
          <button className={styles.saveBtn}>
            <i className="fas fa-save"></i> Save Model
          </button>
          <button className={styles.exportBtn} onClick={exportData}>
            <i className="fas fa-download"></i> Export Data
          </button>
        </div>
      </div>

      {/* Main Content */}
      <div className={styles.mainContent}>
        {/* Top Section - Financial Summary and Settings (NO CHAT) */}
        <div className={styles.topSection}>
          <div className={styles.summaryCard}>
            <h3>Financial Summary</h3>
            <div className={styles.summaryGrid}>
              <div className={styles.summaryItem}>
                <span className={styles.summaryLabel}>Total Benefit</span>
                <span className={styles.summaryValue}>
                  {projectInfo.currency} {financialSummary.totalBenefit.toLocaleString()}
                </span>
              </div>
              <div className={styles.summaryItem}>
                <span className={styles.summaryLabel}>Total Investment</span>
                <span className={styles.summaryValue}>
                  {projectInfo.currency} {financialSummary.totalCost.toLocaleString()}
                </span>
              </div>
              <div className={styles.summaryItem}>
                <span className={styles.summaryLabel}>Net Benefit</span>
                <span className={`${styles.summaryValue} ${financialSummary.netBenefit >= 0 ? styles.positive : styles.negative}`}>
                  {projectInfo.currency} {financialSummary.netBenefit.toLocaleString()}
                </span>
              </div>
              <div className={styles.summaryItem}>
                <span className={styles.summaryLabel}>ROI</span>
                <span className={`${styles.summaryValue} ${financialSummary.roi >= 0 ? styles.positive : styles.negative}`}>
                  {financialSummary.roi.toFixed(1)}%
                </span>
              </div>
              <div className={styles.summaryItem}>
                <span className={styles.summaryLabel}>Payback Period</span>
                <span className={styles.summaryValue}>
                  {financialSummary.paybackPeriod} months
                </span>
              </div>
              <div className={styles.summaryItem}>
                <span className={styles.summaryLabel}>NPV</span>
                <span className={`${styles.summaryValue} ${financialSummary.npv >= 0 ? styles.positive : styles.negative}`}>
                  {projectInfo.currency} {financialSummary.npv.toLocaleString()}
                </span>
              </div>
            </div>
          </div>

          <div className={styles.settingsCard}>
            <h3>Project Settings</h3>
            <div className={styles.settingsGrid}>
              <div className={styles.fieldGroup}>
                <label>Project Name</label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={projectInfo.name}
                  onChange={(e) => setProjectInfo(prev => ({ ...prev, name: e.target.value }))}
                  placeholder="Enter project name"
                  data-field="projectTitle"
                />
              </div>
              <div className={styles.fieldGroup}>
                <label>Start Date</label>
                <input
                  type="date"
                  className={styles.textInput}
                  value={projectInfo.startDate}
                  onChange={(e) => setProjectInfo(prev => ({ ...prev, startDate: e.target.value }))}
                  data-field="startDate"
                />
              </div>
              <div className={styles.fieldGroup}>
                <label>End Date</label>
                <input
                  type="date"
                  className={styles.textInput}
                  value={projectInfo.endDate}
                  onChange={(e) => setProjectInfo(prev => ({ ...prev, endDate: e.target.value }))}
                  data-field="endDate"
                />
              </div>
              <div className={styles.fieldGroup}>
                <label>Total Investment ({projectInfo.currency})</label>
                <input
                  type="number"
                  className={styles.textInput}
                  value={projectInfo.totalInvestment}
                  onChange={(e) => setProjectInfo(prev => ({ ...prev, totalInvestment: parseFloat(e.target.value) || 0 }))}
                  placeholder="0"
                  step="100"
                  data-field="totalInvestment"
                />
              </div>
              <div className={styles.fieldGroup}>
                <label>Discount Rate (%)</label>
                <input
                  type="number"
                  className={styles.textInput}
                  value={projectInfo.discountRate}
                  onChange={(e) => setProjectInfo(prev => ({ ...prev, discountRate: parseFloat(e.target.value) || 10 }))}
                  placeholder="10"
                  step="0.1"
                  min="0"
                  max="50"
                  data-field="discountRate"
                />
              </div>
              <div className={styles.fieldGroup}>
                <label>Currency</label>
                <select
                  className={styles.selectInput}
                  value={projectInfo.currency}
                  onChange={(e) => setProjectInfo(prev => ({ ...prev, currency: e.target.value }))}
                >
                  <option value="USD">USD</option>
                  <option value="EUR">EUR</option>
                  <option value="GBP">GBP</option>
                  <option value="CAD">CAD</option>
                </select>
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.checkboxLabel}>
                  <input
                    type="checkbox"
                    checked={aiSettings.enabled}
                    onChange={(e) => setAiSettings(prev => ({ ...prev, enabled: e.target.checked }))}
                  />
                  Enable AI Predictions
                </label>
              </div>
              <div className={styles.fieldGroup}>
                <label>AI Model</label>
                <select
                  className={styles.selectInput}
                  value={aiSettings.model}
                  onChange={(e) => setAiSettings(prev => ({ ...prev, model: e.target.value }))}
                  disabled={!aiSettings.enabled}
                >
                  <option value="linear_regression">Linear Regression</option>
                  <option value="polynomial">Polynomial</option>
                  <option value="neural_network">Neural Network</option>
                  <option value="time_series">Time Series</option>
                </select>
              </div>
            </div>
          </div>
        </div>

        {/* Enhanced Data Sections with Drag and Drop */}
        <div className={styles.analysisCard}>
          <h2>Metrics & Financial Data</h2>
          <div className={styles.tableActions}>
            <div className={styles.dragHint}>
              <i className="fas fa-hand-rock"></i>
              Drag sections to reorder
            </div>
            <button className={styles.addBtn} onClick={addMetric}>
              <i className="fas fa-plus"></i> Add Metric
            </button>
          </div>

          {/* Drag and Drop Context */}
          <DragDropContext onDragEnd={handleDragEnd}>
            <Droppable droppableId="sections">
              {(provided) => (
                <div {...provided.droppableProps} ref={provided.innerRef}>
                  {sectionOrder.map((section, sectionIndex) => {
                    const sectionInfo = getSectionInfo(section.type);
                    return (
                      <Draggable key={section.id} draggableId={section.id} index={sectionIndex}>
                        {(provided, snapshot) => (
                          <div
                            ref={provided.innerRef}
                            {...provided.draggableProps}
                            className={`${styles.dataSection} ${snapshot.isDragging ? styles.dragging : ''}`}
                          >
                            <div className={styles.sectionHeader} {...provided.dragHandleProps}>
                              <div className={styles.sectionTitle}>
                                <h4 style={{ color: sectionInfo.color }}>
                                  <i className={sectionInfo.icon}></i>
                                  {sectionInfo.title}
                                  {section.type === 'projected' && aiSettings.enabled && (
                                    <span className={styles.enhancedBadge}>AI</span>
                                  )}
                                  <i className="fas fa-grip-vertical" style={{ marginLeft: '0.5rem', opacity: 0.5 }}></i>
                                </h4>
                                <span className={styles.sectionDescription}>{sectionInfo.description}</span>
                              </div>
                              <div className={styles.sectionControls}>
                                <button 
                                  className={styles.moveBtn}
                                  onClick={() => moveSectionUp(sectionIndex)}
                                  disabled={sectionIndex === 0}
                                  title="Move section up"
                                >
                                  <i className="fas fa-chevron-up"></i>
                                </button>
                                <button 
                                  className={styles.moveBtn}
                                  onClick={() => moveSectionDown(sectionIndex)}
                                  disabled={sectionIndex === sectionOrder.length - 1}
                                  title="Move section down"
                                >
                                  <i className="fas fa-chevron-down"></i>
                                </button>
                              </div>
                            </div>

                            <div className={styles.sectionTableContainer}>
                              <table className={styles.sectionTable}>
                                <thead>
                                  <tr>
                                    <th>Metric</th>
                                    <th>Category</th>
                                    <th>Unit</th>
                                    <th>Impact</th>
                                    <th>$/Unit</th>
                                    {periods.map(period => (
                                      <th key={period}>{period}</th>
                                    ))}
                                    {section.type === 'baseline' && <th>Actions</th>}
                                  </tr>
                                </thead>
                                <tbody>
                                  {metrics.map((metric, metricIndex) => (
                                    <tr key={metric.id}>
                                      <td className={styles.metricName}>
                                        <div className={styles.metricInfo}>
                                          <strong>{metric.name}</strong>
                                        </div>
                                      </td>
                                      <td>{metric.category}</td>
                                      <td>{metric.unit}</td>
                                      <td>
                                        <select
                                          className={styles.selectInput}
                                          value={metric.financialImpact}
                                          onChange={(e) => updateMetricImpact(metricIndex, e.target.value)}
                                          disabled={!sectionInfo.editable}
                                        >
                                          <option value="Cost Reduction">Cost Reduction</option>
                                          <option value="Cost Avoidance">Cost Avoidance</option>
                                          <option value="Revenue Increase">Revenue Increase</option>
                                        </select>
                                      </td>
                                      <td>
                                        <input
                                          type="number"
                                          className={styles.numberInput}
                                          value={metric.costPerUnit}
                                          onChange={(e) => updateMetricCostPerUnit(metricIndex, e.target.value)}
                                          disabled={!sectionInfo.editable}
                                          step="0.01"
                                        />
                                      </td>
                                      {periods.map((period, periodIndex) => (
                                        <td key={period}>
                                          <input
                                            type="number"
                                            className={styles.numberInput}
                                            value={metric[section.type][periodIndex] || 0}
                                            onChange={(e) => updateMetricValue(metricIndex, periodIndex, section.type, e.target.value)}
                                            disabled={!sectionInfo.editable}
                                            step="0.01"
                                          />
                                        </td>
                                      ))}
                                      {section.type === 'baseline' && (
                                        <td>
                                          <button
                                            className={styles.removeBtn}
                                            onClick={() => removeMetric(metricIndex)}
                                            disabled={metrics.length === 1}
                                          >
                                            <i className="fas fa-trash"></i>
                                          </button>
                                        </td>
                                      )}
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          </div>
                        )}
                      </Draggable>
                    );
                  })}
                  {provided.placeholder}
                </div>
              )}
            </Droppable>
          </DragDropContext>
        </div>
      </div>

<ResourcePageWrapper 
  pageName="FinY Benefit Model"
  toolName="finy"
  adminSettings={adminSettings}
/>
      
    </div>
  );
};

export default FinY;
