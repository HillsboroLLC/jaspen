import React, { useState, useEffect } from 'react';
import { useAdminSettings } from '../context/AdminContext';
import ResourcePageWrapper from '../../All/components/ResourcePageWrapper';
import styles from './SolutionSelection.module.css';

const SolutionSelection = () => {
  const { adminSettings } = useAdminSettings();

  // Solution Selection Matrix data structure
  const [matrixData, setMatrixData] = useState({
    projectName: '',
    analyst: '',
    analysisTeam: '',
    dateCreated: new Date().toISOString().split('T')[0],
    lastUpdated: new Date().toISOString().split('T')[0],
    
    // Matrix setup
    matrixSetup: {
      purpose: '',
      scope: '',
      decisionContext: '',
      stakeholders: '',
      timeframe: '',
      budget: ''
    },
    
    // Evaluation criteria
    criteria: [
      {
        id: 1,
        name: 'Implementation Cost',
        description: 'Total cost to implement the solution',
        weight: 20,
        type: 'cost', // 'benefit', 'cost', 'risk'
        scale: 'low-high' // 'low-high', 'high-low'
      },
      {
        id: 2,
        name: 'Implementation Time',
        description: 'Time required to fully implement',
        weight: 15,
        type: 'cost',
        scale: 'low-high'
      },
      {
        id: 3,
        name: 'Expected Impact',
        description: 'Anticipated improvement in key metrics',
        weight: 25,
        type: 'benefit',
        scale: 'high-low'
      },
      {
        id: 4,
        name: 'Feasibility',
        description: 'Technical and organizational feasibility',
        weight: 20,
        type: 'benefit',
        scale: 'high-low'
      },
      {
        id: 5,
        name: 'Risk Level',
        description: 'Implementation and operational risks',
        weight: 20,
        type: 'risk',
        scale: 'low-high'
      }
    ],
    
    // Solution options
    solutions: [
      {
        id: 1,
        name: 'Solution A',
        description: '',
        category: 'process', // 'process', 'technology', 'people', 'policy'
        scores: { 1: 0, 2: 0, 3: 0, 4: 0, 5: 0 }, // criteria id: score
        notes: '',
        status: 'under-review' // 'under-review', 'approved', 'rejected', 'on-hold'
      }
    ],
    
    // Analysis results
    results: {
      topSolution: null,
      rankings: [],
      sensitivityAnalysis: false,
      consensusReached: false,
      finalDecision: '',
      nextSteps: ''
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
      if (matrixData.projectName) completedFields++;
      if (matrixData.analyst) completedFields++;
      if (matrixData.analysisTeam) completedFields++;

      // Matrix setup
      totalFields += 3;
      if (matrixData.matrixSetup.purpose) completedFields++;
      if (matrixData.matrixSetup.scope) completedFields++;
      if (matrixData.matrixSetup.decisionContext) completedFields++;

      // Criteria (weights sum to 100)
      totalFields += 1;
      const totalWeight = matrixData.criteria.reduce((sum, c) => sum + (Number(c.weight) || 0), 0);
      if (totalWeight === 100) completedFields++;

      // Solutions (at least one fully scored + description)
      totalFields += 1;
      const hasCompleteSolution = matrixData.solutions.some(solution =>
        Object.values(solution.scores).length === matrixData.criteria.length &&
        Object.values(solution.scores).every(score => Number(score) > 0) &&
        solution.description.trim() !== ''
      );
      if (hasCompleteSolution) completedFields++;

      const percentage = totalFields > 0 ? Math.round((completedFields / totalFields) * 100) : 0;
      setCompletionPercentage(percentage);
    };

    calculateCompletion();
  }, [matrixData]);

  // Helper: whether to invert scoring based on type + scale
  const shouldInvert = (criterion) => {
    // Scale meanings:
    // - 'high-low' => 5 = High, 1 = Low
    // - 'low-high' => 5 = Low, 1 = High
    // Benefits: high is good, low is bad
    // Costs/Risks: low is good, high is bad
    if (criterion.type === 'benefit') {
      return criterion.scale === 'low-high';        // 5 = Low benefit (bad) -> invert
    } else if (criterion.type === 'cost' || criterion.type === 'risk') {
      return criterion.scale === 'high-low';        // 5 = High cost/risk (bad) -> invert
    }
    return false;
  };

  // Calculate solution rankings
  useEffect(() => {
    const calculateRankings = () => {
      const rankings = matrixData.solutions
        .map((solution) => {
          let totalScore = 0;
          let weightedScore = 0;

          matrixData.criteria.forEach((criterion) => {
            const raw = Number(solution.scores[criterion.id] || 0);
            const weight = (Number(criterion.weight) || 0) / 100;

            // Adjust score orientation so "higher adjusted" always means "better"
            const adjusted = shouldInvert(criterion) ? (6 - raw) : raw;

            totalScore += raw;
            weightedScore += adjusted * weight;
          });

          return {
            id: solution.id,
            name: solution.name,
            totalScore,
            weightedScore: Math.round(weightedScore * 100) / 100,
            rank: 0
          };
        })
        .sort((a, b) => b.weightedScore - a.weightedScore)
        .map((item, idx) => ({ ...item, rank: idx + 1 }));

      setMatrixData((prev) => ({
        ...prev,
        results: {
          ...prev.results,
          rankings,
          topSolution: rankings.length > 0 ? rankings[0] : null
        }
      }));
    };

    calculateRankings();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [matrixData.solutions, matrixData.criteria]);

  // Handle field changes
  const handleBasicInfoChange = (field, value) => {
    setMatrixData(prev => ({
      ...prev,
      [field]: value,
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleMatrixSetupChange = (field, value) => {
    setMatrixData(prev => ({
      ...prev,
      matrixSetup: {
        ...prev.matrixSetup,
        [field]: value
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleCriterionChange = (criterionId, field, value) => {
    setMatrixData(prev => ({
      ...prev,
      criteria: prev.criteria.map(criterion =>
        criterion.id === criterionId ? { ...criterion, [field]: value } : criterion
      ),
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleSolutionChange = (solutionId, field, value) => {
    setMatrixData(prev => ({
      ...prev,
      solutions: prev.solutions.map(solution =>
        solution.id === solutionId ? { ...solution, [field]: value } : solution
      ),
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleScoreChange = (solutionId, criterionId, score) => {
    setMatrixData(prev => ({
      ...prev,
      solutions: prev.solutions.map(solution =>
        solution.id === solutionId
          ? {
              ...solution,
              scores: { ...solution.scores, [criterionId]: parseInt(score, 10) || 0 }
            }
          : solution
      ),
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleResultsChange = (field, value) => {
    setMatrixData(prev => ({
      ...prev,
      results: {
        ...prev.results,
        [field]: value
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Add / Remove criterion
  const addCriterion = () => {
    const newCriterion = {
      id: Date.now(),
      name: '',
      description: '',
      weight: 0,
      type: 'benefit',
      scale: 'high-low'
    };

    setMatrixData(prev => ({
      ...prev,
      criteria: [...prev.criteria, newCriterion],
      solutions: prev.solutions.map(solution => ({
        ...solution,
        scores: { ...solution.scores, [newCriterion.id]: 0 }
      })),
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const removeCriterion = (criterionId) => {
    if (matrixData.criteria.length > 1) {
      setMatrixData(prev => ({
        ...prev,
        criteria: prev.criteria.filter(c => c.id !== criterionId),
        solutions: prev.solutions.map(solution => {
          const nextScores = { ...solution.scores };
          delete nextScores[criterionId];
          return { ...solution, scores: nextScores };
        }),
        lastUpdated: new Date().toISOString().split('T')[0]
      }));
    }
  };

  // Add / Remove solution
  const addSolution = () => {
    const newSolution = {
      id: Date.now(),
      name: '',
      description: '',
      category: 'process',
      scores: {},
      notes: '',
      status: 'under-review'
    };

    matrixData.criteria.forEach(criterion => {
      newSolution.scores[criterion.id] = 0;
    });

    setMatrixData(prev => ({
      ...prev,
      solutions: [...prev.solutions, newSolution],
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const removeSolution = (solutionId) => {
    if (matrixData.solutions.length > 1) {
      setMatrixData(prev => ({
        ...prev,
        solutions: prev.solutions.filter(s => s.id !== solutionId),
        lastUpdated: new Date().toISOString().split('T')[0]
      }));
    }
  };

  // Normalize weights to 100%
  const normalizeWeights = () => {
    const totalWeight = matrixData.criteria.reduce((sum, c) => sum + (Number(c.weight) || 0), 0);
    if (totalWeight > 0) {
      setMatrixData(prev => ({
        ...prev,
        criteria: prev.criteria.map(c => ({
          ...c,
          weight: Math.round(((Number(c.weight) || 0) / totalWeight) * 100)
        })),
        lastUpdated: new Date().toISOString().split('T')[0]
      }));
    }
  };

  // Generate sample data
  const generateSampleData = () => {
    const sampleData = {
      matrixSetup: {
        purpose: 'Select the best solution to reduce customer delivery delays identified in our analysis phase',
        scope: 'Solutions applicable to our distribution center operations',
        decisionContext: 'Need to implement within Q2 with limited budget and minimal disruption to operations',
        stakeholders: 'Operations team, IT department, logistics coordinator, customer service',
        timeframe: '3 months for implementation',
        budget: '$50,000 maximum budget'
      },
      solutions: [
        {
          id: 1,
          name: 'Automated Inventory System',
          description: 'Implement RFID-based inventory tracking system with real-time updates',
          category: 'technology',
          scores: { 1: 2, 2: 3, 3: 5, 4: 4, 5: 3 },
          notes: 'High impact but requires significant IT infrastructure changes',
          status: 'under-review'
        },
        {
          id: 2,
          name: 'Process Standardization',
          description: 'Standardize picking and packing procedures with visual work instructions',
          category: 'process',
          scores: { 1: 5, 2: 4, 3: 4, 4: 5, 5: 2 },
          notes: 'Lower cost, faster implementation, good team buy-in expected',
          status: 'under-review'
        },
        {
          id: 3,
          name: 'Additional Training Program',
          description: 'Comprehensive training on new inventory system and procedures',
          category: 'people',
          scores: { 1: 4, 2: 5, 3: 3, 4: 4, 5: 2 },
          notes: 'Essential complement to other solutions, builds capability',
          status: 'under-review'
        },
        {
          id: 4,
          name: 'Third-Party Logistics',
          description: 'Outsource distribution to specialized 3PL provider',
          category: 'policy',
          scores: { 1: 1, 2: 2, 3: 5, 4: 3, 5: 4 },
          notes: 'High impact but major organizational change, ongoing costs',
          status: 'under-review'
        }
      ]
    };

    setMatrixData(prev => ({
      ...prev,
      matrixSetup: sampleData.matrixSetup,
      solutions: sampleData.solutions,
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Get total weight
  const getTotalWeight = () =>
    matrixData.criteria.reduce((sum, c) => sum + (Number(c.weight) || 0), 0);

  return (
    <ResourcePageWrapper
      pageName="Solution Selection Matrix"
      toolName="solutionSelection"
      adminSettings={adminSettings}
    >
      <div className={styles.matrixContainer}>
        {/* Header */}
        <div className={styles.header}>
          <div className={styles.headerContent}>
            <h1>Solution Selection Matrix</h1>
            <div className={styles.progressSection}>
              <div className={styles.progressBar}>
                <div
                  className={styles.progressFill}
                  style={{ width: `${completionPercentage}%`,
    background: '#0a2540',
    backgroundImage: 'none' // overrides any gradient from CSS
  }}


                ></div>
              </div>
              <span className={styles.progressText}>{completionPercentage}% Complete</span>
            </div>
          </div>
          <div className={styles.headerActions}>
            <button className={styles.saveBtn}>
              <i className="fas fa-save"></i> Save Matrix
            </button>
            <button className={styles.exportBtn}>
              <i className="fas fa-download"></i> Export Report
            </button>
          </div>
        </div>

        {/* Main Content (single column—no chat) */}
        <div className={styles.mainContent} style={{ display: 'block' }}>
          {/* Top Section: Matrix Information */}
          <div className={styles.topSection} style={{ display: 'block' }}>
            <div className={styles.processInfoCard}>
              <h2>Solution Selection Matrix Information</h2>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Project Name <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={matrixData.projectName}
                  onChange={(e) => handleBasicInfoChange('projectName', e.target.value)}
                  placeholder="Enter the project name for this solution selection"
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
                    value={matrixData.analyst}
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
                    value={matrixData.analysisTeam}
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
                    value={matrixData.dateCreated}
                    onChange={(e) => handleBasicInfoChange('dateCreated', e.target.value)}
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Last Updated</label>
                  <input
                    type="date"
                    className={styles.textInput}
                    value={matrixData.lastUpdated}
                    readOnly
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Matrix Setup Section */}
          <div className={styles.matrixSetupCard}>
            <div className={styles.sectionHeader}>
              <h2>Matrix Setup</h2>
              <button className={styles.generateBtn} onClick={generateSampleData}>
                <i className="fas fa-random"></i> Sample Data
              </button>
            </div>

            <div className={styles.matrixSetupGrid}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Purpose <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={matrixData.matrixSetup.purpose}
                  onChange={(e) => handleMatrixSetupChange('purpose', e.target.value)}
                  placeholder="What decision are you trying to make? What problem are you solving?"
                  rows={3}
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Scope <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={matrixData.matrixSetup.scope}
                  onChange={(e) => handleMatrixSetupChange('scope', e.target.value)}
                  placeholder="What is included/excluded in this analysis? Any constraints?"
                  rows={3}
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Decision Context <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={matrixData.matrixSetup.decisionContext}
                  onChange={(e) => handleMatrixSetupChange('decisionContext', e.target.value)}
                  placeholder="What factors influence this decision? Timeline, budget, strategic priorities?"
                  rows={3}
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Key Stakeholders</label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={matrixData.matrixSetup.stakeholders}
                  onChange={(e) => handleMatrixSetupChange('stakeholders', e.target.value)}
                  placeholder="Who are the key stakeholders and decision makers?"
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Implementation Timeframe</label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={matrixData.matrixSetup.timeframe}
                  onChange={(e) => handleMatrixSetupChange('timeframe', e.target.value)}
                  placeholder="When does the solution need to be implemented?"
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Budget Constraints</label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={matrixData.matrixSetup.budget}
                  onChange={(e) => handleMatrixSetupChange('budget', e.target.value)}
                  placeholder="What budget constraints exist?"
                />
              </div>
            </div>
          </div>

          {/* Evaluation Criteria Section */}
          <div className={styles.criteriaCard}>
            <div className={styles.sectionHeader}>
              <h2>Evaluation Criteria</h2>
              <div className={styles.criteriaActions}>
                <div className={styles.weightStatus}>
                  <span
                    className={`${styles.weightIndicator} ${
                      getTotalWeight() === 100 ? styles.valid : styles.invalid
                    }`}
                  >
                    Total Weight: {getTotalWeight()}%
                  </span>
                  {getTotalWeight() !== 100 && (
                    <button className={styles.normalizeBtn} onClick={normalizeWeights}>
                      <i className="fas fa-balance-scale"></i> Normalize
                    </button>
                  )}
                </div>
                <button className={styles.addBtn} onClick={addCriterion}>
                  <i className="fas fa-plus"></i> Add Criterion
                </button>
              </div>
            </div>

            <div className={styles.criteriaGrid}>
              {matrixData.criteria.map((criterion, index) => (
                <div key={criterion.id} className={styles.criterionCard}>
                  <div className={styles.criterionHeader}>
                    <h3>Criterion {index + 1}</h3>
                    {matrixData.criteria.length > 1 && (
                      <button
                        className={styles.removeBtn}
                        onClick={() => removeCriterion(criterion.id)}
                      >
                        <i className="fas fa-times"></i>
                      </button>
                    )}
                  </div>

                  <div className={styles.criterionFields}>
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>
                        Criterion Name <span className={styles.required}>*</span>
                      </label>
                      <input
                        type="text"
                        className={styles.textInput}
                        value={criterion.name}
                        onChange={(e) => handleCriterionChange(criterion.id, 'name', e.target.value)}
                        placeholder="e.g., Implementation Cost, Expected Impact"
                      />
                    </div>

                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Description</label>
                      <textarea
                        className={styles.textareaInput}
                        value={criterion.description}
                        onChange={(e) => handleCriterionChange(criterion.id, 'description', e.target.value)}
                        placeholder="Describe what this criterion measures"
                        rows={2}
                      />
                    </div>

                    <div className={styles.criterionDetailsGrid}>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>
                          Weight (%) <span className={styles.required}>*</span>
                        </label>
                        <input
                          type="number"
                          className={styles.textInput}
                          value={criterion.weight}
                          onChange={(e) =>
                            handleCriterionChange(criterion.id, 'weight', parseInt(e.target.value, 10) || 0)
                          }
                          min="0"
                          max="100"
                          placeholder="0-100"
                        />
                      </div>

                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Type</label>
                        <select
                          className={styles.selectInput}
                          value={criterion.type}
                          onChange={(e) => handleCriterionChange(criterion.id, 'type', e.target.value)}
                        >
                          <option value="benefit">Benefit (more is better)</option>
                          <option value="cost">Cost (less is better)</option>
                          <option value="risk">Risk (less is better)</option>
                        </select>
                      </div>

                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Scale Direction</label>
                        <select
                          className={styles.selectInput}
                          value={criterion.scale}
                          onChange={(e) => handleCriterionChange(criterion.id, 'scale', e.target.value)}
                        >
                          <option value="high-low">5=High, 1=Low</option>
                          <option value="low-high">5=Low, 1=High</option>
                        </select>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Solution Options Section */}
          <div className={styles.solutionsCard}>
            <div className={styles.sectionHeader}>
              <h2>Solution Options</h2>
              <button className={styles.addBtn} onClick={addSolution}>
                <i className="fas fa-plus"></i> Add Solution
              </button>
            </div>

            <div className={styles.solutionsGrid}>
              {matrixData.solutions.map((solution, index) => (
                <div key={solution.id} className={styles.solutionCard}>
                  <div className={styles.solutionHeader}>
                    <h3>Solution {index + 1}</h3>
                    {matrixData.solutions.length > 1 && (
                      <button
                        className={styles.removeBtn}
                        onClick={() => removeSolution(solution.id)}
                      >
                        <i className="fas fa-times"></i>
                      </button>
                    )}
                  </div>

                  <div className={styles.solutionFields}>
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>
                        Solution Name <span className={styles.required}>*</span>
                      </label>
                      <input
                        type="text"
                        className={styles.textInput}
                        value={solution.name}
                        onChange={(e) => handleSolutionChange(solution.id, 'name', e.target.value)}
                        placeholder="Enter solution name"
                      />
                    </div>

                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>
                        Description <span className={styles.required}>*</span>
                      </label>
                      <textarea
                        className={styles.textareaInput}
                        value={solution.description}
                        onChange={(e) => handleSolutionChange(solution.id, 'description', e.target.value)}
                        placeholder="Describe the solution in detail"
                        rows={3}
                      />
                    </div>

                    <div className={styles.solutionDetailsGrid}>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Category</label>
                        <select
                          className={styles.selectInput}
                          value={solution.category}
                          onChange={(e) => handleSolutionChange(solution.id, 'category', e.target.value)}
                        >
                          <option value="process">Process Improvement</option>
                          <option value="technology">Technology Solution</option>
                          <option value="people">People/Training</option>
                          <option value="policy">Policy/Organizational</option>
                        </select>
                      </div>

                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Status</label>
                        <select
                          className={styles.selectInput}
                          value={solution.status}
                          onChange={(e) => handleSolutionChange(solution.id, 'status', e.target.value)}
                        >
                          <option value="under-review">Under Review</option>
                          <option value="approved">Approved</option>
                          <option value="rejected">Rejected</option>
                          <option value="on-hold">On Hold</option>
                        </select>
                      </div>
                    </div>

                    {/* Scoring Grid */}
                    <div className={styles.scoringSection}>
                      <h4>Criterion Scores (1-5 scale)</h4>
                      <div className={styles.scoresGrid}>
                        {matrixData.criteria.map((criterion) => (
                          <div key={criterion.id} className={styles.scoreItem}>
                            <label className={styles.scoreLabel}>
                              {criterion.name}
                              <span className={styles.scoreWeight}>({criterion.weight}%)</span>
                            </label>
                            <select
                              className={styles.scoreSelect}
                              value={solution.scores[criterion.id] || 0}
                              onChange={(e) => handleScoreChange(solution.id, criterion.id, e.target.value)}
                            >
                              <option value={0}>Not Scored</option>
                              <option value={1}>1 - Poor</option>
                              <option value={2}>2 - Below Average</option>
                              <option value={3}>3 - Average</option>
                              <option value={4}>4 - Good</option>
                              <option value={5}>5 - Excellent</option>
                            </select>
                          </div>
                        ))}
                      </div>
                    </div>

                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Notes</label>
                      <textarea
                        className={styles.textareaInput}
                        value={solution.notes}
                        onChange={(e) => handleSolutionChange(solution.id, 'notes', e.target.value)}
                        placeholder="Additional notes, assumptions, or considerations"
                        rows={2}
                      />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Results Section */}
          <div className={styles.resultsCard}>
            <div className={styles.sectionHeader}>
              <h2>Analysis Results</h2>
            </div>

            {matrixData.results.rankings.length > 0 ? (
              <div className={styles.resultsContent}>
                {/* Rankings Table */}
                <div className={styles.rankingsSection}>
                  <h3>Solution Rankings</h3>
                  <div className={styles.rankingsTable}>
                    <div className={styles.tableHeader}>
                      <div className={styles.rankCol}>Rank</div>
                      <div className={styles.solutionCol}>Solution</div>
                      <div className={styles.scoreCol}>Raw Score</div>
                      <div className={styles.weightedCol}>Weighted Score</div>
                      <div className={styles.statusCol}>Status</div>
                    </div>
                    {matrixData.results.rankings.map((ranking) => {
                      const solution = matrixData.solutions.find((s) => s.id === ranking.id);
                      return (
                        <div
                          key={ranking.id}
                          className={`${styles.tableRow} ${ranking.rank === 1 ? styles.topSolution : ''}`}
                        >
                          <div className={styles.rankCol}>
                            <span className={styles.rankBadge}>#{ranking.rank}</span>
                          </div>
                          <div className={styles.solutionCol}>
                            <div className={styles.solutionName}>{ranking.name}</div>
                            <div className={styles.solutionCategory}>{solution?.category}</div>
                          </div>
                          <div className={styles.scoreCol}>{ranking.totalScore}</div>
                          <div className={styles.weightedCol}>
                            <span className={styles.weightedScore}>{ranking.weightedScore}</span>
                          </div>
                          <div className={styles.statusCol}>
                            <span className={`${styles.statusBadge} ${styles[solution?.status]}`}>
                              {solution?.status?.replace('-', ' ')}
                            </span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>

                {/* Decision Section */}
                <div className={styles.decisionSection}>
                  <div className={styles.decisionGrid}>
                    <div className={styles.fieldGroup}>
                      <label className={styles.checkboxLabel}>
                        <input
                          type="checkbox"
                          checked={matrixData.results.sensitivityAnalysis}
                          onChange={(e) => handleResultsChange('sensitivityAnalysis', e.target.checked)}
                        />
                        Sensitivity Analysis Performed
                      </label>
                    </div>

                    <div className={styles.fieldGroup}>
                      <label className={styles.checkboxLabel}>
                        <input
                          type="checkbox"
                          checked={matrixData.results.consensusReached}
                          onChange={(e) => handleResultsChange('consensusReached', e.target.checked)}
                        />
                        Team Consensus Reached
                      </label>
                    </div>

                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Final Decision</label>
                      <textarea
                        className={styles.textareaInput}
                        value={matrixData.results.finalDecision}
                        onChange={(e) => handleResultsChange('finalDecision', e.target.value)}
                        placeholder="Document the final decision and rationale"
                        rows={3}
                      />
                    </div>

                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Next Steps</label>
                      <textarea
                        className={styles.textareaInput}
                        value={matrixData.results.nextSteps}
                        onChange={(e) => handleResultsChange('nextSteps', e.target.value)}
                        placeholder="What are the next steps for implementation?"
                        rows={3}
                      />
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <div className={styles.emptyResults}>
                <i className="fas fa-chart-bar"></i>
                <p>Complete solution scoring to see analysis results</p>
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className={styles.footer}>
          <div className={styles.footerContent}>
            <div className={styles.completionStatus}>
              <i className="fas fa-check-circle"></i>
              <span>Solution Selection Matrix {completionPercentage}% Complete</span>
            </div>
            <div className={styles.footerActions}>
              <button className={styles.secondaryBtn}>
                <i className="fas fa-eye"></i> Preview Report
              </button>
              <button className={styles.primaryBtn} disabled={completionPercentage < 70}>
                <i className="fas fa-check"></i> Finalize Selection
              </button>
            </div>
          </div>
        </div>
      </div>
    </ResourcePageWrapper>
  );
};

export default SolutionSelection;
