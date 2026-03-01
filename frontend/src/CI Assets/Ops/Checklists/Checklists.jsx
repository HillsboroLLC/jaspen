import React, { useState, useEffect, useCallback } from 'react';
import styles from './Checklists.module.css';
import { useAdminSettings } from '../context/AdminContext';
import ResourcePageWrapper from '../../All/components/ResourcePageWrapper';
import '@fortawesome/fontawesome-free/css/all.min.css';

const Checklist = () => {
  const { adminSettings } = useAdminSettings();

  const [checklistData, setChecklistData] = useState({
    checklistTitle: '',
    creator: '',
    dateCreated: new Date().toISOString().split('T')[0],
    lastUpdated: new Date().toISOString().split('T')[0],
    checklistConfig: {
      purpose: '',
      scope: '',
      frequency: 'one-time',
      priority: 'medium',
      category: 'quality',
      estimatedTime: '',
      requiredSkills: '',
      approvalRequired: false,
    },
    sections: [
      {
        id: 1,
        title: 'Preparation',
        description: 'Initial setup and preparation tasks',
        items: [
          {
            id: 1,
            text: '',
            completed: false,
            required: true,
            notes: '',
            assignee: '',
            dueDate: '',
            priority: 'medium',
          },
        ],
        collapsed: false,
      },
    ],
    progress: {
      totalItems: 0,
      completedItems: 0,
      completionPercentage: 0,
      startDate: '',
      targetDate: '',
      actualCompletionDate: '',
      status: 'not-started',
    },
    qualityControl: {
      reviewRequired: false,
      reviewer: '',
      reviewDate: '',
      reviewNotes: '',
      approved: false,
      approver: '',
      approvalDate: '',
      rejectionReason: '',
    },
    documentation: {
      completionNotes: '',
      lessonsLearned: '',
      improvements: '',
      nextActions: '',
      attachments: [],
    },
  });

  const [completionPercentage, setCompletionPercentage] = useState(0);

  const handleKiiDataUpdate = useCallback((extracted = {}) => {
    setChecklistData((prev) => {
      const next = { ...prev };

      ['checklistTitle', 'creator', 'dateCreated'].forEach((k) => {
        if (extracted[k] !== undefined) next[k] = extracted[k];
      });

      if (extracted.checklistConfig) {
        next.checklistConfig = { ...next.checklistConfig, ...extracted.checklistConfig };
      } else {
        [
          'purpose',
          'scope',
          'frequency',
          'priority',
          'category',
          'estimatedTime',
          'requiredSkills',
          'approvalRequired',
        ].forEach((k) => {
          if (extracted[k] !== undefined) next.checklistConfig[k] = extracted[k];
        });
      }

      if (Array.isArray(extracted.sections)) {
        const safeSections = extracted.sections.map((s, si) => ({
          id: s.id || Date.now() + si,
          title: s.title ?? `Section ${si + 1}`,
          description: s.description ?? '',
          collapsed: !!s.collapsed,
          items: Array.isArray(s.items)
            ? s.items.map((it, ii) => ({
                id: it.id || Date.now() + si * 1000 + ii,
                text: it.text ?? '',
                completed: !!it.completed,
                required: it.required !== undefined ? !!it.required : true,
                notes: it.notes ?? '',
                assignee: it.assignee ?? '',
                dueDate: it.dueDate ?? '',
                priority: it.priority ?? 'medium',
              }))
            : [],
        }));
        next.sections = safeSections;
      }

      if (extracted.progress) next.progress = { ...next.progress, ...extracted.progress };
      if (extracted.qualityControl) next.qualityControl = { ...next.qualityControl, ...extracted.qualityControl };
      if (extracted.documentation) next.documentation = { ...next.documentation, ...extracted.documentation };

      next.lastUpdated = new Date().toISOString().split('T')[0];
      return next;
    });
  }, []);

  useEffect(() => {
    const calculateCompletion = () => {
      let totalFields = 0;
      let completedFields = 0;

      totalFields += 3;
      if (checklistData.checklistTitle) completedFields++;
      if (checklistData.creator) completedFields++;
      if (checklistData.checklistConfig.purpose) completedFields++;

      totalFields += 2;
      if (checklistData.checklistConfig.scope) completedFields++;
      if (checklistData.checklistConfig.category) completedFields++;

      totalFields += 2;
      const hasItems = checklistData.sections.some((section) =>
        section.items.some((item) => item.text.trim() !== '')
      );
      if (hasItems) completedFields++;
      if (checklistData.sections.length > 1) completedFields++;

      totalFields += 1;
      if (checklistData.progress.targetDate) completedFields++;

      totalFields += 2;
      if (checklistData.documentation.completionNotes) completedFields++;
      if (checklistData.documentation.improvements) completedFields++;

      const percent = totalFields > 0 ? Math.round((completedFields / totalFields) * 100) : 0;
      setCompletionPercentage(percent);

      const totalItems = checklistData.sections.reduce(
        (total, section) => total + section.items.filter((i) => i.text.trim() !== '').length,
        0
      );
      const completedItems = checklistData.sections.reduce(
        (total, section) => total + section.items.filter((i) => i.completed && i.text.trim() !== '').length,
        0
      );
      const itemCompletionPercentage = totalItems > 0 ? Math.round((completedItems / totalItems) * 100) : 0;

      setChecklistData((prev) => ({
        ...prev,
        progress: {
          ...prev.progress,
          totalItems,
          completedItems,
          completionPercentage: itemCompletionPercentage,
          status:
            itemCompletionPercentage === 100
              ? 'completed'
              : itemCompletionPercentage > 0
              ? 'in-progress'
              : 'not-started',
        },
      }));
    };

    calculateCompletion();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    checklistData.checklistTitle,
    checklistData.creator,
    checklistData.checklistConfig,
    checklistData.sections,
    checklistData.progress.targetDate,
    checklistData.documentation,
  ]);

  const handleBasicInfoChange = (field, value) => {
    setChecklistData((prev) => ({
      ...prev,
      [field]: value,
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  const handleConfigChange = (field, value) => {
    setChecklistData((prev) => ({
      ...prev,
      checklistConfig: { ...prev.checklistConfig, [field]: value },
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  const handleSectionChange = (sectionId, field, value) => {
    setChecklistData((prev) => ({
      ...prev,
      sections: prev.sections.map((section) => (section.id === sectionId ? { ...section, [field]: value } : section)),
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  const handleItemChange = (sectionId, itemId, field, value) => {
    setChecklistData((prev) => ({
      ...prev,
      sections: prev.sections.map((section) =>
        section.id === sectionId
          ? { ...section, items: section.items.map((i) => (i.id === itemId ? { ...i, [field]: value } : i)) }
          : section
      ),
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  const addSection = () => {
    const now = Date.now();
    const newSection = {
      id: now,
      title: `Section ${checklistData.sections.length + 1}`,
      description: '',
      items: [
        {
          id: now + 1,
          text: '',
          completed: false,
          required: true,
          notes: '',
          assignee: '',
          dueDate: '',
          priority: 'medium',
        },
      ],
      collapsed: false,
    };
    setChecklistData((prev) => ({
      ...prev,
      sections: [...prev.sections, newSection],
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  const removeSection = (sectionId) => {
    if (checklistData.sections.length > 1) {
      setChecklistData((prev) => ({
        ...prev,
        sections: prev.sections.filter((s) => s.id !== sectionId),
        lastUpdated: new Date().toISOString().split('T')[0],
      }));
    }
  };

  const addItem = (sectionId) => {
    const newItem = {
      id: Date.now(),
      text: '',
      completed: false,
      required: true,
      notes: '',
      assignee: '',
      dueDate: '',
      priority: 'medium',
    };
    setChecklistData((prev) => ({
      ...prev,
      sections: prev.sections.map((s) => (s.id === sectionId ? { ...s, items: [...s.items, newItem] } : s)),
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  const removeItem = (sectionId, itemId) => {
    setChecklistData((prev) => ({
      ...prev,
      sections: prev.sections.map((s) => (s.id === sectionId ? { ...s, items: s.items.filter((i) => i.id !== itemId) } : s)),
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  const toggleSectionCollapse = (sectionId) => {
    setChecklistData((prev) => ({
      ...prev,
      sections: prev.sections.map((s) => (s.id === sectionId ? { ...s, collapsed: !s.collapsed } : s)),
    }));
  };

  const handleProgressChange = (field, value) => {
    setChecklistData((prev) => ({
      ...prev,
      progress: { ...prev.progress, [field]: value },
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  const handleQualityControlChange = (field, value) => {
    setChecklistData((prev) => ({
      ...prev,
      qualityControl: { ...prev.qualityControl, [field]: value },
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  const handleDocumentationChange = (field, value) => {
    setChecklistData((prev) => ({
      ...prev,
      documentation: { ...prev.documentation, [field]: value },
      lastUpdated: new Date().toISOString().split('T')[0],
    }));
  };

  const handleSave = () => {
    console.log('Saving Checklist draft:', checklistData);
  };

  const handleExport = () => {
    console.log('Exporting Checklist to PDF:', checklistData);
  };

  return (
    <ResourcePageWrapper
      pageName="Checklist"
      toolName="Checklist"
      adminSettings={adminSettings}
      currentData={checklistData}
      onDataUpdate={handleKiiDataUpdate}
    >
      <div className={styles.rcaContainer}>
        <div className={styles.header}>
          <div className={styles.headerContent}>
            <h1>Checklist Management</h1>
            <div className={styles.progressSection}>
              <div className={styles.progressBar} style={{ background: 'var(--lss-gray-200)', backgroundImage: 'none' }}>
                <div
                  className={styles.progressFill}
                  style={{ width: `${completionPercentage}%`, background: 'var(--lss-primary)', backgroundImage: 'none' }}
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

        <div className={styles.mainContent}>
          <div className={styles.processInfoCard}>
            <h2>Checklist Information</h2>

            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel}>
                Checklist Title <span className={styles.required}>*</span>
              </label>
              <input
                type="text"
                className={styles.textInput}
                value={checklistData.checklistTitle}
                onChange={(e) => handleBasicInfoChange('checklistTitle', e.target.value)}
                placeholder="Enter the title for your checklist"
              />
            </div>

            <div className={styles.fieldRow}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Creator <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={checklistData.creator}
                  onChange={(e) => handleBasicInfoChange('creator', e.target.value)}
                  placeholder="Who is creating this checklist?"
                />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Date Created</label>
                <input
                  type="date"
                  className={styles.textInput}
                  value={checklistData.dateCreated}
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
                value={checklistData.checklistConfig.purpose}
                onChange={(e) => handleConfigChange('purpose', e.target.value)}
                placeholder="What is the purpose of this checklist?"
                rows={2}
              />
            </div>

            <div className={styles.fieldRow}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Category</label>
                <select
                  className={styles.selectInput}
                  value={checklistData.checklistConfig.category}
                  onChange={(e) => handleConfigChange('category', e.target.value)}
                >
                  <option value="quality">Quality Control</option>
                  <option value="safety">Safety</option>
                  <option value="process">Process</option>
                  <option value="maintenance">Maintenance</option>
                  <option value="audit">Audit</option>
                </select>
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Priority</label>
                <select
                  className={styles.selectInput}
                  value={checklistData.checklistConfig.priority}
                  onChange={(e) => handleConfigChange('priority', e.target.value)}
                >
                  <option value="low">Low</option>
                  <option value="medium">Medium</option>
                  <option value="high">High</option>
                  <option value="critical">Critical</option>
                </select>
              </div>
            </div>

            <div className={styles.fieldRow}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Frequency</label>
                <select
                  className={styles.selectInput}
                  value={checklistData.checklistConfig.frequency}
                  onChange={(e) => handleConfigChange('frequency', e.target.value)}
                >
                  <option value="one-time">One-time</option>
                  <option value="daily">Daily</option>
                  <option value="weekly">Weekly</option>
                  <option value="monthly">Monthly</option>
                  <option value="as-needed">As Needed</option>
                </select>
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Estimated Time</label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={checklistData.checklistConfig.estimatedTime}
                  onChange={(e) => handleConfigChange('estimatedTime', e.target.value)}
                  placeholder="e.g., 30 minutes"
                />
              </div>
            </div>
          </div>

          <div className={styles.analysisCard}>
            <h2>Progress Overview</h2>
            <div className={styles.progressGrid}>
              <div className={styles.progressStats}>
                <div className={styles.statCard}>
                  <div className={styles.statNumber}>{checklistData.progress.totalItems}</div>
                  <div className={styles.statLabel}>Total Items</div>
                </div>
                <div className={styles.statCard}>
                  <div className={styles.statNumber}>{checklistData.progress.completedItems}</div>
                  <div className={styles.statLabel}>Completed</div>
                </div>
                <div className={styles.statCard}>
                  <div className={styles.statNumber}>{checklistData.progress.completionPercentage}%</div>
                  <div className={styles.statLabel}>Progress</div>
                </div>
                <div className={styles.statCard}>
                  <div className={`${styles.statNumber} ${styles[checklistData.progress.status]}`}>
                    {checklistData.progress.status.replace('-', ' ').toUpperCase()}
                  </div>
                  <div className={styles.statLabel}>Status</div>
                </div>
              </div>
              <div className={styles.progressDates}>
                <div className={styles.fieldRow}>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Start Date</label>
                    <input
                      type="date"
                      className={styles.textInput}
                      value={checklistData.progress.startDate}
                      onChange={(e) => handleProgressChange('startDate', e.target.value)}
                    />
                  </div>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Target Date</label>
                    <input
                      type="date"
                      className={styles.textInput}
                      value={checklistData.progress.targetDate}
                      onChange={(e) => handleProgressChange('targetDate', e.target.value)}
                    />
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div className={styles.analysisCard}>
            <div className={styles.sectionHeader}>
              <h2>Checklist Items</h2>
              <button className={styles.addBtn} onClick={addSection}>
                <i className="fas fa-plus"></i> Add Section
              </button>
            </div>

            <div className={styles.checklistSections}>
              {checklistData.sections.map((section) => (
                <div key={section.id} className={styles.checklistSection}>
                  <div className={styles.sectionHeaderRow}>
                    <div className={styles.sectionTitleGroup}>
                      <button className={styles.collapseBtn} onClick={() => toggleSectionCollapse(section.id)}>
                        <i className={`fas fa-chevron-${section.collapsed ? 'right' : 'down'}`}></i>
                      </button>
                      <input
                        type="text"
                        className={styles.sectionTitleInput}
                        value={section.title}
                        onChange={(e) => handleSectionChange(section.id, 'title', e.target.value)}
                        placeholder="Section title"
                      />
                    </div>
                    <div className={styles.sectionActions}>
                      <button className={styles.addItemBtn} onClick={() => addItem(section.id)}>
                        <i className="fas fa-plus"></i> Add Item
                      </button>
                      <button
                        className={styles.removeBtn}
                        onClick={() => removeSection(section.id)}
                        disabled={checklistData.sections.length <= 1}
                      >
                        <i className="fas fa-times"></i>
                      </button>
                    </div>
                  </div>

                  <div className={styles.sectionDescription}>
                    <input
                      type="text"
                      className={styles.textInput}
                      value={section.description}
                      onChange={(e) => handleSectionChange(section.id, 'description', e.target.value)}
                      placeholder="Section description (optional)"
                    />
                  </div>

                  {!section.collapsed && (
                    <div className={styles.sectionItems}>
                      {section.items.map((item) => (
                        <div key={item.id} className={styles.checklistItem}>
                          <div className={styles.itemMainRow}>
                            <div className={styles.itemCheckbox}>
                              <input
                                type="checkbox"
                                checked={item.completed}
                                onChange={(e) => handleItemChange(section.id, item.id, 'completed', e.target.checked)}
                              />
                            </div>
                            <div className={styles.itemContent}>
                              <input
                                type="text"
                                className={styles.itemTextInput}
                                value={item.text}
                                onChange={(e) => handleItemChange(section.id, item.id, 'text', e.target.value)}
                                placeholder="Enter checklist item"
                              />
                            </div>
                            <div className={styles.itemPriority}>
                              <select
                                className={styles.prioritySelect}
                                value={item.priority}
                                onChange={(e) => handleItemChange(section.id, item.id, 'priority', e.target.value)}
                              >
                                <option value="low">Low</option>
                                <option value="medium">Medium</option>
                                <option value="high">High</option>
                                <option value="critical">Critical</option>
                              </select>
                            </div>
                            <div className={styles.itemActions}>
                              <label className={styles.requiredToggle}>
                                <input
                                  type="checkbox"
                                  checked={item.required}
                                  onChange={(e) => handleItemChange(section.id, item.id, 'required', e.target.checked)}
                                />
                                Required
                              </label>
                              <button className={styles.removeBtn} onClick={() => removeItem(section.id, item.id)}>
                                <i className="fas fa-times"></i>
                              </button>
                            </div>
                          </div>

                          <div className={styles.itemDetailsRow}>
                            <div className={styles.fieldGroup}>
                              <label className={styles.fieldLabel}>Assignee</label>
                              <input
                                type="text"
                                className={styles.textInput}
                                value={item.assignee}
                                onChange={(e) => handleItemChange(section.id, item.id, 'assignee', e.target.value)}
                                placeholder="Who is responsible?"
                              />
                            </div>
                            <div className={styles.fieldGroup}>
                              <label className={styles.fieldLabel}>Due Date</label>
                              <input
                                type="date"
                                className={styles.textInput}
                                value={item.dueDate}
                                onChange={(e) => handleItemChange(section.id, item.id, 'dueDate', e.target.value)}
                              />
                            </div>
                            <div className={styles.fieldGroup}>
                              <label className={styles.fieldLabel}>Notes</label>
                              <input
                                type="text"
                                className={styles.textInput}
                                value={item.notes}
                                onChange={(e) => handleItemChange(section.id, item.id, 'notes', e.target.value)}
                                placeholder="Additional notes or instructions"
                              />
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>

          <div className={styles.analysisCard}>
            <div className={styles.sectionHeader}>
              <h2>Quality Control</h2>
              <label className={styles.enableToggle}>
                <input
                  type="checkbox"
                  checked={checklistData.qualityControl.reviewRequired}
                  onChange={(e) => handleQualityControlChange('reviewRequired', e.target.checked)}
                />
                Require Review
              </label>
            </div>

            {checklistData.qualityControl.reviewRequired && (
              <div className={styles.qualityControlGrid}>
                <div className={styles.reviewSection}>
                  <h3>Review Process</h3>
                  <div className={styles.fieldRow}>
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Reviewer</label>
                      <input
                        type="text"
                        className={styles.textInput}
                        value={checklistData.qualityControl.reviewer}
                        onChange={(e) => handleQualityControlChange('reviewer', e.target.value)}
                        placeholder="Who will review this checklist?"
                      />
                    </div>
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Review Date</label>
                      <input
                        type="date"
                        className={styles.textInput}
                        value={checklistData.qualityControl.reviewDate}
                        onChange={(e) => handleQualityControlChange('reviewDate', e.target.value)}
                      />
                    </div>
                  </div>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Review Notes</label>
                    <textarea
                      className={styles.textareaInput}
                      value={checklistData.qualityControl.reviewNotes}
                      onChange={(e) => handleQualityControlChange('reviewNotes', e.target.value)}
                      placeholder="Review comments and feedback"
                      rows={3}
                    />
                  </div>
                </div>

                <div className={styles.approvalSection}>
                  <h3>Approval</h3>
                  <div className={styles.approvalStatus}>
                    <label className={styles.approvalToggle}>
                      <input
                        type="checkbox"
                        checked={checklistData.qualityControl.approved}
                        onChange={(e) => handleQualityControlChange('approved', e.target.checked)}
                      />
                      <span className={styles.approvalLabel}>
                        {checklistData.qualityControl.approved ? 'Approved' : 'Pending Approval'}
                      </span>
                    </label>
                  </div>
                  <div className={styles.fieldRow}>
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Approver</label>
                      <input
                        type="text"
                        className={styles.textInput}
                        value={checklistData.qualityControl.approver}
                        onChange={(e) => handleQualityControlChange('approver', e.target.value)}
                        placeholder="Who approved this checklist?"
                      />
                    </div>
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Approval Date</label>
                      <input
                        type="date"
                        className={styles.textInput}
                        value={checklistData.qualityControl.approvalDate}
                        onChange={(e) => handleQualityControlChange('approvalDate', e.target.value)}
                      />
                    </div>
                  </div>
                  {!checklistData.qualityControl.approved && (
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Rejection Reason</label>
                      <textarea
                        className={styles.textareaInput}
                        value={checklistData.qualityControl.rejectionReason}
                        onChange={(e) => handleQualityControlChange('rejectionReason', e.target.value)}
                        placeholder="If rejected, explain why"
                        rows={2}
                      />
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>

          <div className={styles.analysisCard}>
            <h2>Documentation & Lessons Learned</h2>
            <div className={styles.documentationGrid}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Completion Notes</label>
                <textarea
                  className={styles.textareaInput}
                  value={checklistData.documentation.completionNotes}
                  onChange={(e) => handleDocumentationChange('completionNotes', e.target.value)}
                  placeholder="Document any issues, observations, or notes from checklist execution"
                  rows={3}
                />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Lessons Learned</label>
                <textarea
                  className={styles.textareaInput}
                  value={checklistData.documentation.lessonsLearned}
                  onChange={(e) => handleDocumentationChange('lessonsLearned', e.target.value)}
                  placeholder="What did you learn from using this checklist?"
                  rows={3}
                />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Improvements <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textareaInput}
                  value={checklistData.documentation.improvements}
                  onChange={(e) => handleDocumentationChange('improvements', e.target.value)}
                  placeholder="How can this checklist be improved for future use?"
                  rows={3}
                />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Next Actions</label>
                <textarea
                  className={styles.textareaInput}
                  value={checklistData.documentation.nextActions}
                  onChange={(e) => handleDocumentationChange('nextActions', e.target.value)}
                  placeholder="What follow-up actions are needed?"
                  rows={2}
                />
              </div>
            </div>
          </div>
        </div>
      </div>
    </ResourcePageWrapper>
  );
};

export default Checklist;
