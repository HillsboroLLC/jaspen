import React, { useState, useEffect } from 'react';
import { useAdminSettings } from '../context/AdminContext';
import ResourcePageWrapper from '../../All/components/ResourcePageWrapper';
import styles from './ParetoAnalysis.module.css';

const ParetoAnalysis = () => {
  const { adminSettings } = useAdminSettings();

  // Pareto Analysis data structure
  const [paretoData, setParetoData] = useState({
    projectName: '',
    analyst: '',
    analysisTeam: '',
    dateCreated: new Date().toISOString().split('T')[0],
    lastUpdated: new Date().toISOString().split('T')[0],
    
    // Analysis information
    analysisInfo: {
      problemStatement: '',
      dataSource: '',
      timeframe: '',
      category: 'defects', // 'defects', 'complaints', 'costs', 'time', 'frequency', 'custom'
      unit: '',
      purpose: ''
    },
    
    // Data categories
    categories: [
      {
        id: 1,
        name: 'Category 1',
        count: 0,
        percentage: 0,
        cumulativePercentage: 0,
        description: ''
      }
    ],
    
    // Analysis settings
    settings: {
      showTop: 10, // Show top N categories
      threshold: 80, // 80/20 rule threshold
      sortBy: 'count', // 'count', 'percentage'
      includeOthers: true, // Group remaining categories as "Others"
      chartType: 'bar' // 'bar', 'line', 'combined'
    },
    
    // Results
    results: {
      totalCount: 0,
      topCategories: [],
      vitalFew: [], // Categories contributing to 80%
      trivialMany: [], // Remaining categories
      paretoPoint: 0, // Number of categories for 80%
      insights: []
    }
  });

  const [completionPercentage, setCompletionPercentage] = useState(0);

  // Calculate completion percentage
  useEffect(() => {
    const calculateCompletion = () => {
      let totalFields = 0;
      let completedFields = 0;

      // Basic info
      totalFields += 3;
      if (paretoData.projectName) completedFields++;
      if (paretoData.analyst) completedFields++;
      if (paretoData.analysisTeam) completedFields++;

      // Analysis info
      totalFields += 4;
      if (paretoData.analysisInfo.problemStatement) completedFields++;
      if (paretoData.analysisInfo.dataSource) completedFields++;
      if (paretoData.analysisInfo.timeframe) completedFields++;
      if (paretoData.analysisInfo.unit) completedFields++;

      // Categories
      totalFields += 1;
      const hasValidCategories = paretoData.categories.length > 1 || 
        (paretoData.categories.length === 1 && paretoData.categories[0].name !== 'Category 1');
      if (hasValidCategories) completedFields++;

      // Data completeness
      totalFields += 1;
      const hasData = paretoData.categories.some(cat => cat.count > 0);
      if (hasData) completedFields++;

      const percentage = totalFields > 0 ? Math.round((completedFields / totalFields) * 100) : 0;
      setCompletionPercentage(percentage);
    };

    calculateCompletion();
  }, [paretoData]);

  // Calculate Pareto analysis
  useEffect(() => {
    const calculatePareto = () => {
      // Sort categories by count (descending)
      const sortedCategories = [...paretoData.categories]
        .filter(cat => cat.count > 0)
        .sort((a, b) => b.count - a.count);

      if (sortedCategories.length === 0) {
        setParetoData(prev => ({
          ...prev,
          results: {
            totalCount: 0,
            topCategories: [],
            vitalFew: [],
            trivialMany: [],
            paretoPoint: 0,
            insights: []
          }
        }));
        return;
      }

      const totalCount = sortedCategories.reduce((sum, cat) => sum + cat.count, 0);
      
      // Calculate percentages and cumulative percentages
      let cumulativeCount = 0;
      const categoriesWithPercentages = sortedCategories.map((cat, index) => {
        const percentage = (cat.count / totalCount) * 100;
        cumulativeCount += cat.count;
        const cumulativePercentage = (cumulativeCount / totalCount) * 100;
        
        return {
          ...cat,
          percentage: parseFloat(percentage.toFixed(2)),
          cumulativePercentage: parseFloat(cumulativePercentage.toFixed(2)),
          rank: index + 1
        };
      });

      // Find Pareto point (80% threshold)
      const threshold = paretoData.settings.threshold;
      let paretoPoint = 0;
      let vitalFew = [];
      let trivialMany = [];

      for (let i = 0; i < categoriesWithPercentages.length; i++) {
        if (categoriesWithPercentages[i].cumulativePercentage <= threshold) {
          vitalFew.push(categoriesWithPercentages[i]);
          paretoPoint = i + 1;
        } else {
          trivialMany.push(categoriesWithPercentages[i]);
        }
      }

      // If no categories reach threshold, include at least the top category
      if (vitalFew.length === 0 && categoriesWithPercentages.length > 0) {
        vitalFew.push(categoriesWithPercentages[0]);
        paretoPoint = 1;
        trivialMany = categoriesWithPercentages.slice(1);
      }

      // Generate insights
      const insights = [];
      if (vitalFew.length > 0) {
        const vitalFewPercentage = vitalFew.reduce((sum, cat) => sum + cat.percentage, 0);
        insights.push(`Top ${vitalFew.length} categories (${((vitalFew.length / categoriesWithPercentages.length) * 100).toFixed(1)}% of categories) account for ${vitalFewPercentage.toFixed(1)}% of total occurrences.`);
        
        if (vitalFew.length <= 3) {
          insights.push(`Focus improvement efforts on: ${vitalFew.map(cat => cat.name).join(', ')}.`);
        }
        
        if (vitalFewPercentage >= 80) {
          insights.push(`Strong Pareto effect observed - prioritize these vital few categories for maximum impact.`);
        } else if (vitalFewPercentage >= 60) {
          insights.push(`Moderate Pareto effect - these categories are important but consider expanding focus.`);
        } else {
          insights.push(`Weak Pareto effect - problem may be distributed across many categories.`);
        }
      }

      // Update categories with calculated values
      setParetoData(prev => ({
        ...prev,
        categories: prev.categories.map(cat => {
          const calculated = categoriesWithPercentages.find(c => c.id === cat.id);
          return calculated ? calculated : cat;
        }),
        results: {
          totalCount,
          topCategories: categoriesWithPercentages.slice(0, paretoData.settings.showTop),
          vitalFew,
          trivialMany,
          paretoPoint,
          insights
        }
      }));
    };

    calculatePareto();
  }, [paretoData.categories, paretoData.settings.threshold, paretoData.settings.showTop]);

  // Handle field changes
  const handleBasicInfoChange = (field, value) => {
    setParetoData(prev => ({
      ...prev,
      [field]: value,
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleAnalysisInfoChange = (field, value) => {
    setParetoData(prev => ({
      ...prev,
      analysisInfo: {
        ...prev.analysisInfo,
        [field]: value
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleCategoryChange = (categoryId, field, value) => {
    setParetoData(prev => ({
      ...prev,
      categories: prev.categories.map(cat =>
        cat.id === categoryId ? { ...cat, [field]: value } : cat
      ),
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleSettingsChange = (field, value) => {
    setParetoData(prev => ({
      ...prev,
      settings: {
        ...prev.settings,
        [field]: value
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Add new category
  const addCategory = () => {
    const newCategory = {
      id: Date.now(),
      name: `Category ${paretoData.categories.length + 1}`,
      count: 0,
      percentage: 0,
      cumulativePercentage: 0,
      description: ''
    };
    
    setParetoData(prev => ({
      ...prev,
      categories: [...prev.categories, newCategory],
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Remove category
  const removeCategory = (categoryId) => {
    if (paretoData.categories.length > 1) {
      setParetoData(prev => ({
        ...prev,
        categories: prev.categories.filter(cat => cat.id !== categoryId),
        lastUpdated: new Date().toISOString().split('T')[0]
      }));
    }
  };

  // Generate sample data
  const generateSampleData = () => {
    const sampleCategories = [
      { name: 'Defect Type A', count: 45 },
      { name: 'Defect Type B', count: 32 },
      { name: 'Defect Type C', count: 28 },
      { name: 'Defect Type D', count: 15 },
      { name: 'Defect Type E', count: 12 },
      { name: 'Defect Type F', count: 8 },
      { name: 'Defect Type G', count: 5 },
      { name: 'Defect Type H', count: 3 }
    ];

    const updatedCategories = sampleCategories.map((sample, index) => ({
      id: Date.now() + index,
      name: sample.name,
      count: sample.count,
      percentage: 0,
      cumulativePercentage: 0,
      description: `Sample description for ${sample.name}`
    }));

    setParetoData(prev => ({
      ...prev,
      categories: updatedCategories,
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  return (
    <ResourcePageWrapper
      pageName="Pareto Analysis"
      toolName="Pareto"
      adminSettings={adminSettings}
    >
      <div className={styles.paretoContainer}>
        {/* Header */}
        <div className={styles.header}>
          <div className={styles.headerContent}>
            <h1>Pareto Analysis</h1>
            <div className={styles.progressSection}>
              <div className={styles.progressBar}>
                <div
                  className={styles.progressFill}
                  style={{
                    width: `${completionPercentage}%`,
                    background: '#0B1A33',
                    backgroundImage: 'none'
                  }}
                />
              </div>
              <span className={styles.progressText}>{completionPercentage}% Complete</span>
            </div>
          </div>
          <div className={styles.headerActions}>
            <button className={styles.saveBtn}>
              <i className="fas fa-save"></i> Save Analysis
            </button>
            <button className={styles.exportBtn}>
              <i className="fas fa-download"></i> Export Chart
            </button>
          </div>
        </div>

        {/* Main Content */}
        <div className={styles.mainContent}>
          {/* Top Section removed; info card is now full-width */}
          <div className={styles.processInfoCard}>
            <h2>Pareto Analysis Information</h2>
            
            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel}>
                Project Name <span className={styles.required}>*</span>
              </label>
              <input
                type="text"
                className={styles.textInput}
                value={paretoData.projectName}
                onChange={(e) => handleBasicInfoChange('projectName', e.target.value)}
                placeholder="Enter the project name for this Pareto analysis"
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
                  value={paretoData.analyst}
                  onChange={(e) => handleBasicInfoChange('analyst', e.target.value)}
                  placeholder="Who is conducting this analysis?"
                />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Analysis Team <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={paretoData.analysisTeam}
                  onChange={(e) => handleBasicInfoChange('analysisTeam', e.target.value)}
                  placeholder="List team members involved"
                />
              </div>
            </div>

            <div className={styles.fieldRow}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Date Created
                </label>
                <input
                  type="date"
                  className={styles.textInput}
                  value={paretoData.dateCreated}
                  onChange={(e) => handleBasicInfoChange('dateCreated', e.target.value)}
                />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Last Updated
                </label>
                <input
                  type="date"
                  className={styles.textInput}
                  value={paretoData.lastUpdated}
                  readOnly
                />
              </div>
            </div>
          </div>

          {/* Analysis Details Section */}
          <div className={styles.analysisDetailsCard}>
            <div className={styles.sectionHeader}>
              <h2>Analysis Details</h2>
            </div>

            <div className={styles.analysisDetailsGrid}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Problem Statement <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={paretoData.analysisInfo.problemStatement}
                  onChange={(e) => handleAnalysisInfoChange('problemStatement', e.target.value)}
                  placeholder="Clearly describe the problem you're analyzing"
                  rows={3}
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Data Source <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={paretoData.analysisInfo.dataSource}
                  onChange={(e) => handleAnalysisInfoChange('dataSource', e.target.value)}
                  placeholder="Where is the data coming from?"
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Timeframe <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={paretoData.analysisInfo.timeframe}
                  onChange={(e) => handleAnalysisInfoChange('timeframe', e.target.value)}
                  placeholder="Time period for data collection (e.g., Last 3 months)"
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Category Type
                </label>
                <select
                  className={styles.selectInput}
                  value={paretoData.analysisInfo.category}
                  onChange={(e) => handleAnalysisInfoChange('category', e.target.value)}
                >
                  <option value="defects">Defects</option>
                  <option value="complaints">Customer Complaints</option>
                  <option value="costs">Costs</option>
                  <option value="time">Time/Duration</option>
                  <option value="frequency">Frequency</option>
                  <option value="custom">Custom</option>
                </select>
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Unit of Measurement <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={paretoData.analysisInfo.unit}
                  onChange={(e) => handleAnalysisInfoChange('unit', e.target.value)}
                  placeholder="Units (count, $, hours, etc.)"
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Analysis Purpose
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={paretoData.analysisInfo.purpose}
                  onChange={(e) => handleAnalysisInfoChange('purpose', e.target.value)}
                  placeholder="Why is this analysis being conducted?"
                  rows={3}
                />
              </div>
            </div>
          </div>

          {/* Data Categories Section */}
          <div className={styles.categoriesCard}>
            <div className={styles.sectionHeader}>
              <h2>Data Categories</h2>
              <div className={styles.dataActions}>
                <button className={styles.addBtn} onClick={addCategory}>
                  <i className="fas fa-plus"></i> Add Category
                </button>
                <button className={styles.generateBtn} onClick={generateSampleData}>
                  <i className="fas fa-random"></i> Sample Data
                </button>
                <label className={styles.importBtn}>
                  <i className="fas fa-upload"></i> Import CSV
                  <input
                    type="file"
                    accept=".csv"
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (!file) return;
                      const reader = new FileReader();
                      reader.onload = (ev) => {
                        const text = String(ev.target?.result || '');
                        const lines = text.split('\n');
                        const categories = [];
                        lines.forEach((line, index) => {
                          if (line.trim() && index > 0) {
                            const [name, count, description] = line.split(',').map(item => item.trim());
                            if (name && !isNaN(Number(count))) {
                              categories.push({
                                id: Date.now() + index,
                                name: name.replace(/"/g, ''),
                                count: parseInt(count) || 0,
                                percentage: 0,
                                cumulativePercentage: 0,
                                description: description ? description.replace(/"/g, '') : ''
                              });
                            }
                          }
                        });
                        if (categories.length > 0) {
                          setParetoData(prev => ({
                            ...prev,
                            categories,
                            lastUpdated: new Date().toISOString().split('T')[0]
                          }));
                        }
                      };
                      reader.readAsText(file);
                    }}
                    style={{ display: 'none' }}
                  />
                </label>
              </div>
            </div>

            <div className={styles.categoriesGrid}>
              {paretoData.categories.map((category, index) => (
                <div key={category.id} className={styles.categoryCard}>
                  <div className={styles.categoryHeader}>
                    <h3>Category {index + 1}</h3>
                    {paretoData.categories.length > 1 && (
                      <button 
                        className={styles.removeBtn}
                        onClick={() => removeCategory(category.id)}
                      >
                        <i className="fas fa-times"></i>
                      </button>
                    )}
                  </div>

                  <div className={styles.categoryFields}>
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Category Name</label>
                      <input
                        type="text"
                        className={styles.textInput}
                        value={category.name}
                        onChange={(e) => handleCategoryChange(category.id, 'name', e.target.value)}
                        placeholder="Category name"
                      />
                    </div>

                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Count/Value</label>
                      <input
                        type="number"
                        min="0"
                        className={styles.textInput}
                        value={category.count}
                        onChange={(e) => handleCategoryChange(category.id, 'count', parseInt(e.target.value) || 0)}
                        placeholder="0"
                      />
                    </div>

                    {category.percentage > 0 && (
                      <div className={styles.calculatedValues}>
                        <div className={styles.calculatedItem}>
                          <span className={styles.calculatedLabel}>Percentage:</span>
                          <span className={styles.calculatedValue}>{category.percentage}%</span>
                        </div>
                        <div className={styles.calculatedItem}>
                          <span className={styles.calculatedLabel}>Cumulative:</span>
                          <span className={styles.calculatedValue}>{category.cumulativePercentage}%</span>
                        </div>
                      </div>
                    )}

                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Description</label>
                      <textarea
                        className={styles.textareaInput}
                        value={category.description}
                        onChange={(e) => handleCategoryChange(category.id, 'description', e.target.value)}
                        placeholder="Additional details about this category"
                        rows={2}
                      />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Analysis Settings Section */}
          <div className={styles.settingsCard}>
            <div className={styles.sectionHeader}>
              <h2>Analysis Settings</h2>
            </div>

            <div className={styles.settingsGrid}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Pareto Threshold (%)
                </label>
                <input
                  type="number"
                  min="50"
                  max="95"
                  className={styles.textInput}
                  value={paretoData.settings.threshold}
                  onChange={(e) => handleSettingsChange('threshold', parseInt(e.target.value) || 80)}
                  placeholder="80"
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Show Top N Categories
                </label>
                <input
                  type="number"
                  min="3"
                  max="20"
                  className={styles.textInput}
                  value={paretoData.settings.showTop}
                  onChange={(e) => handleSettingsChange('showTop', parseInt(e.target.value) || 10)}
                  placeholder="10"
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Sort By
                </label>
                <select
                  className={styles.selectInput}
                  value={paretoData.settings.sortBy}
                  onChange={(e) => handleSettingsChange('sortBy', e.target.value)}
                >
                  <option value="count">Count/Value</option>
                  <option value="percentage">Percentage</option>
                </select>
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.checkboxLabel}>
                  <input
                    type="checkbox"
                    checked={paretoData.settings.includeOthers}
                    onChange={(e) => handleSettingsChange('includeOthers', e.target.checked)}
                  />
                  Group remaining as "Others"
                </label>
              </div>
            </div>
          </div>

          {/* Results Section */}
          <div className={styles.resultsCard}>
            <div className={styles.sectionHeader}>
              <h2>Pareto Analysis Results</h2>
            </div>

            {paretoData.results.totalCount > 0 ? (
              <div className={styles.resultsContent}>
                {/* Summary Metrics */}
                <div className={styles.summaryMetrics}>
                  <div className={styles.metricCard}>
                    <h4>Total Count</h4>
                    <div className={styles.metricValue}>
                      {paretoData.results.totalCount}
                    </div>
                    <div className={styles.metricDescription}>Total occurrences</div>
                  </div>
                  <div className={styles.metricCard}>
                    <h4>Categories</h4>
                    <div className={styles.metricValue}>
                      {paretoData.categories.filter(cat => cat.count > 0).length}
                    </div>
                    <div className={styles.metricDescription}>Active categories</div>
                  </div>
                  <div className={styles.metricCard}>
                    <h4>Vital Few</h4>
                    <div className={styles.metricValue}>
                      {paretoData.results.vitalFew.length}
                    </div>
                    <div className={styles.metricDescription}>Top priority categories</div>
                  </div>
                  <div className={styles.metricCard}>
                    <h4>Pareto Point</h4>
                    <div className={styles.metricValue}>
                      {paretoData.results.paretoPoint}
                    </div>
                    <div className={styles.metricDescription}>Categories for {paretoData.settings.threshold}%</div>
                  </div>
                </div>

                {/* Vital Few Categories */}
                {paretoData.results.vitalFew.length > 0 && (
                  <div className={styles.vitalFewSection}>
                    <h3>Vital Few Categories (Priority Focus)</h3>
                    <div className={styles.vitalFewGrid}>
                      {paretoData.results.vitalFew.map((category, index) => (
                        <div key={category.id} className={styles.vitalFewCard}>
                          <div className={styles.vitalFewRank}>#{index + 1}</div>
                          <div className={styles.vitalFewName}>{category.name}</div>
                          <div className={styles.vitalFewStats}>
                            <div className={styles.vitalFewCount}>{category.count}</div>
                            <div className={styles.vitalFewPercentage}>{category.percentage}%</div>
                            <div className={styles.vitalFewCumulative}>Cum: {category.cumulativePercentage}%</div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Top Categories Table */}
                <div className={styles.topCategoriesSection}>
                  <h3>Top Categories Breakdown</h3>
                  <div className={styles.categoriesTable}>
                    <div className={styles.tableHeader}>
                      <div>Rank</div>
                      <div>Category</div>
                      <div>Count</div>
                      <div>Percentage</div>
                      <div>Cumulative %</div>
                    </div>
                    {paretoData.results.topCategories.map((category) => (
                      <div key={category.id} className={styles.tableRow}>
                        <div>{category.rank}</div>
                        <div>{category.name}</div>
                        <div>{category.count}</div>
                        <div>{category.percentage}%</div>
                        <div>{category.cumulativePercentage}%</div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Insights */}
                {paretoData.results.insights.length > 0 && (
                  <div className={styles.insightsSection}>
                    <h3>Key Insights</h3>
                    <div className={styles.insightsList}>
                      {paretoData.results.insights.map((insight, index) => (
                        <div key={index} className={styles.insightItem}>
                          <i className="fas fa-lightbulb"></i>
                          <span>{insight}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div className={styles.emptyResults}>
                <i className="fas fa-chart-bar"></i>
                <p>Add category data to see Pareto analysis results.</p>
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className={styles.footer}>
          <div className={styles.footerContent}>
            <div className={styles.completionStatus}>
              <i className="fas fa-check-circle"></i>
              <span>Pareto Analysis {completionPercentage}% Complete</span>
            </div>
            <div className={styles.footerActions}>
              <button className={styles.secondaryBtn}>
                <i className="fas fa-eye"></i> Preview Chart
              </button>
              <button 
                className={styles.primaryBtn}
                disabled={completionPercentage < 70}
              >
                <i className="fas fa-check"></i> Complete Analysis
              </button>
            </div>
          </div>
        </div>
      </div>
    </ResourcePageWrapper>
  );
};

export default ParetoAnalysis;
