import React, { useState, useEffect } from 'react';
import { useAdminSettings } from '../context/AdminContext';
import ResourcePageWrapper from '../../All/components/ResourcePageWrapper';
import styles from './StandardWork.module.css';

const StandardWork = () => {
  const { adminSettings } = useAdminSettings();

  // Standard Work data structure
  const [standardWorkData, setStandardWorkData] = useState({
    processName: '',
    workStationName: '',
    documentOwner: '',
    dateCreated: new Date().toISOString().split('T')[0],
    lastUpdated: new Date().toISOString().split('T')[0],
    version: '1.0',
    
    // Process overview
    processOverview: {
      processDescription: '',
      processScope: '',
      workStationLocation: '',
      shiftPattern: '',
      cycleTime: '',
      taktTime: '',
      processOwner: '',
      teamMembers: ''
    },
    
    // Work sequence
    workSequence: [
      {
        id: 1,
        stepNumber: 1,
        stepDescription: '',
        keyPoints: '',
        safetyRequirements: '',
        qualityChecks: '',
        timeAllocation: '',
        tools: '',
        materials: '',
        skillLevel: 'basic'
      }
    ],
    
    // Quality standards
    qualityStandards: {
      qualityObjectives: '',
      acceptanceCriteria: [],
      inspectionPoints: [],
      defectPrevention: '',
      qualityTools: '',
      documentationRequirements: ''
    },
    
    // Safety requirements
    safetyRequirements: {
      safetyObjectives: '',
      hazardIdentification: [],
      personalProtectiveEquipment: [],
      safetyProcedures: '',
      emergencyProcedures: '',
      safetyTraining: ''
    },
    
    // Tools and equipment
    toolsEquipment: {
      requiredTools: [],
      equipmentSpecifications: [],
      maintenanceRequirements: '',
      calibrationSchedule: '',
      toolManagement: '',
      backupEquipment: ''
    },
    
    // Materials and supplies
    materialsSupplies: {
      requiredMaterials: [],
      materialSpecifications: [],
      inventoryManagement: '',
      supplierRequirements: '',
      storageRequirements: '',
      wasteManagement: ''
    },
    
    // Training and competency
    trainingCompetency: {
      skillRequirements: [],
      trainingProgram: '',
      competencyAssessment: '',
      certificationRequirements: '',
      refresherTraining: '',
      crossTraining: ''
    },
    
    // Performance metrics
    performanceMetrics: {
      productivityMetrics: [],
      qualityMetrics: [],
      safetyMetrics: [],
      efficiencyMetrics: [],
      targetPerformance: '',
      measurementFrequency: ''
    },
    
    // Continuous improvement
    continuousImprovement: {
      improvementOpportunities: '',
      suggestionSystem: '',
      kaizen: '',
      lessonsLearned: '',
      bestPractices: '',
      changeManagement: ''
    },
    
    // Document control
    documentControl: {
      approvalWorkflow: '',
      distributionList: '',
      revisionHistory: [],
      documentLocation: '',
      accessControl: '',
      archivePolicy: ''
    },
    
    // Standard work status
    status: {
      implementationStatus: 'draft',
      approvalDate: '',
      approvedBy: '',
      implementationDate: '',
      nextReviewDate: '',
      effectiveness: '',
      compliance: '',
      issues: '',
      improvements: ''
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
      if (standardWorkData.processName) completedFields++;
      if (standardWorkData.workStationName) completedFields++;
      if (standardWorkData.documentOwner) completedFields++;

      // Process overview
      totalFields += 4;
      if (standardWorkData.processOverview.processDescription) completedFields++;
      if (standardWorkData.processOverview.workStationLocation) completedFields++;
      if (standardWorkData.processOverview.cycleTime) completedFields++;
      if (standardWorkData.processOverview.processOwner) completedFields++;

      // Work sequence
      totalFields += 1;
      const hasCompleteStep = standardWorkData.workSequence.some(step => 
        step.stepDescription && step.keyPoints && step.timeAllocation
      );
      if (hasCompleteStep) completedFields++;

      // Quality standards
      totalFields += 2;
      if (standardWorkData.qualityStandards.qualityObjectives) completedFields++;
      if (standardWorkData.qualityStandards.acceptanceCriteria.length > 0) completedFields++;

      // Safety requirements
      totalFields += 2;
      if (standardWorkData.safetyRequirements.safetyObjectives) completedFields++;
      if (standardWorkData.safetyRequirements.hazardIdentification.length > 0) completedFields++;

      // Tools and equipment
      totalFields += 1;
      if (standardWorkData.toolsEquipment.requiredTools.length > 0) completedFields++;

      // Training
      totalFields += 1;
      if (standardWorkData.trainingCompetency.skillRequirements.length > 0) completedFields++;

      // Performance metrics
      totalFields += 1;
      if (standardWorkData.performanceMetrics.productivityMetrics.length > 0) completedFields++;

      const percentage = totalFields > 0 ? Math.round((completedFields / totalFields) * 100) : 0;
      setCompletionPercentage(percentage);
    };

    calculateCompletion();
  }, [standardWorkData]);

  // Handle field changes
  const handleBasicInfoChange = (field, value) => {
    setStandardWorkData(prev => ({
      ...prev,
      [field]: value,
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleOverviewChange = (field, value) => {
    setStandardWorkData(prev => ({
      ...prev,
      processOverview: {
        ...prev.processOverview,
        [field]: value
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleWorkStepChange = (stepId, field, value) => {
    setStandardWorkData(prev => ({
      ...prev,
      workSequence: prev.workSequence.map(step =>
        step.id === stepId ? { ...step, [field]: value } : step
      ),
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleQualityChange = (field, value) => {
    setStandardWorkData(prev => ({
      ...prev,
      qualityStandards: {
        ...prev.qualityStandards,
        [field]: value
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleSafetyChange = (field, value) => {
    setStandardWorkData(prev => ({
      ...prev,
      safetyRequirements: {
        ...prev.safetyRequirements,
        [field]: value
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleToolsChange = (field, value) => {
    setStandardWorkData(prev => ({
      ...prev,
      toolsEquipment: {
        ...prev.toolsEquipment,
        [field]: value
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleTrainingChange = (field, value) => {
    setStandardWorkData(prev => ({
      ...prev,
      trainingCompetency: {
        ...prev.trainingCompetency,
        [field]: value
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleMetricsChange = (field, value) => {
    setStandardWorkData(prev => ({
      ...prev,
      performanceMetrics: {
        ...prev.performanceMetrics,
        [field]: value
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleStatusChange = (field, value) => {
    setStandardWorkData(prev => ({
      ...prev,
      status: {
        ...prev.status,
        [field]: value
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Add new work step
  const addWorkStep = () => {
    const newStep = {
      id: Date.now(),
      stepNumber: standardWorkData.workSequence.length + 1,
      stepDescription: '',
      keyPoints: '',
      safetyRequirements: '',
      qualityChecks: '',
      timeAllocation: '',
      tools: '',
      materials: '',
      skillLevel: 'basic'
    };
    
    setStandardWorkData(prev => ({
      ...prev,
      workSequence: [...prev.workSequence, newStep],
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Remove work step
  const removeWorkStep = (stepId) => {
    if (standardWorkData.workSequence.length > 1) {
      setStandardWorkData(prev => ({
        ...prev,
        workSequence: prev.workSequence
          .filter(step => step.id !== stepId)
          .map((step, index) => ({ ...step, stepNumber: index + 1 })),
        lastUpdated: new Date().toISOString().split('T')[0]
      }));
    }
  };

  // Acceptance criteria
  const addAcceptanceCriteria = () => {
    const newCriteria = {
      id: Date.now(),
      criteria: '',
      specification: '',
      measurement: '',
      frequency: ''
    };
    
    setStandardWorkData(prev => ({
      ...prev,
      qualityStandards: {
        ...prev.qualityStandards,
        acceptanceCriteria: [...prev.qualityStandards.acceptanceCriteria, newCriteria]
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const removeAcceptanceCriteria = (criteriaId) => {
    setStandardWorkData(prev => ({
      ...prev,
      qualityStandards: {
        ...prev.qualityStandards,
        acceptanceCriteria: prev.qualityStandards.acceptanceCriteria.filter(c => c.id !== criteriaId)
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleAcceptanceCriteriaChange = (criteriaId, field, value) => {
    setStandardWorkData(prev => ({
      ...prev,
      qualityStandards: {
        ...prev.qualityStandards,
        acceptanceCriteria: prev.qualityStandards.acceptanceCriteria.map(c =>
          c.id === criteriaId ? { ...c, [field]: value } : c
        )
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Hazard
  const addHazard = () => {
    const newHazard = {
      id: Date.now(),
      hazard: '',
      risk: '',
      control: '',
      ppe: ''
    };
    
    setStandardWorkData(prev => ({
      ...prev,
      safetyRequirements: {
        ...prev.safetyRequirements,
        hazardIdentification: [...prev.safetyRequirements.hazardIdentification, newHazard]
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const removeHazard = (hazardId) => {
    setStandardWorkData(prev => ({
      ...prev,
      safetyRequirements: {
        ...prev.safetyRequirements,
        hazardIdentification: prev.safetyRequirements.hazardIdentification.filter(h => h.id !== hazardId)
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleHazardChange = (hazardId, field, value) => {
    setStandardWorkData(prev => ({
      ...prev,
      safetyRequirements: {
        ...prev.safetyRequirements,
        hazardIdentification: prev.safetyRequirements.hazardIdentification.map(h =>
          h.id === hazardId ? { ...h, [field]: value } : h
        )
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Tools
  const addTool = () => {
    const newTool = {
      id: Date.now(),
      name: '',
      specification: '',
      quantity: '',
      location: ''
    };
    
    setStandardWorkData(prev => ({
      ...prev,
      toolsEquipment: {
        ...prev.toolsEquipment,
        requiredTools: [...prev.toolsEquipment.requiredTools, newTool]
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const removeTool = (toolId) => {
    setStandardWorkData(prev => ({
      ...prev,
      toolsEquipment: {
        ...prev.toolsEquipment,
        requiredTools: prev.toolsEquipment.requiredTools.filter(t => t.id !== toolId)
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleToolChange = (toolId, field, value) => {
    setStandardWorkData(prev => ({
      ...prev,
      toolsEquipment: {
        ...prev.toolsEquipment,
        requiredTools: prev.toolsEquipment.requiredTools.map(t =>
          t.id === toolId ? { ...t, [field]: value } : t
        )
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Training
  const addSkillRequirement = () => {
    const newSkill = {
      id: Date.now(),
      skill: '',
      level: 'basic',
      training: '',
      assessment: ''
    };
    
    setStandardWorkData(prev => ({
      ...prev,
      trainingCompetency: {
        ...prev.trainingCompetency,
        skillRequirements: [...prev.trainingCompetency.skillRequirements, newSkill]
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const removeSkillRequirement = (skillId) => {
    setStandardWorkData(prev => ({
      ...prev,
      trainingCompetency: {
        ...prev.trainingCompetency,
        skillRequirements: prev.trainingCompetency.skillRequirements.filter(s => s.id !== skillId)
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleSkillRequirementChange = (skillId, field, value) => {
    setStandardWorkData(prev => ({
      ...prev,
      trainingCompetency: {
        ...prev.trainingCompetency,
        skillRequirements: prev.trainingCompetency.skillRequirements.map(s =>
          s.id === skillId ? { ...s, [field]: value } : s
        )
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Metrics
  const addMetric = (type) => {
    const newMetric = {
      id: Date.now(),
      name: '',
      target: '',
      measurement: '',
      frequency: ''
    };
    
    setStandardWorkData(prev => ({
      ...prev,
      performanceMetrics: {
        ...prev.performanceMetrics,
        [type]: [...prev.performanceMetrics[type], newMetric]
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const removeMetric = (type, metricId) => {
    setStandardWorkData(prev => ({
      ...prev,
      performanceMetrics: {
        ...prev.performanceMetrics,
        [type]: prev.performanceMetrics[type].filter(m => m.id !== metricId)
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleMetricChange = (type, metricId, field, value) => {
    setStandardWorkData(prev => ({
      ...prev,
      performanceMetrics: {
        ...prev.performanceMetrics,
        [type]: prev.performanceMetrics[type].map(m =>
          m.id === metricId ? { ...m, [field]: value } : m
        )
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Sample data
  const generateSampleData = () => {
    const sampleData = {
      processOverview: {
        processDescription: 'Assembly process for automotive brake components with critical safety and quality requirements',
        processScope: 'From component preparation through final assembly, testing, and packaging',
        workStationLocation: 'Assembly Line Station 3, Building A',
        shiftPattern: '3 shifts, 8 hours each (6:00-14:00, 14:00-22:00, 22:00-6:00)',
        cycleTime: '45 seconds per unit',
        taktTime: '50 seconds per unit',
        processOwner: 'Assembly Supervisor',
        teamMembers: 'Assembly operators (3), Quality inspector (1), Team leader (1)'
      },
      workSequence: [
        {
          id: 1,
          stepNumber: 1,
          stepDescription: 'Retrieve brake caliper housing from incoming parts rack',
          keyPoints: 'Check part number matches work order, inspect for damage, verify cleanliness',
          safetyRequirements: 'Wear safety glasses, use proper lifting technique',
          qualityChecks: 'Visual inspection for cracks, dents, or contamination',
          timeAllocation: '8 seconds',
          tools: 'None required',
          materials: 'Brake caliper housing (P/N: BC-2024-A)',
          skillLevel: 'basic'
        },
        {
          id: 2,
          stepNumber: 2,
          stepDescription: 'Install brake pads into caliper housing',
          keyPoints: 'Ensure correct orientation, apply specified torque, verify proper seating',
          safetyRequirements: 'Wear cut-resistant gloves, use torque wrench properly',
          qualityChecks: 'Check pad alignment, verify torque specification (25 Nm ± 2)',
          timeAllocation: '15 seconds',
          tools: 'Torque wrench (10-30 Nm), alignment fixture',
          materials: 'Brake pads (P/N: BP-2024-A), thread locker',
          skillLevel: 'intermediate'
        },
        {
          id: 3,
          stepNumber: 3,
          stepDescription: 'Perform final quality inspection and testing',
          keyPoints: 'Complete dimensional check, function test, documentation',
          safetyRequirements: 'Follow lockout/tagout procedures for test equipment',
          qualityChecks: 'Dimensional verification, function test pass/fail, traceability',
          timeAllocation: '12 seconds',
          tools: 'Go/No-go gauge, test fixture, scanner',
          materials: 'Quality checklist, traceability label',
          skillLevel: 'intermediate'
        }
      ],
      qualityStandards: {
        qualityObjectives: 'Zero defects to customer, 99.5% first pass yield, full traceability',
        acceptanceCriteria: [
          { id: 1, criteria: 'Brake pad alignment', specification: 'Within ±0.5mm of centerline', measurement: 'Go/No-go gauge', frequency: 'Every unit' },
          { id: 2, criteria: 'Torque specification', specification: '25 Nm ± 2 Nm', measurement: 'Torque wrench verification', frequency: 'Every unit' },
          { id: 3, criteria: 'Function test', specification: 'Smooth operation, no binding', measurement: 'Manual operation test', frequency: 'Every unit' }
        ]
      },
      safetyRequirements: {
        safetyObjectives: 'Zero injuries, full compliance with safety procedures, proactive hazard identification',
        hazardIdentification: [
          { id: 1, hazard: 'Sharp edges on brake components', risk: 'Cuts and lacerations', control: 'Cut-resistant gloves, proper handling technique', ppe: 'Cut-resistant gloves (Level 3)' },
          { id: 2, hazard: 'Repetitive motion', risk: 'Ergonomic strain', control: 'Job rotation, ergonomic workstation design', ppe: 'Ergonomic support tools' },
          { id: 3, hazard: 'Torque wrench operation', risk: 'Hand/wrist strain', control: 'Proper technique training, tool maintenance', ppe: 'Wrist support if needed' }
        ]
      },
      toolsEquipment: {
        requiredTools: [
          { id: 1, name: 'Torque wrench', specification: '10-30 Nm range, ±2% accuracy', quantity: '1 per station', location: 'Tool shadow board' },
          { id: 2, name: 'Go/No-go gauge', specification: 'Brake pad alignment gauge BP-2024', quantity: '1 per station', location: 'Quality station' },
          { id: 3, name: 'Alignment fixture', specification: 'Brake caliper fixture BC-2024-F', quantity: '1 per station', location: 'Workstation fixture mount' }
        ]
      },
      trainingCompetency: {
        skillRequirements: [
          { id: 1, skill: 'Torque wrench operation', level: 'intermediate', training: '4-hour hands-on training with certification', assessment: 'Practical demonstration and written test' },
          { id: 2, skill: 'Quality inspection', level: 'intermediate', training: '8-hour quality training program', assessment: 'Quality audit and defect identification test' },
          { id: 3, skill: 'Safety procedures', level: 'basic', training: '2-hour safety orientation', assessment: 'Safety quiz and procedure demonstration' }
        ]
      },
      performanceMetrics: {
        productivityMetrics: [
          { id: 1, name: 'Cycle Time', target: '45 seconds per unit', measurement: 'Automated timing system', frequency: 'Continuous' },
          { id: 2, name: 'Units per Hour', target: '72 units per hour', measurement: 'Production counter', frequency: 'Hourly' }
        ],
        qualityMetrics: [
          { id: 1, name: 'First Pass Yield', target: '≥ 99.5%', measurement: 'Good units / Total units', frequency: 'Daily' },
          { id: 2, name: 'Defect Rate', target: '< 500 PPM', measurement: 'Defects / Million opportunities', frequency: 'Weekly' }
        ]
      }
    };

    setStandardWorkData(prev => ({
      ...prev,
      processOverview: sampleData.processOverview,
      workSequence: sampleData.workSequence,
      qualityStandards: sampleData.qualityStandards,
      safetyRequirements: sampleData.safetyRequirements,
      toolsEquipment: sampleData.toolsEquipment,
      trainingCompetency: sampleData.trainingCompetency,
      performanceMetrics: sampleData.performanceMetrics,
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  return (
    <ResourcePageWrapper
      pageName="Standard Work"
      toolName="standard-work"
      adminSettings={adminSettings}
    >
      <div className={styles.standardWorkContainer}>
        {/* Header */}
        <div className={styles.header}>
          <div className={styles.headerContent}>
            <h1>Standard Work</h1>
            <div className={styles.progressSection}>
              <div className={styles.progressBar}>
                <div 
                  className={styles.progressFill} 
                  style={{ width: `${completionPercentage}%`, backgroundColor: '#0b1d3a' }}
                ></div>
              </div>
              <span className={styles.progressText}>{completionPercentage}% Complete</span>
            </div>
          </div>
          <div className={styles.headerActions}>
              <button className={styles.saveBtn}>
                <i className="fas fa-save"></i> Save Draft
              </button>
              <button className={styles.exportBtn} onClick={generateSampleData}>
                <i className="fas fa-database"></i> Load Sample
              </button>
              <button className={styles.exportBtn}>
                <i className="fas fa-download"></i> Export PDF
              </button>
          </div>
        </div>

        {/* Main Content */}
        <div className={styles.mainContent}>
          {/* Analysis Information (full width; chat removed) */}
          <div className={styles.processInfoCard}>
            <h2>Standard Work Information</h2>
            
            <div className={styles.fieldRow}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Process Name <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={standardWorkData.processName}
                  onChange={(e) => handleBasicInfoChange('processName', e.target.value)}
                  placeholder="Enter process name"
                />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Work Station Name <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={standardWorkData.workStationName}
                  onChange={(e) => handleBasicInfoChange('workStationName', e.target.value)}
                  placeholder="Enter work station name"
                />
              </div>
            </div>

            <div className={styles.fieldRow}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Document Owner <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={standardWorkData.documentOwner}
                  onChange={(e) => handleBasicInfoChange('documentOwner', e.target.value)}
                  placeholder="Enter document owner"
                />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Version</label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={standardWorkData.version}
                  onChange={(e) => handleBasicInfoChange('version', e.target.value)}
                  placeholder="e.g., 1.0"
                />
              </div>
            </div>

            <div className={styles.fieldRow}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Date Created</label>
                <input
                  type="date"
                  className={styles.textInput}
                  value={standardWorkData.dateCreated}
                  onChange={(e) => handleBasicInfoChange('dateCreated', e.target.value)}
                />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Last Updated</label>
                <input
                  type="date"
                  className={styles.textInput}
                  value={standardWorkData.lastUpdated}
                  onChange={(e) => handleBasicInfoChange('lastUpdated', e.target.value)}
                />
              </div>
            </div>
          </div>

          {/* Process Overview Card */}
          <div className={styles.overviewCard}>
            <div className={styles.sectionHeader}>
              <h2>Process Overview</h2>
              <button className={styles.generateBtn} onClick={generateSampleData}>
                Generate Sample Data
              </button>
            </div>
            
            <div className={styles.overviewGrid}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Process Description <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={standardWorkData.processOverview.processDescription}
                  onChange={(e) => handleOverviewChange('processDescription', e.target.value)}
                  placeholder="Describe the process being standardized"
                  rows="3"
                />
              </div>
              
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Process Scope</label>
                  <textarea
                    className={styles.textareaInput}
                    value={standardWorkData.processOverview.processScope}
                    onChange={(e) => handleOverviewChange('processScope', e.target.value)}
                    placeholder="Define the scope of the process"
                    rows="2"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Work Station Location</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={standardWorkData.processOverview.workStationLocation}
                    onChange={(e) => handleOverviewChange('workStationLocation', e.target.value)}
                    placeholder="Physical location of work station"
                  />
                </div>
              </div>
              
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Shift Pattern</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={standardWorkData.processOverview.shiftPattern}
                    onChange={(e) => handleOverviewChange('shiftPattern', e.target.value)}
                    placeholder="e.g., 3 shifts, 8 hours each"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Cycle Time</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={standardWorkData.processOverview.cycleTime}
                    onChange={(e) => handleOverviewChange('cycleTime', e.target.value)}
                    placeholder="e.g., 45 seconds per unit"
                  />
                </div>
              </div>
              
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Takt Time</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={standardWorkData.processOverview.taktTime}
                    onChange={(e) => handleOverviewChange('taktTime', e.target.value)}
                    placeholder="e.g., 50 seconds per unit"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Process Owner</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={standardWorkData.processOverview.processOwner}
                    onChange={(e) => handleOverviewChange('processOwner', e.target.value)}
                    placeholder="Process owner name"
                  />
                </div>
              </div>
              
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Team Members</label>
                <textarea
                  className={styles.textareaInput}
                  value={standardWorkData.processOverview.teamMembers}
                  onChange={(e) => handleOverviewChange('teamMembers', e.target.value)}
                  placeholder="Key team members and roles"
                  rows="2"
                />
              </div>
            </div>
          </div>

          {/* Work Sequence Card */}
          <div className={styles.workSequenceCard}>
            <div className={styles.sectionHeader}>
              <h2>Work Sequence</h2>
              <button className={styles.addBtn} onClick={addWorkStep}>
                Add Work Step
              </button>
            </div>
            
            <div className={styles.workSequenceGrid}>
              {standardWorkData.workSequence.map((step) => (
                <div key={step.id} className={styles.workStepCard}>
                  <div className={styles.workStepHeader}>
                    <h3>Step {step.stepNumber}</h3>
                    <div className={styles.workStepActions}>
                      <span className={`${styles.skillBadge} ${styles[step.skillLevel]}`}>
                        {step.skillLevel}
                      </span>
                      {standardWorkData.workSequence.length > 1 && (
                        <button 
                          className={styles.removeBtn}
                          onClick={() => removeWorkStep(step.id)}
                        >
                          Remove
                        </button>
                      )}
                    </div>
                  </div>
                  
                  <div className={styles.workStepFields}>
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Step Description</label>
                      <textarea
                        className={styles.textareaInput}
                        value={step.stepDescription}
                        onChange={(e) => handleWorkStepChange(step.id, 'stepDescription', e.target.value)}
                        placeholder="Describe what is done in this step"
                        rows="2"
                      />
                    </div>
                    
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Key Points</label>
                      <textarea
                        className={styles.textareaInput}
                        value={step.keyPoints}
                        onChange={(e) => handleWorkStepChange(step.id, 'keyPoints', e.target.value)}
                        placeholder="Critical points for success"
                        rows="2"
                      />
                    </div>
                    
                    <div className={styles.fieldRow}>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Time Allocation</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={step.timeAllocation}
                          onChange={(e) => handleWorkStepChange(step.id, 'timeAllocation', e.target.value)}
                          placeholder="e.g., 15 seconds"
                        />
                      </div>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Skill Level</label>
                        <select
                          className={styles.selectInput}
                          value={step.skillLevel}
                          onChange={(e) => handleWorkStepChange(step.id, 'skillLevel', e.target.value)}
                        >
                          <option value="basic">Basic</option>
                          <option value="intermediate">Intermediate</option>
                          <option value="advanced">Advanced</option>
                          <option value="expert">Expert</option>
                        </select>
                      </div>
                    </div>
                    
                    <div className={styles.fieldRow}>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Tools Required</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={step.tools}
                          onChange={(e) => handleWorkStepChange(step.id, 'tools', e.target.value)}
                          placeholder="Tools needed for this step"
                        />
                      </div>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Materials</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={step.materials}
                          onChange={(e) => handleWorkStepChange(step.id, 'materials', e.target.value)}
                          placeholder="Materials used in this step"
                        />
                      </div>
                    </div>
                    
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Safety Requirements</label>
                      <textarea
                        className={styles.textareaInput}
                        value={step.safetyRequirements}
                        onChange={(e) => handleWorkStepChange(step.id, 'safetyRequirements', e.target.value)}
                        placeholder="Safety requirements for this step"
                        rows="2"
                      />
                    </div>
                    
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Quality Checks</label>
                      <textarea
                        className={styles.textareaInput}
                        value={step.qualityChecks}
                        onChange={(e) => handleWorkStepChange(step.id, 'qualityChecks', e.target.value)}
                        placeholder="Quality checks for this step"
                        rows="2"
                      />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Quality Standards Card */}
          <div className={styles.qualityCard}>
            <div className={styles.sectionHeader}>
              <h2>Quality Standards</h2>
              <button className={styles.addBtn} onClick={addAcceptanceCriteria}>
                Add Acceptance Criteria
              </button>
            </div>
            
            <div className={styles.qualityGrid}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Quality Objectives</label>
                <textarea
                  className={styles.textareaInput}
                  value={standardWorkData.qualityStandards.qualityObjectives}
                  onChange={(e) => handleQualityChange('qualityObjectives', e.target.value)}
                  placeholder="Overall quality objectives for this process"
                  rows="2"
                />
              </div>
              
              <div className={styles.acceptanceCriteriaSection}>
                <h3>Acceptance Criteria</h3>
                <div className={styles.criteriaGrid}>
                  {standardWorkData.qualityStandards.acceptanceCriteria.map((criteria) => (
                    <div key={criteria.id} className={styles.criteriaCard}>
                      <div className={styles.criteriaHeader}>
                        <h4>{criteria.criteria || 'New Criteria'}</h4>
                        <button 
                          className={styles.removeBtn}
                          onClick={() => removeAcceptanceCriteria(criteria.id)}
                        >
                          Remove
                        </button>
                      </div>
                      
                      <div className={styles.criteriaFields}>
                        <div className={styles.fieldRow}>
                          <div className={styles.fieldGroup}>
                            <label className={styles.fieldLabel}>Criteria</label>
                            <input
                              type="text"
                              className={styles.textInput}
                              value={criteria.criteria}
                              onChange={(e) => handleAcceptanceCriteriaChange(criteria.id, 'criteria', e.target.value)}
                              placeholder="e.g., Dimensional accuracy"
                            />
                          </div>
                          <div className={styles.fieldGroup}>
                            <label className={styles.fieldLabel}>Specification</label>
                            <input
                              type="text"
                              className={styles.textInput}
                              value={criteria.specification}
                              onChange={(e) => handleAcceptanceCriteriaChange(criteria.id, 'specification', e.target.value)}
                              placeholder="e.g., ±0.1mm"
                            />
                          </div>
                        </div>
                        
                        <div className={styles.fieldRow}>
                          <div className={styles.fieldGroup}>
                            <label className={styles.fieldLabel}>Measurement Method</label>
                            <input
                              type="text"
                              className={styles.textInput}
                              value={criteria.measurement}
                              onChange={(e) => handleAcceptanceCriteriaChange(criteria.id, 'measurement', e.target.value)}
                              placeholder="How is this measured?"
                            />
                          </div>
                          <div className={styles.fieldGroup}>
                            <label className={styles.fieldLabel}>Frequency</label>
                            <input
                              type="text"
                              className={styles.textInput}
                              value={criteria.frequency}
                              onChange={(e) => handleAcceptanceCriteriaChange(criteria.id, 'frequency', e.target.value)}
                              placeholder="How often?"
                            />
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* Safety Requirements Card */}
          <div className={styles.safetyCard}>
            <div className={styles.sectionHeader}>
              <h2>Safety Requirements</h2>
              <button className={styles.addBtn} onClick={addHazard}>
                Add Hazard
              </button>
            </div>
            
            <div className={styles.safetyGrid}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Safety Objectives</label>
                <textarea
                  className={styles.textareaInput}
                  value={standardWorkData.safetyRequirements.safetyObjectives}
                  onChange={(e) => handleSafetyChange('safetyObjectives', e.target.value)}
                  placeholder="Overall safety objectives for this process"
                  rows="2"
                />
              </div>
              
              <div className={styles.hazardSection}>
                <h3>Hazard Identification</h3>
                <div className={styles.hazardGrid}>
                  {standardWorkData.safetyRequirements.hazardIdentification.map((hazard) => (
                    <div key={hazard.id} className={styles.hazardCard}>
                      <div className={styles.hazardHeader}>
                        <h4>{hazard.hazard || 'New Hazard'}</h4>
                        <button 
                          className={styles.removeBtn}
                          onClick={() => removeHazard(hazard.id)}
                        >
                          Remove
                        </button>
                      </div>
                      
                      <div className={styles.hazardFields}>
                        <div className={styles.fieldRow}>
                          <div className={styles.fieldGroup}>
                            <label className={styles.fieldLabel}>Hazard</label>
                            <input
                              type="text"
                              className={styles.textInput}
                              value={hazard.hazard}
                              onChange={(e) => handleHazardChange(hazard.id, 'hazard', e.target.value)}
                              placeholder="e.g., Sharp edges"
                            />
                          </div>
                          <div className={styles.fieldGroup}>
                            <label className={styles.fieldLabel}>Risk</label>
                            <input
                              type="text"
                              className={styles.textInput}
                              value={hazard.risk}
                              onChange={(e) => handleHazardChange(hazard.id, 'risk', e.target.value)}
                              placeholder="e.g., Cuts and lacerations"
                            />
                          </div>
                        </div>
                        
                        <div className={styles.fieldRow}>
                          <div className={styles.fieldGroup}>
                            <label className={styles.fieldLabel}>Control Measures</label>
                            <input
                              type="text"
                              className={styles.textInput}
                              value={hazard.control}
                              onChange={(e) => handleHazardChange(hazard.id, 'control', e.target.value)}
                              placeholder="How is this controlled?"
                            />
                          </div>
                          <div className={styles.fieldGroup}>
                            <label className={styles.fieldLabel}>PPE Required</label>
                            <input
                              type="text"
                              className={styles.textInput}
                              value={hazard.ppe}
                              onChange={(e) => handleHazardChange(hazard.id, 'ppe', e.target.value)}
                              placeholder="Required PPE"
                            />
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* Tools and Equipment Card */}
          <div className={styles.toolsCard}>
            <div className={styles.sectionHeader}>
              <h2>Tools and Equipment</h2>
              <button className={styles.addBtn} onClick={addTool}>
                Add Tool
              </button>
            </div>
            
            <div className={styles.toolsGrid}>
              {standardWorkData.toolsEquipment.requiredTools.map((tool) => (
                <div key={tool.id} className={styles.toolCard}>
                  <div className={styles.toolHeader}>
                    <h3>{tool.name || 'New Tool'}</h3>
                    <button 
                      className={styles.removeBtn}
                      onClick={() => removeTool(tool.id)}
                    >
                      Remove
                    </button>
                  </div>
                  
                  <div className={styles.toolFields}>
                    <div className={styles.fieldRow}>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Tool Name</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={tool.name}
                          onChange={(e) => handleToolChange(tool.id, 'name', e.target.value)}
                          placeholder="e.g., Torque wrench"
                        />
                      </div>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Quantity</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={tool.quantity}
                          onChange={(e) => handleToolChange(tool.id, 'quantity', e.target.value)}
                          placeholder="e.g., 1 per station"
                        />
                      </div>
                    </div>
                    
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Specification</label>
                      <input
                        type="text"
                        className={styles.textInput}
                        value={tool.specification}
                        onChange={(e) => handleToolChange(tool.id, 'specification', e.target.value)}
                        placeholder="Tool specifications"
                      />
                    </div>
                    
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Location</label>
                      <input
                        type="text"
                        className={styles.textInput}
                        value={tool.location}
                        onChange={(e) => handleToolChange(tool.id, 'location', e.target.value)}
                        placeholder="Where is this tool located?"
                      />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Training and Competency Card */}
          <div className={styles.trainingCard}>
            <div className={styles.sectionHeader}>
              <h2>Training and Competency</h2>
              <button className={styles.addBtn} onClick={addSkillRequirement}>
                Add Skill Requirement
              </button>
            </div>
            
            <div className={styles.trainingGrid}>
              {standardWorkData.trainingCompetency.skillRequirements.map((skill) => (
                <div key={skill.id} className={styles.skillCard}>
                  <div className={styles.skillHeader}>
                    <h3>{skill.skill || 'New Skill'}</h3>
                    <div className={styles.skillActions}>
                      <span className={`${styles.skillBadge} ${styles[skill.level]}`}>
                        {skill.level}
                      </span>
                      <button 
                        className={styles.removeBtn}
                        onClick={() => removeSkillRequirement(skill.id)}
                      >
                        Remove
                      </button>
                    </div>
                  </div>
                  
                  <div className={styles.skillFields}>
                    <div className={styles.fieldRow}>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Skill</label>
                        <input
                          type="text"
                          className={styles.textInput}
                          value={skill.skill}
                          onChange={(e) => handleSkillRequirementChange(skill.id, 'skill', e.target.value)}
                          placeholder="e.g., Torque wrench operation"
                        />
                      </div>
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Level</label>
                        <select
                          className={styles.selectInput}
                          value={skill.level}
                          onChange={(e) => handleSkillRequirementChange(skill.id, 'level', e.target.value)}
                        >
                          <option value="basic">Basic</option>
                          <option value="intermediate">Intermediate</option>
                          <option value="advanced">Advanced</option>
                          <option value="expert">Expert</option>
                        </select>
                      </div>
                    </div>
                    
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Training Required</label>
                      <textarea
                        className={styles.textareaInput}
                        value={skill.training}
                        onChange={(e) => handleSkillRequirementChange(skill.id, 'training', e.target.value)}
                        placeholder="Training requirements"
                        rows="2"
                      />
                    </div>
                    
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Assessment Method</label>
                      <textarea
                        className={styles.textareaInput}
                        value={skill.assessment}
                        onChange={(e) => handleSkillRequirementChange(skill.id, 'assessment', e.target.value)}
                        placeholder="How is competency assessed?"
                        rows="2"
                      />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Performance Metrics Card */}
          <div className={styles.metricsCard}>
            <div className={styles.sectionHeader}>
              <h2>Performance Metrics</h2>
            </div>
            
            <div className={styles.metricsGrid}>
              {/* Productivity Metrics */}
              <div className={styles.metricSection}>
                <div className={styles.metricSectionHeader}>
                  <h3>Productivity Metrics</h3>
                  <button 
                    className={styles.addBtn}
                    onClick={() => addMetric('productivityMetrics')}
                  >
                    Add Metric
                  </button>
                </div>
                
                <div className={styles.metricCards}>
                  {standardWorkData.performanceMetrics.productivityMetrics.map((metric) => (
                    <div key={metric.id} className={styles.metricCard}>
                      <div className={styles.metricHeader}>
                        <h4>{metric.name || 'New Metric'}</h4>
                        <button 
                          className={styles.removeBtn}
                          onClick={() => removeMetric('productivityMetrics', metric.id)}
                        >
                          Remove
                        </button>
                      </div>
                      
                      <div className={styles.metricFields}>
                        <div className={styles.fieldRow}>
                          <div className={styles.fieldGroup}>
                            <label className={styles.fieldLabel}>Metric Name</label>
                            <input
                              type="text"
                              className={styles.textInput}
                              value={metric.name}
                              onChange={(e) => handleMetricChange('productivityMetrics', metric.id, 'name', e.target.value)}
                              placeholder="e.g., Cycle Time"
                            />
                          </div>
                          <div className={styles.fieldGroup}>
                            <label className={styles.fieldLabel}>Target</label>
                            <input
                              type="text"
                              className={styles.textInput}
                              value={metric.target}
                              onChange={(e) => handleMetricChange('productivityMetrics', metric.id, 'target', e.target.value)}
                              placeholder="e.g., 45 seconds"
                            />
                          </div>
                        </div>
                        
                        <div className={styles.fieldRow}>
                          <div className={styles.fieldGroup}>
                            <label className={styles.fieldLabel}>Measurement</label>
                            <input
                              type="text"
                              className={styles.textInput}
                              value={metric.measurement}
                              onChange={(e) => handleMetricChange('productivityMetrics', metric.id, 'measurement', e.target.value)}
                              placeholder="How is this measured?"
                            />
                          </div>
                          <div className={styles.fieldGroup}>
                            <label className={styles.fieldLabel}>Frequency</label>
                            <input
                              type="text"
                              className={styles.textInput}
                              value={metric.frequency}
                              onChange={(e) => handleMetricChange('productivityMetrics', metric.id, 'frequency', e.target.value)}
                              placeholder="How often?"
                            />
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Quality Metrics */}
              <div className={styles.metricSection}>
                <div className={styles.metricSectionHeader}>
                  <h3>Quality Metrics</h3>
                  <button 
                    className={styles.addBtn}
                    onClick={() => addMetric('qualityMetrics')}
                  >
                    Add Metric
                  </button>
                </div>
                
                <div className={styles.metricCards}>
                  {standardWorkData.performanceMetrics.qualityMetrics.map((metric) => (
                    <div key={metric.id} className={styles.metricCard}>
                      <div className={styles.metricHeader}>
                        <h4>{metric.name || 'New Metric'}</h4>
                        <button 
                          className={styles.removeBtn}
                          onClick={() => removeMetric('qualityMetrics', metric.id)}
                        >
                          Remove
                        </button>
                      </div>
                      
                      <div className={styles.metricFields}>
                        <div className={styles.fieldRow}>
                          <div className={styles.fieldGroup}>
                            <label className={styles.fieldLabel}>Metric Name</label>
                            <input
                              type="text"
                              className={styles.textInput}
                              value={metric.name}
                              onChange={(e) => handleMetricChange('qualityMetrics', metric.id, 'name', e.target.value)}
                              placeholder="e.g., First Pass Yield"
                            />
                          </div>
                          <div className={styles.fieldGroup}>
                            <label className={styles.fieldLabel}>Target</label>
                            <input
                              type="text"
                              className={styles.textInput}
                              value={metric.target}
                              onChange={(e) => handleMetricChange('qualityMetrics', metric.id, 'target', e.target.value)}
                              placeholder="e.g., ≥ 99.5%"
                            />
                          </div>
                        </div>
                        
                        <div className={styles.fieldRow}>
                          <div className={styles.fieldGroup}>
                            <label className={styles.fieldLabel}>Measurement</label>
                            <input
                              type="text"
                              className={styles.textInput}
                              value={metric.measurement}
                              onChange={(e) => handleMetricChange('qualityMetrics', metric.id, 'measurement', e.target.value)}
                              placeholder="How is this measured?"
                            />
                          </div>
                          <div className={styles.fieldGroup}>
                            <label className={styles.fieldLabel}>Frequency</label>
                            <input
                              type="text"
                              className={styles.textInput}
                              value={metric.frequency}
                              onChange={(e) => handleMetricChange('qualityMetrics', metric.id, 'frequency', e.target.value)}
                              placeholder="How often?"
                            />
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* Status Card */}
          <div className={styles.statusCard}>
            <div className={styles.sectionHeader}>
              <h2>Standard Work Status</h2>
            </div>
            
            <div className={styles.statusGrid}>
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Implementation Status</label>
                  <select
                    className={styles.selectInput}
                    value={standardWorkData.status.implementationStatus}
                    onChange={(e) => handleStatusChange('implementationStatus', e.target.value)}
                  >
                    <option value="draft">Draft</option>
                    <option value="approved">Approved</option>
                    <option value="implemented">Implemented</option>
                    <option value="active">Active</option>
                    <option value="under-review">Under Review</option>
                  </select>
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Effectiveness</label>
                  <select
                    className={styles.selectInput}
                    value={standardWorkData.status.effectiveness}
                    onChange={(e) => handleStatusChange('effectiveness', e.target.value)}
                  >
                    <option value="">Select effectiveness</option>
                    <option value="excellent">Excellent</option>
                    <option value="good">Good</option>
                    <option value="fair">Fair</option>
                    <option value="poor">Poor</option>
                  </select>
                </div>
              </div>
              
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Approved By</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={standardWorkData.status.approvedBy}
                    onChange={(e) => handleStatusChange('approvedBy', e.target.value)}
                    placeholder="Approver name"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Next Review Date</label>
                  <input
                    type="date"
                    className={styles.textInput}
                    value={standardWorkData.status.nextReviewDate}
                    onChange={(e) => handleStatusChange('nextReviewDate', e.target.value)}
                  />
                </div>
              </div>
              
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Current Issues</label>
                <textarea
                  className={styles.textareaInput}
                  value={standardWorkData.status.issues}
                  onChange={(e) => handleStatusChange('issues', e.target.value)}
                  placeholder="Current issues or concerns"
                  rows="3"
                />
              </div>
              
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Improvement Opportunities</label>
                <textarea
                  className={styles.textareaInput}
                  value={standardWorkData.status.improvements}
                  onChange={(e) => handleStatusChange('improvements', e.target.value)}
                  placeholder="Opportunities for improvement"
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
              <span>Standard Work {completionPercentage}% Complete</span>
            </div>
            <div className={styles.footerActions}>
              <button className={styles.secondaryBtn}>
                Preview Standard Work
              </button>
              <button 
                className={styles.primaryBtn}
                disabled={completionPercentage < 70}
              >
                Activate Standard Work
              </button>
            </div>
          </div>
        </div>
      </div>
    </ResourcePageWrapper>
  );
};

export default StandardWork;
