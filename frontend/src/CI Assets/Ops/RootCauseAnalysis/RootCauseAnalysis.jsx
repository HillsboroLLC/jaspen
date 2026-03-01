import React, { useState, useEffect } from 'react';
import { useAdminSettings } from '../context/AdminContext';
import ResourcePageWrapper from '../../All/components/ResourcePageWrapper';
import styles from './RootCauseAnalysis.module.css';

const RootCauseAnalysis = () => {
  const { adminSettings } = useAdminSettings();

  // RCA data structure
  const [rcaData, setRcaData] = useState({
    problemStatement: '',
    problemOwner: '',
    rcaTeam: '',
    dateCreated: new Date().toISOString().split('T')[0],
    lastUpdated: new Date().toISOString().split('T')[0],
    analysisMethod: '5whys', // '5whys', 'fishbone', 'causeeffect'
    
    // 5 Whys data
    fiveWhys: [
      { id: 1, question: 'Why did this problem occur?', answer: '' },
      { id: 2, question: 'Why did that happen?', answer: '' },
      { id: 3, question: 'Why did that happen?', answer: '' },
      { id: 4, question: 'Why did that happen?', answer: '' },
      { id: 5, question: 'Why did that happen?', answer: '' }
    ],
    
    // Fishbone data
    fishbone: {
      people: [],
      process: [],
      equipment: [],
      materials: [],
      environment: [],
      methods: []
    },
    
    // Root causes and actions
    identifiedRootCauses: [],
    actionPlan: []
  });

  const [completionPercentage, setCompletionPercentage] = useState(0);

  // Calculate completion percentage
  useEffect(() => {
    const calculateCompletion = () => {
      let totalFields = 0;
      let completedFields = 0;

      // Basic info
      totalFields += 3;
      if (rcaData.problemStatement) completedFields++;
      if (rcaData.problemOwner) completedFields++;
      if (rcaData.rcaTeam) completedFields++;

      // Analysis method specific completion
      if (rcaData.analysisMethod === '5whys') {
        totalFields += 5;
        rcaData.fiveWhys.forEach(why => {
          if (why.answer && why.answer.trim() !== '') completedFields++;
        });
      } else if (rcaData.analysisMethod === 'fishbone') {
        const categories = Object.keys(rcaData.fishbone);
        totalFields += categories.length;
        categories.forEach(category => {
          if (rcaData.fishbone[category].length > 0) completedFields++;
        });
      }

      // Root causes and actions
      totalFields += 2;
      if (rcaData.identifiedRootCauses.length > 0) completedFields++;
      if (rcaData.actionPlan.length > 0) completedFields++;

      const percentage = totalFields > 0 ? Math.round((completedFields / totalFields) * 100) : 0;
      setCompletionPercentage(percentage);
    };

    calculateCompletion();
  }, [rcaData]);

  // Handle field changes
  const handleBasicInfoChange = (field, value) => {
    setRcaData(prev => ({
      ...prev,
      [field]: value,
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Handle 5 Whys changes
  const handleWhyChange = (id, answer) => {
    setRcaData(prev => ({
      ...prev,
      fiveWhys: prev.fiveWhys.map(why => 
        why.id === id ? { ...why, answer } : why
      ),
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Handle Fishbone changes
  const addFishboneCause = (category) => {
    const newCauseText = prompt(`Add a potential cause for ${category.charAt(0).toUpperCase() + category.slice(1)}:`);
    if (newCauseText && newCauseText.trim()) {
      setRcaData(prev => ({
        ...prev,
        fishbone: {
          ...prev.fishbone,
          [category]: [...prev.fishbone[category], { id: Date.now(), cause: newCauseText.trim() }]
        },
        lastUpdated: new Date().toISOString().split('T')[0]
      }));
    }
  };

  const removeFishboneCause = (category, id) => {
    setRcaData(prev => ({
      ...prev,
      fishbone: {
        ...prev.fishbone,
        [category]: prev.fishbone[category].filter(cause => cause.id !== id)
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Handle root causes
  const addRootCause = () => {
    const newRootCause = {
      id: Date.now(),
      cause: '',
      evidence: '',
      validation: '',
      priority: 'medium'
    };
    setRcaData(prev => ({
      ...prev,
      identifiedRootCauses: [...prev.identifiedRootCauses, newRootCause],
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const updateRootCause = (id, field, value) => {
    setRcaData(prev => ({
      ...prev,
      identifiedRootCauses: prev.identifiedRootCauses.map(cause =>
        cause.id === id ? { ...cause, [field]: value } : cause
      ),
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const removeRootCause = (id) => {
    setRcaData(prev => ({
      ...prev,
      identifiedRootCauses: prev.identifiedRootCauses.filter(cause => cause.id !== id),
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Handle action plan
  const addAction = () => {
    const newAction = {
      id: Date.now(),
      action: '',
      owner: '',
      targetDate: '',
      status: 'planned'
    };
    setRcaData(prev => ({
      ...prev,
      actionPlan: [...prev.actionPlan, newAction],
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const updateAction = (id, field, value) => {
    setRcaData(prev => ({
      ...prev,
      actionPlan: prev.actionPlan.map(action =>
        action.id === id ? { ...action, [field]: value } : action
      ),
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const removeAction = (id) => {
    setRcaData(prev => ({
      ...prev,
      actionPlan: prev.actionPlan.filter(action => action.id !== id),
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Save/Export
  const handleSave = () => {
    console.log('Saving RCA draft:', rcaData);
  };

  const handleExport = () => {
    console.log('Exporting RCA to PDF:', rcaData);
  };

  return (
    <ResourcePageWrapper
      pageName="Root Cause Analysis"
      toolName="rootCauseAnalysis"
      adminSettings={adminSettings}
    >
      <div className={styles.rcaContainer}>
        {/* Header */}
        <div className={styles.header}>
          <div className={styles.headerContent}>
            <h1>Root Cause Analysis</h1>
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
          {/* RCA Information */}
          <div className={styles.processInfoCard}>
            <h2>RCA Information</h2>
            
            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel}>
                Problem Statement <span className={styles.required}>*</span>
              </label>
              <textarea
                className={styles.textareaInput}
                value={rcaData.problemStatement}
                onChange={(e) => handleBasicInfoChange('problemStatement', e.target.value)}
                placeholder="Clearly describe the specific problem you're investigating..."
                rows={3}
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
                  value={rcaData.problemOwner}
                  onChange={(e) => handleBasicInfoChange('problemOwner', e.target.value)}
                  placeholder="Who owns this problem?"
                />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  RCA Team <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={rcaData.rcaTeam}
                  onChange={(e) => handleBasicInfoChange('rcaTeam', e.target.value)}
                  placeholder="List team members involved in this RCA"
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
                  value={rcaData.dateCreated}
                  onChange={(e) => handleBasicInfoChange('dateCreated', e.target.value)}
                />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Analysis Method
                </label>
                <select
                  className={styles.selectInput}
                  value={rcaData.analysisMethod}
                  onChange={(e) => handleBasicInfoChange('analysisMethod', e.target.value)}
                >
                  <option value="5whys">5 Whys</option>
                  <option value="fishbone">Fishbone Diagram</option>
                  <option value="causeeffect">Cause & Effect</option>
                </select>
              </div>
            </div>
          </div>

          {/* Analysis Method Section */}
          <div className={styles.analysisCard}>
            <h2>
              {rcaData.analysisMethod === '5whys' && '5 Whys Analysis'}
              {rcaData.analysisMethod === 'fishbone' && 'Fishbone Diagram'}
              {rcaData.analysisMethod === 'causeeffect' && 'Cause & Effect Analysis'}
            </h2>

            {rcaData.analysisMethod === '5whys' && (
              <div className={styles.fiveWhysSection}>
                {rcaData.fiveWhys.map((why, index) => (
                  <div key={why.id} className={styles.whyItem}>
                    <div className={styles.whyNumber}>{index + 1}</div>
                    <div className={styles.whyContent}>
                      <label className={styles.whyQuestion}>{why.question}</label>
                      <textarea
                        className={styles.whyAnswer}
                        value={why.answer}
                        onChange={(e) => handleWhyChange(why.id, e.target.value)}
                        placeholder="Enter your answer here..."
                        rows={2}
                      />
                    </div>
                  </div>
                ))}
              </div>
            )}

            {rcaData.analysisMethod === 'fishbone' && (
              <div className={styles.fishboneSection}>
                <div className={styles.fishboneGrid}>
                  {Object.entries(rcaData.fishbone).map(([category, causes]) => (
                    <div key={category} className={styles.fishboneCategory}>
                      <div className={styles.categoryHeader}>
                        <h4>{category.charAt(0).toUpperCase() + category.slice(1)}</h4>
                        <button 
                          className={styles.addCauseBtn}
                          onClick={() => addFishboneCause(category)}
                        >
                          <i className="fas fa-plus"></i>
                        </button>
                      </div>
                      <div className={styles.causesList}>
                        {causes.map((cause) => (
                          <div key={cause.id} className={styles.causeItem}>
                            <span>{cause.cause}</span>
                            <button 
                              className={styles.removeCauseBtn}
                              onClick={() => removeFishboneCause(category, cause.id)}
                            >
                              <i className="fas fa-times"></i>
                            </button>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Root Causes Section */}
          <div className={styles.rootCausesCard}>
            <div className={styles.sectionHeader}>
              <h2>Identified Root Causes</h2>
              <button className={styles.addBtn} onClick={addRootCause}>
                <i className="fas fa-plus"></i> Add Root Cause
              </button>
            </div>

            <div className={styles.rootCausesList}>
              {rcaData.identifiedRootCauses.map((rootCause) => (
                <div key={rootCause.id} className={styles.rootCauseItem}>
                  <div className={styles.rootCauseHeader}>
                    <input
                      type="text"
                      className={styles.rootCauseTitle}
                      value={rootCause.cause}
                      onChange={(e) => updateRootCause(rootCause.id, 'cause', e.target.value)}
                      placeholder="Describe the root cause..."
                    />
                    <select
                      className={styles.prioritySelect}
                      value={rootCause.priority}
                      onChange={(e) => updateRootCause(rootCause.id, 'priority', e.target.value)}
                    >
                      <option value="high">High Priority</option>
                      <option value="medium">Medium Priority</option>
                      <option value="low">Low Priority</option>
                    </select>
                    <button 
                      className={styles.removeBtn}
                      onClick={() => removeRootCause(rootCause.id)}
                    >
                      <i className="fas fa-trash"></i>
                    </button>
                  </div>
                  <div className={styles.rootCauseDetails}>
                    <div className={styles.detailField}>
                      <label>Evidence/Data Supporting This Root Cause:</label>
                      <textarea
                        value={rootCause.evidence}
                        onChange={(e) => updateRootCause(rootCause.id, 'evidence', e.target.value)}
                        placeholder="What evidence supports this as a root cause?"
                        rows={2}
                      />
                    </div>
                    <div className={styles.detailField}>
                      <label>Validation Method:</label>
                      <textarea
                        value={rootCause.validation}
                        onChange={(e) => updateRootCause(rootCause.id, 'validation', e.target.value)}
                        placeholder="How will you validate this root cause?"
                        rows={2}
                      />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Action Plan Section */}
          <div className={styles.actionPlanCard}>
            <div className={styles.sectionHeader}>
              <h2>Corrective Action Plan</h2>
              <button className={styles.addBtn} onClick={addAction}>
                <i className="fas fa-plus"></i> Add Action
              </button>
            </div>

            <div className={styles.actionsList}>
              {rcaData.actionPlan.map((action) => (
                <div key={action.id} className={styles.actionItem}>
                  <div className={styles.actionHeader}>
                    <input
                      type="text"
                      className={styles.actionTitle}
                      value={action.action}
                      onChange={(e) => updateAction(action.id, 'action', e.target.value)}
                      placeholder="Describe the corrective action..."
                    />
                    <input
                      type="text"
                      className={styles.actionOwner}
                      value={action.owner}
                      onChange={(e) => updateAction(action.id, 'owner', e.target.value)}
                      placeholder="Owner"
                    />
                    <input
                      type="date"
                      className={styles.actionDate}
                      value={action.targetDate}
                      onChange={(e) => updateAction(action.id, 'targetDate', e.target.value)}
                    />
                    <select
                      className={styles.statusSelect}
                      value={action.status}
                      onChange={(e) => updateAction(action.id, 'status', e.target.value)}
                    >
                      <option value="planned">Planned</option>
                      <option value="in-progress">In Progress</option>
                      <option value="completed">Completed</option>
                    </select>
                    <button 
                      className={styles.removeBtn}
                      onClick={() => removeAction(action.id)}
                    >
                      <i className="fas fa-trash"></i>
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className={styles.footer}>
          <div className={styles.footerContent}>
            <div className={styles.completionStatus}>
              <i className={`fas ${completionPercentage === 100 ? 'fa-check-circle' : 'fa-clock'}`}></i>
              <span>
                {completionPercentage === 100 
                  ? 'RCA Complete - Ready for Review' 
                  : `${completionPercentage}% Complete`
                }
              </span>
            </div>
            <div className={styles.footerActions}>
              <button className={styles.secondaryBtn}>
                <i className="fas fa-eye"></i> Preview
              </button>
              <button 
                className={styles.primaryBtn}
                disabled={completionPercentage < 100}
              >
                <i className="fas fa-check"></i> Submit for Review
              </button>
            </div>
          </div>
        </div>
      </div>
    </ResourcePageWrapper>
  );
};

export default RootCauseAnalysis;
