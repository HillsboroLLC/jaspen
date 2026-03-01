// ============================================================================
// File: src/Ops/DOE/DOE.jsx
// Purpose: DOE tool with floating chat via ResourcePageWrapper, solid progress
//          bar, and no extra bottom spacing. Keeps existing DOE features/styles.
// ============================================================================

import React, { useState, useEffect, useCallback } from 'react';
import styles from './DOE.module.css';
import { useAdminSettings } from '../context/AdminContext';
import ResourcePageWrapper from '../../All/components/ResourcePageWrapper';
import '@fortawesome/fontawesome-free/css/all.min.css';

const DOE = () => {
  const { adminSettings } = useAdminSettings();

  // Design of Experiments data structure
  const [doeData, setDoeData] = useState({
    projectName: '',
    experimenter: '',
    experimentTeam: '',
    dateCreated: new Date().toISOString().split('T')[0],
    lastUpdated: new Date().toISOString().split('T')[0],

    // Experiment overview
    experimentOverview: {
      objective: '',
      hypothesis: '',
      scope: '',
      constraints: '',
      resources: '',
      timeline: '',
      successCriteria: '',
    },

    // Experimental design
    experimentalDesign: {
      designType: 'full-factorial', // 'full-factorial', 'fractional-factorial', 'response-surface', 'taguchi', 'custom'
      designResolution: 'III', // 'III', 'IV', 'V', 'VI'
      blocks: 1,
      replicates: 1,
      randomization: true,
      centerPoints: 0,
      totalRuns: 0,
    },

    // Factors (independent variables)
    factors: [
      {
        id: 1,
        name: 'Factor A',
        description: '',
        type: 'continuous', // 'continuous', 'discrete', 'categorical'
        unit: '',
        lowLevel: '',
        highLevel: '',
        centerPoint: '',
        levels: ['Low', 'High'], // For categorical factors
        controllable: true,
        noiseLevel: 'low', // 'low', 'medium', 'high'
      },
    ],

    // Responses (dependent variables)
    responses: [
      {
        id: 1,
        name: 'Response 1',
        description: '',
        type: 'continuous', // 'continuous', 'discrete', 'attribute'
        unit: '',
        target: '',
        lowerSpec: '',
        upperSpec: '',
        objective: 'maximize', // 'maximize', 'minimize', 'target', 'none'
        weight: 1,
        measurementMethod: '',
      },
    ],

    // Experimental runs
    experimentalRuns: [],

    // Data collection
    dataCollection: {
      measurementPlan: '',
      dataCollectionSheet: '',
      qualityChecks: '',
      calibration: '',
      environmentalControls: '',
    },

    // Analysis settings
    analysisSettings: {
      significanceLevel: 0.05,
      confidenceLevel: 95,
      analysisType: 'anova', // 'anova', 'regression', 'response-surface'
      transformations: [],
      outlierHandling: 'investigate', // 'investigate', 'remove', 'transform'
    },

    // Results and analysis
    results: {
      experimentStatus: 'planning', // 'planning', 'running', 'completed', 'cancelled'
      dataCollected: false,
      analysisCompleted: false,
      significantFactors: [],
      interactions: [],
      modelEquation: '',
      rSquared: 0,
      recommendations: '',
      nextSteps: '',
      optimumSettings: {},
    },
  });

  const [completionPercentage, setCompletionPercentage] = useState(0);

  // Allow the wrapper's floating chat to update fields dynamically
  const handleKiiDataUpdate = useCallback((extracted = {}) => {
    setDoeData((prev) => {
      const next = { ...prev };

      // Basic fields
      if (extracted.projectName) next.projectName = extracted.projectName;
      if (extracted.experimenter) next.experimenter = extracted.experimenter;
      if (extracted.experimentTeam) next.experimentTeam = extracted.experimentTeam;

      // Overview
      if (extracted.experimentOverview) {
        next.experimentOverview = { ...next.experimentOverview, ...extracted.experimentOverview };
      } else {
        // flat keys fallback
        ['objective', 'hypothesis', 'scope', 'constraints', 'resources', 'timeline', 'successCriteria']
          .forEach((k) => {
            if (extracted[k]) next.experimentOverview[k] = extracted[k];
          });
      }

      // Experimental design
      if (extracted.experimentalDesign) {
        next.experimentalDesign = { ...next.experimentalDesign, ...extracted.experimentalDesign };
      }

      // Factors
      if (Array.isArray(extracted.factors)) {
        next.factors = extracted.factors.map((f, idx) => ({
          id: f.id || Date.now() + idx,
          name: f.name ?? '',
          description: f.description ?? '',
          type: f.type ?? 'continuous',
          unit: f.unit ?? '',
          lowLevel: f.lowLevel ?? '',
          highLevel: f.highLevel ?? '',
          centerPoint: f.centerPoint ?? '',
          levels: Array.isArray(f.levels) ? f.levels : ['Low', 'High'],
          controllable: typeof f.controllable === 'boolean' ? f.controllable : true,
          noiseLevel: f.noiseLevel ?? 'low',
        }));
      }

      // Responses
      if (Array.isArray(extracted.responses)) {
        next.responses = extracted.responses.map((r, idx) => ({
          id: r.id || Date.now() + idx,
          name: r.name ?? '',
          description: r.description ?? '',
          type: r.type ?? 'continuous',
          unit: r.unit ?? '',
          target: r.target ?? '',
          lowerSpec: r.lowerSpec ?? '',
          upperSpec: r.upperSpec ?? '',
          objective: r.objective ?? 'maximize',
          weight: Number.isFinite(r.weight) ? r.weight : 1,
          measurementMethod: r.measurementMethod ?? '',
        }));
      }

      // Data collection
      if (extracted.dataCollection) {
        next.dataCollection = { ...next.dataCollection, ...extracted.dataCollection };
      }

      // Analysis settings
      if (extracted.analysisSettings) {
        next.analysisSettings = { ...next.analysisSettings, ...extracted.analysisSettings };
      }

      // Results
      if (extracted.results) {
        next.results = { ...next.results, ...extracted.results };
      }

      next.lastUpdated = new Date().toISOString().split('T')[0];
      return next;
    });
  }, []);

  // Calculate completion percentage
  useEffect(() => {
    const calculateCompletion = () => {
      let total = 0;
      let done = 0;

      // Basic info
      total += 3;
      if (doeData.projectName) done++;
      if (doeData.experimenter) done++;
      if (doeData.experimentTeam) done++;

      // Overview
      total += 3;
      if (doeData.experimentOverview.objective) done++;
      if (doeData.experimentOverview.hypothesis) done++;
      if (doeData.experimentOverview.successCriteria) done++;

      // Design
      total += 2;
      if (doeData.experimentalDesign.designType) done++;
      if (doeData.experimentalDesign.totalRuns > 0) done++;

      // Factors
      total += 1;
      const factorOK = doeData.factors.some(
        (f) => f.name && f.description && f.lowLevel && f.highLevel
      );
      if (factorOK) done++;

      // Responses
      total += 1;
      const respOK = doeData.responses.some((r) => r.name && r.description && r.objective);
      if (respOK) done++;

      // Data collection
      total += 2;
      if (doeData.dataCollection.measurementPlan) done++;
      if (doeData.dataCollection.dataCollectionSheet) done++;

      setCompletionPercentage(total > 0 ? Math.round((done / total) * 100) : 0);
    };

    calculateCompletion();
  }, [doeData]);

  // Calculate total runs based on design
  useEffect(() => {
    const calculateTotalRuns = () => {
      const { designType, blocks, replicates, centerPoints } = doeData.experimentalDesign;
      const numFactors = doeData.factors.length;
      let baseRuns = 0;

      switch (designType) {
        case 'full-factorial':
          baseRuns = Math.pow(2, numFactors);
          break;
        case 'fractional-factorial':
          baseRuns = Math.pow(2, Math.max(3, numFactors - 1)); // simple approximation
          break;
        case 'response-surface':
          baseRuns = Math.pow(2, numFactors) + 2 * numFactors + 1; // CCD approx
          break;
        case 'taguchi':
          baseRuns = numFactors <= 3 ? 4 : numFactors <= 7 ? 8 : 16; // simplified
          break;
        default:
          baseRuns = Math.pow(2, numFactors);
      }

      const totalRuns = (baseRuns + centerPoints) * replicates * blocks;

      setDoeData((prev) => ({
        ...prev,
        experimentalDesign: { ...prev.experimentalDesign, totalRuns },
      }));
    };

    calculateTotalRuns();
  }, [
    doeData.experimentalDesign.designType,
    doeData.experimentalDesign.blocks,
    doeData.experimentalDesign.replicates,
    doeData.experimentalDesign.centerPoints,
    doeData.factors.length,
  ]);

  // Handlers
  const handleBasicInfoChange = (field, value) => {
    setDoeData((prev) => ({
      ...prev,
      [field]: value,
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  const handleOverviewChange = (field, value) => {
    setDoeData((prev) => ({
      ...prev,
      experimentOverview: { ...prev.experimentOverview, [field]: value },
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  const handleDesignChange = (field, value) => {
    setDoeData((prev) => ({
      ...prev,
      experimentalDesign: { ...prev.experimentalDesign, [field]: value },
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  const handleFactorChange = (id, field, value) => {
    setDoeData((prev) => ({
      ...prev,
      factors: prev.factors.map((f) => (f.id === id ? { ...f, [field]: value } : f)),
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  const handleResponseChange = (id, field, value) => {
    setDoeData((prev) => ({
      ...prev,
      responses: prev.responses.map((r) => (r.id === id ? { ...r, [field]: value } : r)),
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  const handleDataCollectionChange = (field, value) => {
    setDoeData((prev) => ({
      ...prev,
      dataCollection: { ...prev.dataCollection, [field]: value },
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  const handleAnalysisChange = (field, value) => {
    setDoeData((prev) => ({
      ...prev,
      analysisSettings: { ...prev.analysisSettings, [field]: value },
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  const handleResultsChange = (field, value) => {
    setDoeData((prev) => ({
      ...prev,
      results: { ...prev.results, [field]: value },
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  // Factors
  const addFactor = () => {
    const newFactor = {
      id: Date.now(),
      name: `Factor ${String.fromCharCode(65 + doeData.factors.length)}`,
      description: '',
      type: 'continuous',
      unit: '',
      lowLevel: '',
      highLevel: '',
      centerPoint: '',
      levels: ['Low', 'High'],
      controllable: true,
      noiseLevel: 'low',
    };
    setDoeData((prev) => ({
      ...prev,
      factors: [...prev.factors, newFactor],
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  const removeFactor = (factorId) => {
    if (doeData.factors.length > 1) {
      setDoeData((prev) => ({
        ...prev,
        factors: prev.factors.filter((f) => f.id !== factorId),
        lastUpdated: new Date().toISOString().split('T')[0],
      }));
    }
  };

  // Responses
  const addResponse = () => {
    const newResponse = {
      id: Date.now(),
      name: `Response ${doeData.responses.length + 1}`,
      description: '',
      type: 'continuous',
      unit: '',
      target: '',
      lowerSpec: '',
      upperSpec: '',
      objective: 'maximize',
      weight: 1,
      measurementMethod: '',
    };
    setDoeData((prev) => ({
      ...prev,
      responses: [...prev.responses, newResponse],
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  const removeResponse = (responseId) => {
    if (doeData.responses.length > 1) {
      setDoeData((prev) => ({
        ...prev,
        responses: prev.responses.filter((r) => r.id !== responseId),
        lastUpdated: new Date().toISOString().split('T')[0],
      }));
    }
  };

  // Runs
  const generateRuns = () => {
    const { factors } = doeData;
    const { designType, centerPoints, randomization } = doeData.experimentalDesign;

    let runs = [];

    if (designType === 'full-factorial') {
      const numFactors = factors.length;
      const numRuns = Math.pow(2, numFactors);

      for (let i = 0; i < numRuns; i++) {
        const run = {
          id: i + 1,
          runOrder: i + 1,
          block: 1,
          replicate: 1,
          factors: {},
          responses: {},
        };

        factors.forEach((factor, index) => {
          const level = (i >> index) & 1; // binary
          run.factors[factor.id] = level === 0 ? factor.lowLevel : factor.highLevel;
        });

        doeData.responses.forEach((response) => {
          run.responses[response.id] = '';
        });

        runs.push(run);
      }
    }

    // Add center points
    for (let i = 0; i < centerPoints; i++) {
      const centerRun = {
        id: runs.length + i + 1,
        runOrder: runs.length + i + 1,
        block: 1,
        replicate: 1,
        factors: {},
        responses: {},
      };

      factors.forEach((factor) => {
        if (factor.type === 'continuous') {
          const low = parseFloat(factor.lowLevel) || 0;
          const high = parseFloat(factor.highLevel) || 1;
          centerRun.factors[factor.id] = ((low + high) / 2).toString();
        } else {
          centerRun.factors[factor.id] = factor.centerPoint || factor.lowLevel;
        }
      });

      doeData.responses.forEach((response) => {
        centerRun.responses[response.id] = '';
      });

      runs.push(centerRun);
    }

    // Randomize
    if (randomization) {
      runs = runs.sort(() => Math.random() - 0.5).map((r, idx) => ({ ...r, runOrder: idx + 1 }));
    }

    setDoeData((prev) => ({
      ...prev,
      experimentalRuns: runs,
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  // Sample data
  const generateSampleData = () => {
    const sampleData = {
      experimentOverview: {
        objective:
          'Optimize injection molding process to minimize cycle time while maintaining part quality',
        hypothesis:
          'Temperature, pressure, and cooling time significantly affect cycle time and defect rate',
        scope: 'Injection molding machine #3, plastic part XYZ-123, 3-factor experiment',
        constraints: 'Temperature: 180-220°C, Pressure: 80-120 bar, Cooling: 10-30 seconds',
        resources: '40 hours machine time, 200 parts, quality inspector availability',
        timeline: '2 weeks: 1 week setup and runs, 1 week analysis',
        successCriteria: 'Reduce cycle time by 15% while maintaining <2% defect rate',
      },
      factors: [
        {
          id: 1,
          name: 'Temperature',
          description: 'Injection temperature of molten plastic',
          type: 'continuous',
          unit: '°C',
          lowLevel: '180',
          highLevel: '220',
          centerPoint: '200',
          levels: ['Low', 'High'],
          controllable: true,
          noiseLevel: 'low',
        },
        {
          id: 2,
          name: 'Pressure',
          description: 'Injection pressure during filling',
          type: 'continuous',
          unit: 'bar',
          lowLevel: '80',
          highLevel: '120',
          centerPoint: '100',
          levels: ['Low', 'High'],
          controllable: true,
          noiseLevel: 'medium',
        },
        {
          id: 3,
          name: 'Cooling Time',
          description: 'Time for part cooling before ejection',
          type: 'continuous',
          unit: 'seconds',
          lowLevel: '10',
          highLevel: '30',
          centerPoint: '20',
          levels: ['Low', 'High'],
          controllable: true,
          noiseLevel: 'low',
        },
      ],
      responses: [
        {
          id: 1,
          name: 'Cycle Time',
          description: 'Total time from injection start to part ejection',
          type: 'continuous',
          unit: 'seconds',
          target: '45',
          lowerSpec: '',
          upperSpec: '60',
          objective: 'minimize',
          weight: 2,
          measurementMethod: 'Automatic timer on molding machine',
        },
        {
          id: 2,
          name: 'Defect Rate',
          description: 'Percentage of parts with visual defects',
          type: 'continuous',
          unit: '%',
          target: '1',
          lowerSpec: '',
          upperSpec: '2',
          objective: 'minimize',
          weight: 3,
          measurementMethod: 'Visual inspection by quality inspector',
        },
      ],
      dataCollection: {
        measurementPlan:
          'Measure cycle time automatically, inspect 10 parts per run for defects',
        dataCollectionSheet:
          'Standard DOE data sheet with run order, factor settings, and response measurements',
        qualityChecks: 'Calibrate timer daily, train inspector on defect criteria',
        calibration: 'Temperature probe ±1°C, pressure gauge ±2 bar, timer ±0.1 sec',
        environmentalControls: 'Maintain ambient temperature 20±2°C, humidity <60%',
      },
    };

    setDoeData((prev) => ({
      ...prev,
      experimentOverview: sampleData.experimentOverview,
      factors: sampleData.factors,
      responses: sampleData.responses,
      dataCollection: sampleData.dataCollection,
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  const handleSave = () => console.log('Saving DOE design:', doeData);
  const handleExport = () => console.log('Exporting DOE:', doeData);

  return (
    <ResourcePageWrapper
      pageName="Design of Experiments"
      toolName="Design of Experiments"
      adminSettings={adminSettings}
      currentData={doeData}
      onDataUpdate={handleKiiDataUpdate}
    >
      <div className={styles.doeContainer} style={{ paddingBottom: 0 }}>
        {/* Header */}
        <div className={styles.header}>
          <div className={styles.headerContent}>
            <h1>Design of Experiments (DOE)</h1>
            <div className={styles.progressSection}>
              {/* Solid bar, no gradients */}
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
              <i className="fas fa-save"></i>
              Save Design
            </button>
            <button className={styles.exportBtn} onClick={handleExport}>
              <i className="fas fa-download"></i>
              Export
            </button>
          </div>
        </div>

        {/* Main Content */}
        <div className={styles.mainContent}>
          {/* Top Section - Full-width Experiment Info (floating chat handled by wrapper) */}
          <div className={styles.topSection} style={{ display: 'block', marginBottom: 0 }}>
            <div className={styles.processInfoCard} style={{ width: '100%' }}>
              <h2>Experiment Information</h2>

              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>
                    Project Name <span className={styles.required}>*</span>
                  </label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={doeData.projectName}
                    onChange={(e) => handleBasicInfoChange('projectName', e.target.value)}
                    placeholder="Enter project name"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>
                    Experimenter <span className={styles.required}>*</span>
                  </label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={doeData.experimenter}
                    onChange={(e) => handleBasicInfoChange('experimenter', e.target.value)}
                    placeholder="Enter experimenter name"
                  />
                </div>
              </div>

              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Experiment Team</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={doeData.experimentTeam}
                    onChange={(e) => handleBasicInfoChange('experimentTeam', e.target.value)}
                    placeholder="Enter team members"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Date Created</label>
                  <input
                    type="date"
                    className={styles.textInput}
                    value={doeData.dateCreated}
                    onChange={(e) => handleBasicInfoChange('dateCreated', e.target.value)}
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Experiment Overview Card */}
          <div className={styles.overviewCard}>
            <div className={styles.sectionHeader}>
              <h2>Experiment Overview</h2>
              <button className={styles.generateBtn} onClick={generateSampleData}>
                <i className="fas fa-magic"></i>
                Generate Sample Data
              </button>
            </div>

            <div className={styles.overviewGrid}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Objective <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={doeData.experimentOverview.objective}
                  onChange={(e) => handleOverviewChange('objective', e.target.value)}
                  placeholder="What is the main objective of this experiment?"
                  rows="3"
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Hypothesis <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={doeData.experimentOverview.hypothesis}
                  onChange={(e) => handleOverviewChange('hypothesis', e.target.value)}
                  placeholder="What do you expect to find?"
                  rows="3"
                />
              </div>

              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Scope</label>
                  <textarea
                    className={styles.textareaInput}
                    value={doeData.experimentOverview.scope}
                    onChange={(e) => handleOverviewChange('scope', e.target.value)}
                    placeholder="Define the experimental scope"
                    rows="2"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Constraints</label>
                  <textarea
                    className={styles.textareaInput}
                    value={doeData.experimentOverview.constraints}
                    onChange={(e) => handleOverviewChange('constraints', e.target.value)}
                    placeholder="What are the experimental constraints?"
                    rows="2"
                  />
                </div>
              </div>

              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Resources</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={doeData.experimentOverview.resources}
                    onChange={(e) => handleOverviewChange('resources', e.target.value)}
                    placeholder="Required resources"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Timeline</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={doeData.experimentOverview.timeline}
                    onChange={(e) => handleOverviewChange('timeline', e.target.value)}
                    placeholder="Experimental timeline"
                  />
                </div>
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Success Criteria</label>
                <textarea
                  className={styles.textareaInput}
                  value={doeData.experimentOverview.successCriteria}
                  onChange={(e) => handleOverviewChange('successCriteria', e.target.value)}
                  placeholder="How will you measure success?"
                  rows="2"
                />
              </div>
            </div>
          </div>

          {/* Experimental Design Card */}
          <div className={styles.designCard}>
            <div className={styles.sectionHeader}>
              <h2>Experimental Design</h2>
              <div className={styles.designSummary}>
                <span className={styles.runCount}>
                  {doeData.experimentalDesign.totalRuns} Total Runs
                </span>
              </div>
            </div>

            <div className={styles.designGrid}>
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Design Type</label>
                  <select
                    className={styles.selectInput}
                    value={doeData.experimentalDesign.designType}
                    onChange={(e) => handleDesignChange('designType', e.target.value)}
                  >
                    <option value="full-factorial">Full Factorial</option>
                    <option value="fractional-factorial">Fractional Factorial</option>
                    <option value="response-surface">Response Surface (CCD)</option>
                    <option value="taguchi">Taguchi (Orthogonal Arrays)</option>
                    <option value="custom">Custom Design</option>
                  </select>
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Resolution (Fractional Only)</label>
                  <select
                    className={styles.selectInput}
                    value={doeData.experimentalDesign.designResolution}
                    onChange={(e) => handleDesignChange('designResolution', e.target.value)}
                    disabled={doeData.experimentalDesign.designType !== 'fractional-factorial'}
                  >
                    <option value="III">Resolution III</option>
                    <option value="IV">Resolution IV</option>
                    <option value="V">Resolution V</option>
                    <option value="VI">Resolution VI</option>
                  </select>
                </div>
              </div>

              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Blocks</label>
                  <input
                    type="number"
                    className={styles.textInput}
                    value={doeData.experimentalDesign.blocks}
                    onChange={(e) =>
                      handleDesignChange('blocks', parseInt(e.target.value) || 1)
                    }
                    min="1"
                    max="8"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Replicates</label>
                  <input
                    type="number"
                    className={styles.textInput}
                    value={doeData.experimentalDesign.replicates}
                    onChange={(e) =>
                      handleDesignChange('replicates', parseInt(e.target.value) || 1)
                    }
                    min="1"
                    max="10"
                  />
                </div>
              </div>

              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Center Points</label>
                  <input
                    type="number"
                    className={styles.textInput}
                    value={doeData.experimentalDesign.centerPoints}
                    onChange={(e) =>
                      handleDesignChange('centerPoints', parseInt(e.target.value) || 0)
                    }
                    min="0"
                    max="20"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.checkboxLabel}>
                    <input
                      type="checkbox"
                      checked={doeData.experimentalDesign.randomization}
                      onChange={(e) => handleDesignChange('randomization', e.target.checked)}
                    />
                    Randomize Run Order
                  </label>
                </div>
              </div>
            </div>
          </div>

          {/* Factors Card */}
          <div className={styles.factorsCard}>
            <div className={styles.sectionHeader}>
              <h2>Factors (Independent Variables)</h2>
              <button className={styles.addBtn} onClick={addFactor}>
                <i className="fas fa-plus"></i>
                Add Factor
              </button>
            </div>

            <div className={styles.factorsGrid}>
              {doeData.factors.map((factor) => (
                <div key={factor.id} className={styles.factorCard}>
                  <div className={styles.factorHeader}>
                    <h3>{factor.name}</h3>
                    {doeData.factors.length > 1 && (
                      <button className={styles.removeBtn} onClick={() => removeFactor(factor.id)}>
                        <i className="fas fa-times"></i>
                      </button>
                    )}
                  </div>

                  <div className={styles.factorFields}>
                    <div className={styles.fieldRow}>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Factor Name</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={factor.name}
                          onChange={(e) => handleFactorChange(factor.id, 'name', e.target.value)}
                          placeholder="e.g., Temperature"
                        />
                      </div>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Type</label>
                        <select
                          className={styles.selectInput}
                          value={factor.type}
                          onChange={(e) => handleFactorChange(factor.id, 'type', e.target.value)}
                        >
                          <option value="continuous">Continuous</option>
                          <option value="discrete">Discrete</option>
                          <option value="categorical">Categorical</option>
                        </select>
                      </div>
                    </div>

                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Description</label>
                      <textarea
                        className={styles.textareaInput}
                        value={factor.description}
                        onChange={(e) =>
                          handleFactorChange(factor.id, 'description', e.target.value)
                        }
                        placeholder="Describe this factor"
                        rows="2"
                      />
                    </div>

                    <div className={styles.fieldRow}>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Unit</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={factor.unit}
                          onChange={(e) => handleFactorChange(factor.id, 'unit', e.target.value)}
                          placeholder="e.g., °C, bar, mm"
                        />
                      </div>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Noise Level</label>
                        <select
                          className={styles.selectInput}
                          value={factor.noiseLevel}
                          onChange={(e) =>
                            handleFactorChange(factor.id, 'noiseLevel', e.target.value)
                          }
                        >
                          <option value="low">Low</option>
                          <option value="medium">Medium</option>
                          <option value="high">High</option>
                        </select>
                      </div>
                    </div>

                    {factor.type === 'continuous' ? (
                      <div className={styles.fieldRow}>
                        <div className={styles.fieldGroup}>
                          <label className={styles.fieldLabel}>Low Level (-1)</label>
                          <input
                            type="text"
                            className={styles.textInput}
                            value={factor.lowLevel}
                            onChange={(e) =>
                              handleFactorChange(factor.id, 'lowLevel', e.target.value)
                            }
                            placeholder="Minimum value"
                          />
                        </div>
                        <div className={styles.fieldGroup}>
                          <label className={styles.fieldLabel}>High Level (+1)</label>
                          <input
                            type="text"
                            className={styles.textInput}
                            value={factor.highLevel}
                            onChange={(e) =>
                              handleFactorChange(factor.id, 'highLevel', e.target.value)
                            }
                            placeholder="Maximum value"
                          />
                        </div>
                      </div>
                    ) : (
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Levels (comma-separated)</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={factor.levels.join(', ')}
                          onChange={(e) =>
                            handleFactorChange(
                              factor.id,
                              'levels',
                              e.target.value.split(',').map((s) => s.trim())
                            )
                          }
                          placeholder="Level 1, Level 2, Level 3"
                        />
                      </div>
                    )}

                    <div className={styles.fieldGroup}>
                      <label className={styles.checkboxLabel}>
                        <input
                          type="checkbox"
                          checked={factor.controllable}
                          onChange={(e) =>
                            handleFactorChange(factor.id, 'controllable', e.target.checked)
                          }
                        />
                        Controllable Factor
                      </label>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Responses Card */}
          <div className={styles.responsesCard}>
            <div className={styles.sectionHeader}>
              <h2>Responses (Dependent Variables)</h2>
              <button className={styles.addBtn} onClick={addResponse}>
                <i className="fas fa-plus"></i>
                Add Response
              </button>
            </div>

            <div className={styles.responsesGrid}>
              {doeData.responses.map((response) => (
                <div key={response.id} className={styles.responseCard}>
                  <div className={styles.responseHeader}>
                    <h3>{response.name}</h3>
                    {doeData.responses.length > 1 && (
                      <button className={styles.removeBtn} onClick={() => removeResponse(response.id)}>
                        <i className="fas fa-times"></i>
                      </button>
                    )}
                  </div>

                  <div className={styles.responseFields}>
                    <div className={styles.fieldRow}>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Response Name</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={response.name}
                          onChange={(e) =>
                            handleResponseChange(response.id, 'name', e.target.value)
                          }
                          placeholder="e.g., Cycle Time"
                        />
                      </div>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Type</label>
                        <select
                          className={styles.selectInput}
                          value={response.type}
                          onChange={(e) =>
                            handleResponseChange(response.id, 'type', e.target.value)
                          }
                        >
                          <option value="continuous">Continuous</option>
                          <option value="discrete">Discrete</option>
                          <option value="attribute">Attribute</option>
                        </select>
                      </div>
                    </div>

                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Description</label>
                      <textarea
                        className={styles.textareaInput}
                        value={response.description}
                        onChange={(e) =>
                          handleResponseChange(response.id, 'description', e.target.value)
                        }
                        placeholder="Describe this response"
                        rows="2"
                      />
                    </div>

                    <div className={styles.fieldRow}>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Unit</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={response.unit}
                          onChange={(e) => handleResponseChange(response.id, 'unit', e.target.value)}
                          placeholder="e.g., seconds, %, ppm"
                        />
                      </div>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Objective</label>
                        <select
                          className={styles.selectInput}
                          value={response.objective}
                          onChange={(e) =>
                            handleResponseChange(response.id, 'objective', e.target.value)
                          }
                        >
                          <option value="maximize">Maximize</option>
                          <option value="minimize">Minimize</option>
                          <option value="target">Target Value</option>
                          <option value="none">None (Monitor Only)</option>
                        </select>
                      </div>
                    </div>

                    <div className={styles.fieldRow}>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Target/Spec</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={response.target}
                          onChange={(e) =>
                            handleResponseChange(response.id, 'target', e.target.value)
                          }
                          placeholder="Target value"
                        />
                      </div>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Weight</label>
                        <input
                          type="number"
                          className={styles.textInput}
                          value={response.weight}
                          onChange={(e) =>
                            handleResponseChange(
                              response.id,
                              'weight',
                              parseFloat(e.target.value) || 1
                            )
                          }
                          min="0.1"
                          max="10"
                          step="0.1"
                        />
                      </div>
                    </div>

                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Measurement Method</label>
                      <input
                        type="text"
                        className={styles.textInput}
                        value={response.measurementMethod}
                        onChange={(e) =>
                          handleResponseChange(response.id, 'measurementMethod', e.target.value)
                        }
                        placeholder="How will this be measured?"
                      />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Experimental Runs Card */}
          <div className={styles.runsCard}>
            <div className={styles.sectionHeader}>
              <h2>Experimental Runs</h2>
              <button className={styles.generateBtn} onClick={generateRuns}>
                <i className="fas fa-cogs"></i>
                Generate Runs
              </button>
            </div>

            {doeData.experimentalRuns.length > 0 ? (
              <div className={styles.runsTable}>
                <div className={styles.tableHeader}>
                  <div>Run</div>
                  <div>Order</div>
                  <div>Block</div>
                  {doeData.factors.map((factor) => (
                    <div key={factor.id}>{factor.name}</div>
                  ))}
                  {doeData.responses.map((response) => (
                    <div key={response.id}>{response.name}</div>
                  ))}
                </div>

                {doeData.experimentalRuns.slice(0, 10).map((run) => (
                  <div key={run.id} className={styles.tableRow}>
                    <div>{run.id}</div>
                    <div>{run.runOrder}</div>
                    <div>{run.block}</div>
                    {doeData.factors.map((factor) => (
                      <div key={factor.id}>{run.factors[factor.id]}</div>
                    ))}
                    {doeData.responses.map((response) => (
                      <div key={response.id}>
                        <input
                          type="text"
                          className={styles.responseInput}
                          value={run.responses[response.id]}
                          onChange={(e) => {
                            const updatedRuns = doeData.experimentalRuns.map((r) =>
                              r.id === run.id
                                ? {
                                    ...r,
                                    responses: { ...r.responses, [response.id]: e.target.value },
                                  }
                                : r
                            );
                            setDoeData((prev) => ({ ...prev, experimentalRuns: updatedRuns }));
                          }}
                          placeholder="Result"
                        />
                      </div>
                    ))}
                  </div>
                ))}

                {doeData.experimentalRuns.length > 10 && (
                  <div className={styles.tableFooter}>
                    <span>Showing 10 of {doeData.experimentalRuns.length} runs</span>
                  </div>
                )}
              </div>
            ) : (
              <div className={styles.emptyRuns}>
                <i className="fas fa-flask"></i>
                <p>
                  No experimental runs generated yet. Click &quot;Generate Runs&quot; to create the
                  experimental design.
                </p>
              </div>
            )}
          </div>

          {/* Data Collection Card */}
          <div className={styles.dataCollectionCard}>
            <div className={styles.sectionHeader}>
              <h2>Data Collection Plan</h2>
            </div>

            <div className={styles.dataCollectionGrid}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Measurement Plan</label>
                <textarea
                  className={styles.textareaInput}
                  value={doeData.dataCollection.measurementPlan}
                  onChange={(e) => handleDataCollectionChange('measurementPlan', e.target.value)}
                  placeholder="How will measurements be taken?"
                  rows="3"
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Data Collection Sheet</label>
                <textarea
                  className={styles.textareaInput}
                  value={doeData.dataCollection.dataCollectionSheet}
                  onChange={(e) =>
                    handleDataCollectionChange('dataCollectionSheet', e.target.value)
                  }
                  placeholder="Describe the data collection format"
                  rows="3"
                />
              </div>

              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Quality Checks</label>
                  <textarea
                    className={styles.textareaInput}
                    value={doeData.dataCollection.qualityChecks}
                    onChange={(e) => handleDataCollectionChange('qualityChecks', e.target.value)}
                    placeholder="Quality assurance procedures"
                    rows="2"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Calibration</label>
                  <textarea
                    className={styles.textareaInput}
                    value={doeData.dataCollection.calibration}
                    onChange={(e) => handleDataCollectionChange('calibration', e.target.value)}
                    placeholder="Instrument calibration requirements"
                    rows="2"
                  />
                </div>
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Environmental Controls</label>
                <textarea
                  className={styles.textareaInput}
                  value={doeData.dataCollection.environmentalControls}
                  onChange={(e) =>
                    handleDataCollectionChange('environmentalControls', e.target.value)
                  }
                  placeholder="Environmental conditions to control"
                  rows="2"
                />
              </div>
            </div>
          </div>

          {/* Analysis Settings Card */}
          <div className={styles.analysisCard}>
            <div className={styles.sectionHeader}>
              <h2>Analysis Settings</h2>
            </div>

            <div className={styles.analysisGrid}>
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Significance Level (α)</label>
                  <select
                    className={styles.selectInput}
                    value={doeData.analysisSettings.significanceLevel}
                    onChange={(e) =>
                      handleAnalysisChange('significanceLevel', parseFloat(e.target.value))
                    }
                  >
                    <option value={0.01}>0.01 (99% confidence)</option>
                    <option value={0.05}>0.05 (95% confidence)</option>
                    <option value={0.1}>0.10 (90% confidence)</option>
                  </select>
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Analysis Type</label>
                  <select
                    className={styles.selectInput}
                    value={doeData.analysisSettings.analysisType}
                    onChange={(e) => handleAnalysisChange('analysisType', e.target.value)}
                  >
                    <option value="anova">ANOVA</option>
                    <option value="regression">Regression</option>
                    <option value="response-surface">Response Surface</option>
                  </select>
                </div>
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Outlier Handling</label>
                <select
                  className={styles.selectInput}
                  value={doeData.analysisSettings.outlierHandling}
                  onChange={(e) => handleAnalysisChange('outlierHandling', e.target.value)}
                >
                  <option value="investigate">Investigate</option>
                  <option value="remove">Remove</option>
                  <option value="transform">Transform</option>
                </select>
              </div>
            </div>
          </div>

          {/* Results Card */}
          <div className={styles.resultsCard}>
            <div className={styles.sectionHeader}>
              <h2>Results & Analysis</h2>
            </div>

            <div className={styles.resultsGrid}>
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Experiment Status</label>
                  <select
                    className={styles.selectInput}
                    value={doeData.results.experimentStatus}
                    onChange={(e) => handleResultsChange('experimentStatus', e.target.value)}
                  >
                    <option value="planning">Planning</option>
                    <option value="running">Running</option>
                    <option value="completed">Completed</option>
                    <option value="cancelled">Cancelled</option>
                  </select>
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.checkboxLabel}>
                    <input
                      type="checkbox"
                      checked={doeData.results.dataCollected}
                      onChange={(e) => handleResultsChange('dataCollected', e.target.checked)}
                    />
                    Data Collection Complete
                  </label>
                  <label className={styles.checkboxLabel}>
                    <input
                      type="checkbox"
                      checked={doeData.results.analysisCompleted}
                      onChange={(e) => handleResultsChange('analysisCompleted', e.target.checked)}
                    />
                    Analysis Complete
                  </label>
                </div>
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Model Equation</label>
                <textarea
                  className={styles.textareaInput}
                  value={doeData.results.modelEquation}
                  onChange={(e) => handleResultsChange('modelEquation', e.target.value)}
                  placeholder="Y = β₀ + β₁X₁ + β₂X₂ + β₁₂X₁X₂ + ..."
                  rows="2"
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Recommendations</label>
                <textarea
                  className={styles.textareaInput}
                  value={doeData.results.recommendations}
                  onChange={(e) => handleResultsChange('recommendations', e.target.value)}
                  placeholder="Based on the analysis, what are your recommendations?"
                  rows="4"
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Next Steps</label>
                <textarea
                  className={styles.textareaInput}
                  value={doeData.results.nextSteps}
                  onChange={(e) => handleResultsChange('nextSteps', e.target.value)}
                  placeholder="What are the next steps for implementation?"
                  rows="3"
                />
              </div>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className={styles.footer}>
          <div className={styles.footerContent}>
            <div className={styles.completionStatus}>
              <i className="fas fa-check-circle"></i>
              <span>DOE Design {completionPercentage}% Complete</span>
            </div>
            <div className={styles.footerActions}>
              <button className={styles.secondaryBtn}>
                <i className="fas fa-eye"></i>
                Preview Design
              </button>
              <button className={styles.primaryBtn} disabled={completionPercentage < 70}>
                <i className="fas fa-play"></i>
                Run Experiment
              </button>
            </div>
          </div>
        </div>
      </div>
    </ResourcePageWrapper>
  );
};

export default DOE;
