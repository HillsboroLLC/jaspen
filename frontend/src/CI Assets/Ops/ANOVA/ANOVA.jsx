import React, { useState, useEffect } from 'react';
import { useAdminSettings } from '../context/AdminContext';
import ResourcePageWrapper from '../../All/components/ResourcePageWrapper';
import styles from './ANOVA.module.css';

const ANOVA = () => {
    const { adminSettings } = useAdminSettings();

  // ANOVA data structure
  const [anovaData, setAnovaData] = useState({
    // Project Information
    analysisTitle: '',
    analyst: '',
    dateCreated: new Date().toISOString().split('T')[0],
    lastUpdated: new Date().toISOString().split('T')[0],
    
    // Study Design
    studyDesign: {
      analysisType: 'one-way', // 'one-way', 'two-way', 'repeated-measures'
      dependentVariable: '',
      independentVariables: [{ id: 1, name: '', type: 'categorical', levels: [] }],
      hypotheses: {
        null: '',
        alternative: ''
      },
      significanceLevel: 0.05,
      powerAnalysis: {
        desiredPower: 0.80,
        effectSize: '',
        sampleSizePerGroup: ''
      }
    },
    
    // Data Input
    dataInput: {
      inputMethod: 'manual', // 'manual', 'upload', 'paste'
      groups: [
        { id: 1, name: 'Group 1', values: [] },
        { id: 2, name: 'Group 2', values: [] },
        { id: 3, name: 'Group 3', values: [] }
      ],
      rawData: '',
      dataFormat: 'grouped' // 'grouped', 'stacked'
    },
    
    // Assumptions
    assumptions: {
      normality: {
        checked: false,
        method: 'shapiro-wilk', // 'shapiro-wilk', 'kolmogorov-smirnov', 'anderson-darling'
        result: '',
        pValue: '',
        conclusion: ''
      },
      homogeneity: {
        checked: false,
        method: 'levene', // 'levene', 'bartlett', 'brown-forsythe'
        result: '',
        pValue: '',
        conclusion: ''
      },
      independence: {
        checked: false,
        method: 'visual-inspection',
        result: '',
        conclusion: ''
      }
    },
    
    // ANOVA Results
    results: {
      anovaTable: {
        betweenGroups: {
          sumOfSquares: '',
          degreesOfFreedom: '',
          meanSquare: '',
          fStatistic: '',
          pValue: '',
          significance: ''
        },
        withinGroups: {
          sumOfSquares: '',
          degreesOfFreedom: '',
          meanSquare: ''
        },
        total: {
          sumOfSquares: '',
          degreesOfFreedom: ''
        }
      },
      effectSize: {
        etaSquared: '',
        partialEtaSquared: '',
        cohensF: '',
        interpretation: ''
      },
      descriptiveStats: [],
      conclusion: '',
      practicalSignificance: ''
    },
    
    // Post-Hoc Analysis
    postHoc: {
      required: false,
      method: 'tukey', // 'tukey', 'bonferroni', 'scheffe', 'fisher-lsd'
      comparisons: [],
      adjustedAlpha: '',
      significantPairs: []
    },
    
    // Visualization
    visualization: {
      boxPlot: { enabled: true, notes: '' },
      meanPlot: { enabled: true, notes: '' },
      residualPlot: { enabled: false, notes: '' },
      qqPlot: { enabled: false, notes: '' }
    }
  });

  const [completionPercentage, setCompletionPercentage] = useState(0);

  // Kii data integration handler
  const handleKiiDataUpdate = (extractedData) => {
    const updates = {};
    
    // Map extracted data to ANOVA fields
    if (extractedData.analysisTitle) {
      updates.analysisTitle = extractedData.analysisTitle;
    }
    if (extractedData.analyst) {
      updates.analyst = extractedData.analyst;
    }
    if (extractedData.dependentVariable) {
      updates.studyDesign = {
        ...anovaData.studyDesign,
        dependentVariable: extractedData.dependentVariable
      };
    }
    
    if (Object.keys(updates).length > 0) {
      setAnovaData(prev => ({
        ...prev,
        ...updates,
        lastUpdated: new Date().toISOString().split('T')[0]
      }));
    }
  };

  // Calculate completion percentage
  useEffect(() => {
    const calculateCompletion = () => {
      let totalFields = 0;
      let completedFields = 0;

      // Basic info (3 fields)
      totalFields += 3;
      if (anovaData.analysisTitle) completedFields++;
      if (anovaData.analyst) completedFields++;
      if (anovaData.studyDesign.dependentVariable) completedFields++;

      // Study design (3 fields)
      totalFields += 3;
      if (anovaData.studyDesign.hypotheses.null) completedFields++;
      if (anovaData.studyDesign.hypotheses.alternative) completedFields++;
      if (anovaData.studyDesign.independentVariables[0].name) completedFields++;

      // Data input (1 field)
      totalFields += 1;
      const hasData = anovaData.dataInput.groups.some(group => group.values.length > 0);
      if (hasData) completedFields++;

      // Assumptions (3 fields)
      totalFields += 3;
      if (anovaData.assumptions.normality.checked) completedFields++;
      if (anovaData.assumptions.homogeneity.checked) completedFields++;
      if (anovaData.assumptions.independence.checked) completedFields++;

      // Results (2 fields)
      totalFields += 2;
      if (anovaData.results.anovaTable.betweenGroups.fStatistic) completedFields++;
      if (anovaData.results.conclusion) completedFields++;

      const percentage = totalFields > 0 ? Math.round((completedFields / totalFields) * 100) : 0;
      setCompletionPercentage(percentage);
    };

    calculateCompletion();
  }, [anovaData]);

  // Handle basic info changes
  const handleBasicInfoChange = (field, value) => {
    setAnovaData(prev => ({
      ...prev,
      [field]: value,
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Handle study design changes
  const handleStudyDesignChange = (field, value) => {
    setAnovaData(prev => ({
      ...prev,
      studyDesign: {
        ...prev.studyDesign,
        [field]: value
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Handle hypotheses changes
  const handleHypothesesChange = (field, value) => {
    setAnovaData(prev => ({
      ...prev,
      studyDesign: {
        ...prev.studyDesign,
        hypotheses: {
          ...prev.studyDesign.hypotheses,
          [field]: value
        }
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Handle independent variable changes
  const handleIndependentVariableChange = (id, field, value) => {
    setAnovaData(prev => ({
      ...prev,
      studyDesign: {
        ...prev.studyDesign,
        independentVariables: prev.studyDesign.independentVariables.map(variable =>
          variable.id === id ? { ...variable, [field]: value } : variable
        )
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Add independent variable (for two-way ANOVA)
  const addIndependentVariable = () => {
    const newVariable = {
      id: Date.now(),
      name: '',
      type: 'categorical',
      levels: []
    };
    
    setAnovaData(prev => ({
      ...prev,
      studyDesign: {
        ...prev.studyDesign,
        independentVariables: [...prev.studyDesign.independentVariables, newVariable]
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Handle group changes
  const handleGroupChange = (groupId, field, value) => {
    setAnovaData(prev => ({
      ...prev,
      dataInput: {
        ...prev.dataInput,
        groups: prev.dataInput.groups.map(group =>
          group.id === groupId ? { ...group, [field]: value } : group
        )
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Add group
  const addGroup = () => {
    const newGroup = {
      id: Date.now(),
      name: `Group ${anovaData.dataInput.groups.length + 1}`,
      values: []
    };
    
    setAnovaData(prev => ({
      ...prev,
      dataInput: {
        ...prev.dataInput,
        groups: [...prev.dataInput.groups, newGroup]
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Remove group
  const removeGroup = (groupId) => {
    if (anovaData.dataInput.groups.length > 2) {
      setAnovaData(prev => ({
        ...prev,
        dataInput: {
          ...prev.dataInput,
          groups: prev.dataInput.groups.filter(group => group.id !== groupId)
        },
        lastUpdated: new Date().toISOString().split('T')[0]
      }));
    }
  };

  // Handle group values change
  const handleGroupValuesChange = (groupId, valuesString) => {
    const values = valuesString.split(/[,\s\n]+/).filter(val => val.trim() !== '').map(val => parseFloat(val.trim())).filter(val => !isNaN(val));
    handleGroupChange(groupId, 'values', values);
  };

  // Handle assumption changes
  const handleAssumptionChange = (assumption, field, value) => {
    setAnovaData(prev => ({
      ...prev,
      assumptions: {
        ...prev.assumptions,
        [assumption]: {
          ...prev.assumptions[assumption],
          [field]: value
        }
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Handle results changes
  const handleResultsChange = (section, field, value) => {
    setAnovaData(prev => ({
      ...prev,
      results: {
        ...prev.results,
        [section]: typeof prev.results[section] === 'object' && section !== 'descriptiveStats' 
          ? { ...prev.results[section], [field]: value }
          : value
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Calculate descriptive statistics
  const calculateDescriptiveStats = () => {
    const stats = anovaData.dataInput.groups.map(group => {
      if (group.values.length === 0) {
        return {
          groupName: group.name,
          n: 0,
          mean: 0,
          std: 0,
          min: 0,
          max: 0
        };
      }
      
      const values = group.values;
      const n = values.length;
      const mean = values.reduce((sum, val) => sum + val, 0) / n;
      const variance = values.reduce((sum, val) => sum + Math.pow(val - mean, 2), 0) / (n - 1);
      const std = Math.sqrt(variance);
      const min = Math.min(...values);
      const max = Math.max(...values);
      
      return {
        groupName: group.name,
        n: n,
        mean: parseFloat(mean.toFixed(3)),
        std: parseFloat(std.toFixed(3)),
        min: min,
        max: max
      };
    });
    
    setAnovaData(prev => ({
      ...prev,
      results: {
        ...prev.results,
        descriptiveStats: stats
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Save draft
  const handleSave = () => {
    console.log('Saving ANOVA draft:', anovaData);
    // Implement save functionality
  };

  // Export PDF
  const handleExport = () => {
    console.log('Exporting ANOVA to PDF:', anovaData);
    // Implement export functionality
  };

  return (
    <ResourcePageWrapper 
      pageName="ANOVA Analysis"
      toolName="anova"
      adminSettings={{ guidedModeEnabled: true }}
      onDataUpdate={handleKiiDataUpdate}
      currentData={anovaData}
    >
      <div className={styles.rcaContainer}>
        {/* Header - Exact match to RCA/A3/SIPOC/Control Plan */}
        <div className={styles.header}>
          <div className={styles.headerContent}>
            <h1>ANOVA Analysis</h1>
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
        <div className={styles.mainContent}>
          {/* Top Section: Analysis Information only (chat section removed) */}
          <div className={styles.topSection}>
            <div className={styles.processInfoCard}>
              <h2>Analysis Information</h2>
              
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Analysis Title <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={anovaData.analysisTitle}
                  onChange={(e) => handleBasicInfoChange('analysisTitle', e.target.value)}
                  placeholder="Enter the title for your ANOVA analysis"
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
                    value={anovaData.analyst}
                    onChange={(e) => handleBasicInfoChange('analyst', e.target.value)}
                    placeholder="Who is conducting this analysis?"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>
                    Date Created
                  </label>
                  <input
                    type="date"
                    className={styles.textInput}
                    value={anovaData.dateCreated}
                    onChange={(e) => handleBasicInfoChange('dateCreated', e.target.value)}
                  />
                </div>
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Dependent Variable <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={anovaData.studyDesign.dependentVariable}
                  onChange={(e) => handleStudyDesignChange('dependentVariable', e.target.value)}
                  placeholder="What outcome variable are you measuring?"
                />
              </div>

              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>
                    Analysis Type
                  </label>
                  <select
                    className={styles.selectInput}
                    value={anovaData.studyDesign.analysisType}
                    onChange={(e) => handleStudyDesignChange('analysisType', e.target.value)}
                  >
                    <option value="one-way">One-Way ANOVA</option>
                    <option value="two-way">Two-Way ANOVA</option>
                    <option value="repeated-measures">Repeated Measures ANOVA</option>
                  </select>
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>
                    Significance Level (α)
                  </label>
                  <select
                    className={styles.selectInput}
                    value={anovaData.studyDesign.significanceLevel}
                    onChange={(e) => handleStudyDesignChange('significanceLevel', parseFloat(e.target.value))}
                  >
                    <option value={0.01}>0.01</option>
                    <option value={0.05}>0.05</option>
                    <option value={0.10}>0.10</option>
                  </select>
                </div>
              </div>
            </div>
          </div>

          {/* Hypotheses Section */}
          <div className={styles.analysisCard}>
            <h2>Hypotheses</h2>
            <div className={styles.hypothesesGrid}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Null Hypothesis (H₀) <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={anovaData.studyDesign.hypotheses.null}
                  onChange={(e) => handleHypothesesChange('null', e.target.value)}
                  placeholder="e.g., There is no significant difference between group means (μ₁ = μ₂ = μ₃)"
                  rows={2}
                />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Alternative Hypothesis (H₁) <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={anovaData.studyDesign.hypotheses.alternative}
                  onChange={(e) => handleHypothesesChange('alternative', e.target.value)}
                  placeholder="e.g., At least one group mean is significantly different from the others"
                  rows={2}
                />
              </div>
            </div>
          </div>

          {/* Data Input Section */}
          <div className={styles.analysisCard}>
            <div className={styles.sectionHeader}>
              <h2>Data Input</h2>
              <div className={styles.dataActions}>
                <button className={styles.addBtn} onClick={addGroup}>
                  <i className="fas fa-plus"></i> Add Group
                </button>
                <button className={styles.calculateBtn} onClick={calculateDescriptiveStats}>
                  <i className="fas fa-calculator"></i> Calculate Stats
                </button>
              </div>
            </div>
            
            <div className={styles.dataInputGrid}>
              {anovaData.dataInput.groups.map((group) => (
                <div key={group.id} className={styles.groupCard}>
                  <div className={styles.groupHeader}>
                    <input
                      type="text"
                      className={styles.groupNameInput}
                      value={group.name}
                      onChange={(e) => handleGroupChange(group.id, 'name', e.target.value)}
                      placeholder="Group name"
                    />
                    <button
                      className={styles.removeBtn}
                      onClick={() => removeGroup(group.id)}
                      disabled={anovaData.dataInput.groups.length <= 2}
                    >
                      <i className="fas fa-times"></i>
                    </button>
                  </div>
                  <div className={styles.groupContent}>
                    <label className={styles.fieldLabel}>Data Values</label>
                    <textarea
                      className={styles.dataTextarea}
                      value={group.values.join(', ')}
                      onChange={(e) => handleGroupValuesChange(group.id, e.target.value)}
                      placeholder="Enter values separated by commas or spaces"
                      rows={4}
                    />
                    <div className={styles.groupStats}>
                      <span>n = {group.values.length}</span>
                      {group.values.length > 0 && (
                        <>
                          <span>Mean = {(group.values.reduce((sum, val) => sum + val, 0) / group.values.length).toFixed(3)}</span>
                          <span>Range = {Math.min(...group.values)} - {Math.max(...group.values)}</span>
                        </>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Assumptions Section */}
          <div className={styles.analysisCard}>
            <h2>Assumption Testing</h2>
            <div className={styles.assumptionsGrid}>
              {/* Normality */}
              <div className={styles.assumptionCard}>
                <div className={styles.assumptionHeader}>
                  <label className={styles.checkboxLabel}>
                    <input
                      type="checkbox"
                      checked={anovaData.assumptions.normality.checked}
                      onChange={(e) => handleAssumptionChange('normality', 'checked', e.target.checked)}
                    />
                    <h3>Normality</h3>
                  </label>
                </div>
                {anovaData.assumptions.normality.checked && (
                  <div className={styles.assumptionFields}>
                    <div className={styles.fieldRow}>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Test Method</label>
                        <select
                          className={styles.selectInput}
                          value={anovaData.assumptions.normality.method}
                          onChange={(e) => handleAssumptionChange('normality', 'method', e.target.value)}
                        >
                          <option value="shapiro-wilk">Shapiro-Wilk Test</option>
                          <option value="kolmogorov-smirnov">Kolmogorov-Smirnov Test</option>
                          <option value="anderson-darling">Anderson-Darling Test</option>
                        </select>
                      </div>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>P-Value</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={anovaData.assumptions.normality.pValue}
                          onChange={(e) => handleAssumptionChange('normality', 'pValue', e.target.value)}
                          placeholder="Enter p-value"
                        />
                      </div>
                    </div>
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Conclusion</label>
                      <textarea
                        className={styles.textareaInput}
                        value={anovaData.assumptions.normality.conclusion}
                        onChange={(e) => handleAssumptionChange('normality', 'conclusion', e.target.value)}
                        placeholder="Interpret the normality test results"
                        rows={2}
                      />
                    </div>
                  </div>
                )}
              </div>

              {/* Homogeneity of Variance */}
              <div className={styles.assumptionCard}>
                <div className={styles.assumptionHeader}>
                  <label className={styles.checkboxLabel}>
                    <input
                      type="checkbox"
                      checked={anovaData.assumptions.homogeneity.checked}
                      onChange={(e) => handleAssumptionChange('homogeneity', 'checked', e.target.checked)}
                    />
                    <h3>Homogeneity of Variance</h3>
                  </label>
                </div>
                {anovaData.assumptions.homogeneity.checked && (
                  <div className={styles.assumptionFields}>
                    <div className={styles.fieldRow}>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Test Method</label>
                        <select
                          className={styles.selectInput}
                          value={anovaData.assumptions.homogeneity.method}
                          onChange={(e) => handleAssumptionChange('homogeneity', 'method', e.target.value)}
                        >
                          <option value="levene">Levene's Test</option>
                          <option value="bartlett">Bartlett's Test</option>
                          <option value="brown-forsythe">Brown-Forsythe Test</option>
                        </select>
                      </div>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>P-Value</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={anovaData.assumptions.homogeneity.pValue}
                          onChange={(e) => handleAssumptionChange('homogeneity', 'pValue', e.target.value)}
                          placeholder="Enter p-value"
                        />
                      </div>
                    </div>
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Conclusion</label>
                      <textarea
                        className={styles.textareaInput}
                        value={anovaData.assumptions.homogeneity.conclusion}
                        onChange={(e) => handleAssumptionChange('homogeneity', 'conclusion', e.target.value)}
                        placeholder="Interpret the homogeneity test results"
                        rows={2}
                      />
                    </div>
                  </div>
                )}
              </div>

              {/* Independence */}
              <div className={styles.assumptionCard}>
                <div className={styles.assumptionHeader}>
                  <label className={styles.checkboxLabel}>
                    <input
                      type="checkbox"
                      checked={anovaData.assumptions.independence.checked}
                      onChange={(e) => handleAssumptionChange('independence', 'checked', e.target.checked)}
                    />
                    <h3>Independence</h3>
                  </label>
                </div>
                {anovaData.assumptions.independence.checked && (
                  <div className={styles.assumptionFields}>
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Assessment Method</label>
                      <select
                        className={styles.selectInput}
                        value={anovaData.assumptions.independence.method}
                        onChange={(e) => handleAssumptionChange('independence', 'method', e.target.value)}
                      >
                        <option value="visual-inspection">Visual Inspection</option>
                        <option value="study-design">Study Design Review</option>
                        <option value="durbin-watson">Durbin-Watson Test</option>
                      </select>
                    </div>
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Conclusion</label>
                      <textarea
                        className={styles.textareaInput}
                        value={anovaData.assumptions.independence.conclusion}
                        onChange={(e) => handleAssumptionChange('independence', 'conclusion', e.target.value)}
                        placeholder="Assess whether observations are independent"
                        rows={2}
                      />
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Descriptive Statistics Section */}
          <div className={styles.analysisCard}>
            <h2>Descriptive Statistics</h2>
            <div className={styles.descriptiveTable}>
              <table className={styles.statsTable}>
                <thead>
                  <tr>
                    <th>Group</th>
                    <th>n</th>
                    <th>Mean</th>
                    <th>Std Dev</th>
                    <th>Min</th>
                    <th>Max</th>
                  </tr>
                </thead>
                <tbody>
                  {anovaData.results.descriptiveStats.map((stat, index) => (
                    <tr key={index}>
                      <td>{stat.groupName}</td>
                      <td>{stat.n}</td>
                      <td>{stat.mean}</td>
                      <td>{stat.std}</td>
                      <td>{stat.min}</td>
                      <td>{stat.max}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* ANOVA Results Section */}
          <div className={styles.analysisCard}>
            <h2>ANOVA Results</h2>
            <div className={styles.resultsGrid}>
              <div className={styles.anovaTableSection}>
                <h3>ANOVA Table</h3>
                <table className={styles.anovaTable}>
                  <thead>
                    <tr>
                      <th>Source</th>
                      <th>Sum of Squares</th>
                      <th>df</th>
                      <th>Mean Square</th>
                      <th>F</th>
                      <th>p-value</th>
                      <th>Significance</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td>Between Groups</td>
                      <td>
                        <input
                          type="text"
                          className={styles.tableInput}
                          value={anovaData.results.anovaTable.betweenGroups.sumOfSquares}
                          onChange={(e) => handleResultsChange('anovaTable', 'betweenGroups', {
                            ...anovaData.results.anovaTable.betweenGroups,
                            sumOfSquares: e.target.value
                          })}
                          placeholder="SS"
                        />
                      </td>
                      <td>
                        <input
                          type="text"
                          className={styles.tableInput}
                          value={anovaData.results.anovaTable.betweenGroups.degreesOfFreedom}
                          onChange={(e) => handleResultsChange('anovaTable', 'betweenGroups', {
                            ...anovaData.results.anovaTable.betweenGroups,
                            degreesOfFreedom: e.target.value
                          })}
                          placeholder="df"
                        />
                      </td>
                      <td>
                        <input
                          type="text"
                          className={styles.tableInput}
                          value={anovaData.results.anovaTable.betweenGroups.meanSquare}
                          onChange={(e) => handleResultsChange('anovaTable', 'betweenGroups', {
                            ...anovaData.results.anovaTable.betweenGroups,
                            meanSquare: e.target.value
                          })}
                          placeholder="MS"
                        />
                      </td>
                      <td>
                        <input
                          type="text"
                          className={styles.tableInput}
                          value={anovaData.results.anovaTable.betweenGroups.fStatistic}
                          onChange={(e) => handleResultsChange('anovaTable', 'betweenGroups', {
                            ...anovaData.results.anovaTable.betweenGroups,
                            fStatistic: e.target.value
                          })}
                          placeholder="F"
                        />
                      </td>
                      <td>
                        <input
                          type="text"
                          className={styles.tableInput}
                          value={anovaData.results.anovaTable.betweenGroups.pValue}
                          onChange={(e) => handleResultsChange('anovaTable', 'betweenGroups', {
                            ...anovaData.results.anovaTable.betweenGroups,
                            pValue: e.target.value
                          })}
                          placeholder="p"
                        />
                      </td>
                      <td>
                        <select
                          className={styles.tableSelect}
                          value={anovaData.results.anovaTable.betweenGroups.significance}
                          onChange={(e) => handleResultsChange('anovaTable', 'betweenGroups', {
                            ...anovaData.results.anovaTable.betweenGroups,
                            significance: e.target.value
                          })}
                        >
                          <option value="">Select</option>
                          <option value="significant">Significant</option>
                          <option value="not-significant">Not Significant</option>
                        </select>
                      </td>
                    </tr>
                    <tr>
                      <td>Within Groups</td>
                      <td>
                        <input
                          type="text"
                          className={styles.tableInput}
                          value={anovaData.results.anovaTable.withinGroups.sumOfSquares}
                          onChange={(e) => handleResultsChange('anovaTable', 'withinGroups', {
                            ...anovaData.results.anovaTable.withinGroups,
                            sumOfSquares: e.target.value
                          })}
                          placeholder="SS"
                        />
                      </td>
                      <td>
                        <input
                          type="text"
                          className={styles.tableInput}
                          value={anovaData.results.anovaTable.withinGroups.degreesOfFreedom}
                          onChange={(e) => handleResultsChange('anovaTable', 'withinGroups', {
                            ...anovaData.results.anovaTable.withinGroups,
                            degreesOfFreedom: e.target.value
                          })}
                          placeholder="df"
                        />
                      </td>
                      <td>
                        <input
                          type="text"
                          className={styles.tableInput}
                          value={anovaData.results.anovaTable.withinGroups.meanSquare}
                          onChange={(e) => handleResultsChange('anovaTable', 'withinGroups', {
                            ...anovaData.results.anovaTable.withinGroups,
                            meanSquare: e.target.value
                          })}
                          placeholder="MS"
                        />
                      </td>
                      <td>-</td>
                      <td>-</td>
                      <td>-</td>
                    </tr>
                    <tr>
                      <td>Total</td>
                      <td>
                        <input
                          type="text"
                          className={styles.tableInput}
                          value={anovaData.results.anovaTable.total.sumOfSquares}
                          onChange={(e) => handleResultsChange('anovaTable', 'total', {
                            ...anovaData.results.anovaTable.total,
                            sumOfSquares: e.target.value
                          })}
                          placeholder="SS"
                        />
                      </td>
                      <td>
                        <input
                          type="text"
                          className={styles.tableInput}
                          value={anovaData.results.anovaTable.total.degreesOfFreedom}
                          onChange={(e) => handleResultsChange('anovaTable', 'total', {
                            ...anovaData.results.anovaTable.total,
                            degreesOfFreedom: e.target.value
                          })}
                          placeholder="df"
                        />
                      </td>
                      <td>-</td>
                      <td>-</td>
                      <td>-</td>
                      <td>-</td>
                    </tr>
                  </tbody>
                </table>
              </div>

              {/* Effect Size */}
              <div className={styles.effectSizeSection}>
                <h3>Effect Size</h3>
                <div className={styles.effectSizeGrid}>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Eta Squared (η²)</label>
                    <input
                      type="text"
                      className={styles.textInput}
                      value={anovaData.results.effectSize.etaSquared}
                      onChange={(e) => handleResultsChange('effectSize', 'etaSquared', e.target.value)}
                      placeholder="0.000"
                    />
                  </div>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Partial Eta Squared</label>
                    <input
                      type="text"
                      className={styles.textInput}
                      value={anovaData.results.effectSize.partialEtaSquared}
                      onChange={(e) => handleResultsChange('effectSize', 'partialEtaSquared', e.target.value)}
                      placeholder="0.000"
                    />
                  </div>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Cohen's f</label>
                    <input
                      type="text"
                      className={styles.textInput}
                      value={anovaData.results.effectSize.cohensF}
                      onChange={(e) => handleResultsChange('effectSize', 'cohensF', e.target.value)}
                      placeholder="0.000"
                    />
                  </div>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Interpretation</label>
                    <select
                      className={styles.selectInput}
                      value={anovaData.results.effectSize.interpretation}
                      onChange={(e) => handleResultsChange('effectSize', 'interpretation', e.target.value)}
                    >
                      <option value="">Select interpretation</option>
                      <option value="small">Small effect</option>
                      <option value="medium">Medium effect</option>
                      <option value="large">Large effect</option>
                    </select>
                  </div>
                </div>
              </div>
            </div>

            {/* Conclusion */}
            <div className={styles.conclusionSection}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Conclusion <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={anovaData.results.conclusion}
                  onChange={(e) => handleResultsChange('conclusion', '', e.target.value)}
                  placeholder="Summarize your ANOVA findings and their implications"
                  rows={4}
                />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Practical Significance
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={anovaData.results.practicalSignificance}
                  onChange={(e) => handleResultsChange('practicalSignificance', '', e.target.value)}
                  placeholder="Discuss the practical importance of your findings"
                  rows={3}
                />
              </div>
            </div>
          </div>
        </div>
      </div>
    </ResourcePageWrapper>
  );
};

export default ANOVA;
