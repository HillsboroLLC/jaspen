import React, { useState, useCallback, useEffect } from 'react';
import { useAdminSettings } from '../context/AdminContext';
import ResourcePageWrapper from '../../All/components/ResourcePageWrapper';
import styles from './SIPOC.module.css';

const SIPOC = () => {
  const { adminSettings } = useAdminSettings();

  // SIPOC data structure
  const [sipocData, setSipocData] = useState({
    processName: '',
    processOwner: '',
    processDescription: '',
    dateCreated: new Date().toISOString().split('T')[0],
    lastUpdated: new Date().toISOString().split('T')[0],
    suppliers: [{ id: 1, name: '', type: 'Internal', description: '' }],
    inputs: [{ id: 1, name: '', type: 'Material', description: '' }],
    process: [{ id: 1, step: '', description: '', owner: '', duration: '' }],
    outputs: [{ id: 1, name: '', type: 'Product', description: '' }],
    customers: [{ id: 1, name: '', type: 'Internal', description: '' }]
  });

  const [completionPercentage, setCompletionPercentage] = useState(0);

  // Calculate completion percentage
  useEffect(() => {
    const calculateCompletion = () => {
      let totalFields = 0;
      let completedFields = 0;

      // Process info (3 fields)
      totalFields += 3;
      if (sipocData.processName) completedFields++;
      if (sipocData.processOwner) completedFields++;
      if (sipocData.processDescription) completedFields++;

      // SIPOC items - count essential fields
      const sections = ['suppliers', 'inputs', 'process', 'outputs', 'customers'];
      sections.forEach(section => {
        sipocData[section].forEach(item => {
          totalFields += 2; // name/step and description
          if (section === 'process') {
            if (item.step && item.step.trim() !== '') completedFields++;
          } else {
            if (item.name && item.name.trim() !== '') completedFields++;
          }
          if (item.description && item.description.trim() !== '') completedFields++;
        });
      });

      const percentage = totalFields > 0 ? Math.round((completedFields / totalFields) * 100) : 0;
      setCompletionPercentage(percentage);
    };

    calculateCompletion();
  }, [sipocData]);

  // Handle process info changes
  const handleProcessInfoChange = useCallback((field, value) => {
    setSipocData(prev => ({
      ...prev,
      [field]: value,
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  }, []);

  // Handle SIPOC item changes
  const handleSipocItemChange = useCallback((section, id, field, value) => {
    setSipocData(prev => ({
      ...prev,
      [section]: prev[section].map(item =>
        item.id === id ? { ...item, [field]: value } : item
      ),
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  }, []);

  // Add new SIPOC item
  const addSipocItem = useCallback((section) => {
    setSipocData(prev => {
      const newId = Math.max(...prev[section].map(item => item.id)) + 1;
      const newItem = { id: newId, name: '', description: '' };

      // Add section-specific fields
      if (section === 'suppliers' || section === 'customers') {
        newItem.type = section === 'suppliers' ? 'Internal' : 'Internal';
      } else if (section === 'inputs' || section === 'outputs') {
        newItem.type = section === 'inputs' ? 'Material' : 'Product';
      } else if (section === 'process') {
        newItem.step = '';
        newItem.owner = '';
        newItem.duration = '';
        delete newItem.name; // Process uses 'step' instead of 'name'
      }

      return {
        ...prev,
        [section]: [...prev[section], newItem],
        lastUpdated: new Date().toISOString().split('T')[0]
      };
    });
  }, []);

  // Remove SIPOC item
  const removeSipocItem = useCallback((section, id) => {
    setSipocData(prev => {
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

  // Save / Export
  const handleSave = () => {
    console.log('Saving SIPOC draft:', sipocData);
  };

  const handleExport = () => {
    console.log('Exporting SIPOC to PDF:', sipocData);
  };

  return (
    <ResourcePageWrapper
      pageName="SIPOC Analysis"
      toolName="sipoc"
      adminSettings={adminSettings}
    >
      <div className={styles.rcaContainer}>
        {/* Header */}
        <div className={styles.header}>
          <div className={styles.headerContent}>
            <h1>SIPOC Analysis</h1>
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

        {/* Main Content — FULL WIDTH (single column, no chat) */}
        <div className={styles.mainContent} style={{ display: 'block' }}>
          {/* Top Section: Process Information */}
          <div className={styles.topSection} style={{ display: 'block' }}>
            <div className={styles.processInfoCard}>
              <h2>Process Information</h2>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Process Name <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={sipocData.processName}
                  onChange={(e) => handleProcessInfoChange('processName', e.target.value)}
                  placeholder="Enter the process name for SIPOC analysis"
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
                    value={sipocData.processOwner}
                    onChange={(e) => handleProcessInfoChange('processOwner', e.target.value)}
                    placeholder="Who owns this process?"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Date Created</label>
                  <input
                    type="date"
                    className={styles.textInput}
                    value={sipocData.dateCreated}
                    onChange={(e) => handleProcessInfoChange('dateCreated', e.target.value)}
                  />
                </div>
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Process Description <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={sipocData.processDescription}
                  onChange={(e) => handleProcessInfoChange('processDescription', e.target.value)}
                  placeholder="Describe the purpose and scope of this process"
                  rows={3}
                />
              </div>
            </div>
          </div>

          {/* SIPOC Grid Section */}
          <div className={styles.analysisCard}>
            <h2>SIPOC Grid</h2>
            <div className={styles.sipocGrid}>
              <div className={styles.sipocTable}>
                {/* SIPOC Header */}
                <div className={styles.sipocHeader}>
                  <div className={styles.sipocColumn}>
                    <h3>Suppliers</h3>
                    <p>Who provides inputs?</p>
                  </div>
                  <div className={styles.sipocColumn}>
                    <h3>Inputs</h3>
                    <p>What is needed?</p>
                  </div>
                  <div className={styles.sipocColumn}>
                    <h3>Process</h3>
                    <p>What steps transform inputs?</p>
                  </div>
                  <div className={styles.sipocColumn}>
                    <h3>Outputs</h3>
                    <p>What is produced?</p>
                  </div>
                  <div className={styles.sipocColumn}>
                    <h3>Customers</h3>
                    <p>Who receives outputs?</p>
                  </div>
                </div>

                {/* SIPOC Body */}
                <div className={styles.sipocBody}>
                  {Array.from({
                    length: Math.max(
                      sipocData.suppliers.length,
                      sipocData.inputs.length,
                      sipocData.process.length,
                      sipocData.outputs.length,
                      sipocData.customers.length
                    )
                  }).map((_, rowIndex) => (
                    <div key={rowIndex} className={styles.sipocRow}>
                      {/* Suppliers */}
                      <div className={styles.sipocCell}>
                        {sipocData.suppliers[rowIndex] && (
                          <div className={styles.sipocItem}>
                            <input
                              type="text"
                              className={styles.sipocInput}
                              value={sipocData.suppliers[rowIndex].name}
                              onChange={(e) =>
                                handleSipocItemChange('suppliers', sipocData.suppliers[rowIndex].id, 'name', e.target.value)
                              }
                              placeholder="Supplier name"
                            />
                            <select
                              className={styles.sipocSelect}
                              value={sipocData.suppliers[rowIndex].type}
                              onChange={(e) =>
                                handleSipocItemChange('suppliers', sipocData.suppliers[rowIndex].id, 'type', e.target.value)
                              }
                            >
                              <option value="Internal">Internal</option>
                              <option value="External">External</option>
                            </select>
                            <textarea
                              className={styles.sipocTextarea}
                              value={sipocData.suppliers[rowIndex].description}
                              onChange={(e) =>
                                handleSipocItemChange('suppliers', sipocData.suppliers[rowIndex].id, 'description', e.target.value)
                              }
                              placeholder="Description"
                              rows={2}
                            />
                            <button
                              type="button"
                              className={styles.removeBtn}
                              onClick={() => removeSipocItem('suppliers', sipocData.suppliers[rowIndex].id)}
                              disabled={sipocData.suppliers.length <= 1}
                            >
                              <i className="fas fa-times"></i>
                            </button>
                          </div>
                        )}
                      </div>

                      {/* Inputs */}
                      <div className={styles.sipocCell}>
                        {sipocData.inputs[rowIndex] && (
                          <div className={styles.sipocItem}>
                            <input
                              type="text"
                              className={styles.sipocInput}
                              value={sipocData.inputs[rowIndex].name}
                              onChange={(e) =>
                                handleSipocItemChange('inputs', sipocData.inputs[rowIndex].id, 'name', e.target.value)
                              }
                              placeholder="Input name"
                            />
                            <select
                              className={styles.sipocSelect}
                              value={sipocData.inputs[rowIndex].type}
                              onChange={(e) =>
                                handleSipocItemChange('inputs', sipocData.inputs[rowIndex].id, 'type', e.target.value)
                              }
                            >
                              <option value="Material">Material</option>
                              <option value="Information">Information</option>
                              <option value="Service">Service</option>
                              <option value="Resource">Resource</option>
                            </select>
                            <textarea
                              className={styles.sipocTextarea}
                              value={sipocData.inputs[rowIndex].description}
                              onChange={(e) =>
                                handleSipocItemChange('inputs', sipocData.inputs[rowIndex].id, 'description', e.target.value)
                              }
                              placeholder="Description"
                              rows={2}
                            />
                            <button
                              type="button"
                              className={styles.removeBtn}
                              onClick={() => removeSipocItem('inputs', sipocData.inputs[rowIndex].id)}
                              disabled={sipocData.inputs.length <= 1}
                            >
                              <i className="fas fa-times"></i>
                            </button>
                          </div>
                        )}
                      </div>

                      {/* Process */}
                      <div className={styles.sipocCell}>
                        {sipocData.process[rowIndex] && (
                          <div className={styles.sipocItem}>
                            <input
                              type="text"
                              className={styles.sipocInput}
                              value={sipocData.process[rowIndex].step}
                              onChange={(e) =>
                                handleSipocItemChange('process', sipocData.process[rowIndex].id, 'step', e.target.value)
                              }
                              placeholder="Process step"
                            />
                            <input
                              type="text"
                              className={styles.sipocInput}
                              value={sipocData.process[rowIndex].owner}
                              onChange={(e) =>
                                handleSipocItemChange('process', sipocData.process[rowIndex].id, 'owner', e.target.value)
                              }
                              placeholder="Step owner"
                            />
                            <input
                              type="text"
                              className={styles.sipocInput}
                              value={sipocData.process[rowIndex].duration}
                              onChange={(e) =>
                                handleSipocItemChange('process', sipocData.process[rowIndex].id, 'duration', e.target.value)
                              }
                              placeholder="Duration"
                            />
                            <textarea
                              className={styles.sipocTextarea}
                              value={sipocData.process[rowIndex].description}
                              onChange={(e) =>
                                handleSipocItemChange('process', sipocData.process[rowIndex].id, 'description', e.target.value)
                              }
                              placeholder="Description"
                              rows={2}
                            />
                            <button
                              type="button"
                              className={styles.removeBtn}
                              onClick={() => removeSipocItem('process', sipocData.process[rowIndex].id)}
                              disabled={sipocData.process.length <= 1}
                            >
                              <i className="fas fa-times"></i>
                            </button>
                          </div>
                        )}
                      </div>

                      {/* Outputs */}
                      <div className={styles.sipocCell}>
                        {sipocData.outputs[rowIndex] && (
                          <div className={styles.sipocItem}>
                            <input
                              type="text"
                              className={styles.sipocInput}
                              value={sipocData.outputs[rowIndex].name}
                              onChange={(e) =>
                                handleSipocItemChange('outputs', sipocData.outputs[rowIndex].id, 'name', e.target.value)
                              }
                              placeholder="Output name"
                            />
                            <select
                              className={styles.sipocSelect}
                              value={sipocData.outputs[rowIndex].type}
                              onChange={(e) =>
                                handleSipocItemChange('outputs', sipocData.outputs[rowIndex].id, 'type', e.target.value)
                              }
                            >
                              <option value="Product">Product</option>
                              <option value="Service">Service</option>
                              <option value="Information">Information</option>
                              <option value="Decision">Decision</option>
                            </select>
                            <textarea
                              className={styles.sipocTextarea}
                              value={sipocData.outputs[rowIndex].description}
                              onChange={(e) =>
                                handleSipocItemChange('outputs', sipocData.outputs[rowIndex].id, 'description', e.target.value)
                              }
                              placeholder="Description"
                              rows={2}
                            />
                            <button
                              type="button"
                              className={styles.removeBtn}
                              onClick={() => removeSipocItem('outputs', sipocData.outputs[rowIndex].id)}
                              disabled={sipocData.outputs.length <= 1}
                            >
                              <i className="fas fa-times"></i>
                            </button>
                          </div>
                        )}
                      </div>

                      {/* Customers */}
                      <div className={styles.sipocCell}>
                        {sipocData.customers[rowIndex] && (
                          <div className={styles.sipocItem}>
                            <input
                              type="text"
                              className={styles.sipocInput}
                              value={sipocData.customers[rowIndex].name}
                              onChange={(e) =>
                                handleSipocItemChange('customers', sipocData.customers[rowIndex].id, 'name', e.target.value)
                              }
                              placeholder="Customer name"
                            />
                            <select
                              className={styles.sipocSelect}
                              value={sipocData.customers[rowIndex].type}
                              onChange={(e) =>
                                handleSipocItemChange('customers', sipocData.customers[rowIndex].id, 'type', e.target.value)
                              }
                            >
                              <option value="Internal">Internal</option>
                              <option value="External">External</option>
                            </select>
                            <textarea
                              className={styles.sipocTextarea}
                              value={sipocData.customers[rowIndex].description}
                              onChange={(e) =>
                                handleSipocItemChange('customers', sipocData.customers[rowIndex].id, 'description', e.target.value)
                              }
                              placeholder="Description"
                              rows={2}
                            />
                            <button
                              type="button"
                              className={styles.removeBtn}
                              onClick={() => removeSipocItem('customers', sipocData.customers[rowIndex].id)}
                              disabled={sipocData.customers.length <= 1}
                            >
                              <i className="fas fa-times"></i>
                            </button>
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>

                {/* Add buttons for each column */}
                <div className={styles.sipocActions}>
                  <button
                    type="button"
                    className={styles.addBtn}
                    onClick={() => addSipocItem('suppliers')}
                  >
                    <i className="fas fa-plus"></i> Add Supplier
                  </button>
                  <button
                    type="button"
                    className={styles.addBtn}
                    onClick={() => addSipocItem('inputs')}
                  >
                    <i className="fas fa-plus"></i> Add Input
                  </button>
                  <button
                    type="button"
                    className={styles.addBtn}
                    onClick={() => addSipocItem('process')}
                  >
                    <i className="fas fa-plus"></i> Add Step
                  </button>
                  <button
                    type="button"
                    className={styles.addBtn}
                    onClick={() => addSipocItem('outputs')}
                  >
                    <i className="fas fa-plus"></i> Add Output
                  </button>
                  <button
                    type="button"
                    className={styles.addBtn}
                    onClick={() => addSipocItem('customers')}
                  >
                    <i className="fas fa-plus"></i> Add Customer
                  </button>
                </div>
              </div>
            </div>
          </div>

          {/* Process Flow Visualization */}
          <div className={styles.analysisCard}>
            <h2>Process Flow</h2>
            <p className={styles.processFlowDescription}>
              Visual representation of your process steps in sequence
            </p>
            <div className={styles.processFlow}>
              {sipocData.process.length > 0 ? (
                sipocData.process.map((step, index) => (
                  <React.Fragment key={step.id}>
                    <div className={styles.processStep}>
                      <div className={styles.stepNumber}>{index + 1}</div>
                      <div className={styles.stepContent}>
                        <h4>{step.step || 'Untitled Step'}</h4>
                        <p>{step.description || 'No description provided'}</p>
                        <div className={styles.stepDetails}>
                          <span>Owner: {step.owner || 'Not assigned'}</span>
                          <span>Duration: {step.duration || 'Not specified'}</span>
                        </div>
                      </div>
                    </div>
                    {index < sipocData.process.length - 1 && (
                      <div className={styles.stepArrow}>
                        <i className="fas fa-arrow-right"></i>
                      </div>
                    )}
                  </React.Fragment>
                ))
              ) : (
                <div className={styles.emptyState}>
                  Add process steps above to see the flow visualization
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </ResourcePageWrapper>
  );
};

export default SIPOC;
