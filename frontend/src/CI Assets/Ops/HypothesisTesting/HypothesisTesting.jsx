import React, { useState, useEffect } from 'react';
import ResourcePageWrapper from '../../All/components/ResourcePageWrapper';
import { useAdminSettings } from '../context/AdminContext';
import styles from './HypothesisTesting.module.css';

const HypothesisTesting = () => {
  const { adminSettings } = useAdminSettings();

  // Hypothesis Testing data structure
  const [hypothesisData, setHypothesisData] = useState({
    projectName: '',
    analyst: '',
    analysisTeam: '',
    dateCreated: new Date().toISOString().split('T')[0],
    lastUpdated: new Date().toISOString().split('T')[0],
    
    // Test information
    testInfo: {
      hypothesis: '',
      nullHypothesis: '',
      alternativeHypothesis: '',
      testType: 'one-sample-t',
      significance: 0.05,
      confidenceLevel: 95,
      testDirection: 'two-tailed',
      purpose: ''
    },
    
    // Data groups
    dataGroups: [
      {
        id: 1,
        name: 'Group 1',
        description: '',
        data: [],
        sampleSize: 0,
        mean: 0,
        stdDev: 0,
        variance: 0
      }
    ],
    
    // Test parameters
    parameters: {
      populationMean: 0,
      populationStdDev: 0,
      expectedValue: 0,
      assumeEqualVariances: true,
      pairedData: false
    },
    
    // Results
    results: {
      testStatistic: 0,
      pValue: 0,
      criticalValue: 0,
      degreesOfFreedom: 0,
      confidenceInterval: { lower: 0, upper: 0 },
      decision: '',
      conclusion: '',
      effectSize: 0,
      power: 0
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
      if (hypothesisData.projectName) completedFields++;
      if (hypothesisData.analyst) completedFields++;
      if (hypothesisData.analysisTeam) completedFields++;

      // Test info
      totalFields += 4;
      if (hypothesisData.testInfo.hypothesis) completedFields++;
      if (hypothesisData.testInfo.nullHypothesis) completedFields++;
      if (hypothesisData.testInfo.alternativeHypothesis) completedFields++;
      if (hypothesisData.testInfo.purpose) completedFields++;

      // Data groups
      totalFields += 1;
      const hasValidData = hypothesisData.dataGroups.some(group => group.data.length > 0);
      if (hasValidData) completedFields++;

      // Parameters (if applicable)
      if (hypothesisData.testInfo.testType.includes('one-sample')) {
        totalFields += 1;
        if (hypothesisData.parameters.populationMean !== 0) completedFields++;
      }

      const percentage = totalFields > 0 ? Math.round((completedFields / totalFields) * 100) : 0;
      setCompletionPercentage(percentage);
    };

    calculateCompletion();
  }, [hypothesisData]);

  // Calculate statistics for data groups
  useEffect(() => {
    const calculateGroupStats = () => {
      const updatedGroups = hypothesisData.dataGroups.map(group => {
        if (group.data.length === 0) {
          return { ...group, sampleSize: 0, mean: 0, stdDev: 0, variance: 0 };
        }

        const sampleSize = group.data.length;
        const mean = group.data.reduce((sum, val) => sum + val, 0) / sampleSize;
        const variance = group.data.reduce((sum, val) => sum + Math.pow(val - mean, 2), 0) / (sampleSize - 1);
        const stdDev = Math.sqrt(variance);

        return {
          ...group,
          sampleSize,
          mean: parseFloat(mean.toFixed(4)),
          stdDev: parseFloat(stdDev.toFixed(4)),
          variance: parseFloat(variance.toFixed(4))
        };
      });

      setHypothesisData(prev => ({
        ...prev,
        dataGroups: updatedGroups
      }));
    };

    calculateGroupStats();
  }, [hypothesisData.dataGroups.map(group => group.data).join(',')]);

  // Perform hypothesis test (mocked)
  useEffect(() => {
    const performTest = () => {
      const { testType, significance } = hypothesisData.testInfo;
      const groups = hypothesisData.dataGroups.filter(group => group.data.length > 0);
      
      if (groups.length === 0) {
        setHypothesisData(prev => ({
          ...prev,
          results: {
            testStatistic: 0,
            pValue: 0,
            criticalValue: 0,
            degreesOfFreedom: 0,
            confidenceInterval: { lower: 0, upper: 0 },
            decision: '',
            conclusion: '',
            effectSize: 0,
            power: 0
          }
        }));
        return;
      }

      let results = { testStatistic: 0, pValue: 0, criticalValue: 0, degreesOfFreedom: 0 };

      switch (testType) {
        case 'one-sample-t':
          if (groups.length >= 1 && groups[0].sampleSize > 1) {
            const group = groups[0];
            const mu0 = hypothesisData.parameters.populationMean;
            results.testStatistic = (group.mean - mu0) / (group.stdDev / Math.sqrt(group.sampleSize));
            results.degreesOfFreedom = group.sampleSize - 1;
            results.pValue = 0.032;
            results.criticalValue = 2.086;
          }
          break;
        case 'two-sample-t':
          if (groups.length >= 2 && groups[0].sampleSize > 1 && groups[1].sampleSize > 1) {
            const g1 = groups[0];
            const g2 = groups[1];
            const pooledStdDev = Math.sqrt(((g1.sampleSize - 1) * g1.variance + (g2.sampleSize - 1) * g2.variance) / (g1.sampleSize + g2.sampleSize - 2));
            results.testStatistic = (g1.mean - g2.mean) / (pooledStdDev * Math.sqrt(1/g1.sampleSize + 1/g2.sampleSize));
            results.degreesOfFreedom = g1.sampleSize + g2.sampleSize - 2;
            results.pValue = 0.018;
            results.criticalValue = 2.048;
          }
          break;
        case 'paired-t':
          if (groups.length >= 1 && groups[0].sampleSize > 1) {
            results.testStatistic = 2.45;
            results.degreesOfFreedom = groups[0].sampleSize - 1;
            results.pValue = 0.025;
            results.criticalValue = 2.131;
          }
          break;
        case 'chi-square':
          results.testStatistic = 8.32;
          results.degreesOfFreedom = 3;
          results.pValue = 0.040;
          results.criticalValue = 7.815;
          break;
        default:
          break;
      }

      const decision = results.pValue < significance ? 'reject' : 'fail-to-reject';
      const conclusion = decision === 'reject' 
        ? `Reject the null hypothesis. There is sufficient evidence to support the alternative hypothesis at α = ${significance}.`
        : `Fail to reject the null hypothesis. There is insufficient evidence to support the alternative hypothesis at α = ${significance}.`;

      const margin = 1.96 * (groups[0]?.stdDev || 1) / Math.sqrt(groups[0]?.sampleSize || 1);
      const confidenceInterval = {
        lower: parseFloat(((groups[0]?.mean || 0) - margin).toFixed(4)),
        upper: parseFloat(((groups[0]?.mean || 0) + margin).toFixed(4))
      };

      setHypothesisData(prev => ({
        ...prev,
        results: {
          ...results,
          testStatistic: parseFloat(results.testStatistic.toFixed(4)),
          pValue: parseFloat(results.pValue.toFixed(4)),
          criticalValue: parseFloat(results.criticalValue.toFixed(4)),
          confidenceInterval,
          decision,
          conclusion,
          effectSize: 0.65,
          power: 0.82
        }
      }));
    };

    performTest();
  }, [hypothesisData.testInfo, hypothesisData.dataGroups, hypothesisData.parameters]);

  // Field handlers
  const handleBasicInfoChange = (field, value) => {
    setHypothesisData(prev => ({
      ...prev,
      [field]: value,
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleTestInfoChange = (field, value) => {
    setHypothesisData(prev => ({
      ...prev,
      testInfo: {
        ...prev.testInfo,
        [field]: value,
        confidenceLevel: field === 'significance' ? (1 - parseFloat(value)) * 100 : prev.testInfo.confidenceLevel
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleParametersChange = (field, value) => {
    setHypothesisData(prev => ({
      ...prev,
      parameters: { ...prev.parameters, [field]: value },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleGroupChange = (groupId, field, value) => {
    setHypothesisData(prev => ({
      ...prev,
      dataGroups: prev.dataGroups.map(group =>
        group.id === groupId ? { ...group, [field]: value } : group
      ),
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const addDataGroup = () => {
    const newGroup = {
      id: Date.now(),
      name: `Group ${hypothesisData.dataGroups.length + 1}`,
      description: '',
      data: [],
      sampleSize: 0,
      mean: 0,
      stdDev: 0,
      variance: 0
    };
    
    setHypothesisData(prev => ({
      ...prev,
      dataGroups: [...prev.dataGroups, newGroup],
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const removeDataGroup = (groupId) => {
    if (hypothesisData.dataGroups.length > 1) {
      setHypothesisData(prev => ({
        ...prev,
        dataGroups: prev.dataGroups.filter(group => group.id !== groupId),
        lastUpdated: new Date().toISOString().split('T')[0]
      }));
    }
  };

  const addDataToGroup = (groupId, dataString) => {
    const dataArray = dataString.split(',')
      .map(val => parseFloat(val.trim()))
      .filter(val => !isNaN(val));
    
    setHypothesisData(prev => ({
      ...prev,
      dataGroups: prev.dataGroups.map(group =>
        group.id === groupId ? { ...group, data: dataArray } : group
      ),
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const generateSampleData = () => {
    const sampleData1 = Array.from({ length: 20 }, () => parseFloat((Math.random() * 10 + 25).toFixed(2)));
    const sampleData2 = Array.from({ length: 18 }, () => parseFloat((Math.random() * 8 + 22).toFixed(2)));

    const updatedGroups = [
      {
        ...hypothesisData.dataGroups[0],
        name: 'Before Improvement',
        description: 'Process performance before implementing changes',
        data: sampleData1
      }
    ];

    if (hypothesisData.testInfo.testType === 'two-sample-t') {
      if (hypothesisData.dataGroups.length < 2) {
        updatedGroups.push({
          id: Date.now(),
          name: 'After Improvement',
          description: 'Process performance after implementing changes',
          data: sampleData2,
          sampleSize: 0,
          mean: 0,
          stdDev: 0,
          variance: 0
        });
      } else {
        updatedGroups.push({
          ...hypothesisData.dataGroups[1],
          name: 'After Improvement',
          description: 'Process performance after implementing changes',
          data: sampleData2
        });
      }
    }

    setHypothesisData(prev => ({
      ...prev,
      dataGroups: updatedGroups,
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  return (
    <ResourcePageWrapper
      pageName="Hypothesis Testing"
      toolName="hypothesistesting"
      adminSettings={adminSettings}
    >
      <div className={styles.hypothesisContainer} style={{ paddingBottom: 0 }}>
        {/* Header */}
        <div className={styles.header}>
          <div className={styles.headerContent}>
            <h1>Hypothesis Testing</h1>
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
            <button className={styles.saveBtn}>
              <i className="fas fa-save"></i> Save Test
            </button>
            <button className={styles.exportBtn}>
              <i className="fas fa-download"></i> Export Results
            </button>
          </div>
        </div>

        {/* Main Content */}
        <div className={styles.mainContent} style={{ paddingBottom: 0 }}>
          {/* Top Section: Information ONLY (full width) */}
          <div className={styles.topSection}>
            <div className={styles.processInfoCard} style={{ gridColumn: '1 / -1', width: '100%' }}>
              <h2>Hypothesis Testing Information</h2>
              
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Project Name <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={hypothesisData.projectName}
                  onChange={(e) => handleBasicInfoChange('projectName', e.target.value)}
                  placeholder="Enter the project name for this hypothesis test"
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
                    value={hypothesisData.analyst}
                    onChange={(e) => handleBasicInfoChange('analyst', e.target.value)}
                    placeholder="Who is conducting this test?"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>
                    Analysis Team <span className={styles.required}>*</span>
                  </label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={hypothesisData.analysisTeam}
                    onChange={(e) => handleBasicInfoChange('analysisTeam', e.target.value)}
                    placeholder="List team members involved"
                  />
                </div>
              </div>

              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Date Created</label>
                  <input
                    type="date"
                    className={styles.textInput}
                    value={hypothesisData.dateCreated}
                    onChange={(e) => handleBasicInfoChange('dateCreated', e.target.value)}
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Last Updated</label>
                  <input
                    type="date"
                    className={styles.textInput}
                    value={hypothesisData.lastUpdated}
                    readOnly
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Test Setup Section */}
          <div className={styles.testSetupCard}>
            <div className={styles.sectionHeader}>
              <h2>Test Setup</h2>
            </div>

            <div className={styles.testSetupGrid}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Research Hypothesis <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={hypothesisData.testInfo.hypothesis}
                  onChange={(e) => handleTestInfoChange('hypothesis', e.target.value)}
                  placeholder="Describe what you want to test or prove"
                  rows={3}
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Null Hypothesis (H₀) <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={hypothesisData.testInfo.nullHypothesis}
                  onChange={(e) => handleTestInfoChange('nullHypothesis', e.target.value)}
                  placeholder="State the null hypothesis (status quo, no effect)"
                  rows={2}
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Alternative Hypothesis (H₁) <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={hypothesisData.testInfo.alternativeHypothesis}
                  onChange={(e) => handleTestInfoChange('alternativeHypothesis', e.target.value)}
                  placeholder="State the alternative hypothesis (what you want to prove)"
                  rows={2}
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Test Type</label>
                <select
                  className={styles.selectInput}
                  value={hypothesisData.testInfo.testType}
                  onChange={(e) => handleTestInfoChange('testType', e.target.value)}
                >
                  <option value="one-sample-t">One-Sample t-Test</option>
                  <option value="two-sample-t">Two-Sample t-Test</option>
                  <option value="paired-t">Paired t-Test</option>
                  <option value="anova">ANOVA</option>
                  <option value="chi-square">Chi-Square Test</option>
                  <option value="proportion">Proportion Test</option>
                </select>
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Significance Level (α)</label>
                <select
                  className={styles.selectInput}
                  value={hypothesisData.testInfo.significance}
                  onChange={(e) => handleTestInfoChange('significance', parseFloat(e.target.value))}
                >
                  <option value={0.01}>0.01 (99% confidence)</option>
                  <option value={0.05}>0.05 (95% confidence)</option>
                  <option value={0.10}>0.10 (90% confidence)</option>
                </select>
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Test Direction</label>
                <select
                  className={styles.selectInput}
                  value={hypothesisData.testInfo.testDirection}
                  onChange={(e) => handleTestInfoChange('testDirection', e.target.value)}
                >
                  <option value="two-tailed">Two-tailed (≠)</option>
                  <option value="left-tailed">Left-tailed (&lt;)</option>
                  <option value="right-tailed">Right-tailed (&gt;)</option>
                </select>
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Test Purpose</label>
                <textarea
                  className={styles.textareaInput}
                  value={hypothesisData.testInfo.purpose}
                  onChange={(e) => handleTestInfoChange('purpose', e.target.value)}
                  placeholder="Why is this test being conducted?"
                  rows={3}
                />
              </div>
            </div>
          </div>

          {/* Test Parameters Section */}
          {(hypothesisData.testInfo.testType.includes('one-sample') || 
            hypothesisData.testInfo.testType === 'proportion') && (
            <div className={styles.parametersCard}>
              <div className={styles.sectionHeader}>
                <h2>Test Parameters</h2>
              </div>

              <div className={styles.parametersGrid}>
                {hypothesisData.testInfo.testType.includes('one-sample') && (
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>
                      Population Mean (μ₀) <span className={styles.required}>*</span>
                    </label>
                    <input
                      type="number"
                      step="0.01"
                      className={styles.textInput}
                      value={hypothesisData.parameters.populationMean}
                      onChange={(e) => handleParametersChange('populationMean', parseFloat(e.target.value) || 0)}
                      placeholder="Hypothesized population mean"
                    />
                  </div>
                )}

                {hypothesisData.testInfo.testType === 'proportion' && (
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Expected Proportion (p₀)</label>
                    <input
                      type="number"
                      min="0"
                      max="1"
                      step="0.01"
                      className={styles.textInput}
                      value={hypothesisData.parameters.expectedValue}
                      onChange={(e) => handleParametersChange('expectedValue', parseFloat(e.target.value) || 0)}
                      placeholder="Expected proportion (0-1)"
                    />
                  </div>
                )}

                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Population Standard Deviation (σ)</label>
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    className={styles.textInput}
                    value={hypothesisData.parameters.populationStdDev}
                    onChange={(e) => handleParametersChange('populationStdDev', parseFloat(e.target.value) || 0)}
                    placeholder="If known (leave 0 if unknown)"
                  />
                </div>

                {hypothesisData.testInfo.testType === 'two-sample-t' && (
                  <div className={styles.fieldGroup}>
                    <label className={styles.checkboxLabel}>
                      <input
                        type="checkbox"
                        checked={hypothesisData.parameters.assumeEqualVariances}
                        onChange={(e) => handleParametersChange('assumeEqualVariances', e.target.checked)}
                      />
                      Assume equal variances
                    </label>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Data Groups Section */}
          <div className={styles.dataGroupsCard}>
            <div className={styles.sectionHeader}>
              <h2>Data Groups</h2>
              <div className={styles.dataActions}>
                {hypothesisData.testInfo.testType === 'two-sample-t' && hypothesisData.dataGroups.length < 2 && (
                  <button className={styles.addBtn} onClick={addDataGroup}>
                    <i className="fas fa-plus"></i> Add Group
                  </button>
                )}
                <button className={styles.generateBtn} onClick={generateSampleData}>
                  <i className="fas fa-random"></i> Sample Data
                </button>
              </div>
            </div>

            <div className={styles.dataGroupsGrid}>
              {hypothesisData.dataGroups.map((group) => (
                <div key={group.id} className={styles.dataGroupCard}>
                  <div className={styles.groupHeader}>
                    <h3>{group.name}</h3>
                    {hypothesisData.dataGroups.length > 1 && (
                      <button 
                        className={styles.removeBtn}
                        onClick={() => removeDataGroup(group.id)}
                      >
                        <i className="fas fa-times"></i>
                      </button>
                    )}
                  </div>

                  <div className={styles.groupFields}>
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Group Name</label>
                      <input
                        type="text"
                        className={styles.textInput}
                        value={group.name}
                        onChange={(e) => handleGroupChange(group.id, 'name', e.target.value)}
                        placeholder="Group name"
                      />
                    </div>

                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Description</label>
                      <input
                        type="text"
                        className={styles.textInput}
                        value={group.description}
                        onChange={(e) => handleGroupChange(group.id, 'description', e.target.value)}
                        placeholder="Group description"
                      />
                    </div>

                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Data (comma-separated)</label>
                      <textarea
                        className={styles.textareaInput}
                        value={group.data.join(', ')}
                        onChange={(e) => addDataToGroup(group.id, e.target.value)}
                        placeholder="Enter data values separated by commas (e.g., 12.5, 14.2, 13.8)"
                        rows={3}
                      />
                    </div>

                    {group.sampleSize > 0 && (
                      <div className={styles.groupStats}>
                        <div className={styles.statItem}><span className={styles.statLabel}>Sample Size:</span><span className={styles.statValue}>{group.sampleSize}</span></div>
                        <div className={styles.statItem}><span className={styles.statLabel}>Mean:</span><span className={styles.statValue}>{group.mean}</span></div>
                        <div className={styles.statItem}><span className={styles.statLabel}>Std Dev:</span><span className={styles.statValue}>{group.stdDev}</span></div>
                        <div className={styles.statItem}><span className={styles.statLabel}>Variance:</span><span className={styles.statValue}>{group.variance}</span></div>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Results Section (last main card before footer) */}
          <div className={styles.resultsCard} style={{ marginBottom: 0 }}>
            <div className={styles.sectionHeader}>
              <h2>Test Results</h2>
            </div>

            {hypothesisData.results.testStatistic !== 0 ? (
              <div className={styles.resultsContent}>
                <div className={styles.testStats}>
                  <div className={styles.statCard}>
                    <h4>Test Statistic</h4>
                    <div className={styles.statValue}>{hypothesisData.results.testStatistic}</div>
                    <div className={styles.statDescription}>
                      {hypothesisData.testInfo.testType.includes('t') ? 't-statistic' : 
                       hypothesisData.testInfo.testType === 'chi-square' ? 'χ²-statistic' : 'Test statistic'}
                    </div>
                  </div>

                  <div className={styles.statCard}>
                    <h4>P-Value</h4>
                    <div className={`${styles.statValue} ${hypothesisData.results.pValue < hypothesisData.testInfo.significance ? styles.significant : styles.notSignificant}`}>
                      {hypothesisData.results.pValue}
                    </div>
                    <div className={styles.statDescription}>
                      {hypothesisData.results.pValue < hypothesisData.testInfo.significance ? 'Significant' : 'Not significant'}
                    </div>
                  </div>

                  <div className={styles.statCard}>
                    <h4>Critical Value</h4>
                    <div className={styles.statValue}>±{hypothesisData.results.criticalValue}</div>
                    <div className={styles.statDescription}>α = {hypothesisData.testInfo.significance}</div>
                  </div>

                  <div className={styles.statCard}>
                    <h4>Degrees of Freedom</h4>
                    <div className={styles.statValue}>{hypothesisData.results.degreesOfFreedom}</div>
                    <div className={styles.statDescription}>df</div>
                  </div>
                </div>

                <div className={styles.decisionSection}>
                  <div className={styles.decisionCard}>
                    <h3>Statistical Decision</h3>
                    <div className={`${styles.decision} ${styles[hypothesisData.results.decision.replace('-', '')]}`}>
                      {hypothesisData.results.decision === 'reject' ? 
                        'Reject the Null Hypothesis' : 
                        'Fail to Reject the Null Hypothesis'}
                    </div>
                    <p className={styles.conclusion}>{hypothesisData.results.conclusion}</p>
                  </div>

                  <div className={styles.confidenceIntervalCard}>
                    <h3>Confidence Interval</h3>
                    <div className={styles.intervalRange}>
                      [{hypothesisData.results.confidenceInterval.lower}, {hypothesisData.results.confidenceInterval.upper}]
                    </div>
                    <p className={styles.intervalDescription}>
                      {hypothesisData.testInfo.confidenceLevel}% Confidence Interval for the mean
                    </p>
                  </div>
                </div>

                <div className={styles.additionalStats}>
                  <div className={styles.effectSizeCard}>
                    <h4>Effect Size</h4>
                    <div className={styles.effectValue}>{hypothesisData.results.effectSize}</div>
                    <div className={styles.effectInterpretation}>
                      {hypothesisData.results.effectSize < 0.2 ? 'Small effect' :
                       hypothesisData.results.effectSize < 0.5 ? 'Medium effect' : 'Large effect'}
                    </div>
                  </div>

                  <div className={styles.powerCard}>
                    <h4>Statistical Power</h4>
                    <div className={styles.powerValue}>{(hypothesisData.results.power * 100).toFixed(1)}%</div>
                    <div className={styles.powerInterpretation}>
                      {hypothesisData.results.power >= 0.8 ? 'Adequate power' : 'Low power'}
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <div className={styles.emptyResults}>
                <i className="fas fa-calculator"></i>
                <p>Add data to your groups to see hypothesis test results.</p>
              </div>
            )}
          </div>
        </div>

        {/* Footer (no extra bottom space) */}
        <div className={styles.footer} style={{ marginTop: 0, paddingBottom: 0 }}>
          <div className={styles.footerContent}>
            <div className={styles.completionStatus}>
              <i className="fas fa-check-circle"></i>
              <span>Hypothesis Test {completionPercentage}% Complete</span>
            </div>
            <div className={styles.footerActions}>
              <button className={styles.secondaryBtn}>
                <i className="fas fa-chart-line"></i> View Diagnostics
              </button>
              <button 
                className={styles.primaryBtn}
                disabled={completionPercentage < 70}
              >
                <i className="fas fa-check"></i> Complete Test
              </button>
            </div>
          </div>
        </div>
      </div>
    </ResourcePageWrapper>
  );
};

export default HypothesisTesting;
