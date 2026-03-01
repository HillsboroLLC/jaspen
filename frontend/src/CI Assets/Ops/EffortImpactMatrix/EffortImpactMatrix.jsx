// ============================================================================
// File: src/Ops/EffortImpactMatrix/EffortImpactMatrix.jsx
// Purpose: Effort Impact Matrix using floating chat from ResourcePageWrapper,
//          full-width info card, solid progress bar, and no extra bottom space.
// ============================================================================

import React, { useState, useEffect, useCallback } from 'react';
import styles from './EffortImpactMatrix.module.css';
import { useAdminSettings } from '../context/AdminContext';
import ResourcePageWrapper from '../../All/components/ResourcePageWrapper';
import '@fortawesome/fontawesome-free/css/all.min.css';

const EffortImpactMatrix = () => {
  const { adminSettings } = useAdminSettings();

  // Effort Impact Matrix structure
  const [matrixData, setMatrixData] = useState({
    // Matrix Information
    matrixTitle: '',
    facilitator: '',
    dateCreated: new Date().toISOString().split('T')[0],
    lastUpdated: new Date().toISOString().split('T')[0],

    // Matrix Setup
    matrixSetup: {
      purpose: '',
      scope: '',
      timeframe: '',
      criteria: {
        effort: {
          low: 'Low effort (< 1 week)',
          medium: 'Medium effort (1-4 weeks)',
          high: 'High effort (> 4 weeks)',
        },
        impact: {
          low: 'Low impact (minimal improvement)',
          medium: 'Medium impact (moderate improvement)',
          high: 'High impact (significant improvement)',
        },
      },
    },

    // Items to evaluate
    items: [],

    // Matrix quadrants
    quadrants: {
      quickWins: [], // High Impact, Low Effort
      majorProjects: [], // High Impact, High Effort
      fillIns: [], // Low Impact, Low Effort
      thanklessJobs: [], // Low Impact, High Effort
    },

    // Prioritization results
    prioritization: {
      recommended: [],
      deferred: [],
      rejected: [],
      rationale: '',
    },

    // Action planning
    actionPlan: {
      immediate: [],
      shortTerm: [],
      longTerm: [],
      resources: '',
      timeline: '',
      owner: '',
    },

    // Documentation
    documentation: {
      assumptions: '',
      constraints: '',
      risks: '',
      nextSteps: '',
      approver: '',
      approvalDate: '',
    },
  });

  const [completionPercentage, setCompletionPercentage] = useState(0);

  // Accept extracted data from wrapper and merge into model
  const handleKiiDataUpdate = useCallback((extractedData = {}) => {
    setMatrixData((prev) => {
      const next = { ...prev };

      if (extractedData.matrixTitle) next.matrixTitle = extractedData.matrixTitle;
      if (extractedData.facilitator) next.facilitator = extractedData.facilitator;

      const ms = { ...next.matrixSetup };
      if (extractedData.purpose) ms.purpose = extractedData.purpose;
      if (extractedData.scope) ms.scope = extractedData.scope;
      if (extractedData.timeframe) ms.timeframe = extractedData.timeframe;
      if (extractedData.criteria?.effort) {
        ms.criteria = ms.criteria || { effort: {}, impact: {} };
        ms.criteria.effort = { ...ms.criteria.effort, ...extractedData.criteria.effort };
      }
      if (extractedData.criteria?.impact) {
        ms.criteria = ms.criteria || { effort: {}, impact: {} };
        ms.criteria.impact = { ...ms.criteria.impact, ...extractedData.criteria.impact };
      }
      next.matrixSetup = ms;

      if (Array.isArray(extractedData.items)) {
        next.items = extractedData.items.map((it, idx) => ({
          id: it.id || Date.now() + idx,
          title: it.title || '',
          description: it.description || '',
          category: it.category || 'process-improvement',
          effortScore:
            Number.isFinite(it.effortScore) && it.effortScore > 0 ? it.effortScore : 2,
          impactScore:
            Number.isFinite(it.impactScore) && it.impactScore > 0 ? it.impactScore : 2,
          effortJustification: it.effortJustification || '',
          impactJustification: it.impactJustification || '',
          quadrant: it.quadrant || '',
          priority: it.priority || '',
          estimatedDuration: it.estimatedDuration || '',
          estimatedCost: it.estimatedCost || '',
          expectedBenefit: it.expectedBenefit || '',
          stakeholders: it.stakeholders || '',
          dependencies: it.dependencies || '',
          risks: it.risks || '',
          status: it.status || 'evaluated',
        }));
      }

      if (extractedData.prioritization?.rationale) {
        next.prioritization = {
          ...next.prioritization,
          rationale: extractedData.prioritization.rationale,
        };
      }

      if (extractedData.actionPlan) {
        next.actionPlan = { ...next.actionPlan, ...extractedData.actionPlan };
      }

      if (extractedData.documentation) {
        next.documentation = { ...next.documentation, ...extractedData.documentation };
      }

      next.lastUpdated = new Date().toISOString().split('T')[0];
      return next;
    });
  }, []);

  // Calculate completion percentage
  useEffect(() => {
    const calculateCompletion = () => {
      let totalFields = 0;
      let completedFields = 0;

      // Basic info (3 fields)
      totalFields += 3;
      if (matrixData.matrixTitle) completedFields++;
      if (matrixData.facilitator) completedFields++;
      if (matrixData.matrixSetup.purpose) completedFields++;

      // Setup (2 fields)
      totalFields += 2;
      if (matrixData.matrixSetup.scope) completedFields++;
      if (matrixData.matrixSetup.timeframe) completedFields++;

      // Items (1 field)
      totalFields += 1;
      if (matrixData.items.length > 0) completedFields++;

      // Prioritization (1 field)
      totalFields += 1;
      if (matrixData.prioritization.rationale) completedFields++;

      // Action plan (1 field)
      totalFields += 1;
      if (matrixData.actionPlan.timeline) completedFields++;

      // Documentation (1 field)
      totalFields += 1;
      if (matrixData.documentation.assumptions) completedFields++;

      const percentage = totalFields > 0 ? Math.round((completedFields / totalFields) * 100) : 0;
      setCompletionPercentage(percentage);
    };

    calculateCompletion();
  }, [matrixData]);

  // Handle basic info changes
  const handleBasicInfoChange = (field, value) => {
    setMatrixData((prev) => ({
      ...prev,
      [field]: value,
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  // Handle setup changes
  const handleSetupChange = (field, value) => {
    setMatrixData((prev) => ({
      ...prev,
      matrixSetup: {
        ...prev.matrixSetup,
        [field]: value,
      },
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  // Handle criteria changes
  const handleCriteriaChange = (type, level, value) => {
    setMatrixData((prev) => ({
      ...prev,
      matrixSetup: {
        ...prev.matrixSetup,
        criteria: {
          ...prev.matrixSetup.criteria,
          [type]: {
            ...prev.matrixSetup.criteria[type],
            [level]: value,
          },
        },
      },
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  // Add item
  const addItem = () => {
    const newItem = {
      id: Date.now(),
      title: '',
      description: '',
      category: 'process-improvement',
      effortScore: 2,
      impactScore: 2,
      effortJustification: '',
      impactJustification: '',
      quadrant: '',
      priority: '',
      estimatedDuration: '',
      estimatedCost: '',
      expectedBenefit: '',
      stakeholders: '',
      dependencies: '',
      risks: '',
      status: 'evaluated',
    };

    setMatrixData((prev) => ({
      ...prev,
      items: [...prev.items, newItem],
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  // Remove item
  const removeItem = (itemId) => {
    setMatrixData((prev) => ({
      ...prev,
      items: prev.items.filter((item) => item.id !== itemId),
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  // Handle item changes (and compute quadrant/priority)
  const handleItemChange = (itemId, field, value) => {
    setMatrixData((prev) => ({
      ...prev,
      items: prev.items.map((item) => {
        if (item.id === itemId) {
          const updatedItem = { ...item, [field]: value };

          if (field === 'effortScore' || field === 'impactScore') {
            const effort = field === 'effortScore' ? value : item.effortScore;
            const impact = field === 'impactScore' ? value : item.impactScore;

            let quadrant = '';
            let priority = '';

            if (impact >= 3 && effort <= 2) {
              quadrant = 'Quick Wins';
              priority = 'High';
            } else if (impact >= 3 && effort >= 3) {
              quadrant = 'Major Projects';
              priority = 'Medium';
            } else if (impact <= 2 && effort <= 2) {
              quadrant = 'Fill-ins';
              priority = 'Low';
            } else {
              quadrant = 'Thankless Jobs';
              priority = 'Very Low';
            }

            updatedItem.quadrant = quadrant;
            updatedItem.priority = priority;
          }

          return updatedItem;
        }
        return item;
      }),
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  // Update quadrants when items change
  useEffect(() => {
    const quickWins = matrixData.items.filter((i) => i.quadrant === 'Quick Wins');
    const majorProjects = matrixData.items.filter((i) => i.quadrant === 'Major Projects');
    const fillIns = matrixData.items.filter((i) => i.quadrant === 'Fill-ins');
    const thanklessJobs = matrixData.items.filter((i) => i.quadrant === 'Thankless Jobs');

    setMatrixData((prev) => ({
      ...prev,
      quadrants: { quickWins, majorProjects, fillIns, thanklessJobs },
    }));
  }, [matrixData.items]);

  // Handle prioritization changes
  const handlePrioritizationChange = (field, value) => {
    setMatrixData((prev) => ({
      ...prev,
      prioritization: {
        ...prev.prioritization,
        [field]: value,
      },
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  // Handle action plan changes
  const handleActionPlanChange = (field, value) => {
    setMatrixData((prev) => ({
      ...prev,
      actionPlan: {
        ...prev.actionPlan,
        [field]: value,
      },
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  // Handle documentation changes
  const handleDocumentationChange = (field, value) => {
    setMatrixData((prev) => ({
      ...prev,
      documentation: {
        ...prev.documentation,
        [field]: value,
      },
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  // Add / remove / edit action item
  const addActionItem = (timeframe) => {
    const newAction = {
      id: Date.now(),
      item: '',
      owner: '',
      dueDate: '',
      status: 'planned',
    };

    setMatrixData((prev) => ({
      ...prev,
      actionPlan: {
        ...prev.actionPlan,
        [timeframe]: [...prev.actionPlan[timeframe], newAction],
      },
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  const removeActionItem = (timeframe, actionId) => {
    setMatrixData((prev) => ({
      ...prev,
      actionPlan: {
        ...prev.actionPlan,
        [timeframe]: prev.actionPlan[timeframe].filter((a) => a.id !== actionId),
      },
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  const handleActionItemChange = (timeframe, actionId, field, value) => {
    setMatrixData((prev) => ({
      ...prev,
      actionPlan: {
        ...prev.actionPlan,
        [timeframe]: prev.actionPlan[timeframe].map((a) =>
          a.id === actionId ? { ...a, [field]: value } : a
        ),
      },
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  const handleSave = () =>
    console.log('Saving Effort Impact Matrix draft:', matrixData);
  const handleExport = () =>
    console.log('Exporting Effort Impact Matrix to PDF:', matrixData);

  return (
    <ResourcePageWrapper
      pageName="Effort Impact Matrix"
      toolName="Effort Impact Matrix"
      adminSettings={adminSettings}
      currentData={matrixData}
      onDataUpdate={handleKiiDataUpdate}
    >
      <div className={styles.rcaContainer} style={{ paddingBottom: 0 }}>
        {/* Header */}
        <div className={styles.header}>
          <div className={styles.headerContent}>
            <h1>Effort Impact Matrix</h1>
            <div className={styles.progressSection}>
              {/* solid bar, no gradient */}
              <div
                className={styles.progressBar}
                style={{ background: 'var(--lss-gray-200)', backgroundImage: 'none' }}
              >
                <div
                  className={styles.progressFill}
                  style={{
                    width: `${completionPercentage}%`,
                    background: 'var(--lss-primary)',
                    backgroundImage: 'none',
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
        <div className={styles.mainContent}>
          {/* Top Section: Full-width Matrix Information (chat removed; floating chat in wrapper) */}
          <div className={styles.topSection} style={{ display: 'block', marginBottom: 0 }}>
            <div className={styles.processInfoCard} style={{ width: '100%' }}>
              <h2>Matrix Information</h2>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Matrix Title <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={matrixData.matrixTitle}
                  onChange={(e) => handleBasicInfoChange('matrixTitle', e.target.value)}
                  placeholder="Enter the title for your effort impact matrix"
                />
              </div>

              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>
                    Facilitator <span className={styles.required}>*</span>
                  </label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={matrixData.facilitator}
                    onChange={(e) => handleBasicInfoChange('facilitator', e.target.value)}
                    placeholder="Who is facilitating this analysis?"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Date Created</label>
                  <input
                    type="date"
                    className={styles.textInput}
                    value={matrixData.dateCreated}
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
                  value={matrixData.matrixSetup.purpose}
                  onChange={(e) => handleSetupChange('purpose', e.target.value)}
                  placeholder="What is the purpose of this prioritization exercise?"
                  rows={2}
                />
              </div>

              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Scope</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={matrixData.matrixSetup.scope}
                    onChange={(e) => handleSetupChange('scope', e.target.value)}
                    placeholder="What is included in this analysis?"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Timeframe</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={matrixData.matrixSetup.timeframe}
                    onChange={(e) => handleSetupChange('timeframe', e.target.value)}
                    placeholder="What timeframe are we considering?"
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Evaluation Criteria Section */}
          <div className={styles.analysisCard}>
            <h2>Evaluation Criteria</h2>
            <div className={styles.criteriaGrid}>
              <div className={styles.criteriaSection}>
                <h3>Effort Criteria</h3>
                <div className={styles.criteriaLevels}>
                  <div className={styles.criteriaLevel}>
                    <label className={styles.criteriaLabel}>Low Effort (Score: 1)</label>
                    <input
                      type="text"
                      className={styles.textInput}
                      value={matrixData.matrixSetup.criteria.effort.low}
                      onChange={(e) => handleCriteriaChange('effort', 'low', e.target.value)}
                      placeholder="Define low effort criteria"
                    />
                  </div>
                  <div className={styles.criteriaLevel}>
                    <label className={styles.criteriaLabel}>Medium Effort (Score: 2)</label>
                    <input
                      type="text"
                      className={styles.textInput}
                      value={matrixData.matrixSetup.criteria.effort.medium}
                      onChange={(e) => handleCriteriaChange('effort', 'medium', e.target.value)}
                      placeholder="Define medium effort criteria"
                    />
                  </div>
                  <div className={styles.criteriaLevel}>
                    <label className={styles.criteriaLabel}>High Effort (Score: 3)</label>
                    <input
                      type="text"
                      className={styles.textInput}
                      value={matrixData.matrixSetup.criteria.effort.high}
                      onChange={(e) => handleCriteriaChange('effort', 'high', e.target.value)}
                      placeholder="Define high effort criteria"
                    />
                  </div>
                </div>
              </div>

              <div className={styles.criteriaSection}>
                <h3>Impact Criteria</h3>
                <div className={styles.criteriaLevels}>
                  <div className={styles.criteriaLevel}>
                    <label className={styles.criteriaLabel}>Low Impact (Score: 1)</label>
                    <input
                      type="text"
                      className={styles.textInput}
                      value={matrixData.matrixSetup.criteria.impact.low}
                      onChange={(e) => handleCriteriaChange('impact', 'low', e.target.value)}
                      placeholder="Define low impact criteria"
                    />
                  </div>
                  <div className={styles.criteriaLevel}>
                    <label className={styles.criteriaLabel}>Medium Impact (Score: 2)</label>
                    <input
                      type="text"
                      className={styles.textInput}
                      value={matrixData.matrixSetup.criteria.impact.medium}
                      onChange={(e) => handleCriteriaChange('impact', 'medium', e.target.value)}
                      placeholder="Define medium impact criteria"
                    />
                  </div>
                  <div className={styles.criteriaLevel}>
                    <label className={styles.criteriaLabel}>High Impact (Score: 3)</label>
                    <input
                      type="text"
                      className={styles.textInput}
                      value={matrixData.matrixSetup.criteria.impact.high}
                      onChange={(e) => handleCriteriaChange('impact', 'high', e.target.value)}
                      placeholder="Define high impact criteria"
                    />
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Items Evaluation Section */}
          <div className={styles.analysisCard}>
            <div className={styles.sectionHeader}>
              <h2>Items Evaluation</h2>
              <button className={styles.addBtn} onClick={addItem}>
                <i className="fas fa-plus"></i> Add Item
              </button>
            </div>

            <div className={styles.itemsTable}>
              <table className={styles.evaluationTable}>
                <thead>
                  <tr>
                    <th>Title</th>
                    <th>Category</th>
                    <th>Effort Score</th>
                    <th>Impact Score</th>
                    <th>Quadrant</th>
                    <th>Priority</th>
                    <th>Duration</th>
                    <th>Expected Benefit</th>
                    <th>Status</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {matrixData.items.map((item) => (
                    <tr key={item.id}>
                      <td>
                        <input
                          type="text"
                          className={styles.tableInput}
                          value={item.title}
                          onChange={(e) => handleItemChange(item.id, 'title', e.target.value)}
                          placeholder="Item title"
                        />
                      </td>
                      <td>
                        <select
                          className={styles.tableSelect}
                          value={item.category}
                          onChange={(e) => handleItemChange(item.id, 'category', e.target.value)}
                        >
                          <option value="process-improvement">Process Improvement</option>
                          <option value="technology">Technology</option>
                          <option value="training">Training</option>
                          <option value="policy">Policy</option>
                          <option value="other">Other</option>
                        </select>
                      </td>
                      <td>
                        <select
                          className={styles.effortSelect}
                          value={item.effortScore}
                          onChange={(e) =>
                            handleItemChange(item.id, 'effortScore', parseInt(e.target.value))
                          }
                        >
                          <option value={1}>1 - Low</option>
                          <option value={2}>2 - Medium</option>
                          <option value={3}>3 - High</option>
                        </select>
                      </td>
                      <td>
                        <select
                          className={styles.impactSelect}
                          value={item.impactScore}
                          onChange={(e) =>
                            handleItemChange(item.id, 'impactScore', parseInt(e.target.value))
                          }
                        >
                          <option value={1}>1 - Low</option>
                          <option value={2}>2 - Medium</option>
                          <option value={3}>3 - High</option>
                        </select>
                      </td>
                      <td>
                        <span
                          className={`${styles.quadrantBadge} ${
                            styles[item.quadrant?.toLowerCase()?.replace(/\s+/g, '')]
                          }`}
                        >
                          {item.quadrant}
                        </span>
                      </td>
                      <td>
                        <span
                          className={`${styles.priorityBadge} ${
                            styles[item.priority?.toLowerCase()?.replace(/\s+/g, '')]
                          }`}
                        >
                          {item.priority}
                        </span>
                      </td>
                      <td>
                        <input
                          type="text"
                          className={styles.tableInput}
                          value={item.estimatedDuration}
                          onChange={(e) =>
                            handleItemChange(item.id, 'estimatedDuration', e.target.value)
                          }
                          placeholder="Duration"
                        />
                      </td>
                      <td>
                        <input
                          type="text"
                          className={styles.tableInput}
                          value={item.expectedBenefit}
                          onChange={(e) =>
                            handleItemChange(item.id, 'expectedBenefit', e.target.value)
                          }
                          placeholder="Expected benefit"
                        />
                      </td>
                      <td>
                        <select
                          className={styles.statusSelect}
                          value={item.status}
                          onChange={(e) => handleItemChange(item.id, 'status', e.target.value)}
                        >
                          <option value="evaluated">Evaluated</option>
                          <option value="approved">Approved</option>
                          <option value="in-progress">In Progress</option>
                          <option value="completed">Completed</option>
                          <option value="deferred">Deferred</option>
                          <option value="rejected">Rejected</option>
                        </select>
                      </td>
                      <td>
                        <button className={styles.removeBtn} onClick={() => removeItem(item.id)}>
                          <i className="fas fa-times"></i>
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Matrix Visualization Section */}
          <div className={styles.analysisCard}>
            <h2>Matrix Visualization</h2>
            <div className={styles.matrixContainer}>
              <div className={styles.matrixGrid}>
                <div className={styles.matrixQuadrant + ' ' + styles.quickWins}>
                  <div className={styles.quadrantHeader}>
                    <h3>Quick Wins</h3>
                    <span className={styles.quadrantCount}>
                      ({matrixData.quadrants.quickWins.length})
                    </span>
                  </div>
                  <div className={styles.quadrantDescription}>High Impact, Low Effort</div>
                  <div className={styles.quadrantItems}>
                    {matrixData.quadrants.quickWins.map((item) => (
                      <div key={item.id} className={styles.matrixItem}>
                        <div className={styles.itemTitle}>{item.title}</div>
                        <div className={styles.itemScores}>
                          E:{item.effortScore} I:{item.impactScore}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                <div className={styles.matrixQuadrant + ' ' + styles.majorProjects}>
                  <div className={styles.quadrantHeader}>
                    <h3>Major Projects</h3>
                    <span className={styles.quadrantCount}>
                      ({matrixData.quadrants.majorProjects.length})
                    </span>
                  </div>
                  <div className={styles.quadrantDescription}>High Impact, High Effort</div>
                  <div className={styles.quadrantItems}>
                    {matrixData.quadrants.majorProjects.map((item) => (
                      <div key={item.id} className={styles.matrixItem}>
                        <div className={styles.itemTitle}>{item.title}</div>
                        <div className={styles.itemScores}>
                          E:{item.effortScore} I:{item.impactScore}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                <div className={styles.matrixQuadrant + ' ' + styles.fillIns}>
                  <div className={styles.quadrantHeader}>
                    <h3>Fill-ins</h3>
                    <span className={styles.quadrantCount}>
                      ({matrixData.quadrants.fillIns.length})
                    </span>
                  </div>
                  <div className={styles.quadrantDescription}>Low Impact, Low Effort</div>
                  <div className={styles.quadrantItems}>
                    {matrixData.quadrants.fillIns.map((item) => (
                      <div key={item.id} className={styles.matrixItem}>
                        <div className={styles.itemTitle}>{item.title}</div>
                        <div className={styles.itemScores}>
                          E:{item.effortScore} I:{item.impactScore}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                <div className={styles.matrixQuadrant + ' ' + styles.thanklessJobs}>
                  <div className={styles.quadrantHeader}>
                    <h3>Thankless Jobs</h3>
                    <span className={styles.quadrantCount}>
                      ({matrixData.quadrants.thanklessJobs.length})
                    </span>
                  </div>
                  <div className={styles.quadrantDescription}>Low Impact, High Effort</div>
                  <div className={styles.quadrantItems}>
                    {matrixData.quadrants.thanklessJobs.map((item) => (
                      <div key={item.id} className={styles.matrixItem}>
                        <div className={styles.itemTitle}>{item.title}</div>
                        <div className={styles.itemScores}>
                          E:{item.effortScore} I:{item.impactScore}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              <div className={styles.matrixAxes}>
                <div className={styles.yAxis}>
                  <span className={styles.axisLabel}>Impact</span>
                  <div className={styles.axisScale}>
                    <span>High</span>
                    <span>Medium</span>
                    <span>Low</span>
                  </div>
                </div>
                <div className={styles.xAxis}>
                  <span className={styles.axisLabel}>Effort</span>
                  <div className={styles.axisScale}>
                    <span>Low</span>
                    <span>Medium</span>
                    <span>High</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Prioritization Results Section */}
          <div className={styles.analysisCard}>
            <h2>Prioritization Results</h2>
            <div className={styles.prioritizationGrid}>
              <div className={styles.prioritySection}>
                <h3>Recommended (High Priority)</h3>
                <div className={styles.priorityList}>
                  {matrixData.items
                    .filter((item) => item.priority === 'High')
                    .map((item) => (
                      <div key={item.id} className={styles.priorityItem}>
                        <div className={styles.priorityItemHeader}>
                          <span className={styles.priorityItemTitle}>{item.title}</span>
                          <span className={`${styles.priorityBadge} ${styles.high}`}>High</span>
                        </div>
                        <div className={styles.priorityItemDetails}>
                          <span>Effort: {item.effortScore}/3</span>
                          <span>Impact: {item.impactScore}/3</span>
                          <span>Duration: {item.estimatedDuration}</span>
                        </div>
                      </div>
                    ))}
                </div>
              </div>

              <div className={styles.prioritySection}>
                <h3>Consider (Medium Priority)</h3>
                <div className={styles.priorityList}>
                  {matrixData.items
                    .filter((item) => item.priority === 'Medium')
                    .map((item) => (
                      <div key={item.id} className={styles.priorityItem}>
                        <div className={styles.priorityItemHeader}>
                          <span className={styles.priorityItemTitle}>{item.title}</span>
                          <span className={`${styles.priorityBadge} ${styles.medium}`}>Medium</span>
                        </div>
                        <div className={styles.priorityItemDetails}>
                          <span>Effort: {item.effortScore}/3</span>
                          <span>Impact: {item.impactScore}/3</span>
                          <span>Duration: {item.estimatedDuration}</span>
                        </div>
                      </div>
                    ))}
                </div>
              </div>

              <div className={styles.prioritySection}>
                <h3>Avoid (Low Priority)</h3>
                <div className={styles.priorityList}>
                  {matrixData.items
                    .filter((item) => item.priority === 'Low' || item.priority === 'Very Low')
                    .map((item) => (
                      <div key={item.id} className={styles.priorityItem}>
                        <div className={styles.priorityItemHeader}>
                          <span className={styles.priorityItemTitle}>{item.title}</span>
                          <span className={`${styles.priorityBadge} ${styles.low}`}>
                            {item.priority}
                          </span>
                        </div>
                        <div className={styles.priorityItemDetails}>
                          <span>Effort: {item.effortScore}/3</span>
                          <span>Impact: {item.impactScore}/3</span>
                          <span>Duration: {item.estimatedDuration}</span>
                        </div>
                      </div>
                    ))}
                </div>
              </div>
            </div>

            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel}>Prioritization Rationale</label>
              <textarea
                className={styles.textareaInput}
                value={matrixData.prioritization.rationale}
                onChange={(e) => handlePrioritizationChange('rationale', e.target.value)}
                placeholder="Explain the rationale behind the prioritization decisions"
                rows={3}
              />
            </div>
          </div>

          {/* Action Planning Section */}
          <div className={styles.analysisCard}>
            <h2>Action Planning</h2>
            <div className={styles.actionPlanGrid}>
              <div className={styles.timeframeSection}>
                <div className={styles.timeframeHeader}>
                  <h3>Immediate Actions (0-30 days)</h3>
                  <button className={styles.addBtn} onClick={() => addActionItem('immediate')}>
                    <i className="fas fa-plus"></i> Add
                  </button>
                </div>
                <div className={styles.actionsList}>
                  {matrixData.actionPlan.immediate.map((action) => (
                    <div key={action.id} className={styles.actionItem}>
                      <input
                        type="text"
                        className={styles.actionInput}
                        value={action.item}
                        onChange={(e) =>
                          handleActionItemChange('immediate', action.id, 'item', e.target.value)
                        }
                        placeholder="Action item"
                      />
                      <input
                        type="text"
                        className={styles.actionInput}
                        value={action.owner}
                        onChange={(e) =>
                          handleActionItemChange('immediate', action.id, 'owner', e.target.value)
                        }
                        placeholder="Owner"
                      />
                      <input
                        type="date"
                        className={styles.actionInput}
                        value={action.dueDate}
                        onChange={(e) =>
                          handleActionItemChange('immediate', action.id, 'dueDate', e.target.value)
                        }
                      />
                      <button
                        className={styles.removeBtn}
                        onClick={() => removeActionItem('immediate', action.id)}
                      >
                        <i className="fas fa-times"></i>
                      </button>
                    </div>
                  ))}
                </div>
              </div>

              <div className={styles.timeframeSection}>
                <div className={styles.timeframeHeader}>
                  <h3>Short-term Actions (1-3 months)</h3>
                  <button className={styles.addBtn} onClick={() => addActionItem('shortTerm')}>
                    <i className="fas fa-plus"></i> Add
                  </button>
                </div>
                <div className={styles.actionsList}>
                  {matrixData.actionPlan.shortTerm.map((action) => (
                    <div key={action.id} className={styles.actionItem}>
                      <input
                        type="text"
                        className={styles.actionInput}
                        value={action.item}
                        onChange={(e) =>
                          handleActionItemChange('shortTerm', action.id, 'item', e.target.value)
                        }
                        placeholder="Action item"
                      />
                      <input
                        type="text"
                        className={styles.actionInput}
                        value={action.owner}
                        onChange={(e) =>
                          handleActionItemChange('shortTerm', action.id, 'owner', e.target.value)
                        }
                        placeholder="Owner"
                      />
                      <input
                        type="date"
                        className={styles.actionInput}
                        value={action.dueDate}
                        onChange={(e) =>
                          handleActionItemChange('shortTerm', action.id, 'dueDate', e.target.value)
                        }
                      />
                      <button
                        className={styles.removeBtn}
                        onClick={() => removeActionItem('shortTerm', action.id)}
                      >
                        <i className="fas fa-times"></i>
                      </button>
                    </div>
                  ))}
                </div>
              </div>

              <div className={styles.timeframeSection}>
                <div className={styles.timeframeHeader}>
                  <h3>Long-term Actions (3+ months)</h3>
                  <button className={styles.addBtn} onClick={() => addActionItem('longTerm')}>
                    <i className="fas fa-plus"></i> Add
                  </button>
                </div>
                <div className={styles.actionsList}>
                  {matrixData.actionPlan.longTerm.map((action) => (
                    <div key={action.id} className={styles.actionItem}>
                      <input
                        type="text"
                        className={styles.actionInput}
                        value={action.item}
                        onChange={(e) =>
                          handleActionItemChange('longTerm', action.id, 'item', e.target.value)
                        }
                        placeholder="Action item"
                      />
                      <input
                        type="text"
                        className={styles.actionInput}
                        value={action.owner}
                        onChange={(e) =>
                          handleActionItemChange('longTerm', action.id, 'owner', e.target.value)
                        }
                        placeholder="Owner"
                      />
                      <input
                        type="date"
                        className={styles.actionInput}
                        value={action.dueDate}
                        onChange={(e) =>
                          handleActionItemChange('longTerm', action.id, 'dueDate', e.target.value)
                        }
                      />
                      <button
                        className={styles.removeBtn}
                        onClick={() => removeActionItem('longTerm', action.id)}
                      >
                        <i className="fas fa-times"></i>
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <div className={styles.actionPlanDetails}>
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Resources Required</label>
                  <textarea
                    className={styles.textareaInput}
                    value={matrixData.actionPlan.resources}
                    onChange={(e) => handleActionPlanChange('resources', e.target.value)}
                    placeholder="What resources are needed to execute the action plan?"
                    rows={2}
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Overall Timeline</label>
                  <textarea
                    className={styles.textareaInput}
                    value={matrixData.actionPlan.timeline}
                    onChange={(e) => handleActionPlanChange('timeline', e.target.value)}
                    placeholder="What is the overall timeline for implementation?"
                    rows={2}
                  />
                </div>
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Action Plan Owner</label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={matrixData.actionPlan.owner}
                  onChange={(e) => handleActionPlanChange('owner', e.target.value)}
                  placeholder="Who owns the overall action plan execution?"
                />
              </div>
            </div>
          </div>

          {/* Documentation & Summary Section */}
          <div className={styles.analysisCard}>
            <h2>Documentation & Summary</h2>
            <div className={styles.documentationGrid}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Assumptions <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={matrixData.documentation.assumptions}
                  onChange={(e) => handleDocumentationChange('assumptions', e.target.value)}
                  placeholder="What assumptions were made during the evaluation?"
                  rows={3}
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Constraints</label>
                <textarea
                  className={styles.textareaInput}
                  value={matrixData.documentation.constraints}
                  onChange={(e) => handleDocumentationChange('constraints', e.target.value)}
                  placeholder="What constraints affect the prioritization and implementation?"
                  rows={3}
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Risks</label>
                <textarea
                  className={styles.textareaInput}
                  value={matrixData.documentation.risks}
                  onChange={(e) => handleDocumentationChange('risks', e.target.value)}
                  placeholder="What risks should be considered for the prioritized items?"
                  rows={3}
                />
              </div>

              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Next Steps</label>
                  <textarea
                    className={styles.textareaInput}
                    value={matrixData.documentation.nextSteps}
                    onChange={(e) => handleDocumentationChange('nextSteps', e.target.value)}
                    placeholder="What are the next steps after this prioritization?"
                    rows={2}
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Approver</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={matrixData.documentation.approver}
                    onChange={(e) => handleDocumentationChange('approver', e.target.value)}
                    placeholder="Who approved this prioritization?"
                  />
                </div>
              </div>
            </div>
          </div>
        </div>
      </div> {/* rcaContainer */}
    </ResourcePageWrapper>
  );
};

export default EffortImpactMatrix;
