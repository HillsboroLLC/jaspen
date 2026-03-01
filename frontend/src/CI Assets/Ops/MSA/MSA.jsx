import React, { useState, useEffect } from 'react';
import { useAdminSettings } from '../context/AdminContext';
import ResourcePageWrapper from '../../All/components/ResourcePageWrapper';
import styles from './MSA.module.css';

const MSA = () => {
  const { adminSettings } = useAdminSettings();

  // Small Kii integration hook (optional)
  const handleKiiDataUpdate = (extractedData) => {
    const updates = {};
    if (extractedData.projectName) updates.projectName = extractedData.projectName;
    if (extractedData.processOwner) updates.processOwner = extractedData.processOwner;
    if (extractedData.msaTeam) updates.msaTeam = extractedData.msaTeam;

    if (Object.keys(updates).length > 0) {
      setMsaData(prev => ({
        ...prev,
        ...updates,
        lastUpdated: new Date().toISOString().split('T')[0]
      }));
    }
  };

  // MSA data structure
  const [msaData, setMsaData] = useState({
    projectName: '',
    processOwner: '',
    msaTeam: '',
    dateCreated: new Date().toISOString().split('T')[0],
    lastUpdated: new Date().toISOString().split('T')[0],
    
    // Study information
    studyInfo: {
      studyType: 'gauge-rr', // 'gauge-rr', 'bias-linearity', 'stability', 'attribute'
      measurementSystem: '',
      characteristic: '',
      specification: '',
      tolerance: '',
      units: '',
      studyPurpose: ''
    },
    
    // Gauge R&R setup
    gaugeRR: {
      parts: 10,
      operators: 3,
      trials: 2,
      partNumbers: [],
      operatorNames: [],
      measurements: [] // Will store all measurement data
    },
    
    // Bias and Linearity setup
    biasLinearity: {
      referenceStandard: '',
      referenceValue: '',
      measurementRange: '',
      numberOfLevels: 5,
      trialsPerLevel: 10,
      levels: [],
      measurements: []
    },
    
    // Stability setup
    stability: {
      controlPart: '',
      studyDuration: '',
      measurementFrequency: '',
      expectedMeasurements: '',
      measurements: []
    },
    
    // Attribute MSA setup
    attribute: {
      attributeType: 'go-no-go', // 'go-no-go', 'classification', 'rating'
      numberOfParts: 50,
      numberOfOperators: 3,
      numberOfTrials: 2,
      referenceStandard: '',
      parts: [],
      measurements: []
    },
    
    // Analysis results (calculated)
    results: {
      gaugeRR: {
        totalVariation: 0,
        repeatability: 0,
        reproducibility: 0,
        partToPartVariation: 0,
        percentStudyVariation: 0,
        percentTolerance: 0,
        numberOfDistinctCategories: 0,
        acceptable: false
      },
      biasLinearity: {
        bias: 0,
        biasPercent: 0,
        linearity: 0,
        linearityPercent: 0,
        acceptable: false
      },
      stability: {
        controlLimits: { ucl: 0, lcl: 0, centerLine: 0 },
        outOfControl: false,
        acceptable: false
      },
      attribute: {
        operatorAgreement: 0,
        operatorVsStandard: 0,
        kappa: 0,
        acceptable: false
      }
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
      if (msaData.projectName) completedFields++;
      if (msaData.processOwner) completedFields++;
      if (msaData.msaTeam) completedFields++;

      // Study info
      totalFields += 6;
      if (msaData.studyInfo.measurementSystem) completedFields++;
      if (msaData.studyInfo.characteristic) completedFields++;
      if (msaData.studyInfo.specification) completedFields++;
      if (msaData.studyInfo.tolerance) completedFields++;
      if (msaData.studyInfo.units) completedFields++;
      if (msaData.studyInfo.studyPurpose) completedFields++;

      // Study-specific completion
      if (msaData.studyInfo.studyType === 'gauge-rr') {
        totalFields += 3;
        if (msaData.gaugeRR.partNumbers.length > 0) completedFields++;
        if (msaData.gaugeRR.operatorNames.length > 0) completedFields++;
        if (msaData.gaugeRR.measurements.length > 0) completedFields++;
      } else if (msaData.studyInfo.studyType === 'bias-linearity') {
        totalFields += 3;
        if (msaData.biasLinearity.referenceStandard) completedFields++;
        if (msaData.biasLinearity.levels.length > 0) completedFields++;
        if (msaData.biasLinearity.measurements.length > 0) completedFields++;
      } else if (msaData.studyInfo.studyType === 'stability') {
        totalFields += 3;
        if (msaData.stability.controlPart) completedFields++;
        if (msaData.stability.studyDuration) completedFields++;
        if (msaData.stability.measurements.length > 0) completedFields++;
      } else if (msaData.studyInfo.studyType === 'attribute') {
        totalFields += 3;
        if (msaData.attribute.referenceStandard) completedFields++;
        if (msaData.attribute.parts.length > 0) completedFields++;
        if (msaData.attribute.measurements.length > 0) completedFields++;
      }

      const percentage = totalFields > 0 ? Math.round((completedFields / totalFields) * 100) : 0;
      setCompletionPercentage(percentage);
    };

    calculateCompletion();
  }, [msaData]);

  // Handle field changes
  const handleBasicInfoChange = (field, value) => {
    setMsaData(prev => ({
      ...prev,
      [field]: value,
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleStudyInfoChange = (field, value) => {
    setMsaData(prev => ({
      ...prev,
      studyInfo: {
        ...prev.studyInfo,
        [field]: value
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleGaugeRRChange = (field, value) => {
    setMsaData(prev => ({
      ...prev,
      gaugeRR: {
        ...prev.gaugeRR,
        [field]: value
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleBiasLinearityChange = (field, value) => {
    setMsaData(prev => ({
      ...prev,
      biasLinearity: {
        ...prev.biasLinearity,
        [field]: value
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleStabilityChange = (field, value) => {
    setMsaData(prev => ({
      ...prev,
      stability: {
        ...prev.stability,
        [field]: value
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleAttributeChange = (field, value) => {
    setMsaData(prev => ({
      ...prev,
      attribute: {
        ...prev.attribute,
        [field]: value
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Initialize study setup based on type
  const initializeStudySetup = () => {
    const studyType = msaData.studyInfo.studyType;
    
    if (studyType === 'gauge-rr') {
      const partNumbers = Array.from({ length: msaData.gaugeRR.parts }, (_, i) => `Part ${i + 1}`);
      const operatorNames = Array.from({ length: msaData.gaugeRR.operators }, (_, i) => `Operator ${i + 1}`);
      handleGaugeRRChange('partNumbers', partNumbers);
      handleGaugeRRChange('operatorNames', operatorNames);
    } else if (studyType === 'bias-linearity') {
      const levels = Array.from({ length: msaData.biasLinearity.numberOfLevels }, (_, i) => ({
        id: i + 1,
        referenceValue: '',
        measurements: Array.from({ length: msaData.biasLinearity.trialsPerLevel }, () => '')
      }));
      handleBiasLinearityChange('levels', levels);
    } else if (studyType === 'attribute') {
      const parts = Array.from({ length: msaData.attribute.numberOfParts }, (_, i) => ({
        id: i + 1,
        partNumber: `Part ${i + 1}`,
        referenceValue: '',
        measurements: []
      }));
      handleAttributeChange('parts', parts);
    }
  };

  // Add measurement data
  const addMeasurementData = () => {
    const studyType = msaData.studyInfo.studyType;
    
    if (studyType === 'gauge-rr') {
      const measurements = [];
      msaData.gaugeRR.partNumbers.forEach((part, partIndex) => {
        msaData.gaugeRR.operatorNames.forEach((operator, opIndex) => {
          for (let trial = 1; trial <= msaData.gaugeRR.trials; trial++) {
            measurements.push({
              id: `${partIndex}-${opIndex}-${trial}`,
              partNumber: part,
              operator: operator,
              trial: trial,
              measurement: ''
            });
          }
        });
      });
      handleGaugeRRChange('measurements', measurements);
    }
  };

  // Update measurement value
  const updateMeasurement = (id, value) => {
    const studyType = msaData.studyInfo.studyType;
    
    if (studyType === 'gauge-rr') {
      const updatedMeasurements = msaData.gaugeRR.measurements.map(m =>
        m.id === id ? { ...m, measurement: value } : m
      );
      handleGaugeRRChange('measurements', updatedMeasurements);
    }
  };

  // Calculate sample results (mock calculations)
  const calculateResults = () => {
    if (msaData.studyInfo.studyType === 'gauge-rr' && msaData.gaugeRR.measurements.length > 0) {
      const results = {
        totalVariation: 0.0245,
        repeatability: 0.0156,
        reproducibility: 0.0089,
        partToPartVariation: 0.0198,
        percentStudyVariation: 15.2,
        percentTolerance: 12.8,
        numberOfDistinctCategories: 6,
        acceptable: true
      };
      
      setMsaData(prev => ({
        ...prev,
        results: {
          ...prev.results,
          gaugeRR: results
        }
      }));
    }
  };

  return (
    <ResourcePageWrapper
      pageName="Measurement System Analysis"
      toolName="msa"
      adminSettings={adminSettings}
      onDataUpdate={handleKiiDataUpdate}
      currentData={msaData}
    >
      <div className={styles.msaContainer}>
        {/* Header */}
        <div className={styles.header}>
          <div className={styles.headerContent}>
            <h1>Measurement System Analysis (MSA)</h1>
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
              <i className="fas fa-save"></i> Save Draft
            </button>
            <button className={styles.exportBtn}>
              <i className="fas fa-download"></i> Export Report
            </button>
          </div>
        </div>

        {/* Main Content */}
        <div className={styles.mainContent}>
{/* MSA Information (full width) */}
<div className={styles.processInfoCard}>
  <h2>MSA Study Information</h2>
  
  <div className={styles.fieldGroup}>
    <label className={styles.fieldLabel}>
      Project Name <span className={styles.required}>*</span>
    </label>
    <input
      type="text"
      className={styles.textInput}
      value={msaData.projectName}
      onChange={(e) => handleBasicInfoChange('projectName', e.target.value)}
      placeholder="Enter the project name for this MSA study"
    />
  </div>

  <div className={styles.fieldRow}>
    <div className={styles.fieldGroup}>
      <label className={styles.fieldLabel}>
        Process Owner <span className={styles.required}>*</span>
      </label>
      <input
        type="text"
        className={styles.textInput}
        value={msaData.processOwner}
        onChange={(e) => handleBasicInfoChange('processOwner', e.target.value)}
        placeholder="Who owns the measurement process?"
      />
    </div>
    <div className={styles.fieldGroup}>
      <label className={styles.fieldLabel}>
        MSA Team <span className={styles.required}>*</span>
      </label>
      <input
        type="text"
        className={styles.textInput}
        value={msaData.msaTeam}
        onChange={(e) => handleBasicInfoChange('msaTeam', e.target.value)}
        placeholder="List team members conducting the MSA"
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
        value={msaData.dateCreated}
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
        value={msaData.lastUpdated}
        readOnly
      />
    </div>
  </div>

  <div className={styles.fieldGroup}>
    <label className={styles.fieldLabel}>
      Study Type <span className={styles.required}>*</span>
    </label>
    <select
      className={styles.selectInput}
      value={msaData.studyInfo.studyType}
      onChange={(e) => handleStudyInfoChange('studyType', e.target.value)}
    >
      <option value="gauge-rr">Gauge R&R (Repeatability & Reproducibility)</option>
      <option value="bias-linearity">Bias & Linearity</option>
      <option value="stability">Stability</option>
      <option value="attribute">Attribute MSA</option>
    </select>
  </div>
</div>

          {/* Study Details Section */}
          <div className={styles.studyDetailsCard}>
            <div className={styles.sectionHeader}>
              <h2>Study Details</h2>
            </div>

            <div className={styles.studyDetailsGrid}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Measurement System <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={msaData.studyInfo.measurementSystem}
                  onChange={(e) => handleStudyInfoChange('measurementSystem', e.target.value)}
                  placeholder="Describe the measurement system (equipment, tools, etc.)"
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Characteristic <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={msaData.studyInfo.characteristic}
                  onChange={(e) => handleStudyInfoChange('characteristic', e.target.value)}
                  placeholder="What characteristic is being measured?"
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Specification <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={msaData.studyInfo.specification}
                  onChange={(e) => handleStudyInfoChange('specification', e.target.value)}
                  placeholder="Specification limits (e.g., 10.0 ± 0.5)"
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Tolerance <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={msaData.studyInfo.tolerance}
                  onChange={(e) => handleStudyInfoChange('tolerance', e.target.value)}
                  placeholder="Total tolerance (e.g., 1.0)"
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Units <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={msaData.studyInfo.units}
                  onChange={(e) => handleStudyInfoChange('units', e.target.value)}
                  placeholder="Units of measurement (mm, inches, etc.)"
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Study Purpose <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={msaData.studyInfo.studyPurpose}
                  onChange={(e) => handleStudyInfoChange('studyPurpose', e.target.value)}
                  placeholder="Why is this MSA study being conducted?"
                  rows={3}
                />
              </div>
            </div>
          </div>

          {/* Study Type Specific Sections */}
          {msaData.studyInfo.studyType === 'gauge-rr' && (
            <div className={styles.gaugeRRCard}>
              <div className={styles.sectionHeader}>
                <h2>Gauge R&R Setup</h2>
                <button className={styles.setupBtn} onClick={initializeStudySetup}>
                  <i className="fas fa-cog"></i> Initialize Setup
                </button>
              </div>

              <div className={styles.gaugeRRSetup}>
                <div className={styles.setupRow}>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Number of Parts</label>
                    <input
                      type="number"
                      className={styles.textInput}
                      value={msaData.gaugeRR.parts}
                      onChange={(e) => handleGaugeRRChange('parts', parseInt(e.target.value) || 10)}
                      min="5"
                      max="25"
                    />
                  </div>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Number of Operators</label>
                    <input
                      type="number"
                      className={styles.textInput}
                      value={msaData.gaugeRR.operators}
                      onChange={(e) => handleGaugeRRChange('operators', parseInt(e.target.value) || 3)}
                      min="2"
                      max="5"
                    />
                  </div>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Trials per Operator</label>
                    <input
                      type="number"
                      className={styles.textInput}
                      value={msaData.gaugeRR.trials}
                      onChange={(e) => handleGaugeRRChange('trials', parseInt(e.target.value) || 2)}
                      min="2"
                      max="5"
                    />
                  </div>
                  <div className={styles.fieldGroup}>
                    <button className={styles.generateBtn} onClick={addMeasurementData}>
                      <i className="fas fa-table"></i> Generate Data Grid
                    </button>
                  </div>
                </div>
              </div>

              {msaData.gaugeRR.measurements.length > 0 && (
                <div className={styles.measurementGrid}>
                  <h3>Measurement Data Entry</h3>
                  <div className={styles.dataTable}>
                    <div className={styles.tableHeader}>
                      <div>Part</div>
                      <div>Operator</div>
                      <div>Trial</div>
                      <div>Measurement</div>
                    </div>
                    {msaData.gaugeRR.measurements.map((measurement) => (
                      <div key={measurement.id} className={styles.tableRow}>
                        <div>{measurement.partNumber}</div>
                        <div>{measurement.operator}</div>
                        <div>{measurement.trial}</div>
                        <div>
                          <input
                            type="number"
                            step="0.001"
                            className={styles.measurementInput}
                            value={measurement.measurement}
                            onChange={(e) => updateMeasurement(measurement.id, e.target.value)}
                            placeholder="0.000"
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {msaData.studyInfo.studyType === 'bias-linearity' && (
            <div className={styles.biasLinearityCard}>
              <div className={styles.sectionHeader}>
                <h2>Bias & Linearity Setup</h2>
                <button className={styles.setupBtn} onClick={initializeStudySetup}>
                  <i className="fas fa-cog"></i> Initialize Setup
                </button>
              </div>

              <div className={styles.biasLinearitySetup}>
                <div className={styles.setupGrid}>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Reference Standard</label>
                    <input
                      type="text"
                      className={styles.textInput}
                      value={msaData.biasLinearity.referenceStandard}
                      onChange={(e) => handleBiasLinearityChange('referenceStandard', e.target.value)}
                      placeholder="Describe the reference standard used"
                    />
                  </div>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Measurement Range</label>
                    <input
                      type="text"
                      className={styles.textInput}
                      value={msaData.biasLinearity.measurementRange}
                      onChange={(e) => handleBiasLinearityChange('measurementRange', e.target.value)}
                      placeholder="e.g., 5.0 to 15.0"
                    />
                  </div>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Number of Levels</label>
                    <input
                      type="number"
                      className={styles.textInput}
                      value={msaData.biasLinearity.numberOfLevels}
                      onChange={(e) => handleBiasLinearityChange('numberOfLevels', parseInt(e.target.value) || 5)}
                      min="3"
                      max="10"
                    />
                  </div>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Trials per Level</label>
                    <input
                      type="number"
                      className={styles.textInput}
                      value={msaData.biasLinearity.trialsPerLevel}
                      onChange={(e) => handleBiasLinearityChange('trialsPerLevel', parseInt(e.target.value) || 10)}
                      min="5"
                      max="20"
                    />
                  </div>
                </div>
              </div>
            </div>
          )}

          {msaData.studyInfo.studyType === 'stability' && (
            <div className={styles.stabilityCard}>
              <div className={styles.sectionHeader}>
                <h2>Stability Setup</h2>
              </div>

              <div className={styles.stabilitySetup}>
                <div className={styles.setupGrid}>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Control Part</label>
                    <input
                      type="text"
                      className={styles.textInput}
                      value={msaData.stability.controlPart}
                      onChange={(e) => handleStabilityChange('controlPart', e.target.value)}
                      placeholder="Describe the control part used"
                    />
                  </div>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Study Duration</label>
                    <input
                      type="text"
                      className={styles.textInput}
                      value={msaData.stability.studyDuration}
                      onChange={(e) => handleStabilityChange('studyDuration', e.target.value)}
                      placeholder="e.g., 30 days, 12 weeks"
                    />
                  </div>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Measurement Frequency</label>
                    <input
                      type="text"
                      className={styles.textInput}
                      value={msaData.stability.measurementFrequency}
                      onChange={(e) => handleStabilityChange('measurementFrequency', e.target.value)}
                      placeholder="e.g., daily, weekly"
                    />
                  </div>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Expected Measurements</label>
                    <input
                      type="number"
                      className={styles.textInput}
                      value={msaData.stability.expectedMeasurements}
                      onChange={(e) => handleStabilityChange('expectedMeasurements', e.target.value)}
                      placeholder="Total number of measurements expected"
                    />
                  </div>
                </div>
              </div>
            </div>
          )}

          {msaData.studyInfo.studyType === 'attribute' && (
            <div className={styles.attributeCard}>
              <div className={styles.sectionHeader}>
                <h2>Attribute MSA Setup</h2>
                <button className={styles.setupBtn} onClick={initializeStudySetup}>
                  <i className="fas fa-cog"></i> Initialize Setup
                </button>
              </div>

              <div className={styles.attributeSetup}>
                <div className={styles.setupGrid}>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Attribute Type</label>
                    <select
                      className={styles.selectInput}
                      value={msaData.attribute.attributeType}
                      onChange={(e) => handleAttributeChange('attributeType', e.target.value)}
                    >
                      <option value="go-no-go">Go/No-Go</option>
                      <option value="classification">Classification</option>
                      <option value="rating">Rating Scale</option>
                    </select>
                  </div>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Number of Parts</label>
                    <input
                      type="number"
                      className={styles.textInput}
                      value={msaData.attribute.numberOfParts}
                      onChange={(e) => handleAttributeChange('numberOfParts', parseInt(e.target.value) || 50)}
                      min="30"
                      max="100"
                    />
                  </div>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Number of Operators</label>
                    <input
                      type="number"
                      className={styles.textInput}
                      value={msaData.attribute.numberOfOperators}
                      onChange={(e) => handleAttributeChange('numberOfOperators', parseInt(e.target.value) || 3)}
                      min="2"
                      max="5"
                    />
                  </div>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Number of Trials</label>
                    <input
                      type="number"
                      className={styles.textInput}
                      value={msaData.attribute.numberOfTrials}
                      onChange={(e) => handleAttributeChange('numberOfTrials', parseInt(e.target.value) || 2)}
                      min="2"
                      max="3"
                    />
                  </div>
                </div>

                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Reference Standard</label>
                  <textarea
                    className={styles.textareaInput}
                    value={msaData.attribute.referenceStandard}
                    onChange={(e) => handleAttributeChange('referenceStandard', e.target.value)}
                    placeholder="Describe the reference standard or known correct classification"
                    rows={3}
                  />
                </div>
              </div>
            </div>
          )}

          {/* Results Section */}
          <div className={styles.resultsCard}>
            <div className={styles.sectionHeader}>
              <h2>Analysis Results</h2>
              <button className={styles.analyzeBtn} onClick={calculateResults}>
                <i className="fas fa-calculator"></i> Calculate Results
              </button>
            </div>

            {msaData.studyInfo.studyType === 'gauge-rr' && msaData.gaugeRR.measurements.length > 0 ? (
              <div className={styles.gaugeRRResults}>
                <div className={styles.resultsGrid}>
                  <div className={styles.resultCard}>
                    <h4>Study Variation (%)</h4>
                    <div className={styles.resultValue}>
                      {msaData.results.gaugeRR.percentStudyVariation.toFixed(1)}%
                    </div>
                    <div className={styles.resultStatus}>
                      {msaData.results.gaugeRR.percentStudyVariation < 10 ? 'Excellent' : 
                       msaData.results.gaugeRR.percentStudyVariation < 30 ? 'Acceptable' : 'Poor'}
                    </div>
                  </div>

                  <div className={styles.resultCard}>
                    <h4>Tolerance (%)</h4>
                    <div className={styles.resultValue}>
                      {msaData.results.gaugeRR.percentTolerance.toFixed(1)}%
                    </div>
                    <div className={styles.resultStatus}>
                      {msaData.results.gaugeRR.percentTolerance < 10 ? 'Excellent' : 
                       msaData.results.gaugeRR.percentTolerance < 30 ? 'Acceptable' : 'Poor'}
                    </div>
                  </div>

                  <div className={styles.resultCard}>
                    <h4>Distinct Categories</h4>
                    <div className={styles.resultValue}>
                      {msaData.results.gaugeRR.numberOfDistinctCategories}
                    </div>
                    <div className={styles.resultStatus}>
                      {msaData.results.gaugeRR.numberOfDistinctCategories >= 5 ? 'Adequate' : 'Inadequate'}
                    </div>
                  </div>

                  <div className={styles.resultCard}>
                    <h4>Overall Assessment</h4>
                    <div className={styles.resultValue}>
                      {msaData.results.gaugeRR.acceptable ? 'PASS' : 'FAIL'}
                    </div>
                    <div className={styles.resultStatus}>
                      {msaData.results.gaugeRR.acceptable ? 'System Acceptable' : 'System Needs Improvement'}
                    </div>
                  </div>
                </div>

                <div className={styles.variationBreakdown}>
                  <h4>Variation Breakdown</h4>
                  <div className={styles.variationChart}>
                    <div className={styles.variationBar}>
                      <div className={styles.variationLabel}>Repeatability</div>
                      <div className={styles.variationValue}>63.7%</div>
                    </div>
                    <div className={styles.variationBar}>
                      <div className={styles.variationLabel}>Reproducibility</div>
                      <div className={styles.variationValue}>36.3%</div>
                    </div>
                    <div className={styles.variationBar}>
                      <div className={styles.variationLabel}>Part-to-Part</div>
                      <div className={styles.variationValue}>80.8%</div>
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <div className={styles.emptyResults}>
                <i className="fas fa-chart-bar"></i>
                <p>Complete data collection and click "Calculate Results" to see analysis.</p>
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className={styles.footer}>
          <div className={styles.footerContent}>
            <div className={styles.completionStatus}>
              <i className="fas fa-check-circle"></i>
              <span>MSA Study {completionPercentage}% Complete</span>
            </div>
            <div className={styles.footerActions}>
              <button className={styles.secondaryBtn}>
                <i className="fas fa-eye"></i> Preview Report
              </button>
              <button 
                className={styles.primaryBtn}
                disabled={completionPercentage < 80}
              >
                <i className="fas fa-check"></i> Complete Study
              </button>
            </div>
          </div>
        </div>
      </div>
    </ResourcePageWrapper>
  );
};

export default MSA;
