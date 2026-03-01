import React, { useState, useCallback, useEffect } from 'react';
import { useAdminSettings } from '../context/AdminContext';
import ResourcePageWrapper from '../../All/components/ResourcePageWrapper';
import styles from './A3.module.css';

const A3 = () => {
    const { adminSettings } = useAdminSettings();

  // A3 data structure
  const [a3Data, setA3Data] = useState({
    // Project Information
    projectTitle: '',
    problemOwner: '',
    teamMembers: '',
    dateCreated: new Date().toISOString().split('T')[0],
    lastUpdated: new Date().toISOString().split('T')[0],
    targetCompletionDate: '',
    
    // Step 1: Background/Problem Statement
    background: '',
    problemStatement: '',
    businessImpact: '',
    
    // Step 2: Current State Analysis
    currentStateDescription: '',
    currentStateMetrics: [{ id: 1, metric: '', current: '', target: '', unit: '' }],
    
    // Step 3: Goal/Target State
    goalStatement: '',
    targetStateDescription: '',
    successCriteria: [{ id: 1, criteria: '', measurement: '' }],
    
    // Step 4: Root Cause Analysis
    rootCauseMethod: 'Five Whys',
    rootCauseAnalysis: [{ id: 1, cause: '', category: 'People', priority: 'High' }],
    
    // Step 5: Countermeasures
    countermeasures: [{ id: 1, action: '', owner: '', dueDate: '', status: 'Not Started' }],
    
    // Step 6: Implementation Plan
    implementationSteps: [{ id: 1, step: '', owner: '', startDate: '', endDate: '', dependencies: '' }],
    
    // Step 7: Follow-up Actions
    followUpActions: [{ id: 1, action: '', frequency: 'Weekly', owner: '', nextReview: '' }],
    
    // Step 8: Results/Lessons Learned
    results: '',
    lessonsLearned: '',
    nextSteps: '',
    approvalStatus: 'Draft'
  });

  const [completionPercentage, setCompletionPercentage] = useState(0);

  // Handle data updates from Kii
  const handleKiiDataUpdate = useCallback((extractedData) => {
    console.log('Kii extracted data:', extractedData);
    
    // Update the A3 form with extracted data
    setA3Data(prev => ({
      ...prev,
      ...extractedData,
      lastUpdated: new Date().toISOString().split('T')[0]
    }));

    // Show visual feedback that data was updated
    showDataUpdateFeedback(extractedData);
  }, []);

  // Show visual feedback when Kii updates data
  const showDataUpdateFeedback = (updatedFields) => {
    Object.keys(updatedFields).forEach(fieldName => {
      const element = document.querySelector(`[data-field="${fieldName}"]`);
      if (element) {
        element.classList.add(styles.fieldUpdated);
        setTimeout(() => {
          element.classList.remove(styles.fieldUpdated);
        }, 2000);
      }
    });
  };

  // Calculate completion percentage
  useEffect(() => {
    const calculateCompletion = () => {
      let totalFields = 0;
      let completedFields = 0;

      // Project info (6 fields)
      totalFields += 6;
      if (a3Data.projectTitle) completedFields++;
      if (a3Data.problemOwner) completedFields++;
      if (a3Data.teamMembers) completedFields++;
      if (a3Data.targetCompletionDate) completedFields++;
      if (a3Data.background) completedFields++;
      if (a3Data.problemStatement) completedFields++;

      // Step sections (6 main sections)
      const stepSections = [
        'currentStateDescription', 'goalStatement', 'targetStateDescription', 
        'results', 'lessonsLearned', 'nextSteps'
      ];
      totalFields += stepSections.length;
      stepSections.forEach(section => {
        if (a3Data[section] && a3Data[section].trim() !== '') completedFields++;
      });

      // Array sections - count essential fields
      const arraySections = ['currentStateMetrics', 'successCriteria', 'rootCauseAnalysis', 'countermeasures', 'implementationSteps', 'followUpActions'];
      arraySections.forEach(section => {
        a3Data[section].forEach(item => {
          totalFields += 2; // Count 2 essential fields per item
          const keys = Object.keys(item).filter(key => key !== 'id');
          let filledCount = 0;
          keys.forEach(key => {
            if (item[key] && item[key].toString().trim() !== '') filledCount++;
          });
          completedFields += Math.min(filledCount, 2); // Cap at 2 per item
        });
      });

      const percentage = totalFields > 0 ? Math.round((completedFields / totalFields) * 100) : 0;
      setCompletionPercentage(percentage);
    };

    calculateCompletion();
  }, [a3Data]);

  // Handle project info changes
  const handleProjectInfoChange = useCallback((field, value) => {
    setA3Data(prev => ({
      ...prev,
      [field]: value,
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  }, []);

  // Handle array item changes
  const handleArrayItemChange = useCallback((section, id, field, value) => {
    setA3Data(prev => ({
      ...prev,
      [section]: prev[section].map(item => 
        item.id === id ? { ...item, [field]: value } : item
      ),
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  }, []);

  // Add new array item
  const addArrayItem = useCallback((section) => {
    setA3Data(prev => {
      const newId = Math.max(...prev[section].map(item => item.id)) + 1;
      let newItem = { id: newId };
      
      // Add section-specific fields
      switch (section) {
        case 'currentStateMetrics':
          newItem = { ...newItem, metric: '', current: '', target: '', unit: '' };
          break;
        case 'successCriteria':
          newItem = { ...newItem, criteria: '', measurement: '' };
          break;
        case 'rootCauseAnalysis':
          newItem = { ...newItem, cause: '', category: 'People', priority: 'High' };
          break;
        case 'countermeasures':
          newItem = { ...newItem, action: '', owner: '', dueDate: '', status: 'Not Started' };
          break;
        case 'implementationSteps':
          newItem = { ...newItem, step: '', owner: '', startDate: '', endDate: '', dependencies: '' };
          break;
        case 'followUpActions':
          newItem = { ...newItem, action: '', frequency: 'Weekly', owner: '', nextReview: '' };
          break;
        default:
          break;
      }

      return {
        ...prev,
        [section]: [...prev[section], newItem],
        lastUpdated: new Date().toISOString().split('T')[0]
      };
    });
  }, []);

  // Remove array item
  const removeArrayItem = useCallback((section, id) => {
    setA3Data(prev => {
      if (prev[section].length > 1) {
        return {
          ...prev,
          [section]: prev[section].filter(item => item.id !== id),
          lastUpdated: new Date().toISOString().split('T')[0]
        };
      }
      return prev;
    });
  }, []);

  // Save draft
  const handleSave = () => {
    console.log('Saving A3 draft:', a3Data);
    // Implement save functionality
  };

  // Export PDF
  const handleExport = () => {
    console.log('Exporting A3 to PDF:', a3Data);
    // Implement export functionality
  };

  return (
    <div className={styles.rcaContainer}>
      {/* Header */}
      <div className={styles.header}>
        <div className={styles.headerContent}>
          <h1>A3 Problem Solving</h1>
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
        {/* Top Section: A3 Information - Now full width without chat */}
        <div className={styles.topSectionFullWidth}>
          <div className={styles.processInfoCard}>
            <h2>A3 Information</h2>
            
            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel}>
                Project Title <span className={styles.required}>*</span>
              </label>
              <input
                type="text"
                className={styles.textInput}
                value={a3Data.projectTitle}
                onChange={(e) => handleProjectInfoChange('projectTitle', e.target.value)}
                placeholder="Enter the project title for A3 analysis"
                data-field="projectTitle"
              />
            </div>

            <div className={styles.fieldRow}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Problem Owner <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={a3Data.problemOwner}
                  onChange={(e) => handleProjectInfoChange('problemOwner', e.target.value)}
                  placeholder="Who owns this problem?"
                  data-field="problemOwner"
                />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Team Members <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={a3Data.teamMembers}
                  onChange={(e) => handleProjectInfoChange('teamMembers', e.target.value)}
                  placeholder="List team members involved in this A3"
                  data-field="teamMembers"
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
                  value={a3Data.dateCreated}
                  onChange={(e) => handleProjectInfoChange('dateCreated', e.target.value)}
                  data-field="dateCreated"
                />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Target Completion
                </label>
                <input
                  type="date"
                  className={styles.textInput}
                  value={a3Data.targetCompletionDate}
                  onChange={(e) => handleProjectInfoChange('targetCompletionDate', e.target.value)}
                  data-field="targetCompletionDate"
                />
              </div>
            </div>
          </div>
        </div>

        {/* A3 Steps Analysis */}
        <div className={styles.analysisCard}>
          <h2>A3 Problem Solving Steps</h2>
          
          {/* Step 1: Background & Problem Statement */}
          <div className={styles.stepSection}>
            <div className={styles.stepHeader}>
              <h3>
                <span className={styles.stepNumber}>1</span>
                Background & Problem Statement
              </h3>
            </div>
            
            <div className={styles.stepContent}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Background <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={a3Data.background}
                  onChange={(e) => handleProjectInfoChange('background', e.target.value)}
                  placeholder="Provide context about why this problem is important to solve now..."
                  rows={4}
                  data-field="background"
                />
              </div>
              
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Problem Statement <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={a3Data.problemStatement}
                  onChange={(e) => handleProjectInfoChange('problemStatement', e.target.value)}
                  placeholder="Clearly define the problem without including solutions..."
                  rows={3}
                  data-field="problemStatement"
                />
              </div>
              
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Business Impact
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={a3Data.businessImpact}
                  onChange={(e) => handleProjectInfoChange('businessImpact', e.target.value)}
                  placeholder="Describe the impact this problem has on the business..."
                  rows={3}
                  data-field="businessImpact"
                />
              </div>
            </div>
          </div>

          {/* Step 2: Current State Analysis */}
          <div className={styles.stepSection}>
            <div className={styles.stepHeader}>
              <h3>
                <span className={styles.stepNumber}>2</span>
                Current State Analysis
              </h3>
            </div>
            
            <div className={styles.stepContent}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Current State Description <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={a3Data.currentStateDescription}
                  onChange={(e) => handleProjectInfoChange('currentStateDescription', e.target.value)}
                  placeholder="Document the current state with facts and data..."
                  rows={4}
                  data-field="currentStateDescription"
                />
              </div>
              
              <div className={styles.metricsSection}>
                <div className={styles.sectionHeader}>
                  <h4>Current State Metrics</h4>
                  <button 
                    className={styles.addBtn}
                    onClick={() => addArrayItem('currentStateMetrics')}
                  >
                    <i className="fas fa-plus"></i> Add Metric
                  </button>
                </div>
                
                <div className={styles.metricsTable}>
                  <table className={styles.dataTable}>
                    <thead>
                      <tr>
                        <th>Metric</th>
                        <th>Current Value</th>
                        <th>Target Value</th>
                        <th>Unit</th>
                        <th>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {a3Data.currentStateMetrics.map((metric) => (
                        <tr key={metric.id}>
                          <td>
                            <input
                              type="text"
                              className={styles.tableInput}
                              value={metric.metric}
                              onChange={(e) => handleArrayItemChange('currentStateMetrics', metric.id, 'metric', e.target.value)}
                              placeholder="Metric name"
                            />
                          </td>
                          <td>
                            <input
                              type="text"
                              className={styles.tableInput}
                              value={metric.current}
                              onChange={(e) => handleArrayItemChange('currentStateMetrics', metric.id, 'current', e.target.value)}
                              placeholder="Current value"
                            />
                          </td>
                          <td>
                            <input
                              type="text"
                              className={styles.tableInput}
                              value={metric.target}
                              onChange={(e) => handleArrayItemChange('currentStateMetrics', metric.id, 'target', e.target.value)}
                              placeholder="Target value"
                            />
                          </td>
                          <td>
                            <input
                              type="text"
                              className={styles.tableInput}
                              value={metric.unit}
                              onChange={(e) => handleArrayItemChange('currentStateMetrics', metric.id, 'unit', e.target.value)}
                              placeholder="Unit"
                            />
                          </td>
                          <td>
                            <button
                              className={styles.removeBtn}
                              onClick={() => removeArrayItem('currentStateMetrics', metric.id)}
                              disabled={a3Data.currentStateMetrics.length === 1}
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

          {/* Step 3: Goal/Target State */}
          <div className={styles.stepSection}>
            <div className={styles.stepHeader}>
              <h3>
                <span className={styles.stepNumber}>3</span>
                Goal/Target State
              </h3>
            </div>
            
            <div className={styles.stepContent}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Goal Statement <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={a3Data.goalStatement}
                  onChange={(e) => handleProjectInfoChange('goalStatement', e.target.value)}
                  placeholder="Define what success looks like with specific, measurable outcomes..."
                  rows={3}
                  data-field="goalStatement"
                />
              </div>
              
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Target State Description <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={a3Data.targetStateDescription}
                  onChange={(e) => handleProjectInfoChange('targetStateDescription', e.target.value)}
                  placeholder="Describe the desired future state in detail..."
                  rows={4}
                  data-field="targetStateDescription"
                />
              </div>
              
              <div className={styles.metricsSection}>
                <div className={styles.sectionHeader}>
                  <h4>Success Criteria</h4>
                  <button 
                    className={styles.addBtn}
                    onClick={() => addArrayItem('successCriteria')}
                  >
                    <i className="fas fa-plus"></i> Add Criteria
                  </button>
                </div>
                
                <div className={styles.metricsTable}>
                  <table className={styles.dataTable}>
                    <thead>
                      <tr>
                        <th>Success Criteria</th>
                        <th>Measurement Method</th>
                        <th>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {a3Data.successCriteria.map((criteria) => (
                        <tr key={criteria.id}>
                          <td>
                            <input
                              type="text"
                              className={styles.tableInput}
                              value={criteria.criteria}
                              onChange={(e) => handleArrayItemChange('successCriteria', criteria.id, 'criteria', e.target.value)}
                              placeholder="Success criteria"
                            />
                          </td>
                          <td>
                            <input
                              type="text"
                              className={styles.tableInput}
                              value={criteria.measurement}
                              onChange={(e) => handleArrayItemChange('successCriteria', criteria.id, 'measurement', e.target.value)}
                              placeholder="How will this be measured?"
                            />
                          </td>
                          <td>
                            <button
                              className={styles.removeBtn}
                              onClick={() => removeArrayItem('successCriteria', criteria.id)}
                              disabled={a3Data.successCriteria.length === 1}
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

          {/* Step 4: Root Cause Analysis */}
          <div className={styles.stepSection}>
            <div className={styles.stepHeader}>
              <h3>
                <span className={styles.stepNumber}>4</span>
                Root Cause Analysis
              </h3>
            </div>
            
            <div className={styles.stepContent}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Root Cause Method
                </label>
                <select
                  className={styles.selectInput}
                  value={a3Data.rootCauseMethod}
                  onChange={(e) => handleProjectInfoChange('rootCauseMethod', e.target.value)}
                  data-field="rootCauseMethod"
                >
                  <option value="Five Whys">Five Whys</option>
                  <option value="Fishbone Diagram">Fishbone Diagram</option>
                  <option value="Fault Tree Analysis">Fault Tree Analysis</option>
                  <option value="Pareto Analysis">Pareto Analysis</option>
                </select>
              </div>
              
              <div className={styles.metricsSection}>
                <div className={styles.sectionHeader}>
                  <h4>Root Causes</h4>
                  <button 
                    className={styles.addBtn}
                    onClick={() => addArrayItem('rootCauseAnalysis')}
                  >
                    <i className="fas fa-plus"></i> Add Root Cause
                  </button>
                </div>
                
                <div className={styles.metricsTable}>
                  <table className={styles.dataTable}>
                    <thead>
                      <tr>
                        <th>Root Cause</th>
                        <th>Category</th>
                        <th>Priority</th>
                        <th>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {a3Data.rootCauseAnalysis.map((cause) => (
                        <tr key={cause.id}>
                          <td>
                            <input
                              type="text"
                              className={styles.tableInput}
                              value={cause.cause}
                              onChange={(e) => handleArrayItemChange('rootCauseAnalysis', cause.id, 'cause', e.target.value)}
                              placeholder="Describe the root cause"
                            />
                          </td>
                          <td>
                            <select
                              className={styles.tableSelect}
                              value={cause.category}
                              onChange={(e) => handleArrayItemChange('rootCauseAnalysis', cause.id, 'category', e.target.value)}
                            >
                              <option value="People">People</option>
                              <option value="Process">Process</option>
                              <option value="Equipment">Equipment</option>
                              <option value="Material">Material</option>
                              <option value="Environment">Environment</option>
                              <option value="Method">Method</option>
                            </select>
                          </td>
                          <td>
                            <select
                              className={styles.tableSelect}
                              value={cause.priority}
                              onChange={(e) => handleArrayItemChange('rootCauseAnalysis', cause.id, 'priority', e.target.value)}
                            >
                              <option value="High">High</option>
                              <option value="Medium">Medium</option>
                              <option value="Low">Low</option>
                            </select>
                          </td>
                          <td>
                            <button
                              className={styles.removeBtn}
                              onClick={() => removeArrayItem('rootCauseAnalysis', cause.id)}
                              disabled={a3Data.rootCauseAnalysis.length === 1}
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

          {/* Step 5: Countermeasures */}
          <div className={styles.stepSection}>
            <div className={styles.stepHeader}>
              <h3>
                <span className={styles.stepNumber}>5</span>
                Countermeasures
              </h3>
            </div>
            
            <div className={styles.stepContent}>
              <div className={styles.metricsSection}>
                <div className={styles.sectionHeader}>
                  <h4>Countermeasures</h4>
                  <button 
                    className={styles.addBtn}
                    onClick={() => addArrayItem('countermeasures')}
                  >
                    <i className="fas fa-plus"></i> Add Countermeasure
                  </button>
                </div>
                
                <div className={styles.metricsTable}>
                  <table className={styles.dataTable}>
                    <thead>
                      <tr>
                        <th>Countermeasure Action</th>
                        <th>Owner</th>
                        <th>Due Date</th>
                        <th>Status</th>
                        <th>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {a3Data.countermeasures.map((countermeasure) => (
                        <tr key={countermeasure.id}>
                          <td>
                            <input
                              type="text"
                              className={styles.tableInput}
                              value={countermeasure.action}
                              onChange={(e) => handleArrayItemChange('countermeasures', countermeasure.id, 'action', e.target.value)}
                              placeholder="Describe the countermeasure action"
                            />
                          </td>
                          <td>
                            <input
                              type="text"
                              className={styles.tableInput}
                              value={countermeasure.owner}
                              onChange={(e) => handleArrayItemChange('countermeasures', countermeasure.id, 'owner', e.target.value)}
                              placeholder="Action owner"
                            />
                          </td>
                          <td>
                            <input
                              type="date"
                              className={styles.tableInput}
                              value={countermeasure.dueDate}
                              onChange={(e) => handleArrayItemChange('countermeasures', countermeasure.id, 'dueDate', e.target.value)}
                            />
                          </td>
                          <td>
                            <select
                              className={styles.tableSelect}
                              value={countermeasure.status}
                              onChange={(e) => handleArrayItemChange('countermeasures', countermeasure.id, 'status', e.target.value)}
                            >
                              <option value="Not Started">Not Started</option>
                              <option value="In Progress">In Progress</option>
                              <option value="Completed">Completed</option>
                              <option value="On Hold">On Hold</option>
                            </select>
                          </td>
                          <td>
                            <button
                              className={styles.removeBtn}
                              onClick={() => removeArrayItem('countermeasures', countermeasure.id)}
                              disabled={a3Data.countermeasures.length === 1}
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

          {/* Step 6: Implementation Plan */}
          <div className={styles.stepSection}>
            <div className={styles.stepHeader}>
              <h3>
                <span className={styles.stepNumber}>6</span>
                Implementation Plan
              </h3>
            </div>
            
            <div className={styles.stepContent}>
              <div className={styles.metricsSection}>
                <div className={styles.sectionHeader}>
                  <h4>Implementation Steps</h4>
                  <button 
                    className={styles.addBtn}
                    onClick={() => addArrayItem('implementationSteps')}
                  >
                    <i className="fas fa-plus"></i> Add Step
                  </button>
                </div>
                
                <div className={styles.metricsTable}>
                  <table className={styles.dataTable}>
                    <thead>
                      <tr>
                        <th>Implementation Step</th>
                        <th>Owner</th>
                        <th>Start Date</th>
                        <th>End Date</th>
                        <th>Dependencies</th>
                        <th>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {a3Data.implementationSteps.map((step) => (
                        <tr key={step.id}>
                          <td>
                            <input
                              type="text"
                              className={styles.tableInput}
                              value={step.step}
                              onChange={(e) => handleArrayItemChange('implementationSteps', step.id, 'step', e.target.value)}
                              placeholder="Implementation step"
                            />
                          </td>
                          <td>
                            <input
                              type="text"
                              className={styles.tableInput}
                              value={step.owner}
                              onChange={(e) => handleArrayItemChange('implementationSteps', step.id, 'owner', e.target.value)}
                              placeholder="Step owner"
                            />
                          </td>
                          <td>
                            <input
                              type="date"
                              className={styles.tableInput}
                              value={step.startDate}
                              onChange={(e) => handleArrayItemChange('implementationSteps', step.id, 'startDate', e.target.value)}
                            />
                          </td>
                          <td>
                            <input
                              type="date"
                              className={styles.tableInput}
                              value={step.endDate}
                              onChange={(e) => handleArrayItemChange('implementationSteps', step.id, 'endDate', e.target.value)}
                            />
                          </td>
                          <td>
                            <input
                              type="text"
                              className={styles.tableInput}
                              value={step.dependencies}
                              onChange={(e) => handleArrayItemChange('implementationSteps', step.id, 'dependencies', e.target.value)}
                              placeholder="Dependencies"
                            />
                          </td>
                          <td>
                            <button
                              className={styles.removeBtn}
                              onClick={() => removeArrayItem('implementationSteps', step.id)}
                              disabled={a3Data.implementationSteps.length === 1}
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

          {/* Step 7: Follow-up Actions */}
          <div className={styles.stepSection}>
            <div className={styles.stepHeader}>
              <h3>
                <span className={styles.stepNumber}>7</span>
                Follow-up Actions
              </h3>
            </div>
            
            <div className={styles.stepContent}>
              <div className={styles.metricsSection}>
                <div className={styles.sectionHeader}>
                  <h4>Follow-up Actions</h4>
                  <button 
                    className={styles.addBtn}
                    onClick={() => addArrayItem('followUpActions')}
                  >
                    <i className="fas fa-plus"></i> Add Follow-up
                  </button>
                </div>
                
                <div className={styles.metricsTable}>
                  <table className={styles.dataTable}>
                    <thead>
                      <tr>
                        <th>Follow-up Action</th>
                        <th>Frequency</th>
                        <th>Owner</th>
                        <th>Next Review</th>
                        <th>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {a3Data.followUpActions.map((action) => (
                        <tr key={action.id}>
                          <td>
                            <input
                              type="text"
                              className={styles.tableInput}
                              value={action.action}
                              onChange={(e) => handleArrayItemChange('followUpActions', action.id, 'action', e.target.value)}
                              placeholder="Follow-up action"
                            />
                          </td>
                          <td>
                            <select
                              className={styles.tableSelect}
                              value={action.frequency}
                              onChange={(e) => handleArrayItemChange('followUpActions', action.id, 'frequency', e.target.value)}
                            >
                              <option value="Daily">Daily</option>
                              <option value="Weekly">Weekly</option>
                              <option value="Monthly">Monthly</option>
                              <option value="Quarterly">Quarterly</option>
                            </select>
                          </td>
                          <td>
                            <input
                              type="text"
                              className={styles.tableInput}
                              value={action.owner}
                              onChange={(e) => handleArrayItemChange('followUpActions', action.id, 'owner', e.target.value)}
                              placeholder="Action owner"
                            />
                          </td>
                          <td>
                            <input
                              type="date"
                              className={styles.tableInput}
                              value={action.nextReview}
                              onChange={(e) => handleArrayItemChange('followUpActions', action.id, 'nextReview', e.target.value)}
                            />
                          </td>
                          <td>
                            <button
                              className={styles.removeBtn}
                              onClick={() => removeArrayItem('followUpActions', action.id)}
                              disabled={a3Data.followUpActions.length === 1}
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

          {/* Step 8: Results/Lessons Learned */}
          <div className={styles.stepSection}>
            <div className={styles.stepHeader}>
              <h3>
                <span className={styles.stepNumber}>8</span>
                Results & Lessons Learned
              </h3>
            </div>
            
            <div className={styles.stepContent}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Results <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={a3Data.results}
                  onChange={(e) => handleProjectInfoChange('results', e.target.value)}
                  placeholder="Document the results achieved from implementing countermeasures..."
                  rows={4}
                  data-field="results"
                />
              </div>
              
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Lessons Learned <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={a3Data.lessonsLearned}
                  onChange={(e) => handleProjectInfoChange('lessonsLearned', e.target.value)}
                  placeholder="What lessons were learned during this A3 process?"
                  rows={4}
                  data-field="lessonsLearned"
                />
              </div>
              
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Next Steps <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={a3Data.nextSteps}
                  onChange={(e) => handleProjectInfoChange('nextSteps', e.target.value)}
                  placeholder="What are the next steps or future improvements to consider?"
                  rows={3}
                  data-field="nextSteps"
                />
              </div>
              
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Approval Status
                </label>
                <select
                  className={styles.selectInput}
                  value={a3Data.approvalStatus}
                  onChange={(e) => handleProjectInfoChange('approvalStatus', e.target.value)}
                  data-field="approvalStatus"
                >
                  <option value="Draft">Draft</option>
                  <option value="Under Review">Under Review</option>
                  <option value="Approved">Approved</option>
                  <option value="Rejected">Rejected</option>
                </select>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Kii Integration */}
<ResourcePageWrapper 
  pageName="A3"
  toolName="A3 Problem Solving"
  adminSettings={adminSettings}
/>
    </div>
  );
};

export default A3;
