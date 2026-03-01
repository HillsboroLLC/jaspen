// ============================================================================
// File: src/Ops/CapabilityAnalysis/CapabilityAnalysis.jsx
// Purpose: Process Capability Study with floating chat via ResourcePageWrapper,
//          solid progress bar, and full feature parity with your original.
// ============================================================================

import React, { useState, useEffect, useCallback } from 'react';
import styles from './CapabilityAnalysis.module.css';
import { useAdminSettings } from '../context/AdminContext';
import ResourcePageWrapper from '../../All/components/ResourcePageWrapper';
import '@fortawesome/fontawesome-free/css/all.min.css';

const CapabilityAnalysis = () => {
  const { adminSettings } = useAdminSettings();

  // Process Capability data structure
  const [capabilityData, setCapabilityData] = useState({
    projectName: '',
    processOwner: '',
    capabilityTeam: '',
    dateCreated: new Date().toISOString().split('T')[0],
    lastUpdated: new Date().toISOString().split('T')[0],

    // Process information
    processInfo: {
      processName: '',
      characteristic: '',
      units: '',
      dataType: 'continuous', // 'continuous', 'discrete'
      sampleSize: 100,
      samplingPeriod: '',
      studyPurpose: '',
    },

    // Specifications
    specifications: {
      lsl: '', // Lower Specification Limit
      usl: '', // Upper Specification Limit
      target: '', // Target value
      tolerance: '',
      specType: 'bilateral', // 'bilateral', 'unilateral-upper', 'unilateral-lower'
    },

    // Data collection
    dataCollection: {
      collectionMethod: 'manual', // 'manual', 'automated', 'sampling'
      measurements: [],
      subgroupSize: 5,
      numberOfSubgroups: 20,
      collectionNotes: '',
    },

    // Analysis settings
    analysisSettings: {
      confidenceLevel: 95, // 90, 95, 99
      transformData: false,
      transformation: 'none', // 'none', 'log', 'sqrt', 'box-cox'
      outlierHandling: 'include', // 'include', 'exclude', 'investigate'
      assumeNormality: true,
    },

    // Results (calculated)
    results: {
      descriptiveStats: {
        mean: 0,
        stdDev: 0,
        variance: 0,
        range: 0,
        minimum: 0,
        maximum: 0,
        median: 0,
        q1: 0,
        q3: 0,
      },
      capabilityIndices: {
        cp: 0,
        cpk: 0,
        cpl: 0,
        cpu: 0,
        pp: 0,
        ppk: 0,
        ppl: 0,
        ppu: 0,
        cpm: 0,
      },
      processPerformance: {
        processYield: 0,
        defectRate: 0,
        sigmaLevel: 0,
        ppm: 0,
      },
      normalityTest: {
        andersonDarling: 0,
        pValue: 0,
        isNormal: false,
      },
      processStability: {
        isStable: false,
        outOfControlPoints: 0,
        trends: 0,
        shifts: 0,
      },
    },
  });

  const [completionPercentage, setCompletionPercentage] = useState(0);

  // Allow floating chat (from ResourcePageWrapper) to update data dynamically
  const handleKiiDataUpdate = useCallback((extracted = {}) => {
    setCapabilityData((prev) => {
      const next = { ...prev };

      // Top-level basics
      if (extracted.projectName) next.projectName = extracted.projectName;
      if (extracted.processOwner) next.processOwner = extracted.processOwner;
      if (extracted.capabilityTeam) next.capabilityTeam = extracted.capabilityTeam;

      // Process info
      if (extracted.processInfo) {
        next.processInfo = { ...next.processInfo, ...extracted.processInfo };
      } else {
        ['processName', 'characteristic', 'units', 'dataType', 'sampleSize', 'samplingPeriod', 'studyPurpose'].forEach(
          (k) => {
            if (extracted[k] !== undefined) next.processInfo[k] = extracted[k];
          }
        );
      }

      // Specifications
      if (extracted.specifications) {
        next.specifications = { ...next.specifications, ...extracted.specifications };
      } else {
        ['lsl', 'usl', 'target', 'tolerance', 'specType'].forEach((k) => {
          if (extracted[k] !== undefined) next.specifications[k] = extracted[k];
        });
      }

      // Data collection
      if (extracted.dataCollection) {
        const incoming = { ...extracted.dataCollection };
        if (Array.isArray(incoming.measurements)) {
          incoming.measurements = incoming.measurements.map((m, idx) => ({
            id: m.id || Date.now() + idx,
            value: typeof m.value === 'number' ? m.value : parseFloat(m.value) || 0,
            timestamp: m.timestamp || new Date().toISOString(),
          }));
        }
        next.dataCollection = { ...next.dataCollection, ...incoming };
      }

      // Analysis settings
      if (extracted.analysisSettings) {
        next.analysisSettings = { ...next.analysisSettings, ...extracted.analysisSettings };
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

      // Basic info
      totalFields += 3;
      if (capabilityData.projectName) completedFields++;
      if (capabilityData.processOwner) completedFields++;
      if (capabilityData.capabilityTeam) completedFields++;

      // Process info
      totalFields += 5;
      if (capabilityData.processInfo.processName) completedFields++;
      if (capabilityData.processInfo.characteristic) completedFields++;
      if (capabilityData.processInfo.units) completedFields++;
      if (capabilityData.processInfo.samplingPeriod) completedFields++;
      if (capabilityData.processInfo.studyPurpose) completedFields++;

      // Specifications
      totalFields += 3;
      if (capabilityData.specifications.lsl || capabilityData.specifications.usl) completedFields++;
      if (capabilityData.specifications.target) completedFields++;
      if (capabilityData.specifications.tolerance) completedFields++;

      // Data collection
      totalFields += 2;
      if (capabilityData.dataCollection.measurements.length > 0) completedFields++;
      if (capabilityData.dataCollection.collectionNotes) completedFields++;

      const percentage = totalFields > 0 ? Math.round((completedFields / totalFields) * 100) : 0;
      setCompletionPercentage(percentage);
    };

    calculateCompletion();
  }, [capabilityData]);

  // Handle field changes
  const handleBasicInfoChange = (field, value) => {
    setCapabilityData((prev) => ({
      ...prev,
      [field]: value,
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  const handleProcessInfoChange = (field, value) => {
    setCapabilityData((prev) => ({
      ...prev,
      processInfo: {
        ...prev.processInfo,
        [field]: value,
      },
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  const handleSpecificationChange = (field, value) => {
    setCapabilityData((prev) => ({
      ...prev,
      specifications: {
        ...prev.specifications,
        [field]: value,
      },
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  const handleDataCollectionChange = (field, value) => {
    setCapabilityData((prev) => ({
      ...prev,
      dataCollection: {
        ...prev.dataCollection,
        [field]: value,
      },
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  const handleAnalysisSettingsChange = (field, value) => {
    setCapabilityData((prev) => ({
      ...prev,
      analysisSettings: {
        ...prev.analysisSettings,
        [field]: value,
      },
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  // Generate sample data
  const generateSampleData = () => {
    const sampleSize = capabilityData.processInfo.sampleSize || 100;
    const target = parseFloat(capabilityData.specifications.target) || 10;
    const stdDev = 0.5;

    const measurements = [];
    for (let i = 0; i < sampleSize; i++) {
      const u1 = Math.random();
      const u2 = Math.random();
      const z0 = Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
      const value = target + z0 * stdDev;
      measurements.push({
        id: i + 1,
        value: parseFloat(value.toFixed(3)),
        timestamp: new Date(Date.now() - (sampleSize - i) * 60000).toISOString(),
      });
    }

    handleDataCollectionChange('measurements', measurements);
  };

  // Import data from CSV
  const handleFileImport = (event) => {
    const file = event.target.files[0];
    if (file) {
      const reader = new FileReader();
      reader.onload = (e) => {
        const text = e.target.result;
        const lines = text.split('\n');
        const measurements = [];

        lines.forEach((line, index) => {
          if (line.trim() && index > 0) {
            const value = parseFloat(line.trim());
            if (!isNaN(value)) {
              measurements.push({
                id: measurements.length + 1,
                value,
                timestamp: new Date().toISOString(),
              });
            }
          }
        });

        handleDataCollectionChange('measurements', measurements);
      };
      reader.readAsText(file);
    }
  };

  // Calculate capability indices (simplified demo math)
  const calculateCapability = () => {
    const measurements = capabilityData.dataCollection.measurements;
    if (measurements.length === 0) return;

    const values = measurements.map((m) => m.value);
    const n = values.length;

    // Descriptive statistics
    const mean = values.reduce((sum, val) => sum + val, 0) / n;
    const variance = values.reduce((sum, val) => sum + Math.pow(val - mean, 2), 0) / (n - 1);
    const stdDev = Math.sqrt(variance);
    const minimum = Math.min(...values);
    const maximum = Math.max(...values);
    const range = maximum - minimum;

    const sortedValues = [...values].sort((a, b) => a - b);
    const median = n % 2 === 0 ? (sortedValues[n / 2 - 1] + sortedValues[n / 2]) / 2 : sortedValues[Math.floor(n / 2)];
    const q1 = sortedValues[Math.floor(n * 0.25)];
    const q3 = sortedValues[Math.floor(n * 0.75)];

    // Specification limits
    const lsl = parseFloat(capabilityData.specifications.lsl);
    const usl = parseFloat(capabilityData.specifications.usl);
    const target = parseFloat(capabilityData.specifications.target);

    // Capability indices
    let cp = 0,
      cpk = 0,
      cpl = 0,
      cpu = 0;
    let pp = 0,
      ppk = 0,
      ppl = 0,
      ppu = 0,
      cpm = 0;

    if (!isNaN(lsl) && !isNaN(usl)) {
      cp = (usl - lsl) / (6 * stdDev);
      cpl = (mean - lsl) / (3 * stdDev);
      cpu = (usl - mean) / (3 * stdDev);
      cpk = Math.min(cpl, cpu);

      // Simple placeholders for demo parity
      pp = cp;
      ppl = cpl;
      ppu = cpu;
      ppk = cpk;

      if (!isNaN(target)) {
        cpm = (usl - lsl) / (6 * Math.sqrt(variance + Math.pow(mean - target, 2)));
      }
    } else if (!isNaN(usl)) {
      cpu = (usl - mean) / (3 * stdDev);
      cpk = cpu;
      ppu = cpu;
      ppk = cpu;
    } else if (!isNaN(lsl)) {
      cpl = (mean - lsl) / (3 * stdDev);
      cpk = cpl;
      ppl = cpl;
      ppk = cpl;
    }

    // Process performance
    let processYield = 100;
    let defectRate = 0;
    let ppm = 0;

    if (!isNaN(lsl) && !isNaN(usl)) {
      const defects = values.filter((v) => v < lsl || v > usl).length;
      defectRate = (defects / n) * 100;
      processYield = 100 - defectRate;
      ppm = defectRate * 10000;
    }

    const sigmaLevel = cpk > 0 ? cpk * 3 + 1.5 : 0;

    setCapabilityData((prev) => ({
      ...prev,
      results: {
        ...prev.results,
        descriptiveStats: {
          mean: parseFloat(mean.toFixed(4)),
          stdDev: parseFloat(stdDev.toFixed(4)),
          variance: parseFloat(variance.toFixed(4)),
          range: parseFloat(range.toFixed(4)),
          minimum: parseFloat(minimum.toFixed(4)),
          maximum: parseFloat(maximum.toFixed(4)),
          median: parseFloat(median.toFixed(4)),
          q1: parseFloat(q1.toFixed(4)),
          q3: parseFloat(q3.toFixed(4)),
        },
        capabilityIndices: {
          cp: parseFloat(cp.toFixed(3)),
          cpk: parseFloat(cpk.toFixed(3)),
          cpl: parseFloat(cpl.toFixed(3)),
          cpu: parseFloat(cpu.toFixed(3)),
          pp: parseFloat(pp.toFixed(3)),
          ppk: parseFloat(ppk.toFixed(3)),
          ppl: parseFloat(ppl.toFixed(3)),
          ppu: parseFloat(ppu.toFixed(3)),
          cpm: parseFloat(cpm.toFixed(3)),
        },
        processPerformance: {
          processYield: parseFloat(processYield.toFixed(2)),
          defectRate: parseFloat(defectRate.toFixed(4)),
          sigmaLevel: parseFloat(sigmaLevel.toFixed(2)),
          ppm: parseFloat(ppm.toFixed(0)),
        },
        normalityTest: {
          andersonDarling: 0.234,
          pValue: 0.156,
          isNormal: true,
        },
        processStability: {
          isStable: true,
          outOfControlPoints: 0,
          trends: 0,
          shifts: 0,
        },
      },
    }));
  };

  return (
    <ResourcePageWrapper
      pageName="Capability Analysis"
      toolName="Capability Analysis"
      adminSettings={adminSettings}
      currentData={capabilityData}
      onDataUpdate={handleKiiDataUpdate}
    >
      <div className={styles.capabilityContainer} style={{ paddingBottom: 0 }}>
        {/* Header */}
        <div className={styles.header}>
          <div className={styles.headerContent}>
            <h1>Process Capability Study</h1>
            <div className={styles.progressSection}>
              {/* Force SOLID color (no gradients) */}
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
            <button className={styles.saveBtn}>
              <i className="fas fa-save"></i> Save Study
            </button>
            <button className={styles.exportBtn}>
              <i className="fas fa-download"></i> Export Report
            </button>
          </div>
        </div>

        {/* Main Content */}
        <div className={styles.mainContent}>
          {/* Process Capability Information */}
          <div className={styles.processInfoCard}>
            <h2>Process Capability Information</h2>

            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel}>
                Project Name <span className={styles.required}>*</span>
              </label>
              <input
                type="text"
                className={styles.textInput}
                value={capabilityData.projectName}
                onChange={(e) => handleBasicInfoChange('projectName', e.target.value)}
                placeholder="Enter project name"
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
                  value={capabilityData.processOwner}
                  onChange={(e) => handleBasicInfoChange('processOwner', e.target.value)}
                  placeholder="Name of process owner"
                />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Capability Team <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={capabilityData.capabilityTeam}
                  onChange={(e) => handleBasicInfoChange('capabilityTeam', e.target.value)}
                  placeholder="Team conducting the study"
                />
              </div>
            </div>

            <div className={styles.fieldRow}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Date Created</label>
                <input
                  type="date"
                  className={styles.textInput}
                  value={capabilityData.dateCreated}
                  onChange={(e) => handleBasicInfoChange('dateCreated', e.target.value)}
                />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Last Updated</label>
                <input type="date" className={styles.textInput} value={capabilityData.lastUpdated} readOnly />
              </div>
            </div>
          </div>

          {/* Process Details Section */}
          <div className={styles.processDetailsCard}>
            <div className={styles.sectionHeader}>
              <h2>Process Details</h2>
            </div>

            <div className={styles.processDetailsGrid}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Process Name <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={capabilityData.processInfo.processName}
                  onChange={(e) => handleProcessInfoChange('processName', e.target.value)}
                  placeholder="Name of the process being analyzed"
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Characteristic <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={capabilityData.processInfo.characteristic}
                  onChange={(e) => handleProcessInfoChange('characteristic', e.target.value)}
                  placeholder="What characteristic is being measured?"
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Units <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={capabilityData.processInfo.units}
                  onChange={(e) => handleProcessInfoChange('units', e.target.value)}
                  placeholder="Units of measurement (mm, inches, etc.)"
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Data Type</label>
                <select
                  className={styles.selectInput}
                  value={capabilityData.processInfo.dataType}
                  onChange={(e) => handleProcessInfoChange('dataType', e.target.value)}
                >
                  <option value="continuous">Continuous (Variable)</option>
                  <option value="discrete">Discrete (Attribute)</option>
                </select>
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Sample Size</label>
                <input
                  type="number"
                  className={styles.textInput}
                  value={capabilityData.processInfo.sampleSize}
                  onChange={(e) => handleProcessInfoChange('sampleSize', parseInt(e.target.value) || 100)}
                  min="30"
                  max="1000"
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Sampling Period <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={capabilityData.processInfo.samplingPeriod}
                  onChange={(e) => handleProcessInfoChange('samplingPeriod', e.target.value)}
                  placeholder="Time period for data collection (e.g., 2 weeks)"
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Study Purpose <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={capabilityData.processInfo.studyPurpose}
                  onChange={(e) => handleProcessInfoChange('studyPurpose', e.target.value)}
                  placeholder="Why is this capability study being conducted?"
                  rows={3}
                />
              </div>
            </div>
          </div>

          {/* Specifications Section */}
          <div className={styles.specificationsCard}>
            <div className={styles.sectionHeader}>
              <h2>Specifications</h2>
            </div>

            <div className={styles.specificationsGrid}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Specification Type</label>
                <select
                  className={styles.selectInput}
                  value={capabilityData.specifications.specType}
                  onChange={(e) => handleSpecificationChange('specType', e.target.value)}
                >
                  <option value="bilateral">Bilateral (LSL and USL)</option>
                  <option value="unilateral-upper">Unilateral Upper (USL only)</option>
                  <option value="unilateral-lower">Unilateral Lower (LSL only)</option>
                </select>
              </div>

              {(capabilityData.specifications.specType === 'bilateral' ||
                capabilityData.specifications.specType === 'unilateral-lower') && (
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Lower Specification Limit (LSL)</label>
                  <input
                    type="number"
                    step="0.001"
                    className={styles.textInput}
                    value={capabilityData.specifications.lsl}
                    onChange={(e) => handleSpecificationChange('lsl', e.target.value)}
                    placeholder="Lower limit"
                  />
                </div>
              )}

              {(capabilityData.specifications.specType === 'bilateral' ||
                capabilityData.specifications.specType === 'unilateral-upper') && (
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Upper Specification Limit (USL)</label>
                  <input
                    type="number"
                    step="0.001"
                    className={styles.textInput}
                    value={capabilityData.specifications.usl}
                    onChange={(e) => handleSpecificationChange('usl', e.target.value)}
                    placeholder="Upper limit"
                  />
                </div>
              )}

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Target Value</label>
                <input
                  type="number"
                  step="0.001"
                  className={styles.textInput}
                  value={capabilityData.specifications.target}
                  onChange={(e) => handleSpecificationChange('target', e.target.value)}
                  placeholder="Target or nominal value"
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Tolerance</label>
                <input
                  type="number"
                  step="0.001"
                  className={styles.textInput}
                  value={capabilityData.specifications.tolerance}
                  onChange={(e) => handleSpecificationChange('tolerance', e.target.value)}
                  placeholder="Total tolerance (USL - LSL)"
                />
              </div>
            </div>
          </div>

          {/* Data Collection Section */}
          <div className={styles.dataCollectionCard}>
            <div className={styles.sectionHeader}>
              <h2>Data Collection</h2>
              <div className={styles.dataActions}>
                <button className={styles.generateBtn} onClick={generateSampleData}>
                  <i className="fas fa-random"></i> Generate Sample Data
                </button>
                <label className={styles.importBtn}>
                  <i className="fas fa-upload"></i> Import CSV
                  <input type="file" accept=".csv" onChange={handleFileImport} style={{ display: 'none' }} />
                </label>
              </div>
            </div>

            <div className={styles.dataCollectionGrid}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Collection Method</label>
                <select
                  className={styles.selectInput}
                  value={capabilityData.dataCollection.collectionMethod}
                  onChange={(e) => handleDataCollectionChange('collectionMethod', e.target.value)}
                >
                  <option value="manual">Manual Measurement</option>
                  <option value="automated">Automated System</option>
                  <option value="sampling">Statistical Sampling</option>
                </select>
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Subgroup Size</label>
                <input
                  type="number"
                  className={styles.textInput}
                  value={capabilityData.dataCollection.subgroupSize}
                  onChange={(e) => handleDataCollectionChange('subgroupSize', parseInt(e.target.value) || 5)}
                  min="1"
                  max="25"
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Number of Subgroups</label>
                <input
                  type="number"
                  className={styles.textInput}
                  value={capabilityData.dataCollection.numberOfSubgroups}
                  onChange={(e) =>
                    handleDataCollectionChange('numberOfSubgroups', parseInt(e.target.value) || 20)
                  }
                  min="5"
                  max="100"
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Collection Notes</label>
                <textarea
                  className={styles.textareaInput}
                  value={capabilityData.dataCollection.collectionNotes}
                  onChange={(e) => handleDataCollectionChange('collectionNotes', e.target.value)}
                  placeholder="Notes about data collection conditions, methods, etc."
                  rows={3}
                />
              </div>
            </div>

            {capabilityData.dataCollection.measurements.length > 0 && (
              <div className={styles.dataPreview}>
                <h3>Data Preview ({capabilityData.dataCollection.measurements.length} measurements)</h3>
                <div className={styles.dataTable}>
                  <div className={styles.tableHeader}>
                    <div>ID</div>
                    <div>Value</div>
                    <div>Timestamp</div>
                  </div>
                  {capabilityData.dataCollection.measurements.slice(0, 10).map((m) => (
                    <div key={m.id} className={styles.tableRow}>
                      <div>{m.id}</div>
                      <div>{m.value}</div>
                      <div>{new Date(m.timestamp).toLocaleString()}</div>
                    </div>
                  ))}
                  {capabilityData.dataCollection.measurements.length > 10 && (
                    <div className={styles.tableRow}>
                      <div colSpan="3" className={styles.moreData}>
                        ... and {capabilityData.dataCollection.measurements.length - 10} more measurements
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Analysis Settings Section */}
          <div className={styles.analysisSettingsCard}>
            <div className={styles.sectionHeader}>
              <h2>Analysis Settings</h2>
            </div>

            <div className={styles.analysisSettingsGrid}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Confidence Level</label>
                <select
                  className={styles.selectInput}
                  value={capabilityData.analysisSettings.confidenceLevel}
                  onChange={(e) => handleAnalysisSettingsChange('confidenceLevel', parseInt(e.target.value))}
                >
                  <option value={90}>90%</option>
                  <option value={95}>95%</option>
                  <option value={99}>99%</option>
                </select>
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Data Transformation</label>
                <select
                  className={styles.selectInput}
                  value={capabilityData.analysisSettings.transformation}
                  onChange={(e) => handleAnalysisSettingsChange('transformation', e.target.value)}
                >
                  <option value="none">None</option>
                  <option value="log">Natural Log</option>
                  <option value="sqrt">Square Root</option>
                  <option value="box-cox">Box-Cox</option>
                </select>
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Outlier Handling</label>
                <select
                  className={styles.selectInput}
                  value={capabilityData.analysisSettings.outlierHandling}
                  onChange={(e) => handleAnalysisSettingsChange('outlierHandling', e.target.value)}
                >
                  <option value="include">Include All Data</option>
                  <option value="exclude">Exclude Outliers</option>
                  <option value="investigate">Investigate Outliers</option>
                </select>
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.checkboxLabel}>
                  <input
                    type="checkbox"
                    checked={capabilityData.analysisSettings.assumeNormality}
                    onChange={(e) => handleAnalysisSettingsChange('assumeNormality', e.target.checked)}
                  />
                  Assume Normal Distribution
                </label>
              </div>
            </div>

            <div className={styles.analysisActions}>
              <button
                className={styles.calculateBtn}
                onClick={calculateCapability}
                disabled={capabilityData.dataCollection.measurements.length === 0}
              >
                <i className="fas fa-calculator"></i> Calculate Capability
              </button>
            </div>
          </div>

          {/* Results Section */}
          <div className={styles.resultsCard}>
            <div className={styles.sectionHeader}>
              <h2>Analysis Results</h2>
            </div>

            {capabilityData.dataCollection.measurements.length > 0 ? (
              <div className={styles.resultsContent}>
                {/* Capability Indices */}
                <div className={styles.capabilityIndices}>
                  <h3>Capability Indices</h3>
                  <div className={styles.indicesGrid}>
                    <div className={styles.indexCard}>
                      <h4>Cp</h4>
                      <div className={styles.indexValue}>{capabilityData.results.capabilityIndices.cp}</div>
                      <div className={styles.indexDescription}>Potential Capability</div>
                    </div>
                    <div className={styles.indexCard}>
                      <h4>Cpk</h4>
                      <div className={styles.indexValue}>{capabilityData.results.capabilityIndices.cpk}</div>
                      <div className={styles.indexDescription}>Actual Capability</div>
                    </div>
                    <div className={styles.indexCard}>
                      <h4>Pp</h4>
                      <div className={styles.indexValue}>{capabilityData.results.capabilityIndices.pp}</div>
                      <div className={styles.indexDescription}>Process Performance</div>
                    </div>
                    <div className={styles.indexCard}>
                      <h4>Ppk</h4>
                      <div className={styles.indexValue}>{capabilityData.results.capabilityIndices.ppk}</div>
                      <div className={styles.indexDescription}>Process Performance Index</div>
                    </div>
                  </div>
                </div>

                {/* Process Performance */}
                <div className={styles.processPerformance}>
                  <h3>Process Performance</h3>
                  <div className={styles.performanceGrid}>
                    <div className={styles.performanceCard}>
                      <h4>Yield</h4>
                      <div className={styles.performanceValue}>
                        {capabilityData.results.processPerformance.processYield}%
                      </div>
                    </div>
                    <div className={styles.performanceCard}>
                      <h4>Defect Rate</h4>
                      <div className={styles.performanceValue}>
                        {capabilityData.results.processPerformance.defectRate}%
                      </div>
                    </div>
                    <div className={styles.performanceCard}>
                      <h4>Sigma Level</h4>
                      <div className={styles.performanceValue}>
                        {capabilityData.results.processPerformance.sigmaLevel}σ
                      </div>
                    </div>
                    <div className={styles.performanceCard}>
                      <h4>PPM Defects</h4>
                      <div className={styles.performanceValue}>{capabilityData.results.processPerformance.ppm}</div>
                    </div>
                  </div>
                </div>

                {/* Descriptive Statistics */}
                <div className={styles.descriptiveStats}>
                  <h3>Descriptive Statistics</h3>
                  <div className={styles.statsGrid}>
                    <div className={styles.statItem}>
                      <span className={styles.statLabel}>Mean:</span>
                      <span className={styles.statValue}>{capabilityData.results.descriptiveStats.mean}</span>
                    </div>
                    <div className={styles.statItem}>
                      <span className={styles.statLabel}>Std Dev:</span>
                      <span className={styles.statValue}>{capabilityData.results.descriptiveStats.stdDev}</span>
                    </div>
                    <div className={styles.statItem}>
                      <span className={styles.statLabel}>Minimum:</span>
                      <span className={styles.statValue}>{capabilityData.results.descriptiveStats.minimum}</span>
                    </div>
                    <div className={styles.statItem}>
                      <span className={styles.statLabel}>Maximum:</span>
                      <span className={styles.statValue}>{capabilityData.results.descriptiveStats.maximum}</span>
                    </div>
                    <div className={styles.statItem}>
                      <span className={styles.statLabel}>Range:</span>
                      <span className={styles.statValue}>{capabilityData.results.descriptiveStats.range}</span>
                    </div>
                    <div className={styles.statItem}>
                      <span className={styles.statLabel}>Median:</span>
                      <span className={styles.statValue}>{capabilityData.results.descriptiveStats.median}</span>
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <div className={styles.emptyResults}>
                <i className="fas fa-chart-bar"></i>
                <p>Add measurement data and click "Calculate Capability" to see analysis results.</p>
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className={styles.footer}>
          <div className={styles.footerContent}>
            <div className={styles.completionStatus}>
              <i className="fas fa-check-circle"></i>
              <span>Capability Study {completionPercentage}% Complete</span>
            </div>
            <div className={styles.footerActions}>
              <button className={styles.secondaryBtn}>
                <i className="fas fa-eye"></i> Preview Report
              </button>
              <button className={styles.primaryBtn} disabled={completionPercentage < 80}>
                <i className="fas fa-check"></i> Complete Study
              </button>
            </div>
          </div>
        </div>
      </div>
    </ResourcePageWrapper>
  );
};

export default CapabilityAnalysis;
