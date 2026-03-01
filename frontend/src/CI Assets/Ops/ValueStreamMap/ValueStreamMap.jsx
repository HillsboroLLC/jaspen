import React, { useState, useEffect } from 'react';
import { useAdminSettings } from '../context/AdminContext';
import ResourcePageWrapper from '../../All/components/ResourcePageWrapper';
import styles from './ValueStreamMap.module.css';

const ValueStreamMap = () => {
  const { adminSettings } = useAdminSettings();

  // Value Stream Map data structure
  const [vsmData, setVsmData] = useState({
    projectName: '',
    processOwner: '',
    mappingTeam: '',
    dateCreated: new Date().toISOString().split('T')[0],
    lastUpdated: new Date().toISOString().split('T')[0],
    
    // Process information
    processInfo: {
      processName: '',
      productFamily: '',
      customer: '',
      supplier: '',
      mapType: 'current', // 'current', 'future'
      scope: '',
      purpose: ''
    },
    
    // Process steps
    processSteps: [
      {
        id: 1,
        name: 'Process Step 1',
        type: 'process', // 'process', 'inspection', 'delay', 'transport', 'storage'
        cycleTime: 0,
        leadTime: 0,
        uptime: 100,
        changeover: 0,
        batchSize: 1,
        workers: 1,
        shifts: 1,
        workingTime: 480, // minutes per day
        scrap: 0,
        rework: 0,
        notes: ''
      }
    ],
    
    // Information flow
    informationFlow: [
      {
        id: 1,
        from: 'Customer',
        to: 'Production Control',
        method: 'email', // 'email', 'phone', 'fax', 'system', 'paper'
        frequency: 'daily',
        information: 'Orders',
        notes: ''
      }
    ],
    
    // Material flow
    materialFlow: [
      {
        id: 1,
        from: 'Supplier',
        to: 'Process Step 1',
        method: 'truck', // 'truck', 'conveyor', 'forklift', 'manual', 'pipeline'
        frequency: 'weekly',
        batchSize: 100,
        leadTime: 2, // days
        inventory: 50,
        notes: ''
      }
    ],
    
    // Waste identification
    wasteAnalysis: {
      transportation: { identified: false, description: '', impact: 'low' },
      inventory: { identified: false, description: '', impact: 'low' },
      motion: { identified: false, description: '', impact: 'low' },
      waiting: { identified: false, description: '', impact: 'low' },
      overproduction: { identified: false, description: '', impact: 'low' },
      overprocessing: { identified: false, description: '', impact: 'low' },
      defects: { identified: false, description: '', impact: 'low' },
      skills: { identified: false, description: '', impact: 'low' }
    },
    
    // Metrics
    metrics: {
      totalLeadTime: 0,
      totalProcessTime: 0,
      processEfficiency: 0,
      valueAddedTime: 0,
      nonValueAddedTime: 0,
      valueAddedRatio: 0,
      taktTime: 0,
      customerDemand: 0
    },
    
    // Improvement opportunities
    improvements: []
  });

  const [completionPercentage, setCompletionPercentage] = useState(0);

  // Calculate completion percentage
  useEffect(() => {
    const calculateCompletion = () => {
      let totalFields = 0;
      let completedFields = 0;

      // Basic info
      totalFields += 3;
      if (vsmData.projectName) completedFields++;
      if (vsmData.processOwner) completedFields++;
      if (vsmData.mappingTeam) completedFields++;

      // Process info
      totalFields += 5;
      if (vsmData.processInfo.processName) completedFields++;
      if (vsmData.processInfo.productFamily) completedFields++;
      if (vsmData.processInfo.customer) completedFields++;
      if (vsmData.processInfo.supplier) completedFields++;
      if (vsmData.processInfo.scope) completedFields++;

      // Process steps
      totalFields += 1;
      if (vsmData.processSteps.length > 1 || vsmData.processSteps[0].name !== 'Process Step 1') completedFields++;

      // Flows
      totalFields += 2;
      if (vsmData.informationFlow.length > 0 && vsmData.informationFlow[0].information !== 'Orders') completedFields++;
      if (vsmData.materialFlow.length > 0 && vsmData.materialFlow[0].from !== 'Supplier') completedFields++;

      // Waste analysis
      totalFields += 1;
      const wasteIdentified = Object.values(vsmData.wasteAnalysis).some(waste => waste.identified);
      if (wasteIdentified) completedFields++;

      const percentage = totalFields > 0 ? Math.round((completedFields / totalFields) * 100) : 0;
      setCompletionPercentage(percentage);
    };

    calculateCompletion();
  }, [vsmData]);

  // Calculate metrics (derived from steps)
  useEffect(() => {
    const calculateMetrics = () => {
      const totalProcessTime = vsmData.processSteps.reduce((sum, step) => sum + (step.cycleTime || 0), 0);
      const totalLeadTime = vsmData.processSteps.reduce((sum, step) => sum + (step.leadTime || 0), 0);
      const valueAddedTime = totalProcessTime;
      const nonValueAddedTime = totalLeadTime - totalProcessTime;
      const valueAddedRatio = totalLeadTime > 0 ? (valueAddedTime / totalLeadTime) * 100 : 0;
      const processEfficiency = totalLeadTime > 0 ? (totalProcessTime / totalLeadTime) * 100 : 0;

      setVsmData(prev => ({
        ...prev,
        metrics: {
          ...prev.metrics,
          totalLeadTime: parseFloat(totalLeadTime.toFixed(2)),
          totalProcessTime: parseFloat(totalProcessTime.toFixed(2)),
          processEfficiency: parseFloat(processEfficiency.toFixed(2)),
          valueAddedTime: parseFloat(valueAddedTime.toFixed(2)),
          nonValueAddedTime: parseFloat(nonValueAddedTime.toFixed(2)),
          valueAddedRatio: parseFloat(valueAddedRatio.toFixed(2))
        }
      }));
    };

    calculateMetrics();
  }, [vsmData.processSteps]);

  // Handlers
  const handleBasicInfoChange = (field, value) => {
    setVsmData(prev => ({
      ...prev,
      [field]: value,
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleProcessInfoChange = (field, value) => {
    setVsmData(prev => ({
      ...prev,
      processInfo: {
        ...prev.processInfo,
        [field]: value
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleProcessStepChange = (stepId, field, value) => {
    setVsmData(prev => ({
      ...prev,
      processSteps: prev.processSteps.map(step =>
        step.id === stepId ? { ...step, [field]: value } : step
      ),
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleInformationFlowChange = (flowId, field, value) => {
    setVsmData(prev => ({
      ...prev,
      informationFlow: prev.informationFlow.map(flow =>
        flow.id === flowId ? { ...flow, [field]: value } : flow
      ),
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleMaterialFlowChange = (flowId, field, value) => {
    setVsmData(prev => ({
      ...prev,
      materialFlow: prev.materialFlow.map(flow =>
        flow.id === flowId ? { ...flow, [field]: value } : flow
      ),
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const handleWasteChange = (wasteType, field, value) => {
    setVsmData(prev => ({
      ...prev,
      wasteAnalysis: {
        ...prev.wasteAnalysis,
        [wasteType]: {
          ...prev.wasteAnalysis[wasteType],
          [field]: value
        }
      },
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Add / Remove rows
  const addProcessStep = () => {
    const newStep = {
      id: Date.now(),
      name: `Process Step ${vsmData.processSteps.length + 1}`,
      type: 'process',
      cycleTime: 0,
      leadTime: 0,
      uptime: 100,
      changeover: 0,
      batchSize: 1,
      workers: 1,
      shifts: 1,
      workingTime: 480,
      scrap: 0,
      rework: 0,
      notes: ''
    };
    
    setVsmData(prev => ({
      ...prev,
      processSteps: [...prev.processSteps, newStep],
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const removeProcessStep = (stepId) => {
    if (vsmData.processSteps.length > 1) {
      setVsmData(prev => ({
        ...prev,
        processSteps: prev.processSteps.filter(step => step.id !== stepId),
        lastUpdated: new Date().toISOString().split('T')[0]
      }));
    }
  };

  const addInformationFlow = () => {
    const newFlow = {
      id: Date.now(),
      from: '',
      to: '',
      method: 'email',
      frequency: 'daily',
      information: '',
      notes: ''
    };
    
    setVsmData(prev => ({
      ...prev,
      informationFlow: [...prev.informationFlow, newFlow],
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  const addMaterialFlow = () => {
    const newFlow = {
      id: Date.now(),
      from: '',
      to: '',
      method: 'truck',
      frequency: 'daily',
      batchSize: 1,
      leadTime: 1,
      inventory: 0,
      notes: ''
    };
    
    setVsmData(prev => ({
      ...prev,
      materialFlow: [...prev.materialFlow, newFlow],
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  };

  // Save / Export hooks
  const handleSave = () => {
    console.log('Saving VSM:', vsmData);
    // Implement save functionality
  };

  const handleExport = () => {
    console.log('Exporting VSM:', vsmData);
    // Implement export functionality
  };

  return (
    <ResourcePageWrapper
      pageName="Value Stream Map"
      toolName="value-stream-map"
      adminSettings={adminSettings}
    >
      <div className={styles.vsmContainer}>
        {/* Header */}
        <div className={styles.header}>
          <div className={styles.headerContent}>
            <h1>Value Stream Map</h1>
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
            <button className={styles.saveBtn} onClick={handleSave}>
              <i className="fas fa-save"></i> Save Map
            </button>
            <button className={styles.exportBtn} onClick={handleExport}>
              <i className="fas fa-download"></i> Export VSM
            </button>
          </div>
        </div>

        {/* Main Content */}
        <div className={styles.mainContent}>
          {/* VSM Information */}
          <div className={styles.processInfoCard}>
            <h2>Value Stream Map Information</h2>
            
            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel}>
                Project Name <span className={styles.required}>*</span>
              </label>
              <input
                type="text"
                className={styles.textInput}
                value={vsmData.projectName}
                onChange={(e) => handleBasicInfoChange('projectName', e.target.value)}
                placeholder="Enter the project name for this value stream map"
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
                  value={vsmData.processOwner}
                  onChange={(e) => handleBasicInfoChange('processOwner', e.target.value)}
                  placeholder="Who owns this process?"
                />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Mapping Team <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={vsmData.mappingTeam}
                  onChange={(e) => handleBasicInfoChange('mappingTeam', e.target.value)}
                  placeholder="List team members creating the map"
                />
              </div>
            </div>

            <div className={styles.fieldRow}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Date Created</label>
                <input
                  type="date"
                  className={styles.textInput}
                  value={vsmData.dateCreated}
                  onChange={(e) => handleBasicInfoChange('dateCreated', e.target.value)}
                />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Last Updated</label>
                <input
                  type="date"
                  className={styles.textInput}
                  value={vsmData.lastUpdated}
                  readOnly
                />
              </div>
            </div>
          </div>

          {/* Process Details */}
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
                  value={vsmData.processInfo.processName}
                  onChange={(e) => handleProcessInfoChange('processName', e.target.value)}
                  placeholder="Name of the process being mapped"
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Product Family <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={vsmData.processInfo.productFamily}
                  onChange={(e) => handleProcessInfoChange('productFamily', e.target.value)}
                  placeholder="Product or service family"
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Customer <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={vsmData.processInfo.customer}
                  onChange={(e) => handleProcessInfoChange('customer', e.target.value)}
                  placeholder="End customer or next process"
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Supplier <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={vsmData.processInfo.supplier}
                  onChange={(e) => handleProcessInfoChange('supplier', e.target.value)}
                  placeholder="Key supplier or previous process"
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Map Type</label>
                <select
                  className={styles.selectInput}
                  value={vsmData.processInfo.mapType}
                  onChange={(e) => handleProcessInfoChange('mapType', e.target.value)}
                >
                  <option value="current">Current State</option>
                  <option value="future">Future State</option>
                </select>
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Scope <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={vsmData.processInfo.scope}
                  onChange={(e) => handleProcessInfoChange('scope', e.target.value)}
                  placeholder="Start and end points of the map"
                />
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Purpose</label>
                <textarea
                  className={styles.textareaInput}
                  value={vsmData.processInfo.purpose}
                  onChange={(e) => handleProcessInfoChange('purpose', e.target.value)}
                  placeholder="Why is this value stream map being created?"
                  rows={3}
                />
              </div>
            </div>
          </div>

          {/* Process Steps */}
          <div className={styles.processStepsCard}>
            <div className={styles.sectionHeader}>
              <h2>Process Steps</h2>
              <button className={styles.addBtn} onClick={addProcessStep}>
                <i className="fas fa-plus"></i> Add Step
              </button>
            </div>

            <div className={styles.processStepsGrid}>
              {vsmData.processSteps.map((step, index) => (
                <div key={step.id} className={styles.processStepCard}>
                  <div className={styles.stepHeader}>
                    <h3>Step {index + 1}</h3>
                    {vsmData.processSteps.length > 1 && (
                      <button 
                        className={styles.removeBtn}
                        onClick={() => removeProcessStep(step.id)}
                      >
                        <i className="fas fa-times"></i>
                      </button>
                    )}
                  </div>

                  <div className={styles.stepFieldsGrid}>
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Step Name</label>
                      <input
                        type="text"
                        className={styles.textInput}
                        value={step.name}
                        onChange={(e) => handleProcessStepChange(step.id, 'name', e.target.value)}
                        placeholder="Process step name"
                      />
                    </div>

                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Type</label>
                      <select
                        className={styles.selectInput}
                        value={step.type}
                        onChange={(e) => handleProcessStepChange(step.id, 'type', e.target.value)}
                      >
                        <option value="process">Process</option>
                        <option value="inspection">Inspection</option>
                        <option value="delay">Delay</option>
                        <option value="transport">Transport</option>
                        <option value="storage">Storage</option>
                      </select>
                    </div>

                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Cycle Time (min)</label>
                      <input
                        type="number"
                        step="0.1"
                        className={styles.textInput}
                        value={step.cycleTime}
                        onChange={(e) => handleProcessStepChange(step.id, 'cycleTime', parseFloat(e.target.value) || 0)}
                        placeholder="0"
                      />
                    </div>

                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Lead Time (min)</label>
                      <input
                        type="number"
                        step="0.1"
                        className={styles.textInput}
                        value={step.leadTime}
                        onChange={(e) => handleProcessStepChange(step.id, 'leadTime', parseFloat(e.target.value) || 0)}
                        placeholder="0"
                      />
                    </div>

                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Uptime (%)</label>
                      <input
                        type="number"
                        min="0"
                        max="100"
                        className={styles.textInput}
                        value={step.uptime}
                        onChange={(e) => handleProcessStepChange(step.id, 'uptime', parseFloat(e.target.value) || 0)}
                        placeholder="100"
                      />
                    </div>

                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Changeover (min)</label>
                      <input
                        type="number"
                        step="0.1"
                        className={styles.textInput}
                        value={step.changeover}
                        onChange={(e) => handleProcessStepChange(step.id, 'changeover', parseFloat(e.target.value) || 0)}
                        placeholder="0"
                      />
                    </div>

                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Batch Size</label>
                      <input
                        type="number"
                        min="1"
                        className={styles.textInput}
                        value={step.batchSize}
                        onChange={(e) => handleProcessStepChange(step.id, 'batchSize', parseInt(e.target.value) || 1)}
                        placeholder="1"
                      />
                    </div>

                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Workers</label>
                      <input
                        type="number"
                        min="1"
                        className={styles.textInput}
                        value={step.workers}
                        onChange={(e) => handleProcessStepChange(step.id, 'workers', parseInt(e.target.value) || 1)}
                        placeholder="1"
                      />
                    </div>

                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Notes</label>
                      <textarea
                        className={styles.textareaInput}
                        value={step.notes}
                        onChange={(e) => handleProcessStepChange(step.id, 'notes', e.target.value)}
                        placeholder="Additional notes about this step"
                        rows={2}
                      />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Information Flow */}
          <div className={styles.flowCard}>
            <div className={styles.sectionHeader}>
              <h2>Information Flow</h2>
              <button className={styles.addBtn} onClick={addInformationFlow}>
                <i className="fas fa-plus"></i> Add Flow
              </button>
            </div>
            <div className={styles.flowGrid}>
              {vsmData.informationFlow.map(flow => (
                <div key={flow.id} className={styles.flowRow}>
                  <input
                    className={styles.textInput}
                    placeholder="From"
                    value={flow.from}
                    onChange={(e) => handleInformationFlowChange(flow.id, 'from', e.target.value)}
                  />
                  <input
                    className={styles.textInput}
                    placeholder="To"
                    value={flow.to}
                    onChange={(e) => handleInformationFlowChange(flow.id, 'to', e.target.value)}
                  />
                  <select
                    className={styles.selectInput}
                    value={flow.method}
                    onChange={(e) => handleInformationFlowChange(flow.id, 'method', e.target.value)}
                  >
                    <option value="email">Email</option>
                    <option value="phone">Phone</option>
                    <option value="fax">Fax</option>
                    <option value="system">System</option>
                    <option value="paper">Paper</option>
                  </select>
                  <input
                    className={styles.textInput}
                    placeholder="Frequency"
                    value={flow.frequency}
                    onChange={(e) => handleInformationFlowChange(flow.id, 'frequency', e.target.value)}
                  />
                  <input
                    className={styles.textInput}
                    placeholder="Information"
                    value={flow.information}
                    onChange={(e) => handleInformationFlowChange(flow.id, 'information', e.target.value)}
                  />
                  <input
                    className={styles.textInput}
                    placeholder="Notes"
                    value={flow.notes}
                    onChange={(e) => handleInformationFlowChange(flow.id, 'notes', e.target.value)}
                  />
                </div>
              ))}
            </div>
          </div>

          {/* Material Flow */}
          <div className={styles.flowCard}>
            <div className={styles.sectionHeader}>
              <h2>Material Flow</h2>
              <button className={styles.addBtn} onClick={addMaterialFlow}>
                <i className="fas fa-plus"></i> Add Flow
              </button>
            </div>
            <div className={styles.flowGrid}>
              {vsmData.materialFlow.map(flow => (
                <div key={flow.id} className={styles.flowRow}>
                  <input
                    className={styles.textInput}
                    placeholder="From"
                    value={flow.from}
                    onChange={(e) => handleMaterialFlowChange(flow.id, 'from', e.target.value)}
                  />
                  <input
                    className={styles.textInput}
                    placeholder="To"
                    value={flow.to}
                    onChange={(e) => handleMaterialFlowChange(flow.id, 'to', e.target.value)}
                  />
                  <select
                    className={styles.selectInput}
                    value={flow.method}
                    onChange={(e) => handleMaterialFlowChange(flow.id, 'method', e.target.value)}
                  >
                    <option value="truck">Truck</option>
                    <option value="conveyor">Conveyor</option>
                    <option value="forklift">Forklift</option>
                    <option value="manual">Manual</option>
                    <option value="pipeline">Pipeline</option>
                  </select>
                  <input
                    type="text"
                    className={styles.textInput}
                    placeholder="Frequency"
                    value={flow.frequency}
                    onChange={(e) => handleMaterialFlowChange(flow.id, 'frequency', e.target.value)}
                  />
                  <input
                    type="number"
                    className={styles.textInput}
                    placeholder="Batch Size"
                    value={flow.batchSize}
                    onChange={(e) => handleMaterialFlowChange(flow.id, 'batchSize', parseInt(e.target.value) || 0)}
                  />
                  <input
                    type="number"
                    step="0.1"
                    className={styles.textInput}
                    placeholder="Lead Time (days)"
                    value={flow.leadTime}
                    onChange={(e) => handleMaterialFlowChange(flow.id, 'leadTime', parseFloat(e.target.value) || 0)}
                  />
                  <input
                    type="number"
                    className={styles.textInput}
                    placeholder="Inventory"
                    value={flow.inventory}
                    onChange={(e) => handleMaterialFlowChange(flow.id, 'inventory', parseInt(e.target.value) || 0)}
                  />
                  <input
                    className={styles.textInput}
                    placeholder="Notes"
                    value={flow.notes}
                    onChange={(e) => handleMaterialFlowChange(flow.id, 'notes', e.target.value)}
                  />
                </div>
              ))}
            </div>
          </div>

          {/* Waste Analysis */}
          <div className={styles.wasteAnalysisCard}>
            <div className={styles.sectionHeader}>
              <h2>Waste Analysis (8 Wastes of Lean)</h2>
            </div>

            <div className={styles.wasteGrid}>
              {Object.entries(vsmData.wasteAnalysis).map(([wasteType, waste]) => (
                <div key={wasteType} className={styles.wasteCard}>
                  <div className={styles.wasteHeader}>
                    <label className={styles.checkboxLabel}>
                      <input
                        type="checkbox"
                        checked={waste.identified}
                        onChange={(e) => handleWasteChange(wasteType, 'identified', e.target.checked)}
                      />
                      <span className={styles.wasteTitle}>
                        {wasteType.charAt(0).toUpperCase() + wasteType.slice(1)}
                      </span>
                    </label>
                    {waste.identified && (
                      <select
                        className={styles.impactSelect}
                        value={waste.impact}
                        onChange={(e) => handleWasteChange(wasteType, 'impact', e.target.value)}
                      >
                        <option value="low">Low Impact</option>
                        <option value="medium">Medium Impact</option>
                        <option value="high">High Impact</option>
                      </select>
                    )}
                  </div>
                  {waste.identified && (
                    <textarea
                      className={styles.wasteDescription}
                      value={waste.description}
                      onChange={(e) => handleWasteChange(wasteType, 'description', e.target.value)}
                      placeholder={`Describe the ${wasteType} waste identified...`}
                      rows={3}
                    />
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Metrics */}
          <div className={styles.metricsCard}>
            <div className={styles.sectionHeader}>
              <h2>Value Stream Metrics</h2>
            </div>

            <div className={styles.metricsGrid}>
              <div className={styles.metricCard}>
                <h4>Total Lead Time</h4>
                <div className={styles.metricValue}>
                  {vsmData.metrics.totalLeadTime} min
                </div>
                <div className={styles.metricDescription}>End-to-end process time</div>
              </div>
              <div className={styles.metricCard}>
                <h4>Total Process Time</h4>
                <div className={styles.metricValue}>
                  {vsmData.metrics.totalProcessTime} min
                </div>
                <div className={styles.metricDescription}>Actual work time</div>
              </div>
              <div className={styles.metricCard}>
                <h4>Process Efficiency</h4>
                <div className={styles.metricValue}>
                  {vsmData.metrics.processEfficiency}%
                </div>
                <div className={styles.metricDescription}>Process time / Lead time</div>
              </div>
              <div className={styles.metricCard}>
                <h4>Value Added Ratio</h4>
                <div className={styles.metricValue}>
                  {vsmData.metrics.valueAddedRatio}%
                </div>
                <div className={styles.metricDescription}>Value-added time ratio</div>
              </div>
            </div>

            <div className={styles.additionalMetrics}>
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Customer Demand (units/day)</label>
                  <input
                    type="number"
                    className={styles.textInput}
                    value={vsmData.metrics.customerDemand}
                    onChange={(e) => {
                      const newDemand = parseInt(e.target.value) || 0;
                      const newTakt = newDemand > 0 ? parseFloat((480 / newDemand).toFixed(2)) : 0;
                      setVsmData(prev => ({
                        ...prev,
                        metrics: {
                          ...prev.metrics,
                          customerDemand: newDemand,
                          taktTime: newTakt
                        }
                      }));
                    }}
                    placeholder="Daily customer demand"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Takt Time (min)</label>
                  <input
                    type="number"
                    step="0.1"
                    className={styles.textInput}
                    value={vsmData.metrics.taktTime}
                    readOnly
                    placeholder="Calculated automatically"
                  />
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className={styles.footer}>
          <div className={styles.footerContent}>
            <div className={styles.completionStatus}>
              <i className="fas fa-check-circle"></i>
              <span>Value Stream Map {completionPercentage}% Complete</span>
            </div>
            <div className={styles.footerActions}>
              <button className={styles.secondaryBtn}>
                <i className="fas fa-eye"></i> Preview Map
              </button>
              <button 
                className={styles.primaryBtn}
                disabled={completionPercentage < 70}
              >
                <i className="fas fa-check"></i> Complete VSM
              </button>
            </div>
          </div>
        </div>
      </div>
    </ResourcePageWrapper>
  );
};

export default ValueStreamMap;
